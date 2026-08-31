#!/usr/bin/env python3
"""第 05 阶段：以 v2 自适应 package 从冻结 Source Atom 提取 Cue。

职责：默认对冻结 Source Atom 做只读分包和费用预检；仅在显式执行授权后调用固定模型，
并由程序回填最终 Cue。输入是 Source SUCCESS、Source Atom、模型配置、提示词和 Schema；
输出是预检报告，或逐包工件、最终 Cue 与 SUCCESS。它位于 Source QA 后、Cue QA 前。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import jsonschema
import yaml


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_VERSION = "v1.1.0"
CONFIG_VERSION = "v1.1.0"
SOURCE_SCHEMA_VERSION = "v1.1.0"
CUE_SCHEMA_VERSION = "v1.0.0"


class ContractError(RuntimeError):
    """冻结合同、输入血缘、响应结构或恢复边界不一致。"""


@dataclass(frozen=True)
class Settings:
    """第 05 阶段从 T0 冻结配置提取的不可变执行参数。"""

    endpoint: str
    region: str
    credential_environment_variable: str
    model_id: str
    thinking_enabled: bool
    reasoning_effort: str
    temperature: int | float
    prompt_version: str
    final_cue_schema: str
    final_cue_schema_version: str
    shard_size: int
    maximum_atoms: int
    maximum_request_utf8_bytes: int
    output_tokens_per_atom: int
    max_retries: int
    target_requests_per_minute: int
    target_total_tokens_per_minute: int
    layout: dict[str, str]
    input_price_cny_per_million_tokens: float
    output_price_cny_per_million_tokens: float
    execution: dict[str, Any]
    protocol_context: dict[str, Any]


def utc_now() -> str:
    """生成 UTC 时间以避免本地时区破坏账本和 SUCCESS 的可审计性。"""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    """流式哈希文件，避免生产 JSONL 被整体读进内存。"""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    """按固定 JSON 编码计算哈希，使键顺序和空白不会改变恢复边界。"""

    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    """读取 JSON 对象；标记或 Schema 失效时在联网前终止。"""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractError(f"无法读取 JSON：{path}") from error
    if not isinstance(value, dict):
        raise ContractError(f"JSON 根节点必须是 object：{path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读取且严格限制 JSONL 为无空行的对象序列，以稳定行数和哈希门。"""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise ContractError(f"无法读取 JSONL：{path}") from error
    result: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise ContractError(f"JSONL 不允许空行：{path}:{line_number}")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ContractError(f"JSONL 格式无效：{path}:{line_number}") from error
        if not isinstance(value, dict):
            raise ContractError(f"JSONL 行必须是 object：{path}:{line_number}")
        result.append(value)
    return result


def atomic_write_json(path: Path, value: Any) -> None:
    """完成并 fsync 临时 JSON 后再原子替换，避免 SUCCESS 或标记半写入。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def atomic_write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """全量 fsync JSONL 临时文件再替换，防止合并读到半个 package 结果。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def append_ledger_event(path: Path, event: dict[str, Any]) -> None:
    """追加并 fsync 单次账本行；事件设计上不包含请求或模型响应正文。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_validator(path: Path) -> jsonschema.Draft202012Validator:
    """加载冻结 Schema，失败时不能进入请求构造或恢复分支。"""

    return jsonschema.Draft202012Validator(read_json(path))


def validate_record(validator: jsonschema.Draft202012Validator, record: dict[str, Any], label: str) -> None:
    """以稳定错误拒绝 Schema 不符记录，避免异常回显可能的模型正文。"""

    if list(validator.iter_errors(record)):
        raise ContractError(f"{label} 未通过 Schema")


def verified_source(artifact: Path, marker_path: Path) -> dict[str, Any]:
    """验证 Source SUCCESS 的受管相对路径、版本、行数与 SHA256。"""

    marker = read_json(marker_path)
    declared = Path(str(marker.get("artifact_path", "")))
    expected = (ROOT / declared).resolve()
    # 不从标记目录猜测路径；拒绝绝对或 ``..`` 路径以确保只能读取项目内冻结 Source。
    if (
        not artifact.is_file()
        or not marker_path.is_file()
        or declared.is_absolute()
        or ".." in declared.parts
        or expected != artifact.resolve()
    ):
        raise ContractError("Source SUCCESS 的 artifact_path 不是受管项目内相对路径")
    schema_versions = marker.get("schema_versions")
    if not isinstance(schema_versions, dict):
        raise ContractError("Source SUCCESS 缺少 schema_versions")
    if (
        marker.get("contract_version") != CONTRACT_VERSION
        or marker.get("config_version") != CONFIG_VERSION
        or schema_versions.get("source_video_atom") != SOURCE_SCHEMA_VERSION
        or marker.get("sha256") != sha256_file(artifact)
        or marker.get("row_count") != len(read_jsonl(artifact))
    ):
        raise ContractError("Source SUCCESS 的版本、哈希或行数不匹配")
    return marker


def managed_relative_path(path: Path) -> str:
    """将正式产物标记为 benchmark 根相对路径，令 T4 可跨机器复现地校验它。"""

    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as error:
        # 允许任意绝对输出会使 SUCCESS 在另一台机器上失效，也绕过 T4 的受管路径门。
        raise ContractError("正式 Cue 输出必须位于 egopm_bench_v1 项目目录内") from error


def settings_from_registry(path: Path) -> Settings:
    """读取 T0 冻结的 Cue v2 运行配置，并拒绝未走变更流程的参数漂移。"""

    try:
        registry = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise ContractError("无法读取模型配置") from error
    if not isinstance(registry, dict):
        raise ContractError("模型配置根节点必须是对象")
    cue = registry.get("models", {}).get("cue_extraction")
    if not isinstance(cue, dict) or not isinstance(cue.get("execution"), dict):
        raise ContractError("缺少冻结的 cue_extraction.execution")
    execution = cue["execution"]
    package = execution.get("package_policy")
    rate = execution.get("rate_limit_policy")
    pricing = execution.get("pricing_snapshot")
    layout = execution.get("shard_layout")
    if not all(isinstance(value, dict) for value in (package, rate, pricing, layout)):
        raise ContractError("Cue v2 缺少 package、限流、价格或分片布局配置")

    expected_execution = {
        "cue_execution_policy_version": "v2.0.0",
        "protocol_hash_payload_version": "v1.0.0",
        "mode": "explicit_execute_only",
        "shard_size_atoms": 500,
        "max_retries": 2,
        "transport": "realtime_chat_completions",
    }
    expected_package = {
        "maximum_atoms": 5,
        "maximum_request_utf8_bytes": 24000,
        "ordering": "atom_id_lexicographic",
        "output_tokens_per_atom": 128,
        "output_max_tokens_formula": "output_tokens_per_atom_times_package_atom_count",
        "inference_schema": "cue_inference_batch_v1.schema.json",
        "inference_schema_version": "v1.0.0",
        "response_top_level_field": "items",
        "response_correlation_field": "item_index",
    }
    expected_controlled = {
        "model_input_fields": ["item_index", "text"],
        "model_output_fields": ["item_index", "entities", "scene_type", "activity_type", "cue_type", "normalized_predicate", "supporting_text_span", "confidence", "ambiguity_reason", "validation_status"],
        "program_backfilled_fields": ["cue_id", "atom_id", "split", "source_text", "model_id", "prompt_version", "schema_version", "run_id"],
        "raw_model_response_storage": "forbidden",
    }
    expected_layout = {
        "root": "cues/shards", "package_directory": "packages", "input_manifest_suffix": ".input.jsonl",
        "output_suffix": ".result.jsonl", "ledger_suffix": ".ledger.jsonl", "completion_suffix": ".complete.json",
        "failed_suffix": ".failed.json", "merge_order": "numeric_shard_index_ascending",
    }
    expected_pricing = {
        "pricing_version": "2026-09-01_cn-beijing_list", "official_pricing_url": "https://help.aliyun.com/zh/model-studio/model-pricing",
        "input_price_cny_per_million_tokens": 0.2, "output_price_cny_per_million_tokens": 0.8,
        "price_region": "cn-beijing", "input_context_window_tokens": 32000,
        "retry_attempts_billed_independently": True,
    }
    # 逐项冻结是为了避免“代码默认值”在价格、并发、回填字段或恢复规则变更时继续生产。
    if (
        registry.get("contract_version") != CONTRACT_VERSION or registry.get("config_version") != CONFIG_VERSION
        or cue.get("model_id") != "qwen3.7-flash-2026-07-15" or cue.get("thinking_enabled") is not False
        or cue.get("reasoning_effort") != "none" or cue.get("temperature") != 0
        or cue.get("prompt_version") != "cue_extractor_v2" or cue.get("schema") != "cue_candidate.schema.json"
        or cue.get("schema_version") != CUE_SCHEMA_VERSION
        or any(execution.get(key) != value for key, value in expected_execution.items())
        or package != expected_package or execution.get("controlled_field_policy") != expected_controlled
        or layout != expected_layout or pricing != expected_pricing
        or rate.get("target_requests_per_minute") != 300 or rate.get("target_total_tokens_per_minute") != 1_000_000
        or registry.get("credential_policy") != "environment_only" or registry.get("raw_response_policy") != "forbidden"
    ):
        raise ContractError("Cue v2 冻结模型、执行或账本配置发生漂移")

    protocol_context = {
        "payload_version": execution["protocol_hash_payload_version"],
        "model": {
            "model_id": cue["model_id"], "thinking_enabled": cue["thinking_enabled"],
            "reasoning_effort": cue["reasoning_effort"], "temperature": cue["temperature"],
            "prompt_version": cue["prompt_version"], "final_cue_schema": cue["schema"],
            "final_cue_schema_version": cue["schema_version"],
        },
        "service": {
            "endpoint": registry["default_endpoint"], "region": registry["default_region"],
            "credential_policy": registry["credential_policy"], "raw_response_policy": registry["raw_response_policy"],
        },
    }
    return Settings(
        endpoint=str(registry["default_endpoint"]).rstrip("/"), region=str(registry["default_region"]),
        credential_environment_variable=str(registry["credential_environment_variable"]), model_id=str(cue["model_id"]),
        thinking_enabled=bool(cue["thinking_enabled"]), reasoning_effort=str(cue["reasoning_effort"]),
        temperature=cue["temperature"], prompt_version=str(cue["prompt_version"]),
        final_cue_schema=str(cue["schema"]), final_cue_schema_version=str(cue["schema_version"]),
        shard_size=int(execution["shard_size_atoms"]), maximum_atoms=int(package["maximum_atoms"]),
        maximum_request_utf8_bytes=int(package["maximum_request_utf8_bytes"]), output_tokens_per_atom=int(package["output_tokens_per_atom"]),
        max_retries=int(execution["max_retries"]), target_requests_per_minute=int(rate["target_requests_per_minute"]),
        target_total_tokens_per_minute=int(rate["target_total_tokens_per_minute"]), layout=dict(layout),
        input_price_cny_per_million_tokens=float(pricing["input_price_cny_per_million_tokens"]),
        output_price_cny_per_million_tokens=float(pricing["output_price_cny_per_million_tokens"]),
        execution=execution, protocol_context=protocol_context,
    )


def protocol_hash(settings: Settings, prompt_path: Path, inference_schema_path: Path) -> str:
    """计算与 T4 相同的完整协议哈希，作为 package 恢复和最终 QA 的硬边界。"""

    payload = {
        **settings.protocol_context,
        "execution": settings.execution,
        "cue_prompt_sha256": sha256_file(prompt_path),
        "cue_inference_schema_sha256": sha256_file(inference_schema_path),
    }
    return canonical_sha256(payload)


def build_request(prompt: str, schema: dict[str, Any], atoms: list[dict[str, Any]], settings: Settings) -> dict[str, Any]:
    """构造单 package 请求；模型只能看到局部索引和文本，受控字段由程序回填。"""

    items = [{"item_index": index, "text": atom["visible_text"]} for index, atom in enumerate(atoms)]
    return {
        "model": settings.model_id, "temperature": settings.temperature,
        "enable_thinking": settings.thinking_enabled, "max_tokens": settings.output_tokens_per_atom * len(atoms),
        "stream": False,
        "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": json.dumps({"items": items}, ensure_ascii=False, separators=(",", ":"))}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "cue_inference_batch_v1", "strict": True, "schema": schema}},
    }


def request_utf8_bytes(prompt: str, schema: dict[str, Any], atoms: list[dict[str, Any]], settings: Settings) -> int:
    """按实际序列化请求的 UTF-8 字节数计入上界，中文文本不会被低估。"""

    request = build_request(prompt, schema, atoms, settings)
    return len(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def ordered_atoms(atoms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 atom_id 固定顺序并拒绝重复，确保分包和最终合并可重现。"""

    ordered = sorted(atoms, key=lambda atom: str(atom.get("atom_id", "")))
    identifiers = [atom.get("atom_id") for atom in ordered]
    if not all(isinstance(identifier, str) and identifier for identifier in identifiers):
        raise ContractError("每条 Source Atom 必须有非空 atom_id")
    if len(set(identifiers)) != len(identifiers):
        raise ContractError("Source Atom 的 atom_id 不能重复")
    return ordered


def package_manifest(atoms: list[dict[str, Any]], source_sha256: str, protocol_sha256: str, run_id: str, shard_index: int, package_index: int) -> dict[str, Any]:
    """生成绑定 run、Atom 行哈希、Source 和协议哈希的自包含输入清单。"""

    package_id = f"shard_{shard_index:05d}_package_{package_index:03d}"
    return {
        "run_id": run_id, "shard_index": shard_index, "package_index": package_index, "package_id": package_id,
        "source_atoms_sha256": source_sha256, "cue_execution_protocol_sha256": protocol_sha256,
        "atoms": [{"atom_id": atom["atom_id"], "atom_sha256": canonical_sha256(atom)} for atom in atoms],
    }


def build_packages(atoms: list[dict[str, Any]], source_sha256: str, prompt: str, schema: dict[str, Any], settings: Settings, protocol_sha256: str, run_id: str) -> list[dict[str, Any]]:
    """每 500 Atom 一个逻辑 shard，再以五条/24K 双门限稳定贪心分 package。"""

    manifests: list[dict[str, Any]] = []
    for shard_index, start in enumerate(range(0, len(atoms), settings.shard_size)):
        current: list[dict[str, Any]] = []
        package_index = 0
        for atom in atoms[start : start + settings.shard_size]:
            candidate = current + [atom]
            if len(candidate) <= settings.maximum_atoms and request_utf8_bytes(prompt, schema, candidate, settings) <= settings.maximum_request_utf8_bytes:
                current = candidate
                continue
            # 单条超限不能截断文本；必须在 API 前失败，保持 Source-to-Cue 可追溯性。
            if not current:
                raise ContractError("单条 Atom 超过 24000 UTF-8 字节请求保护线")
            manifests.append(package_manifest(current, source_sha256, protocol_sha256, run_id, shard_index, package_index))
            package_index += 1
            current = [atom]
            if request_utf8_bytes(prompt, schema, current, settings) > settings.maximum_request_utf8_bytes:
                raise ContractError("单条 Atom 超过 24000 UTF-8 字节请求保护线")
        if current:
            manifests.append(package_manifest(current, source_sha256, protocol_sha256, run_id, shard_index, package_index))
    return manifests


def package_paths(run_root: Path, manifest: dict[str, Any], layout: dict[str, str]) -> dict[str, Path]:
    """用 package_id 隔离每包清单、结果、账本和标记，避免失败重跑影响其他包。"""

    package_id = str(manifest["package_id"])
    directory = run_root / layout["package_directory"] / package_id
    return {
        "manifest": directory / f"{package_id}{layout['input_manifest_suffix']}",
        "result": directory / f"{package_id}{layout['output_suffix']}",
        "ledger": directory / f"{package_id}{layout['ledger_suffix']}",
        "complete": directory / f"{package_id}{layout['completion_suffix']}",
        "failed": directory / f"{package_id}{layout['failed_suffix']}",
    }


def is_complete(manifest: dict[str, Any], files: dict[str, Path]) -> bool:
    """当前清单语义与结果/账本哈希全匹配才允许跳过，禁止错 run 或错 Atom 复用。"""

    if not all(files[name].is_file() for name in ("manifest", "result", "ledger", "complete")):
        return False
    try:
        completion = read_json(files["complete"])
        if read_jsonl(files["manifest"]) != [manifest]:
            return False
    except ContractError:
        return False
    return (
        completion.get("package_id") == manifest["package_id"]
        and completion.get("source_atoms_sha256") == manifest["source_atoms_sha256"]
        and completion.get("cue_execution_protocol_sha256") == manifest["cue_execution_protocol_sha256"]
        and completion.get("input_manifest_sha256") == sha256_file(files["manifest"])
        and completion.get("result_sha256") == sha256_file(files["result"])
        and completion.get("ledger_sha256") == sha256_file(files["ledger"])
    )


def pending_packages(manifests: list[dict[str, Any]], run_root: Path, layout: dict[str, str], rerun_failed_packages: bool = False) -> list[dict[str, Any]]:
    """失败 package 必须加显式开关才重跑，避免恢复命令无意产生新的计费尝试。"""

    pending: list[dict[str, Any]] = []
    for manifest in manifests:
        files = package_paths(run_root, manifest, layout)
        if is_complete(manifest, files):
            continue
        if files["failed"].is_file() and not rerun_failed_packages:
            continue
        pending.append(manifest)
    return pending


def parse_inference_items(response: dict[str, Any], atoms: list[dict[str, Any]], inference_validator: jsonschema.Draft202012Validator, cue_validator: jsonschema.Draft202012Validator, settings: Settings, run_id: str) -> list[dict[str, Any]]:
    """验证模型推理数组后再回填 ID、split、原文与模型字段，只输出 accepted Cue。"""

    validate_record(inference_validator, response, "Cue v2 推理响应")
    items = response["items"]
    if len(items) != len(atoms) or sorted(item["item_index"] for item in items) != list(range(len(atoms))):
        raise ContractError("推理响应必须为 package 中每条 Atom 恰好返回一次 item_index")
    cues: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda value: value["item_index"]):
        atom = atoms[item["item_index"]]
        # 这两条局部约束防止 package 中一条 Atom 的文本或谓词被错归到另一条。
        if item["supporting_text_span"] not in atom["visible_text"]:
            raise ContractError("supporting_text_span 不属于对应 Atom 的可见文本")
        if not any(clause.get("slot") == item["cue_type"] for clause in item["normalized_predicate"]["all_of"]):
            raise ContractError("normalized_predicate 未包含与 cue_type 对齐的 all_of 子句")
        inferred = {key: value for key, value in item.items() if key != "item_index"}
        cue = {
            **inferred, "cue_id": f"cue_{atom['atom_id'].removeprefix('src_')}", "atom_id": atom["atom_id"],
            "split": atom["split"], "source_text": atom["visible_text"], "model_id": settings.model_id,
            "prompt_version": settings.prompt_version, "schema_version": settings.final_cue_schema_version, "run_id": run_id,
        }
        validate_record(cue_validator, cue, "程序回填的 Cue")
        if cue["validation_status"] == "accepted":
            cues.append(cue)
    return cues


def preflight_report(manifests: list[dict[str, Any]], atoms: list[dict[str, Any]], prompt: str, schema: dict[str, Any], settings: Settings, protocol_sha256: str) -> dict[str, Any]:
    """线性核算包大小和重试费用；不创建目录、不读密钥、不访问网络。"""

    # 一次 ID 映射避免每个 package 重扫全部 370,799 条 Atom 而退化为平方复杂度。
    atom_by_id = {atom["atom_id"]: atom for atom in atoms}
    package_bytes = [request_utf8_bytes(prompt, schema, [atom_by_id[item["atom_id"]] for item in manifest["atoms"]], settings) for manifest in manifests]
    input_bound = sum(package_bytes)
    output_bound = sum(settings.output_tokens_per_atom * len(manifest["atoms"]) for manifest in manifests)
    def fee(multiplier: int) -> dict[str, float]:
        input_cost = input_bound * multiplier / 1_000_000 * settings.input_price_cny_per_million_tokens
        output_cost = output_bound * multiplier / 1_000_000 * settings.output_price_cny_per_million_tokens
        return {"input_cny_upper_bound": input_cost, "output_cny_upper_bound": output_cost, "total_cny_upper_bound": input_cost + output_cost}
    return {
        "mode": "preflight", "network_called": False, "credentials_read": False, "formal_outputs_written": False,
        "atom_count": len(atoms), "package_count": len(manifests),
        "logical_shard_count": (len(atoms) + settings.shard_size - 1) // settings.shard_size,
        "maximum_atoms_per_package": settings.maximum_atoms, "maximum_request_utf8_bytes": settings.maximum_request_utf8_bytes,
        "max_observed_package_request_utf8_bytes": max(package_bytes, default=0), "input_utf8_bytes_upper_bound": input_bound,
        "output_tokens_upper_bound": output_bound, "cue_execution_protocol_sha256": protocol_sha256,
        "cny_upper_bounds": {"baseline_one_attempt_per_package": fee(1), "conservative_all_packages_exhaust_max_retries": fee(settings.max_retries + 1)},
        "recovery": "仅当前清单、来源哈希、完整协议哈希、结果和账本 SHA256 均匹配时跳过；失败 package 必须显式重跑。",
    }


class RateLimiter:
    """以冻结 RPM 与 TPM 实现跨 package 无突发节流。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.next_allowed_at: float | None = None

    def wait(self, reserved_tokens: int) -> float:
        """返回本次仅因限流等待的秒数；指数退避不混入该审计字段。"""

        current = time.monotonic()
        scheduled = current if self.next_allowed_at is None else self.next_allowed_at
        waited = max(0.0, scheduled - current)
        if waited:
            time.sleep(waited)
        after_wait = time.monotonic()
        interval = max(60.0 / self.settings.target_requests_per_minute, reserved_tokens * 60.0 / self.settings.target_total_tokens_per_minute)
        self.next_allowed_at = max(scheduled, after_wait) + interval
        return waited


def normalise_usage(response: dict[str, Any]) -> dict[str, int | None]:
    """只接受服务端三个一致的整数 usage；缺失时记录 null，绝不使用预检值伪造。"""

    empty = {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return empty
    values = {key: usage.get(key) for key in empty}
    if not all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in values.values()):
        return empty
    if values["prompt_tokens"] + values["completion_tokens"] != values["total_tokens"]:
        return empty
    return values


def safe_failure_details(error: BaseException) -> tuple[str, str, list[str]]:
    """保留可审计的类别而不把异常字符串中的模型或 HTTP 正文写入磁盘。"""

    if isinstance(error, (HTTPError, URLError, TimeoutError)):
        return "transport_error", "请求传输失败；未保存原始响应", [type(error).__name__]
    if isinstance(error, json.JSONDecodeError):
        return "response_decode_error", "响应无法解析为预期 JSON；未保存原始响应", [type(error).__name__]
    return "response_contract_error", "响应未通过冻结合同；未保存原始响应", [type(error).__name__]


def execution_cycle(ledger_path: Path) -> int:
    """为显式失败重跑增加账本周期，保留历史尝试而不覆盖其审计证据。"""

    if not ledger_path.is_file():
        return 1
    try:
        cycles = [event.get("execution_cycle") for event in read_jsonl(ledger_path)]
    except ContractError:
        return 1
    values = [value for value in cycles if isinstance(value, int) and value >= 1]
    return max(values, default=0) + 1


def make_ledger_event(manifest: dict[str, Any], settings: Settings, attempt_index: int, retry_count: int, cycle: int, waited: float, status: str, parse_status: str, usage: dict[str, int | None], failure_summary: str | None, validation_errors: list[str]) -> dict[str, Any]:
    """生成逐请求自包含账本：包含用量、重试、血缘与本次限流等待，但不存正文。"""

    return {
        "run_id": manifest["run_id"], "package_id": manifest["package_id"], "attempt_index": attempt_index,
        "retry_count": retry_count, "execution_cycle": cycle, "request_time": utc_now(),
        "input_atom_ids": [item["atom_id"] for item in manifest["atoms"]], "model_id": settings.model_id,
        "region": settings.region, "endpoint": settings.endpoint, "thinking_enabled": settings.thinking_enabled,
        "reasoning_effort": settings.reasoning_effort, "temperature": settings.temperature,
        "prompt_version": settings.prompt_version, "schema_version": settings.final_cue_schema_version,
        "source_atoms_sha256": manifest["source_atoms_sha256"], "cue_execution_protocol_sha256": manifest["cue_execution_protocol_sha256"],
        "raw_response_path": None, "parse_status": parse_status, "validation_errors": validation_errors,
        "usage": usage, "failure_summary": failure_summary, "rate_limit_wait_seconds": waited,
        "raw_response_saved": False, "status": status,
    }


def execute_package(manifest: dict[str, Any], atom_by_id: dict[str, dict[str, Any]], run_root: Path, prompt: str, schema: dict[str, Any], inference_validator: jsonschema.Draft202012Validator, cue_validator: jsonschema.Draft202012Validator, settings: Settings, limiter: RateLimiter) -> None:
    """执行一个可恢复 package：每个 HTTP 尝试落账，成功后才写结果和完成标记。"""

    files = package_paths(run_root, manifest, settings.layout)
    atomic_write_jsonl(files["manifest"], [manifest])
    atoms = [atom_by_id[item["atom_id"]] for item in manifest["atoms"]]
    payload = build_request(prompt, schema, atoms, settings)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    reserved_tokens = len(body) + int(payload["max_tokens"])
    # 默认预检不会经过此处；只有 ``--execute`` 才从环境读取一次密钥，且不会记录它。
    api_key = os.environ.get(settings.credential_environment_variable)
    if not api_key:
        raise ContractError(f"未设置 {settings.credential_environment_variable}")
    request = Request(f"{settings.endpoint}/chat/completions", data=body, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
    cycle = execution_cycle(files["ledger"])
    for retry_count in range(settings.max_retries + 1):
        attempt_index = retry_count + 1
        waited = limiter.wait(reserved_tokens)
        try:
            with urlopen(request, timeout=60) as handle:
                response = json.loads(handle.read().decode("utf-8"))
            if not isinstance(response, dict):
                raise ContractError("HTTP 响应根节点必须是对象")
            inferred = json.loads(response["choices"][0]["message"]["content"])
            if not isinstance(inferred, dict):
                raise ContractError("模型 content 根节点必须是对象")
            cues = parse_inference_items(inferred, atoms, inference_validator, cue_validator, settings, str(manifest["run_id"]))
            append_ledger_event(files["ledger"], make_ledger_event(manifest, settings, attempt_index, retry_count, cycle, waited, "success", "validated", normalise_usage(response), None, []))
            atomic_write_jsonl(files["result"], cues)
            atomic_write_json(files["complete"], {
                "package_id": manifest["package_id"], "source_atoms_sha256": manifest["source_atoms_sha256"],
                "cue_execution_protocol_sha256": manifest["cue_execution_protocol_sha256"],
                "input_manifest_sha256": sha256_file(files["manifest"]), "result_sha256": sha256_file(files["result"]),
                "ledger_sha256": sha256_file(files["ledger"]), "completed_at": utc_now(), "accepted_row_count": len(cues),
            })
            # 成功后的历史失败仍在账本中；仅清除“当前未完成”失败标记。
            if files["failed"].is_file():
                files["failed"].unlink()
            return
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ContractError, KeyError, IndexError) as error:
            parse_status, summary, errors = safe_failure_details(error)
            append_ledger_event(files["ledger"], make_ledger_event(manifest, settings, attempt_index, retry_count, cycle, waited, "failed", parse_status, {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}, summary, errors))
            if retry_count == settings.max_retries:
                atomic_write_json(files["failed"], {
                    "package_id": manifest["package_id"], "source_atoms_sha256": manifest["source_atoms_sha256"],
                    "cue_execution_protocol_sha256": manifest["cue_execution_protocol_sha256"], "ledger_sha256": sha256_file(files["ledger"]),
                    "execution_cycle": cycle, "failure_category": type(error).__name__, "failed_at": utc_now(),
                })
                raise ContractError(f"package {manifest['package_id']} 已耗尽冻结重试次数") from error
            # 短暂故障退避不计作限流等待；下一 attempt 的 rate_limit_wait_seconds 仍单独记录。
            time.sleep(min(2 ** retry_count, 4))


def merge_completed_packages(manifests: list[dict[str, Any]], run_root: Path, settings: Settings, output: Path) -> int:
    """按数字 shard/package 顺序合并；任何未完成或失败包都会阻止写最终 Cue JSONL。"""

    if pending_packages(manifests, run_root, settings.layout, rerun_failed_packages=True):
        raise ContractError("禁止合并未完成、失败或恢复边界不匹配的 package")
    cues: list[dict[str, Any]] = []
    for manifest in sorted(manifests, key=lambda item: (item["shard_index"], item["package_index"])):
        cues.extend(read_jsonl(package_paths(run_root, manifest, settings.layout)["result"]))
    identifiers = [cue.get("cue_id") for cue in cues]
    if len(identifiers) != len(set(identifiers)):
        raise ContractError("确定性合并发现重复 cue_id")
    atomic_write_jsonl(output, cues)
    return len(cues)


def usage_summary(manifests: list[dict[str, Any]], run_root: Path, settings: Settings) -> dict[str, Any]:
    """汇总真实逐请求账本 usage；缺失显式计数，绝不以预检上界替代实际数据。"""

    events = [event for manifest in manifests for event in read_jsonl(package_paths(run_root, manifest, settings.layout)["ledger"])]
    def usage_total(field: str) -> int:
        return sum(event["usage"][field] for event in events if isinstance(event.get("usage"), dict) and isinstance(event["usage"].get(field), int) and not isinstance(event["usage"].get(field), bool) and event["usage"][field] >= 0)
    cycle_counts: dict[tuple[str, int], int] = {}
    for event in events:
        package_id, cycle = event.get("package_id"), event.get("execution_cycle")
        if isinstance(package_id, str) and isinstance(cycle, int) and cycle >= 1:
            cycle_counts[(package_id, cycle)] = cycle_counts.get((package_id, cycle), 0) + 1
    return {
        "package_count": len(manifests), "attempt_count": len(events),
        "successful_attempt_count": sum(event.get("status") == "success" for event in events),
        "failed_attempt_count": sum(event.get("status") == "failed" for event in events),
        "prompt_tokens": usage_total("prompt_tokens"), "completion_tokens": usage_total("completion_tokens"), "total_tokens": usage_total("total_tokens"),
        "missing_usage_count": sum(1 for event in events if not isinstance(event.get("usage"), dict) or not all(isinstance(event["usage"].get(field), int) and not isinstance(event["usage"].get(field), bool) and event["usage"][field] >= 0 for field in ("prompt_tokens", "completion_tokens", "total_tokens"))),
        "retry_count": sum(max(0, count - 1) for count in cycle_counts.values()),
        "rate_limit_wait_seconds": sum(float(event.get("rate_limit_wait_seconds", 0.0)) for event in events),
    }


def run(arguments: argparse.Namespace) -> int:
    """装配第 05 阶段；默认分支严格只读，执行分支最后才读取密钥并写工件。"""

    settings = settings_from_registry(arguments.model_registry)
    marker = verified_source(arguments.source_atoms, arguments.source_success)
    source_validator = load_validator(arguments.source_schema)
    inference_validator = load_validator(arguments.inference_schema)
    cue_validator = load_validator(arguments.cue_schema)
    atoms = ordered_atoms(read_jsonl(arguments.source_atoms))
    for atom in atoms:
        validate_record(source_validator, atom, "Source Atom")
    prompt = arguments.prompt.read_text(encoding="utf-8")
    schema = read_json(arguments.inference_schema)
    run_id = arguments.run_id or f"run_cue_{uuid.uuid4().hex[:16]}"
    protocol_sha256 = protocol_hash(settings, arguments.prompt, arguments.inference_schema)
    manifests = build_packages(atoms, str(marker["sha256"]), prompt, schema, settings, protocol_sha256, run_id)
    report = preflight_report(manifests, atoms, prompt, schema, settings, protocol_sha256)
    if not arguments.execute:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    run_root = arguments.run_root / run_id
    atom_by_id = {atom["atom_id"]: atom for atom in atoms}
    limiter = RateLimiter(settings)
    for manifest in pending_packages(manifests, run_root, settings.layout, arguments.rerun_failed_packages):
        execute_package(manifest, atom_by_id, run_root, prompt, schema, inference_validator, cue_validator, settings, limiter)
    count = merge_completed_packages(manifests, run_root, settings, arguments.output)
    # SUCCESS 必须最后写，才能让下游只读取完整合并结果和全部 package 账本。
    atomic_write_json(arguments.success_marker, {
        "artifact_path": managed_relative_path(arguments.output), "sha256": sha256_file(arguments.output), "row_count": count,
        "contract_version": CONTRACT_VERSION, "config_version": CONFIG_VERSION, "schema_versions": {"cue_candidate": CUE_SCHEMA_VERSION},
        "generated_at": utc_now(), "upstream_hashes": {"source_atoms": marker["sha256"]}, "model_id": settings.model_id,
        "prompt_version": settings.prompt_version, "cue_execution_policy_version": settings.execution["cue_execution_policy_version"],
        "protocol_hash_payload_version": settings.execution["protocol_hash_payload_version"], "cue_execution_protocol_sha256": protocol_sha256,
        "cue_prompt_sha256": sha256_file(arguments.prompt), "cue_inference_schema": settings.execution["package_policy"]["inference_schema"],
        "cue_inference_schema_version": settings.execution["package_policy"]["inference_schema_version"], "cue_inference_schema_sha256": sha256_file(arguments.inference_schema),
        "source_atoms_sha256": marker["sha256"], "usage_summary": usage_summary(manifests, run_root, settings),
    })
    return 0


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """定义只读默认值；``--execute`` 是唯一允许读取环境密钥和联网的开关。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-registry", type=Path, default=ROOT / "config/model_registry.yaml")
    parser.add_argument("--source-atoms", type=Path, default=ROOT / "source/source_video_atoms.jsonl")
    parser.add_argument("--source-success", type=Path, default=ROOT / "source/SOURCE_ATOMS_SUCCESS.json")
    parser.add_argument("--source-schema", type=Path, default=ROOT / "schemas/source_video_atom.schema.json")
    parser.add_argument("--cue-schema", type=Path, default=ROOT / "schemas/cue_candidate.schema.json")
    parser.add_argument("--inference-schema", type=Path, default=ROOT / "schemas/cue_inference_batch_v1.schema.json")
    parser.add_argument("--prompt", type=Path, default=ROOT / "prompts/cue_extractor_v2.md")
    parser.add_argument("--run-root", type=Path, default=ROOT / "cues/shards")
    parser.add_argument("--output", type=Path, default=ROOT / "cues/cue_library.jsonl")
    parser.add_argument("--success-marker", type=Path, default=ROOT / "cues/CUE_LIBRARY_SUCCESS.json")
    parser.add_argument("--run-id")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--rerun-failed-packages", action="store_true")
    return parser.parse_args(argv)


def main() -> int:
    """将合同失败转为稳定退出码，避免回溯中出现请求/响应正文。"""

    try:
        return run(parse_arguments())
    except ContractError as error:
        print(f"合同门禁失败：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
