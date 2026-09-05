#!/usr/bin/env python3
"""第 05 阶段：为冻结 Source Atom 构建 v2.2 Batch File 的无 API 计划。

职责：验证冻结 Source、紧凑提示词和 Schema，并只在内存中生成五条 Atom package、Batch
任务元数据与费用预检。输入是 Source SUCCESS、Source Atom、模型配置、提示词和 Schema；
输出是只读预检报告，或在用户显式授权的生产入口中写入已验证 Cue 片段、无正文账本和收据。
它位于 Source QA 后、Cue QA 前；默认模式绝不联网，正式 Cue 合并与 SUCCESS 仍由后续 QA 门控制。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from urllib import error as urlerror
from urllib import request as urlrequest
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

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
    layout: dict[str, str]
    input_price_cny_per_million_tokens: float
    output_price_cny_per_million_tokens: float
    execution: dict[str, Any]
    protocol_context: dict[str, Any]
    batch_file_policy: dict[str, Any]
    compact_policy: dict[str, Any]
    batch_ledger_policy: dict[str, Any]


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


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    """逐行读取严格 JSONL，供正式预检避免将冻结 Source 全量留在内存。"""

    # Source 已冻结为数十万条记录；全量 list 会把 Atom、包和请求正文同时留在内存，
    # 既不利于低成本预检，也会让仅核算阶段因内存耗尽中断。因此把顺序、类型与空行门
    # 保留在流式迭代器中，调用方仍须逐条做 Schema 校验。
    try:
        handle = path.open("r", encoding="utf-8", newline=None)
    except (OSError, UnicodeDecodeError) as error:
        raise ContractError(f"无法读取 JSONL：{path}") from error
    with handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ContractError(f"JSONL 不允许空行：{path}:{line_number}")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ContractError(f"JSONL 格式无效：{path}:{line_number}") from error
            if not isinstance(value, dict):
                raise ContractError(f"JSONL 行必须是 object：{path}:{line_number}")
            yield value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """在测试或小型 package 场景收集 JSONL；正式 Source 预检必须使用迭代器。"""

    return list(iter_jsonl(path))


def jsonl_row_count(path: Path) -> int:
    """只计数冻结 JSONL 行，避免 SUCCESS 校验复制整份 Source 到内存。"""

    return sum(1 for _ in iter_jsonl(path))


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
        or marker.get("row_count") != jsonl_row_count(artifact)
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
    """读取 T0 冻结的 Cue v2.2 配置，并拒绝混入实时调用的旧合同。"""

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
    pricing = execution.get("pricing_snapshot")
    layout = execution.get("shard_layout")
    batch = execution.get("batch_file_policy")
    compact = execution.get("compact_inference_policy")
    ledger_policy = execution.get("batch_ledger_policy")
    if not all(isinstance(value, dict) for value in (package, pricing, layout, batch, compact, ledger_policy)):
        raise ContractError("Cue v2.2 缺少 package、Batch、紧凑码、价格或分片布局配置")

    expected_execution = {
        "cue_execution_policy_version": "v2.2.1",
        "protocol_hash_payload_version": "v2.0.0",
        "mode": "explicit_batch_file_execute_only",
        "shard_size_atoms": 500,
        "max_retries": 2,
        "transport": "batch_file",
    }
    expected_package = {
        "maximum_atoms": 5,
        "maximum_request_utf8_bytes": 24000,
        "ordering": "atom_id_lexicographic",
        "output_tokens_per_atom": 96,
        "output_max_tokens_formula": "output_tokens_per_atom_times_package_atom_count",
        "inference_schema": "cue_inference_batch_compact_v1.schema.json",
        "inference_schema_version": "v1.0.0",
        "response_top_level_field": "items",
        "response_correlation_field": "n",
    }
    expected_controlled = {
        "model_input_fields": ["item_index", "text"],
        "model_output_fields": ["n", "t", "p", "x", "c", "v", "e", "s", "a", "r"],
        "program_backfilled_fields": ["cue_id", "atom_id", "split", "source_text", "model_id", "prompt_version", "schema_version", "run_id"],
        "raw_model_response_storage": "forbidden",
    }
    expected_layout = {
        "root": "cues/batch", "package_directory": "packages", "input_manifest_suffix": ".input.jsonl",
        "batch_tasks_manifest": "batch_tasks_manifest.jsonl", "output_suffix": ".result.jsonl", "ledger_suffix": ".ledger.jsonl", "completion_suffix": ".complete.json",
        "failed_suffix": ".failed.json", "batch_input_suffix": ".batch.jsonl", "batch_manifest_suffix": ".batch.json",
        "batch_receipt_suffix": ".batch_receipt.json", "merge_order": "numeric_shard_index_ascending",
    }
    expected_pricing = {
        "pricing_version": "2026-09-01_cn-beijing_batch_file_list", "official_pricing_url": "https://help.aliyun.com/zh/model-studio/model-pricing",
        "input_price_cny_per_million_tokens": 0.1, "output_price_cny_per_million_tokens": 0.4,
        "price_region": "cn-beijing", "input_context_window_tokens": 32000,
        "successful_requests_only_billed": True, "context_cache_supported": False,
    }
    # 逐项冻结是为了避免“代码默认值”在价格、并发、回填字段或恢复规则变更时继续生产。
    if (
        registry.get("contract_version") != CONTRACT_VERSION or registry.get("config_version") != CONFIG_VERSION
        or cue.get("model_id") != "qwen3.7-flash" or cue.get("thinking_enabled") is not False
        or cue.get("reasoning_effort") != "none" or cue.get("temperature") != 0
        or cue.get("prompt_version") != "cue_extractor_v3_compact" or cue.get("schema") != "cue_candidate.schema.json"
        or cue.get("schema_version") != CUE_SCHEMA_VERSION
        or any(execution.get(key) != value for key, value in expected_execution.items())
        or package != expected_package or execution.get("controlled_field_policy") != expected_controlled
        or any(layout.get(key) != value for key, value in expected_layout.items()) or pricing != expected_pricing
        or compact != {
            "cue_type_codes": {"T": "time", "P": "person", "L": "place", "O": "object", "A": "activity", "S": "state_change"},
            "operator_codes": {"=": "eq", "!": "not_eq", "+": "present", "-": "absent", "^": "starts", "$": "ends", "~": "contains"},
            "required_fields": ["n", "t", "p", "x", "c", "v"], "optional_defaults": {"e": [], "s": None, "a": None, "r": None}, "confidence_scale": 100,
        }
        or batch != {
            "logical_shards_per_task": 10, "completion_window": "24h", "max_requests_per_file": 50000,
            "max_input_file_bytes": 500000000, "max_request_line_bytes": 1000000,
            "request_endpoint": "/v1/chat/completions", "custom_id_format": "v22_s{shard_index:05d}_p{package_index:03d}_{manifest_sha256_8}",
            "local_request_body_storage": "temporary_delete_after_upload", "local_raw_result_storage": "forbidden_stream_only",
            "remote_files_delete_after_cue_qa": "required", "successful_local_validation_failure": "quarantine_no_auto_retry",
        }
        or ledger_policy != {
            "required_fields": ["batch_task_index", "batch_custom_id", "batch_input_sha256", "remote_file_id", "remote_cleanup_status", "outcome"],
            "terminal_outcomes": ["validated_success", "service_line_failure_requeueable", "local_validation_quarantine"],
            "require_single_terminal_outcome_per_custom_id": True, "prohibit_requeue_after_local_validation_quarantine": True,
        }
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
        endpoint=str(registry["default_endpoint"]).rstrip("/"), region=str(registry["default_region"]), model_id=str(cue["model_id"]),
        thinking_enabled=bool(cue["thinking_enabled"]), reasoning_effort=str(cue["reasoning_effort"]),
        temperature=cue["temperature"], prompt_version=str(cue["prompt_version"]),
        final_cue_schema=str(cue["schema"]), final_cue_schema_version=str(cue["schema_version"]),
        shard_size=int(execution["shard_size_atoms"]), maximum_atoms=int(package["maximum_atoms"]),
        maximum_request_utf8_bytes=int(package["maximum_request_utf8_bytes"]), output_tokens_per_atom=int(package["output_tokens_per_atom"]),
        max_retries=int(execution["max_retries"]), layout=dict(layout),
        input_price_cny_per_million_tokens=float(pricing["input_price_cny_per_million_tokens"]),
        output_price_cny_per_million_tokens=float(pricing["output_price_cny_per_million_tokens"]),
        execution=execution, protocol_context=protocol_context, batch_file_policy=dict(batch), compact_policy=dict(compact), batch_ledger_policy=dict(ledger_policy),
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
    """构造 Batch 行内的 chat body；模型只能看到局部索引和文本。"""

    items = [{"item_index": index, "text": atom["visible_text"]} for index, atom in enumerate(atoms)]
    return {
        "model": settings.model_id, "temperature": settings.temperature,
        "enable_thinking": settings.thinking_enabled, "max_tokens": settings.output_tokens_per_atom * len(atoms),
        "stream": False,
        "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": json.dumps({"items": items}, ensure_ascii=False, separators=(",", ":"))}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "cue_inference_batch_compact_v1", "strict": True, "schema": schema}},
    }


def batch_request_line(manifest: dict[str, Any], atoms: list[dict[str, Any]], prompt: str, schema: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """封装 Batch File 单行；此函数只构造内存对象，不上传也不落盘。"""

    return {
        "custom_id": manifest["batch_custom_id"],
        "method": "POST",
        "url": settings.batch_file_policy["request_endpoint"],
        "body": build_request(prompt, schema, atoms, settings),
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
    """生成绑定 run、Atom、Source、协议及可校验 custom_id 的本地清单。"""

    package_id = f"shard_{shard_index:05d}_package_{package_index:03d}"
    manifest = {
        "run_id": run_id, "shard_index": shard_index, "package_index": package_index, "package_id": package_id,
        "batch_task_index": shard_index // 10,
        "source_atoms_sha256": source_sha256, "cue_execution_protocol_sha256": protocol_sha256,
        "atoms": [{"atom_id": atom["atom_id"], "atom_sha256": canonical_sha256(atom)} for atom in atoms],
    }
    # custom_id 以不含自身的清单哈希作后缀，既可与服务端结果行双向比对，又不会形成哈希循环。
    manifest_sha256_8 = canonical_sha256(manifest)[:8]
    manifest["batch_custom_id"] = f"v22_s{shard_index:05d}_p{package_index:03d}_{manifest_sha256_8}"
    return manifest


def build_packages(atoms: list[dict[str, Any]], source_sha256: str, prompt: str, schema: dict[str, Any], settings: Settings, protocol_sha256: str, run_id: str, shard_offset: int = 0) -> list[dict[str, Any]]:
    """每 500 Atom 一个逻辑 shard，再以五条/24K 双门限稳定贪心分 package。"""

    manifests: list[dict[str, Any]] = []
    for local_shard_index, start in enumerate(range(0, len(atoms), settings.shard_size)):
        shard_index = local_shard_index + shard_offset
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


def build_batch_tasks(manifests: list[dict[str, Any]], atom_by_id: dict[str, dict[str, Any]], prompt: str, schema: dict[str, Any], settings: Settings) -> list[dict[str, Any]]:
    """按十个逻辑 shard 构建 Batch 任务计划，并在内存中检查每项/每文件大小。"""

    tasks: list[dict[str, Any]] = []
    per_task = int(settings.batch_file_policy["logical_shards_per_task"])
    maximum_shard = max((m["shard_index"] for m in manifests), default=-1)
    for task_index, first_shard in enumerate(range(0, maximum_shard + 1, per_task)):
        selected = [m for m in manifests if first_shard <= m["shard_index"] < first_shard + per_task]
        if not selected:
            # 流式预检会按单个 task 调用本函数；跳过此前不存在的 shard，不能构造空的
            # Batch 文件，也不能把它们计入远端任务数量或费用。
            continue
        lines: list[dict[str, Any]] = []
        for manifest in selected:
            atoms = [atom_by_id[item["atom_id"]] for item in manifest["atoms"]]
            line = batch_request_line(manifest, atoms, prompt, schema, settings)
            line_bytes = len(json.dumps(line, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
            if line_bytes > int(settings.batch_file_policy["max_request_line_bytes"]):
                raise ContractError("单条 Batch 请求超过冻结的 1MB 行上限")
            lines.append(line)
        serialized = "".join(json.dumps(line, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for line in lines).encode("utf-8")
        if len(lines) > int(settings.batch_file_policy["max_requests_per_file"]):
            raise ContractError("Batch 输入文件超过冻结的请求行数上限")
        if len(serialized) > int(settings.batch_file_policy["max_input_file_bytes"]):
            raise ContractError("Batch 输入文件超过冻结的 500MB 上限")
        custom_ids = [line["custom_id"] for line in lines]
        if len(set(custom_ids)) != len(custom_ids):
            raise ContractError("Batch custom_id 必须全局唯一")
        tasks.append({
            "run_id": selected[0]["run_id"] if selected else "", "batch_task_index": task_index,
            "wave_index": wave_index_for_task(task_index, settings),
            "source_atoms_sha256": selected[0]["source_atoms_sha256"] if selected else "",
            "cue_execution_protocol_sha256": selected[0]["cue_execution_protocol_sha256"] if selected else "",
            "batch_input_sha256": hashlib.sha256(serialized).hexdigest(), "request_count": len(lines),
            "custom_ids_sha256": canonical_sha256(custom_ids), "logical_shard_start": first_shard,
            # 末个 task 常不足十个 shard；记录实际边界避免恢复时虚构不存在的 Source 范围。
            "logical_shard_end": max(manifest["shard_index"] for manifest in selected), "remote_file_id": None,
            "status": "planned_no_api", "request_lines": lines,
        })
    return tasks


def wave_index_for_task(task_index: int, settings: Settings) -> int:
    """把冻结连续 task 编号映射为八波编号，使任务清单可独立定位接收收据。"""

    for wave_index in range(1, 9):
        if task_index in wave_task_indexes(wave_index, settings):
            return wave_index
    raise ContractError("Batch task 编号不属于冻结的八波计划")


def streaming_preflight_report(
    source_path: Path,
    source_validator: jsonschema.Draft202012Validator,
    source_sha256: str,
    prompt: str,
    schema: dict[str, Any],
    settings: Settings,
    protocol_sha256: str,
    run_id: str,
) -> dict[str, Any]:
    """流式构建正式 Source 的无 API 预检，最多暂存一个十-shard Batch 任务。"""

    # 每个 Batch task 最多十个 shard。仅将这一个 task 的请求行临时放在内存中以重算
    # `batch_input_sha256`，任务结束立即释放；因此不会把数万条请求正文或 37 万 Atom
    # 作为“预检产物”保留，也不会向磁盘写入任何请求文件。
    task_packages: list[dict[str, Any]] = []
    task_atom_by_id: dict[str, dict[str, Any]] = {}
    public_tasks: list[dict[str, Any]] = []
    source_count = 0
    package_count = 0
    output_bound = 0
    input_bound = 0
    max_observed = 0
    previous_atom_id: str | None = None
    current_shard: int | None = None
    current_package_index = 0
    current_atoms: list[dict[str, Any]] = []

    def finish_task() -> None:
        """完成当前十-shard计划的瞬时哈希与核算，然后只保留无正文元数据。"""

        nonlocal task_packages, task_atom_by_id, input_bound, max_observed
        if not task_packages:
            return
        task = build_batch_tasks(task_packages, task_atom_by_id, prompt, schema, settings)[0]
        request_sizes = [
            len(json.dumps(line, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
            for line in task["request_lines"]
        ]
        input_bound += sum(request_sizes)
        max_observed = max(max_observed, max(request_sizes, default=0))
        public_tasks.append(public_batch_task_manifest(task))
        task_packages = []
        task_atom_by_id = {}

    def finish_package() -> None:
        """把当前至多五条 Atom 变为包清单，并保留到其所属 task 的 SHA 核算完成。"""

        nonlocal current_atoms, current_package_index, package_count, output_bound
        if not current_atoms or current_shard is None:
            return
        task_packages.append(
            package_manifest(
                current_atoms, source_sha256, protocol_sha256, run_id, current_shard, current_package_index
            )
        )
        task_atom_by_id.update({atom["atom_id"]: atom for atom in current_atoms})
        package_count += 1
        output_bound += settings.output_tokens_per_atom * len(current_atoms)
        current_package_index += 1
        current_atoms = []

    for atom in iter_jsonl(source_path):
        validate_record(source_validator, atom, "Source Atom")
        atom_id = atom.get("atom_id")
        if not isinstance(atom_id, str) or not atom_id:
            raise ContractError("每条 Source Atom 必须有非空 atom_id")
        if previous_atom_id is not None and atom_id <= previous_atom_id:
            # 固定 atom_id 顺序是 package/custom_id/最终合并一致的共同前提；预检不能为
            # 省内存而悄悄接受乱序输入，否则正式执行会改变冻结覆盖范围。
            raise ContractError("Source Atom 必须已按 atom_id 严格升序冻结，流式预检拒绝乱序输入")
        previous_atom_id = atom_id
        shard_index = source_count // settings.shard_size
        if current_shard is not None and shard_index != current_shard:
            finish_package()
            if shard_index // int(settings.batch_file_policy["logical_shards_per_task"]) != current_shard // int(settings.batch_file_policy["logical_shards_per_task"]):
                finish_task()
            current_package_index = 0
        current_shard = shard_index
        candidate = current_atoms + [atom]
        if len(candidate) <= settings.maximum_atoms and request_utf8_bytes(prompt, schema, candidate, settings) <= settings.maximum_request_utf8_bytes:
            current_atoms = candidate
        else:
            if not current_atoms:
                raise ContractError("单条 Atom 超过 24000 UTF-8 字节请求保护线")
            finish_package()
            if request_utf8_bytes(prompt, schema, [atom], settings) > settings.maximum_request_utf8_bytes:
                raise ContractError("单条 Atom 超过 24000 UTF-8 字节请求保护线")
            current_atoms = [atom]
        source_count += 1
    finish_package()
    finish_task()
    if source_count == 0:
        raise ContractError("Source Atom 不能为空")
    input_cost = input_bound / 1_000_000 * settings.input_price_cny_per_million_tokens
    output_cost = output_bound / 1_000_000 * settings.output_price_cny_per_million_tokens
    return {
        "mode": "batch_preflight_no_api", "network_called": False, "credentials_read": False, "formal_outputs_written": False,
        "atom_count": source_count, "package_count": package_count, "batch_task_count": len(public_tasks),
        "logical_shard_count": (source_count + settings.shard_size - 1) // settings.shard_size,
        "maximum_atoms_per_package": settings.maximum_atoms, "maximum_request_utf8_bytes": settings.maximum_request_utf8_bytes,
        "max_observed_batch_request_utf8_bytes": max_observed, "batch_input_utf8_bytes_upper_bound": input_bound,
        "output_tokens_upper_bound": output_bound, "cue_execution_protocol_sha256": protocol_sha256,
        "batch_task_manifests": public_tasks,
        "cny_upper_bound_successful_requests_only": {"input_cny_upper_bound": input_cost, "output_cny_upper_bound": output_cost, "total_cny_upper_bound": input_cost + output_cost},
        "recovery": "仅重组未完成或行级失败 package；服务端成功而本地验证失败进入 quarantine，禁止自动重试。",
    }


def public_batch_task_manifest(task: dict[str, Any]) -> dict[str, Any]:
    """剥离临时请求正文后生成可保存的任务元数据，防止 Git 或账本留存原文。"""

    allowed = {
        "run_id", "batch_task_index", "wave_index", "source_atoms_sha256", "cue_execution_protocol_sha256",
        "batch_input_sha256", "request_count", "custom_ids_sha256", "logical_shard_start",
        "logical_shard_end", "remote_file_id", "status",
    }
    return {key: task[key] for key in sorted(allowed)}


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
    """严格展开紧凑项并回填受控字段；未知短码或跨 Atom 证据一律拒绝。"""

    validate_record(inference_validator, response, "Cue v2.2 紧凑推理响应")
    items = response["items"]
    if len(items) != len(atoms) or sorted(item["n"] for item in items) != list(range(len(atoms))):
        raise ContractError("紧凑响应必须为 package 中每条 Atom 恰好返回一次 n")
    cue_codes = settings.compact_policy["cue_type_codes"]
    operator_codes = settings.compact_policy["operator_codes"]
    defaults = settings.compact_policy["optional_defaults"]
    cues: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda value: value["n"]):
        atom = atoms[item["n"]]
        cue_type = cue_codes.get(item["t"])
        if not isinstance(cue_type, str):
            raise ContractError("出现未知 cue_type 短码")
        clauses: list[dict[str, str]] = []
        for compact_clause in item["p"]:
            slot = cue_codes.get(compact_clause[0])
            operator = operator_codes.get(compact_clause[1])
            if not isinstance(slot, str) or not isinstance(operator, str):
                raise ContractError("出现未知 predicate 槽位或操作短码")
            clauses.append({"slot": slot, "operator": operator, "value": compact_clause[2]})
        # 连续原文和主槽位门在展开前检查，避免正确 JSON 被错误 Atom 或错误语义接纳。
        if item["x"] not in atom["visible_text"]:
            raise ContractError("x 不属于对应 Atom 的可见文本")
        if not any(clause["slot"] == cue_type for clause in clauses):
            raise ContractError("p 未包含与 t 对齐的主槽位")
        status = {"A": "accepted", "R": "rejected", "N": "needs_review"}.get(item["v"])
        if status is None:
            raise ContractError("出现未知 validation_status 短码")
        cue = {
            "cue_id": f"cue_{atom['atom_id'].removeprefix('src_')}", "atom_id": atom["atom_id"],
            "split": atom["split"], "entities": item.get("e", defaults["e"]),
            "scene_type": item.get("s", defaults["s"]), "activity_type": item.get("a", defaults["a"]),
            "cue_type": cue_type, "normalized_predicate": {"all_of": clauses}, "supporting_text_span": item["x"],
            "source_text": atom["visible_text"], "confidence": item["c"] / settings.compact_policy["confidence_scale"],
            "ambiguity_reason": item.get("r", defaults["r"]), "model_id": settings.model_id,
            "prompt_version": settings.prompt_version, "schema_version": settings.final_cue_schema_version,
            "run_id": run_id, "validation_status": status,
        }
        validate_record(cue_validator, cue, "程序展开的 Cue")
        if cue["validation_status"] == "accepted":
            cues.append(cue)
    return cues


def preflight_report(manifests: list[dict[str, Any]], atoms: list[dict[str, Any]], prompt: str, schema: dict[str, Any], settings: Settings, protocol_sha256: str) -> dict[str, Any]:
    """核算内存中的 Batch 行与任务文件；默认不创建目录、不读密钥、不访问网络。"""

    atom_by_id = {atom["atom_id"]: atom for atom in atoms}
    tasks = build_batch_tasks(manifests, atom_by_id, prompt, schema, settings)
    request_sizes = [len(json.dumps(line, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1 for task in tasks for line in task["request_lines"]]
    input_bound = sum(request_sizes)
    output_bound = sum(settings.output_tokens_per_atom * len(manifest["atoms"]) for manifest in manifests)
    input_cost = input_bound / 1_000_000 * settings.input_price_cny_per_million_tokens
    output_cost = output_bound / 1_000_000 * settings.output_price_cny_per_million_tokens
    return {
        "mode": "batch_preflight_no_api", "network_called": False, "credentials_read": False, "formal_outputs_written": False,
        "atom_count": len(atoms), "package_count": len(manifests), "batch_task_count": len(tasks),
        "logical_shard_count": (len(atoms) + settings.shard_size - 1) // settings.shard_size,
        "maximum_atoms_per_package": settings.maximum_atoms, "maximum_request_utf8_bytes": settings.maximum_request_utf8_bytes,
        "max_observed_batch_request_utf8_bytes": max(request_sizes, default=0), "batch_input_utf8_bytes_upper_bound": input_bound,
        "output_tokens_upper_bound": output_bound, "cue_execution_protocol_sha256": protocol_sha256,
        "batch_task_manifests": [public_batch_task_manifest(task) for task in tasks],
        "cny_upper_bound_successful_requests_only": {"input_cny_upper_bound": input_cost, "output_cny_upper_bound": output_cost, "total_cny_upper_bound": input_cost + output_cost},
        "recovery": "仅重组未完成或行级失败 package；服务端成功而本地验证失败进入 quarantine，禁止自动重试。",
    }


def batch_ledger_event(manifest: dict[str, Any], task: dict[str, Any], outcome: str, parse_status: str, usage: dict[str, int | None], failure_summary: str | None = None) -> dict[str, Any]:
    """生成无正文行级账本；可审计 Batch 身份而不留请求、响应或错误内容。"""

    return {
        "run_id": manifest["run_id"], "package_id": manifest["package_id"], "input_atom_ids": [item["atom_id"] for item in manifest["atoms"]],
        "batch_task_index": task["batch_task_index"], "batch_custom_id": manifest["batch_custom_id"], "batch_input_sha256": task["batch_input_sha256"],
        "remote_file_id": task["remote_file_id"], "remote_cleanup_status": "pending_t4_cue_qa", "request_time": utc_now(),
        "outcome": outcome, "status": outcome, "parse_status": parse_status, "usage": usage, "failure_summary": failure_summary,
        "raw_response_saved": False, "raw_response_path": None,
    }


def parse_batch_result_line(result_line: dict[str, Any], manifest_by_custom_id: dict[str, dict[str, Any]], atom_by_id: dict[str, dict[str, Any]], task: dict[str, Any], inference_validator: jsonschema.Draft202012Validator, cue_validator: jsonschema.Draft202012Validator, settings: Settings) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """仅解析内存中的单行模拟结果，区分可重组失败与不可自动重试的隔离失败。"""

    custom_id = result_line.get("custom_id")
    if not isinstance(custom_id, str) or custom_id not in manifest_by_custom_id:
        raise ContractError("Batch 结果 custom_id 不能与本地清单双向匹配")
    manifest = manifest_by_custom_id[custom_id]
    line_sha256 = canonical_sha256(result_line)
    if result_line.get("error") is not None:
        event = batch_ledger_event(manifest, task, "service_line_failure_requeueable", "remote_line_error", {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}, "服务端行级失败；可重新组批")
        event.update({"result_line_sha256": line_sha256, "retry_eligible": True, "failure_origin": "service_line"})
        return "line_failed_requeue", [], event
    try:
        response = result_line.get("response")
        if not isinstance(response, dict):
            raise ContractError("Batch 成功行缺少响应对象")
        body = response.get("body")
        if not isinstance(body, dict):
            raise ContractError("Batch 成功行缺少响应 body")
        content = body.get("choices", [{}])[0].get("message", {}).get("content")
        parsed = json.loads(content) if isinstance(content, str) else None
        if not isinstance(parsed, dict):
            raise ContractError("Batch 成功行推理正文不是对象")
        atoms = [atom_by_id[item["atom_id"]] for item in manifest["atoms"]]
        cues = parse_inference_items(parsed, atoms, inference_validator, cue_validator, settings, manifest["run_id"])
        usage = normalise_usage(body)
        event = batch_ledger_event(manifest, task, "validated_success", "validated", usage)
        event.update({"result_line_sha256": line_sha256, "retry_eligible": False, "failure_origin": None})
        return "validated", cues, event
    except (ContractError, KeyError, IndexError, TypeError, json.JSONDecodeError):
        # 本地语义验证失败说明服务端已成功完成，自动重传会造成重复收费，因此只能隔离并人工决策。
        event = batch_ledger_event(manifest, task, "local_validation_quarantine", "local_validation_failed", {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}, "服务端成功但本地合同验证失败；禁止自动重试")
        event.update({"result_line_sha256": line_sha256, "retry_eligible": False, "failure_origin": "local_validation"})
        return "quarantine", [], event


def validate_batch_ledger_events(events: list[dict[str, Any]], settings: Settings) -> None:
    """校验终态账本：同一 custom_id 只能终结一次，隔离后绝不能进入重排队。"""

    required = set(settings.batch_ledger_policy["required_fields"])
    outcomes = set(settings.batch_ledger_policy["terminal_outcomes"])
    seen: dict[str, str] = {}
    for event in events:
        if not required.issubset(event) or event.get("outcome") not in outcomes:
            raise ContractError("Batch 账本缺少冻结字段或具有未知终态")
        custom_id = event["batch_custom_id"]
        if not isinstance(custom_id, str):
            raise ContractError("Batch 账本 custom_id 无效")
        if custom_id in seen:
            raise ContractError("同一 Batch custom_id 不得具有多个终态")
        seen[custom_id] = event["outcome"]


def requeueable_batch_custom_ids(events: list[dict[str, Any]], settings: Settings) -> set[str]:
    """只返回服务端行级失败的 package；隔离结果必须由人工处理，不能自动付费重传。"""

    validate_batch_ledger_events(events, settings)
    return {
        str(event["batch_custom_id"])
        for event in events
        if event["outcome"] == "service_line_failure_requeueable"
    }


def normalise_usage(response: dict[str, Any]) -> dict[str, int | None]:
    """只接受三个相加一致的 usage；缺失值必须显式保留为 null。"""

    empty = {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return empty
    values = {key: usage.get(key) for key in empty}
    if not all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in values.values()):
        return empty
    return values if values["prompt_tokens"] + values["completion_tokens"] == values["total_tokens"] else empty


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


def write_synthetic_batch_task_manifest(path: Path, tasks: list[dict[str, Any]], manifests: list[dict[str, Any]]) -> None:
    """仅供 pytest 临时目录验证元数据格式；绝不写入正式 Batch 路径或请求正文。"""

    by_task: dict[int, dict[str, str]] = {}
    for manifest in manifests:
        by_task.setdefault(manifest["batch_task_index"], {})[manifest["batch_custom_id"]] = manifest["package_id"]
    rows = []
    for task in tasks:
        row = public_batch_task_manifest(task)
        row["custom_id_to_package_id"] = by_task.get(task["batch_task_index"], {})
        rows.append(row)
    atomic_write_jsonl(path, rows)


def wave_task_indexes(wave_index: int, settings: Settings) -> list[int]:
    """按冻结的 1、6×10、14 计划返回一个波次的连续 task 编号。"""

    policy = settings.execution.get("batch_execution_policy")
    if not isinstance(policy, dict) or policy.get("wave_task_counts") != [1, 10, 10, 10, 10, 10, 10, 14]:
        raise ContractError("Batch 波次计划未按冻结的八波合同配置")
    counts = policy["wave_task_counts"]
    if not isinstance(wave_index, int) or not 1 <= wave_index <= len(counts):
        raise ContractError("wave_index 必须是 1..8")
    start = sum(counts[: wave_index - 1])
    return list(range(start, start + counts[wave_index - 1]))


def load_execution_authorization(
    path: Path,
    settings: Settings,
    source_sha256: str,
    protocol_sha256: str,
    wave_index: int,
    wave_cost_upper_bound: float,
) -> dict[str, Any]:
    """校验本机、显式且可审计的执行授权；缺预算或数据保留同意即拒绝联网。"""

    authorization = read_json(path)
    policy = settings.execution["batch_execution_policy"]
    required = {
        "authorization_version", "approved", "approved_by", "approved_at", "maximum_total_cny",
        "allowed_wave_indexes", "source_atoms_sha256", "cue_execution_protocol_sha256",
        "accept_remote_text_retention_until_t4_cue_qa", "accept_quarantine_manual_review_only",
    }
    if required.difference(authorization):
        raise ContractError("执行授权缺少冻结字段")
    if authorization["authorization_version"] != policy["authorization_version"] or authorization["approved"] is not True:
        raise ContractError("执行授权版本不匹配或尚未明确批准")
    if authorization["source_atoms_sha256"] != source_sha256 or authorization["cue_execution_protocol_sha256"] != protocol_sha256:
        raise ContractError("执行授权未绑定当前冻结 Source 或执行协议")
    if wave_index not in authorization["allowed_wave_indexes"]:
        raise ContractError("本次波次不在执行授权允许范围")
    budget = authorization["maximum_total_cny"]
    if not isinstance(budget, (int, float)) or isinstance(budget, bool) or budget < wave_cost_upper_bound:
        raise ContractError("执行授权预算不足以覆盖本波次保守上界")
    if authorization["accept_remote_text_retention_until_t4_cue_qa"] is not True:
        raise ContractError("未同意远端文本文件保留至 T4 Cue QA")
    if authorization["accept_quarantine_manual_review_only"] is not True:
        raise ContractError("未同意本地验证隔离项只能人工处置")
    return authorization


def execution_readiness_report(
    report: dict[str, Any], settings: Settings, source_sha256: str, wave_index: int, authorization_path: Path | None) -> dict[str, Any]:
    """输出不联网的波次就绪报告，供正式调用前复核预算、task 范围和授权文件。"""

    task_indexes = wave_task_indexes(wave_index, settings)
    tasks = report["batch_task_manifests"]
    if len(tasks) != sum(settings.execution["batch_execution_policy"]["wave_task_counts"]):
        raise ContractError("预检 task 数与八波计划不一致")
    selected = [tasks[index] for index in task_indexes]
    # 预检费用已是全量的保守上界。task 内 package 均由同一上限约束，按请求数比例切分
    # 只用于授权前的保守预留；结束后仍只能以每条 response_usage 汇总作最终计费账本。
    total_requests = int(report["package_count"])
    selected_requests = sum(int(task["request_count"]) for task in selected)
    wave_cost = float(report["cny_upper_bound_successful_requests_only"]["total_cny_upper_bound"]) * selected_requests / total_requests
    authorization_status = "not_provided"
    if authorization_path is not None and authorization_path.is_file():
        load_execution_authorization(authorization_path, settings, source_sha256, report["cue_execution_protocol_sha256"], wave_index, wave_cost)
        authorization_status = "valid"
    return {
        "mode": "batch_execution_readiness_no_api",
        "network_called": False,
        "credentials_read": False,
        "formal_outputs_written": False,
        "wave_index": wave_index,
        "batch_task_indexes": task_indexes,
        "batch_task_count": len(selected),
        "package_count": selected_requests,
        "wave_cny_upper_bound_proxy": wave_cost,
        "authorization_status": authorization_status,
        "remote_cleanup_gate": settings.execution["batch_execution_policy"]["remote_cleanup_gate"],
        "max_local_validation_quarantine_per_wave": settings.execution["batch_execution_policy"]["max_local_validation_quarantine_per_wave"],
    }


def materialize_task_from_source(
    source_path: Path,
    source_validator: jsonschema.Draft202012Validator,
    source_sha256: str,
    task_index: int,
    prompt: str,
    schema: dict[str, Any],
    settings: Settings,
    protocol_sha256: str,
    run_id: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """只 materialize 一个已授权 task 的 Atom 与请求行，避免全量 Source 常驻内存。"""

    per_task = int(settings.batch_file_policy["logical_shards_per_task"])
    first_shard = task_index * per_task
    last_shard = first_shard + per_task - 1
    atoms: list[dict[str, Any]] = []
    previous_id: str | None = None
    for position, atom in enumerate(iter_jsonl(source_path)):
        validate_record(source_validator, atom, "Source Atom")
        atom_id = atom.get("atom_id")
        if not isinstance(atom_id, str) or (previous_id is not None and atom_id <= previous_id):
            raise ContractError("Source Atom 顺序或 atom_id 不符合冻结合同")
        previous_id = atom_id
        shard_index = position // settings.shard_size
        if first_shard <= shard_index <= last_shard:
            atoms.append(atom)
        elif shard_index > last_shard:
            break
    if not atoms:
        raise ContractError("授权 task 未找到对应的 Source Atom")
    manifests = build_packages(atoms, source_sha256, prompt, schema, settings, protocol_sha256, run_id, shard_offset=first_shard)
    atom_by_id = {atom["atom_id"]: atom for atom in atoms}
    tasks = build_batch_tasks(manifests, atom_by_id, prompt, schema, settings)
    expected = next((task for task in tasks if task["batch_task_index"] == task_index), None)
    if expected is None:
        raise ContractError("无法构造授权 task 的 Batch 请求")
    return manifests, {line["custom_id"]: line for line in expected["request_lines"]}


def write_batch_input_temp(path: Path, request_lines: Iterable[dict[str, Any]]) -> str:
    """以临时文件写入 JSONL 并返回 SHA256；调用方必须在上传后删除该明文文件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    digest = hashlib.sha256()
    with temporary.open("wb") as handle:
        for line in request_lines:
            encoded = (json.dumps(line, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            handle.write(encoded)
            digest.update(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    return digest.hexdigest()


def submit_authorized_wave(
    arguments: argparse.Namespace,
    settings: Settings,
    marker: dict[str, Any],
    source_validator: jsonschema.Draft202012Validator,
    prompt: str,
    schema: dict[str, Any],
    protocol_sha256: str,
    authorization: dict[str, Any],
) -> dict[str, Any]:
    """提交已授权波次的 Batch task；不下载结果、不写 Cue，返回无正文远端句柄。"""

    if arguments.wave_index != 1:
        raise ContractError("当前首个受控 API 入口仅允许先提交第 1 波")
    api_key_name = "DASHSCOPE_API_KEY"
    api_key = os.environ.get(api_key_name)
    if not api_key:
        raise ContractError(f"缺少环境变量 {api_key_name}；未发出请求")
    run_id = arguments.run_id or f"wave_{arguments.wave_index:02d}"
    manifests, request_by_id = materialize_task_from_source(
        arguments.source_atoms, source_validator, str(marker["sha256"]), 0, prompt, schema, settings, protocol_sha256, run_id
    )
    line_list = list(request_by_id.values())
    estimated_cost = sum(len(json.dumps(line, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1 for line in line_list) / 1_000_000 * settings.input_price_cny_per_million_tokens
    estimated_cost += sum(len(manifest["atoms"]) for manifest in manifests) * settings.output_tokens_per_atom / 1_000_000 * settings.output_price_cny_per_million_tokens
    load_execution_authorization(arguments.authorization, settings, str(marker["sha256"]), protocol_sha256, 1, estimated_cost)
    run_root = arguments.run_root / f"wave_{arguments.wave_index:02d}"
    input_path = run_root / "task_000.batch.jsonl"
    input_sha = write_batch_input_temp(input_path, line_list)
    try:
        transport = BatchFileTransport(settings.endpoint, api_key)
        remote_file_id = transport.upload_input_file(input_path)
        created = transport.create_batch(remote_file_id, settings, {
            "run_id": run_id, "batch_task_index": "0", "source_atoms_sha256": str(marker["sha256"]),
            "cue_execution_protocol_sha256": protocol_sha256, "batch_input_sha256": input_sha,
        })
    finally:
        # 输入包含 Source 文本，上传结束（成功或失败）都必须删除本地明文。
        if input_path.exists():
            input_path.unlink()
    batch_id = created.get("id") if isinstance(created, dict) else None
    if not isinstance(batch_id, str) or not batch_id:
        raise ContractError("Batch 创建未返回 batch_id")
    state = {
        "run_id": run_id, "wave_index": 1, "batch_task_index": 0, "batch_id": batch_id,
        "remote_file_id": remote_file_id, "batch_input_sha256": input_sha,
        "source_atoms_sha256": marker["sha256"], "cue_execution_protocol_sha256": protocol_sha256,
        "request_count": len(line_list), "status": "submitted", "remote_cleanup_status": "pending_t4_cue_qa",
    }
    atomic_write_json(run_root / settings.execution["batch_execution_policy"]["execution_state_filename"], state)
    return {key: state[key] for key in ("wave_index", "batch_task_index", "batch_id", "remote_file_id", "batch_input_sha256", "request_count", "status")}


class BatchFileTransport:
    """第 05 阶段的最小 Batch File HTTP 适配器；仅在显式生产命令中持有环境变量密钥。"""

    def __init__(self, endpoint: str, api_key: str, opener: Callable[..., Any] = urlrequest.urlopen) -> None:
        """绑定官方兼容端点与短生命周期密钥；禁止将密钥或响应正文写入对象字段。"""

        if not endpoint.startswith("https://") or not api_key:
            raise ContractError("Batch 传输需要 HTTPS endpoint 与非空环境变量密钥")
        self.endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._opener = opener

    def _open(self, method: str, path: str, data: bytes | None, content_type: str | None) -> Any:
        """发送单次 HTTP 请求；异常仅报告状态，不回显可能含文本的远端错误正文。"""

        headers = {"Authorization": f"Bearer {self._api_key}"}
        if content_type is not None:
            headers["Content-Type"] = content_type
        request = urlrequest.Request(f"{self.endpoint}{path}", data=data, headers=headers, method=method)
        try:
            return self._opener(request, timeout=60)
        except urlerror.HTTPError as error:
            raise ContractError(f"Batch 远端返回 HTTP {error.code}") from error
        except urlerror.URLError as error:
            raise ContractError("Batch 远端连接失败") from error

    def request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """调用 JSON API 并仅返回结构化元数据；不得记录响应原文。"""

        data = None if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        with self._open(method, path, data, "application/json" if data is not None else None) as response:
            try:
                value = json.loads(response.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ContractError("Batch 远端 JSON 元数据不可解析") from error
        if not isinstance(value, dict):
            raise ContractError("Batch 远端 JSON 元数据必须为对象")
        return value

    def upload_input_file(self, path: Path) -> str:
        """上传临时 Batch JSONL，返回远端 file ID；调用方必须在成功后删除本地明文。"""

        if not path.is_file():
            raise ContractError("待上传的临时 Batch 输入文件不存在")
        boundary = f"----EgoPM{uuid.uuid4().hex}"
        prefix = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\nbatch\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            "Content-Type: application/jsonl\r\n\r\n"
        ).encode("utf-8")
        suffix = f"\r\n--{boundary}--\r\n".encode("utf-8")
        # 此处允许短暂读取一个 task 的输入（当前最多约 11 MB）；上传完成后由执行器
        # 无条件删除临时文件，不能将 Source 文本遗留在可恢复运行目录。
        payload = prefix + path.read_bytes() + suffix
        with self._open("POST", "/files", payload, f"multipart/form-data; boundary={boundary}") as response:
            try:
                value = json.loads(response.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ContractError("上传 Batch 输入后的元数据不可解析") from error
        file_id = value.get("id") if isinstance(value, dict) else None
        if not isinstance(file_id, str) or not file_id:
            raise ContractError("上传 Batch 输入未返回远端 file ID")
        return file_id

    def create_batch(self, input_file_id: str, settings: Settings, metadata: dict[str, str]) -> dict[str, Any]:
        """以冻结端点和 24 小时窗口创建远端任务，元数据仅含哈希与 ID。"""

        return self.request_json("POST", "/batches", {
            "input_file_id": input_file_id,
            "endpoint": settings.batch_file_policy["request_endpoint"],
            "completion_window": settings.batch_file_policy["completion_window"],
            "metadata": metadata,
        })

    def get_batch(self, batch_id: str) -> dict[str, Any]:
        """读取一个远端 Batch 状态；状态正文只在内存中用于状态机判断。"""

        return self.request_json("GET", f"/batches/{batch_id}")

    def stream_jsonl_file(self, file_id: str) -> Iterable[dict[str, Any]]:
        """流式读取结果或错误 JSONL，不在本地落盘原始 response/error。"""

        with self._open("GET", f"/files/{file_id}/content", None, None) as response:
            for raw_line in response:
                if not raw_line.strip():
                    continue
                try:
                    value = json.loads(raw_line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise ContractError("远端 Batch 结果行不可解析") from error
                if not isinstance(value, dict):
                    raise ContractError("远端 Batch 结果行必须为对象")
                yield value

    def delete_file(self, file_id: str) -> None:
        """删除远端输入、结果或错误文件；仅在 T4 Cue QA 通过后的清理命令调用。"""

        self.request_json("DELETE", f"/files/{file_id}")


def execution_state_path(run_root: Path, wave_index: int, settings: Settings) -> Path:
    """定位无正文执行状态；接收器只能消费提交器已原子写入的同一波次句柄。"""

    return run_root / f"wave_{wave_index:02d}" / settings.execution["batch_execution_policy"]["execution_state_filename"]


def rebuild_task_for_receipt(
    state: dict[str, Any], arguments: argparse.Namespace, settings: Settings,
    source_validator: jsonschema.Draft202012Validator, prompt: str, schema: dict[str, Any],
    protocol_sha256: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    """从冻结 Source 重建提交时的 package 映射，以输入哈希和 custom_id 双向阻止漂移。"""

    task_index = state.get("batch_task_index")
    run_id = state.get("run_id")
    if not isinstance(task_index, int) or not isinstance(run_id, str) or not run_id:
        raise ContractError("执行状态缺少 batch_task_index 或 run_id")
    manifests, request_by_id = materialize_task_from_source(
        arguments.source_atoms, source_validator, str(state["source_atoms_sha256"]), task_index,
        prompt, schema, settings, protocol_sha256, run_id,
    )
    atom_by_id: dict[str, dict[str, Any]] = {}
    for manifest in manifests:
        for item in manifest["atoms"]:
            atom_by_id[item["atom_id"]] = item
    # `materialize_task_from_source` 的清单只保留包内 atom_id，实际 Atom 需再做一次受限流式读取。
    selected_ids = set(atom_by_id)
    actual_atoms = {
        atom["atom_id"]: atom for atom in iter_jsonl(arguments.source_atoms) if atom.get("atom_id") in selected_ids
    }
    if set(actual_atoms) != selected_ids:
        raise ContractError("冻结 Source 无法重建接收所需 Atom")
    tasks = build_batch_tasks(manifests, actual_atoms, prompt, schema, settings)
    task = next((item for item in tasks if item["batch_task_index"] == task_index), None)
    if task is None:
        raise ContractError("冻结 Source 无法重建 Batch task")
    if task["wave_index"] != state.get("wave_index"):
        raise ContractError("执行状态 wave_index 与冻结任务计划不匹配")
    if state.get("batch_input_sha256") != task["batch_input_sha256"]:
        raise ContractError("执行状态 batch_input_sha256 与冻结重建请求不匹配")
    expected_custom_ids = set(request_by_id)
    if expected_custom_ids != {line["custom_id"] for line in task["request_lines"]}:
        raise ContractError("冻结重建 custom_id 映射不一致")
    task["remote_file_id"] = state.get("remote_file_id")
    return manifests, actual_atoms, task


def poll_batch_until_terminal(transport: BatchFileTransport, batch_id: str, settings: Settings, attempts: int) -> dict[str, Any]:
    """按冻结退避策略轮询远端元数据；不读取结果正文且单次命令可安全恢复。"""

    if not isinstance(attempts, int) or attempts < 1:
        raise ContractError("poll_attempts 必须为正整数")
    initial = int(settings.execution["batch_execution_policy"]["completion_poll_initial_seconds"])
    maximum = int(settings.execution["batch_execution_policy"]["completion_poll_max_seconds"])
    batch: dict[str, Any] = {}
    for index in range(attempts):
        batch = transport.get_batch(batch_id)
        status = batch.get("status")
        if status in {"completed", "failed", "expired", "cancelled"}:
            return batch
        if not isinstance(status, str):
            raise ContractError("Batch 状态缺少 status")
        if index + 1 < attempts:
            # 延迟只发生在用户显式接收命令内；默认一次查询，避免后台等待或隐式联网循环。
            time.sleep(min(maximum, initial * (2 ** index)))
    return batch


def receipt_path(run_root: Path, task_index: int, settings: Settings) -> Path:
    """生成 task 级无正文收据路径；其命名受冻结 shard layout 控制。"""

    return run_root / f"task_{task_index:03d}{settings.layout['batch_receipt_suffix']}"


def save_public_task_manifest(task: dict[str, Any], manifests: list[dict[str, Any]], run_root: Path, settings: Settings) -> None:
    """原子登记一个完成 task 的无正文映射，供 T4 将收据和每包账本逐一追溯。"""

    path = run_root / settings.layout["batch_tasks_manifest"]
    record = public_batch_task_manifest(task)
    record["custom_id_to_package_id"] = {
        manifest["batch_custom_id"]: manifest["package_id"] for manifest in manifests
    }
    record["status"] = "completed"
    rows = read_jsonl(path) if path.is_file() else []
    retained = [row for row in rows if row.get("batch_task_index") != task["batch_task_index"]]
    if len(retained) != len(rows) and any(
        row.get("batch_task_index") == task["batch_task_index"] and row != record for row in rows
    ):
        raise ContractError("既有 Batch task 清单与本次冻结重建结果冲突")
    atomic_write_jsonl(path, retained + [record])


def save_package_terminal(
    manifest: dict[str, Any], cues: list[dict[str, Any]], event: dict[str, Any], run_root: Path, settings: Settings,
) -> None:
    """原子保存一个包的最终片段；只有验证成功包可获得 complete 标记。"""

    files = package_paths(run_root, manifest, settings.layout)
    atomic_write_jsonl(files["manifest"], [manifest])
    atomic_write_jsonl(files["ledger"], [event])
    if event["outcome"] == "validated_success":
        atomic_write_jsonl(files["result"], cues)
        atomic_write_json(files["complete"], {
            "package_id": manifest["package_id"], "source_atoms_sha256": manifest["source_atoms_sha256"],
            "cue_execution_protocol_sha256": manifest["cue_execution_protocol_sha256"],
            "input_manifest_sha256": sha256_file(files["manifest"]), "result_sha256": sha256_file(files["result"]),
            "ledger_sha256": sha256_file(files["ledger"]),
        })
    else:
        # 失败标记只记录终态及账本哈希，绝不写远端错误或响应正文；隔离项不可自动重跑。
        atomic_write_json(files["failed"], {
            "package_id": manifest["package_id"], "outcome": event["outcome"],
            "ledger_sha256": sha256_file(files["ledger"]), "retry_eligible": event["retry_eligible"],
        })


def receive_authorized_wave(
    arguments: argparse.Namespace, settings: Settings, marker: dict[str, Any],
    source_validator: jsonschema.Draft202012Validator, prompt: str, schema: dict[str, Any], protocol_sha256: str,
) -> dict[str, Any]:
    """接收一个已提交 Batch 的流式结果，验证后仅写 Cue 片段、无正文账本和收据。"""

    state_path = execution_state_path(arguments.run_root, arguments.wave_index, settings)
    state = read_json(state_path)
    required = {"run_id", "wave_index", "batch_task_index", "batch_id", "remote_file_id", "batch_input_sha256", "source_atoms_sha256", "cue_execution_protocol_sha256", "request_count", "status"}
    if required.difference(state) or state["wave_index"] != arguments.wave_index:
        raise ContractError("执行状态不完整或波次不匹配")
    if state["source_atoms_sha256"] != marker["sha256"] or state["cue_execution_protocol_sha256"] != protocol_sha256:
        raise ContractError("执行状态未绑定当前冻结 Source 或执行协议")
    if state["status"] in {"received_completed", "received_failed"}:
        raise ContractError("该 Batch 已完成接收；禁止重复写入终态片段")
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        raise ContractError("缺少环境变量 DASHSCOPE_API_KEY；未发出请求")
    load_execution_authorization(arguments.authorization, settings, str(marker["sha256"]), protocol_sha256, arguments.wave_index, 0.0)
    manifests, atom_by_id, task = rebuild_task_for_receipt(state, arguments, settings, source_validator, prompt, schema, protocol_sha256)
    transport = BatchFileTransport(settings.endpoint, api_key)
    batch = poll_batch_until_terminal(transport, str(state["batch_id"]), settings, arguments.poll_attempts)
    if batch.get("id") != state["batch_id"] or batch.get("input_file_id") not in {None, state["remote_file_id"]}:
        raise ContractError("远端 Batch 身份或输入文件句柄漂移")
    remote_status = batch.get("status")
    receipt = {
        "run_id": state["run_id"], "wave_index": state["wave_index"], "batch_task_index": state["batch_task_index"],
        "batch_id": state["batch_id"], "remote_file_id": state["remote_file_id"],
        "output_file_id": batch.get("output_file_id"), "error_file_id": batch.get("error_file_id"),
        "batch_input_sha256": state["batch_input_sha256"], "source_atoms_sha256": state["source_atoms_sha256"],
        "cue_execution_protocol_sha256": state["cue_execution_protocol_sha256"], "status": remote_status,
        "request_count": state["request_count"], "received_at": utc_now(), "raw_response_saved": False,
    }
    if remote_status not in {"completed", "failed", "expired", "cancelled"}:
        receipt.update({"received_line_count": 0, "validated_count": 0, "service_line_failure_count": 0,
                        "local_validation_quarantine_count": 0, "remote_result_line_sha256": None, "remote_error_line_sha256": None})
        atomic_write_json(receipt_path(state_path.parent, int(state["batch_task_index"]), settings), receipt)
        return {"status": "pending", "batch_id": state["batch_id"], "network_called": True}
    if remote_status != "completed":
        receipt.update({"received_line_count": 0, "validated_count": 0, "service_line_failure_count": 0,
                        "local_validation_quarantine_count": 0, "remote_result_line_sha256": None, "remote_error_line_sha256": None})
        atomic_write_json(receipt_path(state_path.parent, int(state["batch_task_index"]), settings), receipt)
        state.update({"status": "received_failed", "received_at": utc_now(), "remote_status": remote_status})
        atomic_write_json(state_path, state)
        return {"status": "remote_batch_failed", "batch_id": state["batch_id"], "network_called": True}
    inference_validator = load_validator(arguments.inference_schema)
    cue_validator = load_validator(arguments.cue_schema)
    by_custom_id = {manifest["batch_custom_id"]: manifest for manifest in manifests}
    received: dict[str, tuple[str, list[dict[str, Any]], dict[str, Any]]] = {}
    result_hashes: list[str] = []
    error_hashes: list[str] = []
    for file_key, hash_sink in (("output_file_id", result_hashes), ("error_file_id", error_hashes)):
        file_id = batch.get(file_key)
        if file_id is None:
            continue
        if not isinstance(file_id, str) or not file_id:
            raise ContractError("远端结果文件 ID 无效")
        for line in transport.stream_jsonl_file(file_id):
            custom_id = line.get("custom_id")
            if not isinstance(custom_id, str) or custom_id in received:
                raise ContractError("远端结果 custom_id 重复或无效")
            state_name, cues, event = parse_batch_result_line(line, by_custom_id, atom_by_id, task, inference_validator, cue_validator, settings)
            event.update({"wave_index": state["wave_index"], "batch_id": state["batch_id"], "result_file_id": batch.get("output_file_id"), "error_file_id": batch.get("error_file_id")})
            received[custom_id] = (state_name, cues, event)
            hash_sink.append(event["result_line_sha256"])
    if set(received) != set(by_custom_id):
        raise ContractError("远端结果与冻结 custom_id 清单不构成一对一对应")
    events = [received[manifest["batch_custom_id"]][2] for manifest in manifests]
    validate_batch_ledger_events(events, settings)
    if len(events) != int(state["request_count"]):
        raise ContractError("接收终态数量与冻结请求数不一致")
    for manifest in manifests:
        state_name, cues, event = received[manifest["batch_custom_id"]]
        # package_id 已由全局 shard/package 编号固定；放在 batch 根目录使跨 wave 恢复和 T4
        # 汇总校验只需一处查找，wave 子目录仅保存远端 task 句柄与收据。
        save_package_terminal(manifest, cues, event, state_path.parent.parent, settings)
    receipt.update({
        "received_line_count": len(received), "validated_count": sum(event["outcome"] == "validated_success" for event in events),
        "service_line_failure_count": sum(event["outcome"] == "service_line_failure_requeueable" for event in events),
        "local_validation_quarantine_count": sum(event["outcome"] == "local_validation_quarantine" for event in events),
        "remote_result_line_sha256": canonical_sha256(result_hashes) if batch.get("output_file_id") is not None else None,
        "remote_error_line_sha256": canonical_sha256(error_hashes) if batch.get("error_file_id") is not None else None,
    })
    save_public_task_manifest(task, manifests, state_path.parent.parent, settings)
    atomic_write_json(receipt_path(state_path.parent, int(state["batch_task_index"]), settings), receipt)
    state.update({"status": "received_completed", "received_at": utc_now(), "remote_status": remote_status})
    atomic_write_json(state_path, state)
    return {"status": "received_completed", "batch_id": state["batch_id"], "network_called": True,
            "validated_count": receipt["validated_count"], "service_line_failure_count": receipt["service_line_failure_count"],
            "local_validation_quarantine_count": receipt["local_validation_quarantine_count"]}


def run(arguments: argparse.Namespace) -> int:
    """装配第 05 阶段；默认预检只读，提交和接收均须独立显式授权。"""

    if arguments.rerun_failed_packages:
        raise ContractError("失败 package 重跑必须在独立授权与 T4 审阅后启用")

    settings = settings_from_registry(arguments.model_registry)
    marker = verified_source(arguments.source_atoms, arguments.source_success)
    source_validator = load_validator(arguments.source_schema)
    # 即使当前只预检也加载冻结 Schema，确保成本核算不会建立在不存在或替换后的协议之上。
    load_validator(arguments.inference_schema)
    load_validator(arguments.cue_schema)
    prompt = arguments.prompt.read_text(encoding="utf-8")
    schema = read_json(arguments.inference_schema)
    # 预检不写可恢复工件，故使用稳定名称即可；正式 run_id 只能在未来获单独授权的执行阶段引入。
    run_id = arguments.run_id or "preflight_no_api"
    protocol_sha256 = protocol_hash(settings, arguments.prompt, arguments.inference_schema)
    if getattr(arguments, "receive", False):
        if getattr(arguments, "confirmation", "") != "RECEIVE_BATCH_RESULTS_API":
            raise ContractError("结果接收需要显式 confirmation=RECEIVE_BATCH_RESULTS_API")
        if getattr(arguments, "authorization", None) is None:
            raise ContractError("结果接收必须提供本机执行授权文件")
        result = receive_authorized_wave(
            arguments, settings, marker, source_validator, prompt, schema, protocol_sha256
        )
        print(json.dumps({"mode": "batch_wave_receive", **result}, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    if arguments.execute:
        if getattr(arguments, "confirmation", "") != "START_WAVE_1_API":
            raise ContractError("生产调用需要显式 confirmation=START_WAVE_1_API")
        if getattr(arguments, "authorization", None) is None:
            raise ContractError("生产调用必须提供本机执行授权文件")
        report = streaming_preflight_report(
            arguments.source_atoms, source_validator, str(marker["sha256"]), prompt, schema, settings, protocol_sha256, arguments.run_id or "wave_01"
        )
        result = submit_authorized_wave(arguments, settings, marker, source_validator, prompt, schema, protocol_sha256, load_execution_authorization(
            arguments.authorization, settings, str(marker["sha256"]), protocol_sha256, arguments.wave_index,
            execution_readiness_report(report, settings, str(marker["sha256"]), arguments.wave_index, arguments.authorization)["wave_cny_upper_bound_proxy"],
        ))
        print(json.dumps({"mode": "batch_wave_submitted", "network_called": True, **result}, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    report = streaming_preflight_report(
        arguments.source_atoms,
        source_validator,
        str(marker["sha256"]),
        prompt,
        schema,
        settings,
        protocol_sha256,
        run_id,
    )
    if getattr(arguments, "validate_execution_plan", False):
        readiness = execution_readiness_report(
            report, settings, str(marker["sha256"]), getattr(arguments, "wave_index", 1), getattr(arguments, "authorization", None)
        )
        print(json.dumps(readiness, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """定义只读默认值和执行前核验参数；`--execute` 仍需后续明确生产指令。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-registry", type=Path, default=ROOT / "config/model_registry.yaml")
    parser.add_argument("--source-atoms", type=Path, default=ROOT / "source/source_video_atoms.jsonl")
    parser.add_argument("--source-success", type=Path, default=ROOT / "source/SOURCE_ATOMS_SUCCESS.json")
    parser.add_argument("--source-schema", type=Path, default=ROOT / "schemas/source_video_atom.schema.json")
    parser.add_argument("--cue-schema", type=Path, default=ROOT / "schemas/cue_candidate.schema.json")
    parser.add_argument("--inference-schema", type=Path, default=ROOT / "schemas/cue_inference_batch_compact_v1.schema.json")
    parser.add_argument("--prompt", type=Path, default=ROOT / "prompts/cue_extractor_v3_compact.md")
    parser.add_argument("--run-root", type=Path, default=ROOT / "cues/batch")
    parser.add_argument("--output", type=Path, default=ROOT / "cues/cue_library.jsonl")
    parser.add_argument("--success-marker", type=Path, default=ROOT / "cues/CUE_LIBRARY_SUCCESS.json")
    parser.add_argument("--run-id")
    parser.add_argument("--authorization", type=Path, help="本机未提交的执行授权 JSON")
    parser.add_argument("--wave-index", type=int, default=1, help="八波计划中的目标波次（1--8）")
    parser.add_argument("--validate-execution-plan", action="store_true", help="只校验授权、波次和预算，绝不联网")
    parser.add_argument("--confirmation", default="", help="提交或接收的显式 API 确认短语")
    parser.add_argument("--execute", action="store_true", help="提交首波 Batch；需授权文件和显式 confirmation")
    parser.add_argument("--receive", action="store_true", help="接收已提交 Batch 的结果；需独立确认和授权")
    parser.add_argument("--poll-attempts", type=int, default=1, help="接收命令内的最多轮询次数；默认一次")
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
