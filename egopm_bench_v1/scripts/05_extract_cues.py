#!/usr/bin/env python3
"""第 05 阶段：从冻结 Source Atom 分片提取 Cue。

输入是已验证的 Source Atom、模型登记、提示词和 Cue Schema；输出（仅显式执行时）是
固定顺序的 shard 输入清单、Cue JSONL、完成标记和不含原始响应的账本，全部完成后才可
合并正式线索库。默认预检严格只读：不读密钥、不访问网络、不写 Cue 或 SUCCESS。
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
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_VERSION = CONFIG_VERSION = SOURCE_SCHEMA_VERSION = "v1.1.0"
CUE_SCHEMA_VERSION, EXPECTED_MODEL_ID, PROMPT_VERSION = "v1.0.0", "qwen3.7-flash-2026-07-15", "cue_extractor_v1"
SUCCESS_FIELDS = {"artifact_path", "sha256", "row_count", "contract_version", "config_version", "schema_versions", "generated_at", "upstream_hashes"}


class ContractError(RuntimeError):
    """合同、哈希、配置、输入或恢复状态不符合冻结要求。"""


@dataclass(frozen=True)
class Settings:
    """从冻结登记读取的模型、限额和 shard 版式；禁止用隐式默认值替代。"""
    endpoint: str; credential: str; region: str; max_tokens: int; max_retries: int
    shard_size: int; rpm: int; tpm: int; layout: dict[str, str]


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try: value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error: raise ContractError(f"无法读取 JSON：{path}") from error
    if not isinstance(value, dict): raise ContractError(f"JSON 根节点必须是 object：{path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    try: lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error: raise ContractError(f"无法读取 JSONL：{path}") from error
    result = []
    for number, line in enumerate(lines, 1):
        if not line.strip(): raise ContractError(f"JSONL 不允许空行：{path}:{number}")
        try: row = json.loads(line)
        except json.JSONDecodeError as error: raise ContractError(f"JSONL 不是有效 JSON：{path}:{number}") from error
        if not isinstance(row, dict): raise ContractError(f"JSONL 行必须是 object：{path}:{number}")
        result.append(row)
    return result


def _declares_artifact(marker: dict[str, Any], artifact: Path) -> bool:
    """相对 artifact_path 只能以项目根为锚；拒绝 ``..`` 与 marker 相邻目录猜测。"""
    declared = Path(str(marker["artifact_path"]))
    if declared.is_absolute(): return declared.resolve() == artifact.resolve()
    if ".." in declared.parts: return False
    try: candidate = (ROOT / declared).resolve(); candidate.relative_to(ROOT.resolve())
    except ValueError: return False
    return candidate == artifact.resolve()


def require_verified_success(artifact: Path, marker_path: Path, expected_schema_version: str) -> dict[str, Any]:
    """先验证 SUCCESS、项目内路径、哈希和行数，避免未冻结输入进入任何后续阶段。"""
    if not artifact.is_file() or not marker_path.is_file(): raise ContractError("缺少正式输入或 SUCCESS 标记")
    marker = read_json(marker_path)
    if missing := SUCCESS_FIELDS - marker.keys(): raise ContractError(f"SUCCESS 标记缺字段：{sorted(missing)}")
    if marker["contract_version"] != CONTRACT_VERSION or marker["config_version"] != CONFIG_VERSION: raise ContractError("SUCCESS 版本不兼容")
    if expected_schema_version not in json.dumps(marker["schema_versions"], ensure_ascii=False): raise ContractError("SUCCESS 未声明预期 Schema")
    if not _declares_artifact(marker, artifact): raise ContractError("SUCCESS 的 artifact_path 与项目内实际输入不一致")
    if marker["sha256"] != sha256_file(artifact): raise ContractError("SUCCESS SHA256 与输入不匹配")
    if not isinstance(marker["row_count"], int) or marker["row_count"] != len(read_jsonl(artifact)): raise ContractError("SUCCESS row_count 与输入不匹配")
    return marker


def load_yaml(path: Path) -> dict[str, Any]:
    try: value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error: raise ContractError(f"无法读取 YAML：{path}") from error
    if not isinstance(value, dict): raise ContractError("YAML 根节点必须是 object")
    return value


def _positive(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0: raise ContractError(f"{label} 必须是正整数")
    return value


def load_runtime_settings(path: Path) -> Settings:
    """严格读取 T0 冻结的 ``cue_extraction.execution``，任何漂移都阻断预检和执行。"""
    registry = load_yaml(path); cue = registry.get("models", {}).get("cue_extraction", {}); execution = cue.get("execution")
    if registry.get("contract_version") != CONTRACT_VERSION or registry.get("config_version") != CONFIG_VERSION: raise ContractError("model_registry 版本不兼容")
    if cue.get("model_id") != EXPECTED_MODEL_ID or cue.get("prompt_version") != PROMPT_VERSION or cue.get("thinking_enabled") is not False or cue.get("temperature") != 0 or cue.get("schema_version") != CUE_SCHEMA_VERSION: raise ContractError("Cue 模型或请求参数未按冻结值设置")
    if not isinstance(execution, dict) or execution.get("cue_execution_policy_version") != "v1.0.0" or execution.get("mode") != "explicit_execute_only": raise ContractError("cue_extraction.execution 未按冻结策略设置")
    limit, accounting, layout, recovery = execution.get("rate_limit_policy"), execution.get("token_accounting"), execution.get("shard_layout"), execution.get("recovery")
    if not all(isinstance(v, dict) for v in (limit, accounting, layout, recovery)): raise ContractError("execution 缺少限速、计量、布局或恢复配置")
    if accounting != {"authoritative_source": "response_usage", "input_field": "prompt_tokens", "output_field": "completion_tokens", "total_field": "total_tokens", "preflight_upper_bound": "serialized_utf8_request_bytes", "raw_response_storage": "forbidden"}: raise ContractError("token_accounting 未冻结为服务端 usage 且禁止原始响应")
    expected_layout = {"root": "cues/shards", "input_manifest_suffix": ".input.jsonl", "output_suffix": ".output.jsonl", "ledger_suffix": ".ledger.jsonl", "completion_suffix": ".complete.json", "merge_order": "numeric_shard_index_ascending"}
    if layout != expected_layout or recovery != {"require_matching_source_hash": True, "rerun_only_incomplete_or_failed_shards": True, "completion_marker_requires_sha256": True}: raise ContractError("shard 布局或恢复策略未按冻结值设置")
    if registry.get("credential_environment_variable") != "DASHSCOPE_API_KEY" or registry.get("credential_policy") != "environment_only": raise ContractError("凭据策略不兼容")
    endpoint, region = registry.get("default_endpoint"), registry.get("default_region")
    if not isinstance(endpoint, str) or not endpoint.startswith("https://") or not isinstance(region, str) or not region: raise ContractError("endpoint 或 region 无效")
    return Settings(endpoint.rstrip("/"), "DASHSCOPE_API_KEY", region, _positive(execution.get("max_tokens"), "max_tokens"), _positive(execution.get("max_retries", 0) + 1, "max_retries+1") - 1, _positive(execution.get("shard_size_atoms"), "shard_size_atoms"), _positive(limit.get("target_requests_per_minute"), "target_requests_per_minute"), _positive(limit.get("target_total_tokens_per_minute"), "target_total_tokens_per_minute"), expected_layout)


def load_validator(path: Path) -> jsonschema.Draft202012Validator:
    schema = read_json(path)
    try: jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as error: raise ContractError("Schema 无效") from error
    return jsonschema.Draft202012Validator(schema)


def validate_instance(validator: jsonschema.Draft202012Validator, row: dict[str, Any], label: str) -> None:
    errors = list(validator.iter_errors(row))
    if errors: raise ContractError(f"{label} 未通过 Schema：{errors[0].message}")


def cue_id_for(atom_id: str) -> str: return f"cue_{atom_id.removeprefix('src_')}"
def make_run_id(requested: str | None) -> str: return requested or f"run_cue_{uuid.uuid4().hex[:16]}"


def build_chat_request(*, prompt: str, schema: dict[str, Any], atom: dict[str, Any], run_id: str, settings: Settings) -> dict[str, Any]:
    """只把可见文本传入固定 JSON Schema 请求，防止路径和隐藏来源信息泄漏。"""
    controlled = {"cue_id": cue_id_for(str(atom["atom_id"])), "atom_id": atom["atom_id"], "split": atom["split"], "source_text": atom["visible_text"], "model_id": EXPECTED_MODEL_ID, "prompt_version": PROMPT_VERSION, "schema_version": CUE_SCHEMA_VERSION, "run_id": run_id}
    return {"model": EXPECTED_MODEL_ID, "temperature": 0, "max_tokens": settings.max_tokens, "enable_thinking": False, "stream": False, "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": json.dumps({"instruction": "请按系统提示词和 response_format 输出一个 cue candidate。", "prefilled_contract_fields": controlled, "visible_text": atom["visible_text"]}, ensure_ascii=False)}], "response_format": {"type": "json_schema", "json_schema": {"name": "cue_candidate", "strict": True, "schema": schema}}}


def response_usage(response: dict[str, Any]) -> dict[str, int | None]:
    """账本只记录服务端数字 usage；模型原始响应和内容绝不可被持久化。"""
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    return {key: usage.get(key) if isinstance(usage.get(key), int) and usage[key] >= 0 else None for key in ("prompt_tokens", "completion_tokens", "total_tokens")}


def _content(response: dict[str, Any]) -> str:
    try: content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error: raise ContractError("响应缺少结构化 content") from error
    if not isinstance(content, str): raise ContractError("响应 content 必须是字符串")
    return content


def call_structured_qwen(*, settings: Settings, payload: dict[str, Any], timeout_sec: float, opener: Callable[..., Any] = urlopen) -> tuple[dict[str, Any], int, dict[str, int | None]]:
    """此函数仅由显式执行守卫调用；密钥只在这一分支由环境变量读取。"""
    key = os.environ.get(settings.credential)
    if not key: raise ContractError("未设置 DASHSCOPE_API_KEY")
    request = Request(settings.endpoint + "/chat/completions", data=json.dumps(payload, ensure_ascii=False).encode(), headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    last: Exception | None = None
    for retry in range(settings.max_retries + 1):
        try:
            with opener(request, timeout=timeout_sec) as handle: response = json.loads(handle.read().decode())
            value = json.loads(_content(response))
            if not isinstance(value, dict): raise ContractError("结构化结果根节点必须是 object")
            return value, retry, response_usage(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            last = error
            if retry == settings.max_retries: break
            time.sleep(min(2 ** retry, 4))
    raise ContractError("千问调用耗尽重试次数") from last


def validate_cue_semantics(atom: dict[str, Any], cue: dict[str, Any]) -> None:
    for field, value in {"cue_id": cue_id_for(str(atom["atom_id"])), "atom_id": atom["atom_id"], "split": atom["split"], "source_text": atom["visible_text"], "model_id": EXPECTED_MODEL_ID, "prompt_version": PROMPT_VERSION, "schema_version": CUE_SCHEMA_VERSION}.items():
        if cue.get(field) != value: raise ContractError(f"cue 的 {field} 与受控输入不一致")
    if cue.get("supporting_text_span") not in str(atom["visible_text"]): raise ContractError("cue supporting_text_span 不是原文连续子串")
    if not any(part.get("slot") == cue.get("cue_type") for part in cue.get("normalized_predicate", {}).get("all_of", [])): raise ContractError("cue 谓词缺少对应 cue_type")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"); temp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows: handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    temp.replace(path)


def sorted_atoms(atoms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = sorted(atoms, key=lambda item: str(item.get("atom_id", ""))); ids = [str(row.get("atom_id", "")) for row in rows]
    if not all(ids) or len(ids) != len(set(ids)): raise ContractError("atom_id 必须非空且唯一，才能固定分片")
    return rows


def manifests(atoms: list[dict[str, Any]], source_sha: str, shard_size: int, run_id: str) -> list[dict[str, Any]]:
    """每个 manifest 有独立的有序输入 ID 与行哈希，恢复时不依赖易变的内存状态。"""
    ordered = sorted_atoms(atoms); result = []
    for index, offset in enumerate(range(0, len(ordered), shard_size)):
        rows = ordered[offset:offset + shard_size]
        result.append({"run_id": run_id, "shard_index": index, "shard_id": f"shard_{index:05d}", "source_atoms_sha256": source_sha, "atoms": [{"atom_id": row["atom_id"], "atom_sha256": stable_hash(row)} for row in rows]})
    return result


def paths(run_root: Path, manifest: dict[str, Any], layout: dict[str, str]) -> dict[str, Path]:
    base = run_root / manifest["shard_id"]
    return {"manifest": base / (manifest["shard_id"] + layout["input_manifest_suffix"]), "output": base / (manifest["shard_id"] + layout["output_suffix"]), "ledger": base / (manifest["shard_id"] + layout["ledger_suffix"]), "complete": base / (manifest["shard_id"] + layout["completion_suffix"])}


def _complete(manifest: dict[str, Any], file_paths: dict[str, Path]) -> bool:
    # ledger 与候选输出同属可消费边界；缺失或篡改账本时必须重跑，不能静默跳过 shard。
    if not all(file_paths[key].is_file() for key in ("manifest", "output", "ledger", "complete")): return False
    try:
        marker = read_json(file_paths["complete"])
        # 标记自己的哈希不足以说明它属于当前输入；必须逐项匹配重新构造的固定清单。
        if read_jsonl(file_paths["manifest"]) != manifest["atoms"]: return False
    except ContractError: return False
    return marker.get("source_atoms_sha256") == manifest["source_atoms_sha256"] and marker.get("input_manifest_sha256") == sha256_file(file_paths["manifest"]) and marker.get("output_sha256") == sha256_file(file_paths["output"]) and marker.get("ledger_sha256") == sha256_file(file_paths["ledger"]) and marker.get("shard_id") == manifest["shard_id"]


def pending_shards(shard_manifests: list[dict[str, Any]], run_root: Path, layout: dict[str, str]) -> list[dict[str, Any]]:
    """只挑选缺失、失败或哈希不匹配 shard，已完成 shard 不会被重复请求。"""
    return [item for item in shard_manifests if not _complete(item, paths(run_root, item, layout))]


def merge_completed_shards(shard_manifests: list[dict[str, Any]], run_root: Path, layout: dict[str, str], target: Path) -> int:
    missing = pending_shards(shard_manifests, run_root, layout)
    if missing: raise ContractError(f"禁止合并：{len(missing)} 个 shard 尚未完成")
    rows: list[dict[str, Any]] = []
    for item in sorted(shard_manifests, key=lambda row: row["shard_index"]): rows.extend(read_jsonl(paths(run_root, item, layout)["output"]))
    write_jsonl(target, rows); return len(rows)


def token_bounds(atoms: list[dict[str, Any]], prompt: str, schema: dict[str, Any], run_id: str, settings: Settings) -> dict[str, Any]:
    sizes = [len(json.dumps(build_chat_request(prompt=prompt, schema=schema, atom=row, run_id=run_id, settings=settings), ensure_ascii=False, separators=(",", ":")).encode()) for row in atoms]
    count, input_upper, output_upper = len(atoms), sum(sizes), len(atoms) * settings.max_tokens
    return {"authoritative_at_runtime": "response_usage.prompt_tokens/completion_tokens/total_tokens", "preflight_upper_bound": "serialized_utf8_request_bytes", "input_tokens_lower_bound": count, "input_tokens_upper_bound": input_upper, "output_tokens_lower_bound": 0, "output_tokens_upper_bound": output_upper, "total_tokens_upper_bound": input_upper + output_upper, "max_request_utf8_bytes": max(sizes, default=0), "estimated_minimum_minutes_at_target_limits": max(count / settings.rpm, (input_upper + output_upper) / settings.tpm) if count else 0}


def preflight(atoms: list[dict[str, Any]], marker: dict[str, Any], prompt: str, schema: dict[str, Any], run_id: str, settings: Settings) -> dict[str, Any]:
    shard_manifests = manifests(atoms, marker["sha256"], settings.shard_size, run_id)
    return {"mode": "preflight", "network_called": False, "credentials_read": False, "formal_outputs_written": False, "run_id": run_id, "atom_count": len(atoms), "source_atoms_sha256": marker["sha256"], "shard_size_atoms": settings.shard_size, "shard_count": len(shard_manifests), "last_shard_atom_count": len(shard_manifests[-1]["atoms"]) if shard_manifests else 0, "max_tokens": settings.max_tokens, "max_retries": settings.max_retries, "target_requests_per_minute": settings.rpm, "target_total_tokens_per_minute": settings.tpm, "token_statistics": token_bounds(atoms, prompt, schema, run_id, settings), "recovery": "匹配输入清单、来源哈希、输出 SHA256 和完成标记的 shard 跳过；其余 shard 独立重跑；仅全部完成后按数字编号合并"}


def append_ledger(path: Path, event: dict[str, Any]) -> None:
    """逐请求立即持久化无正文账本，使中断、重试与服务端 usage 可审计且不泄漏响应。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"); handle.flush(); os.fsync(handle.fileno())


def execute_shard(manifest: dict[str, Any], atom_map: dict[str, dict[str, Any]], run_root: Path, prompt: str, schema: dict[str, Any], validator: jsonschema.Draft202012Validator, run_id: str, settings: Settings, timeout: float) -> None:
    file_paths = paths(run_root, manifest, settings.layout); write_jsonl(file_paths["manifest"], manifest["atoms"]); cues = []
    for item in manifest["atoms"]:
        atom = atom_map[item["atom_id"]]; event = {"event_type": "request", "run_id": run_id, "shard_id": manifest["shard_id"], "atom_id": atom["atom_id"], "requested_at": now(), "model_id": EXPECTED_MODEL_ID, "raw_response_saved": False}
        try:
            cue, retry, usage = call_structured_qwen(settings=settings, payload=build_chat_request(prompt=prompt, schema=schema, atom=atom, run_id=run_id, settings=settings), timeout_sec=timeout)
            validate_instance(validator, cue, "cue"); validate_cue_semantics(atom, cue)
            event.update({"status": "success", "retry_count": retry, "usage": usage, "failure_category": None, "failure_summary": None})
            if cue.get("validation_status") == "accepted": cues.append(cue)
        except Exception as error:
            event.update({"status": "failed", "retry_count": settings.max_retries, "usage": {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}, "failure_category": type(error).__name__, "failure_summary": str(error)[:160].replace("\n", " ")}); append_ledger(file_paths["ledger"], event); raise
        append_ledger(file_paths["ledger"], event)
    write_jsonl(file_paths["output"], cues)
    write_json(file_paths["complete"], {"run_id": run_id, "shard_id": manifest["shard_id"], "source_atoms_sha256": manifest["source_atoms_sha256"], "input_manifest_sha256": sha256_file(file_paths["manifest"]), "output_sha256": sha256_file(file_paths["output"]), "ledger_sha256": sha256_file(file_paths["ledger"]), "completed_at": now(), "raw_response_saved": False})


def run(args: argparse.Namespace) -> int:
    settings = load_runtime_settings(args.model_registry); marker = require_verified_success(args.source_atoms, args.source_success, SOURCE_SCHEMA_VERSION)
    source_validator, cue_validator, schema = load_validator(args.source_schema), load_validator(args.cue_schema), read_json(args.cue_schema); prompt = args.prompt.read_text(encoding="utf-8")
    if not prompt.strip(): raise ContractError("Cue 提示词不能为空")
    atoms = sorted_atoms(read_jsonl(args.source_atoms))
    for atom in atoms: validate_instance(source_validator, atom, "source atom")
    run_id = make_run_id(args.run_id); report = preflight(atoms, marker, prompt, schema, run_id, settings)
    if not args.execute: print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)); return 0
    # 默认路径绝不可触网；仅经过预算审批的 ``--execute`` 才能走到此处读取环境变量。
    run_root = args.run_root / run_id; shard_manifests = manifests(atoms, marker["sha256"], settings.shard_size, run_id); write_json(run_root / "run_metadata.json", {**report, "mode": "execute", "started_at": now(), "raw_response_saved": False})
    atom_map = {atom["atom_id"]: atom for atom in atoms}
    for manifest in pending_shards(shard_manifests, run_root, settings.layout): execute_shard(manifest, atom_map, run_root, prompt, schema, cue_validator, run_id, settings, args.timeout_sec)
    count = merge_completed_shards(shard_manifests, run_root, settings.layout, args.output)
    write_json(args.success_marker, {"artifact_path": str(args.output.resolve()), "sha256": sha256_file(args.output), "row_count": count, "contract_version": CONTRACT_VERSION, "config_version": CONFIG_VERSION, "schema_versions": {"cue_candidate": CUE_SCHEMA_VERSION}, "generated_at": now(), "upstream_hashes": {"source_atoms": marker["sha256"]}, "run_id": run_id, "raw_response_path": None})
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-registry", type=Path, default=ROOT / "config/model_registry.yaml"); parser.add_argument("--source-atoms", type=Path, default=ROOT / "source/source_video_atoms.jsonl"); parser.add_argument("--source-success", type=Path, default=ROOT / "source/SOURCE_ATOMS_SUCCESS.json"); parser.add_argument("--source-schema", type=Path, default=ROOT / "schemas/source_video_atom.schema.json"); parser.add_argument("--cue-schema", type=Path, default=ROOT / "schemas/cue_candidate.schema.json"); parser.add_argument("--prompt", type=Path, default=ROOT / "prompts/cue_extractor_v1.md"); parser.add_argument("--run-root", type=Path, default=ROOT / "cues/shards"); parser.add_argument("--output", type=Path, default=ROOT / "cues/cue_library.jsonl"); parser.add_argument("--success-marker", type=Path, default=ROOT / "cues/CUE_LIBRARY_SUCCESS.json"); parser.add_argument("--run-id"); parser.add_argument("--timeout-sec", type=float, default=60); parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if args.timeout_sec <= 0: parser.error("timeout-sec 必须大于零")
    return args


def main() -> int:
    try: return run(parse_args())
    except ContractError as error: print(f"合同门禁失败：{error}", file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
