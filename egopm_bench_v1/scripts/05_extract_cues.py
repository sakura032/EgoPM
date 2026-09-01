#!/usr/bin/env python3
"""第 05 阶段：为冻结 Source Atom 构建 v2.2 Batch File 的无 API 计划。

职责：验证冻结 Source、紧凑提示词和 Schema，并只在内存中生成五条 Atom package、Batch
任务元数据与费用预检。输入是 Source SUCCESS、Source Atom、模型配置、提示词和 Schema；
输出是只读预检报告及供合成测试使用的无正文解析函数。它位于 Source QA 后、Cue QA 前，
当前合同明确禁止上传、下载、调用模型、写正式 Cue 或 SUCCESS。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

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
        "cue_execution_policy_version": "v2.2.0",
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
        or cue.get("model_id") != "qwen3.7-flash-2026-07-15" or cue.get("thinking_enabled") is not False
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


def build_batch_tasks(manifests: list[dict[str, Any]], atom_by_id: dict[str, dict[str, Any]], prompt: str, schema: dict[str, Any], settings: Settings) -> list[dict[str, Any]]:
    """按十个逻辑 shard 构建 Batch 任务计划，并在内存中检查每项/每文件大小。"""

    tasks: list[dict[str, Any]] = []
    per_task = int(settings.batch_file_policy["logical_shards_per_task"])
    maximum_shard = max((m["shard_index"] for m in manifests), default=-1)
    for task_index, first_shard in enumerate(range(0, maximum_shard + 1, per_task)):
        selected = [m for m in manifests if first_shard <= m["shard_index"] < first_shard + per_task]
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
            "source_atoms_sha256": selected[0]["source_atoms_sha256"] if selected else "",
            "cue_execution_protocol_sha256": selected[0]["cue_execution_protocol_sha256"] if selected else "",
            "batch_input_sha256": hashlib.sha256(serialized).hexdigest(), "request_count": len(lines),
            "custom_ids_sha256": canonical_sha256(custom_ids), "logical_shard_start": first_shard,
            # 末个 task 常不足十个 shard；记录实际边界避免恢复时虚构不存在的 Source 范围。
            "logical_shard_end": max(manifest["shard_index"] for manifest in selected), "remote_file_id": None,
            "status": "planned_no_api", "request_lines": lines,
        })
    return tasks


def public_batch_task_manifest(task: dict[str, Any]) -> dict[str, Any]:
    """剥离临时请求正文后生成可保存的任务元数据，防止 Git 或账本留存原文。"""

    allowed = {
        "run_id", "batch_task_index", "source_atoms_sha256", "cue_execution_protocol_sha256",
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
    if result_line.get("error") is not None:
        return "line_failed_requeue", [], batch_ledger_event(manifest, task, "service_line_failure_requeueable", "remote_line_error", {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}, "服务端行级失败；可重新组批")
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
        return "validated", cues, batch_ledger_event(manifest, task, "validated_success", "validated", usage)
    except (ContractError, KeyError, IndexError, TypeError, json.JSONDecodeError):
        # 本地语义验证失败说明服务端已成功完成，自动重传会造成重复收费，因此只能隔离并人工决策。
        return "quarantine", [], batch_ledger_event(manifest, task, "local_validation_quarantine", "local_validation_failed", {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}, "服务端成功但本地合同验证失败；禁止自动重试")


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


def run(arguments: argparse.Namespace) -> int:
    """装配第 05 阶段；当前 CR 只允许预检，任何执行开关都在本地合同门阻断。"""

    if arguments.execute or arguments.rerun_failed_packages:
        raise ContractError("v2.2 当前仅允许无 API 预检；禁止创建 Batch、上传文件、下载结果或写正式 Cue")

    settings = settings_from_registry(arguments.model_registry)
    marker = verified_source(arguments.source_atoms, arguments.source_success)
    source_validator = load_validator(arguments.source_schema)
    # 即使当前只预检也加载冻结 Schema，确保成本核算不会建立在不存在或替换后的协议之上。
    load_validator(arguments.inference_schema)
    load_validator(arguments.cue_schema)
    atoms = ordered_atoms(read_jsonl(arguments.source_atoms))
    for atom in atoms:
        validate_record(source_validator, atom, "Source Atom")
    prompt = arguments.prompt.read_text(encoding="utf-8")
    schema = read_json(arguments.inference_schema)
    # 预检不写可恢复工件，故使用稳定名称即可；正式 run_id 只能在未来获单独授权的执行阶段引入。
    run_id = arguments.run_id or "preflight_no_api"
    protocol_sha256 = protocol_hash(settings, arguments.prompt, arguments.inference_schema)
    manifests = build_packages(atoms, str(marker["sha256"]), prompt, schema, settings, protocol_sha256, run_id)
    report = preflight_report(manifests, atoms, prompt, schema, settings, protocol_sha256)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """定义只读默认值；保留执行参数仅为明确报错，不能触及密钥或网络。"""

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
    parser.add_argument("--execute", action="store_true", help="当前无 API 阶段必定被合同门阻断")
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
