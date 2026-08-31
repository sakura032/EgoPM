#!/usr/bin/env python3
"""第 07 阶段：从已验证线索和诱饵集合生成待人工审计的种子候选。

职责是在第 05、06 阶段成功后，以固定的千问 Plus 模型将来源原子、线索库和
``trigger_lure_sets.jsonl`` 生成 ``reminder_seed_candidates.jsonl`` 与成功标记；
该脚本位于人工审计和 Seed 冻结之前。输入必须都带有哈希匹配的成功标记，输出只写
``candidate`` 状态且通过提醒种子 JSON Schema 和硬条件校验的候选；不冻结种子，也
不生成任何提醒/静默金标。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import jsonschema
import yaml


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_MODEL_ID = "qwen3.7-plus-2026-05-26"
PROMPT_VERSION = "seed_generator_v1"
CONTRACT_VERSION = "v1.0.0"
CONFIG_VERSION = "v1.0.0"
REQUIRED_TERMINAL_CONDITIONS = {"completed", "cancelled", "expired", "already_reminded"}
SUCCESS_REQUIRED_FIELDS = {
    "artifact_path",
    "sha256",
    "row_count",
    "contract_version",
    "config_version",
    "schema_versions",
    "generated_at",
    "upstream_hashes",
}


class ContractError(RuntimeError):
    """输入、模型或输出违背冻结合同。"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"无法读取 JSON 文件：{path}") from error
    if not isinstance(value, dict):
        raise ContractError(f"JSON 根节点必须是 object：{path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ContractError(f"无法读取 JSONL 文件：{path}") from error
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise ContractError(f"JSONL 不允许空行：{path}:{line_number}")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ContractError(f"JSONL 不是有效 JSON：{path}:{line_number}") from error
        if not isinstance(value, dict):
            raise ContractError(f"JSONL 行必须是 object：{path}:{line_number}")
        rows.append(value)
    return rows


def _declares_artifact(marker: dict[str, Any], artifact: Path, marker_path: Path) -> bool:
    declared = Path(str(marker["artifact_path"]))
    candidates = [declared] if declared.is_absolute() else [
        marker_path.parent / declared,
        ROOT.parent / declared,
        artifact.parent / declared,
    ]
    return any(candidate.resolve() == artifact.resolve() for candidate in candidates)


def require_verified_success(artifact: Path, marker_path: Path) -> dict[str, Any]:
    # 下游生成前验证 artifact 与标记，防止未完成或已被替换的上游数据进入提示词。
    if not artifact.is_file() or not marker_path.is_file():
        raise ContractError(f"缺少正式输入或 SUCCESS 标记：{artifact}；{marker_path}")
    marker = read_json(marker_path)
    missing = SUCCESS_REQUIRED_FIELDS.difference(marker)
    if missing:
        raise ContractError(f"SUCCESS 标记缺少字段：{sorted(missing)}")
    if marker["contract_version"] != CONTRACT_VERSION or marker["config_version"] != CONFIG_VERSION:
        raise ContractError("SUCCESS 标记版本不兼容")
    if not isinstance(marker["row_count"], int) or marker["row_count"] < 0:
        raise ContractError("SUCCESS 标记 row_count 无效")
    if not isinstance(marker["upstream_hashes"], (dict, list)):
        raise ContractError("SUCCESS 标记 upstream_hashes 无效")
    if not _declares_artifact(marker, artifact, marker_path):
        raise ContractError("SUCCESS 标记 artifact_path 与输入不一致")
    if marker["sha256"] != sha256_file(artifact):
        raise ContractError("SUCCESS 标记 SHA256 与输入不匹配")
    if marker["row_count"] != len(read_jsonl(artifact)):
        raise ContractError("SUCCESS 标记 row_count 与输入不匹配")
    return marker


def require_direct_upstream(marker: dict[str, Any], name: str, expected_hash: str) -> None:
    upstream_hashes = marker["upstream_hashes"]
    if not isinstance(upstream_hashes, dict) or upstream_hashes.get(name) != expected_hash:
        # 不仅单文件哈希正确，还要保证 cue 和检索确实建立在本次来源版本上。
        raise ContractError(f"上游 SUCCESS 标记未绑定预期 {name} 哈希")


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ContractError(f"无法读取 YAML 配置：{path}") from error
    if not isinstance(value, dict):
        raise ContractError(f"YAML 根节点必须是 object：{path}")
    return value


def load_runtime_settings(model_registry: Path) -> tuple[str, str, str, dict[str, Any]]:
    registry = load_yaml(model_registry)
    seed_settings = registry.get("models", {}).get("seed_generation", {})
    # 与第 05 阶段一致，代码常量和冻结登记同时校验，以阻止模型或采样参数无审计漂移。
    if registry.get("contract_version") != CONTRACT_VERSION:
        raise ContractError("model_registry 合同版本不兼容")
    if seed_settings.get("model_id") != EXPECTED_MODEL_ID:
        raise ContractError("Seed 模型必须固定为 qwen3.7-plus-2026-05-26")
    if seed_settings.get("prompt_version") != PROMPT_VERSION:
        raise ContractError("Seed 提示词版本不兼容")
    if seed_settings.get("temperature") != 0:
        raise ContractError("Seed 温度必须为 0")
    endpoint = registry.get("default_endpoint")
    key_name = registry.get("credential_environment_variable")
    if not isinstance(endpoint, str) or not endpoint.startswith("https://"):
        raise ContractError("model_registry 的 endpoint 无效")
    if key_name != "DASHSCOPE_API_KEY" or registry.get("credential_policy") != "environment_only":
        raise ContractError("凭据配置必须只读取 DASHSCOPE_API_KEY 环境变量")
    region = registry.get("default_region")
    if not isinstance(region, str) or not region:
        raise ContractError("model_registry 的 region 无效")
    return endpoint.rstrip("/"), key_name, region, seed_settings


def load_validator(path: Path) -> jsonschema.Draft202012Validator:
    schema = read_json(path)
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as error:
        raise ContractError(f"Schema 无效：{path}") from error
    return jsonschema.Draft202012Validator(schema)


def validate_rows(
    rows: list[dict[str, Any]], validator: jsonschema.Draft202012Validator, label: str
) -> None:
    for index, row in enumerate(rows, start=1):
        errors = sorted(validator.iter_errors(row), key=lambda item: list(item.path))
        if errors:
            raise ContractError(f"{label} 第 {index} 行未通过 Schema：{errors[0].message}")


def validate_retrieval_rows(rows: list[dict[str, Any]]) -> None:
    required = {
        "retrieval_id",
        "cue_id",
        "trigger_atom_id",
        "split",
        "source_group_id",
        "lure_atom_ids",
        "run_id",
        "schema_version",
    }
    seen: set[str] = set()
    for row in rows:
        missing = required.difference(row)
        if missing:
            raise ContractError(f"trigger/lure 集缺少字段：{sorted(missing)}")
        if row["retrieval_id"] in seen:
            raise ContractError("trigger/lure 集存在重复 retrieval_id")
        seen.add(row["retrieval_id"])
        if row["schema_version"] != CONTRACT_VERSION:
            raise ContractError("trigger/lure 集 Schema 版本不兼容")
        lure_ids = row["lure_atom_ids"]
        if not isinstance(lure_ids, list) or len(lure_ids) < 2 or len(set(lure_ids)) != len(lure_ids):
            raise ContractError("每个 trigger/lure 集至少需要两个不同 lure")


def seed_identifiers(index: int) -> dict[str, str | list[str]]:
    suffix = f"{index:04d}"
    return {
        "seed_id": f"seed_candidate_{suffix}",
        "family_id": f"family_candidate_{suffix}",
        "intention_id": f"int_candidate_{suffix}",
        "rule_ids": [f"rule_candidate_{suffix}"],
    }


def build_chat_request(
    *,
    prompt: str,
    schema: dict[str, Any],
    cue: dict[str, Any],
    trigger: dict[str, Any],
    lures: list[dict[str, Any]],
    identifiers: dict[str, str | list[str]],
    run_id: str,
    thinking_settings: dict[str, Any],
) -> dict[str, Any]:
    # 预填受控 ID 与链接字段，让模型只决定候选语义，不能重写来源、split 或运行血缘。
    prefilled = {
        "seed_id": identifiers["seed_id"],
        "family_id": identifiers["family_id"],
        "split": trigger["split"],
        "source_group_id": trigger["source_group_id"],
        "intention_id": identifiers["intention_id"],
        "primary_cue_type": cue["cue_type"],
        "trigger_atom_id": trigger["atom_id"],
        "lure_atom_ids": [lure["atom_id"] for lure in lures],
        "rule_ids": identifiers["rule_ids"],
        "generation_record": {
            "run_id": run_id,
            "model_id": EXPECTED_MODEL_ID,
            "prompt_version": PROMPT_VERSION,
            "schema_version": CONTRACT_VERSION,
        },
    }
    user_input = {
        "instruction": "请按系统提示词和 response_format 生成一个待人工审计的 Seed candidate。",
        "prefilled_contract_fields": prefilled,
        "trigger_cue": cue,
        "trigger_atom": {"atom_id": trigger["atom_id"], "split": trigger["split"], "visible_text": trigger["visible_text"]},
        "lure_atoms": [
            {"atom_id": lure["atom_id"], "split": lure["split"], "visible_text": lure["visible_text"]}
            for lure in lures
        ],
    }
    return {
        "model": EXPECTED_MODEL_ID,
        "temperature": 0,
        "stream": False,
        "enable_thinking": bool(thinking_settings.get("thinking_enabled")),
        "reasoning_effort": thinking_settings.get("reasoning_effort"),
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(user_input, ensure_ascii=False)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "reminder_seed", "strict": True, "schema": schema},
        },
    }


def _response_content(response: dict[str, Any]) -> str:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise ContractError("千问响应没有 choices[0].message.content") from error
    if not isinstance(content, str):
        raise ContractError("千问响应 content 必须是 JSON 字符串")
    return content


def call_structured_qwen(
    *,
    endpoint: str,
    api_key_name: str,
    payload: dict[str, Any],
    max_retries: int,
    timeout_sec: float,
    opener: Callable[..., Any] = urlopen,
) -> tuple[dict[str, Any], int]:
    api_key = os.environ.get(api_key_name)
    # 只允许环境凭据，避免 API Key 出现在命令历史、配置或候选 JSONL 中。
    if not api_key:
        raise ContractError(f"未设置环境变量 {api_key_name}")
    request = Request(
        f"{endpoint}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    last_error: Exception | None = None
    for retry_count in range(max_retries + 1):
        try:
            with opener(request, timeout=timeout_sec) as handle:
                response = json.loads(handle.read().decode("utf-8"))
            value = json.loads(_response_content(response))
            if not isinstance(value, dict):
                raise ContractError("结构化响应根节点必须是 object")
            return value, retry_count
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            # 仅网络/解码失败可重试；候选不合约必须被外层语义检查立即拒绝。
            if retry_count == max_retries:
                break
            time.sleep(min(2**retry_count, 4))
    raise ContractError("千问结构化调用失败，已耗尽重试次数") from last_error


def clause_set(predicate: dict[str, Any]) -> set[tuple[str, str, str]]:
    return {
        (clause["slot"], clause["operator"], clause["value"])
        for clause in predicate["all_of"]
    }


def validate_seed_semantics(
    *,
    seed: dict[str, Any],
    cue: dict[str, Any],
    trigger: dict[str, Any],
    lures: list[dict[str, Any]],
    identifiers: dict[str, str | list[str]],
    run_id: str,
) -> None:
    expected = {
        "seed_id": identifiers["seed_id"],
        "family_id": identifiers["family_id"],
        "split": trigger["split"],
        "source_group_id": trigger["source_group_id"],
        "primary_cue_type": cue["cue_type"],
        "trigger_atom_id": trigger["atom_id"],
        "rule_ids": identifiers["rule_ids"],
    }
    for field, value in expected.items():
        if seed.get(field) != value:
            raise ContractError(f"Seed 的 {field} 与受控输入不一致")
    if seed["intention"]["intention_id"] != identifiers["intention_id"]:
        raise ContractError("Seed intention_id 与受控输入不一致")
    generation = seed["generation_record"]
    if generation != {
        "run_id": run_id,
        "model_id": EXPECTED_MODEL_ID,
        "prompt_version": PROMPT_VERSION,
        "schema_version": CONTRACT_VERSION,
    }:
        raise ContractError("Seed generation_record 与本次调用元数据不一致")
    lure_ids = seed["lure_atom_ids"]
    supplied_lure_ids = {lure["atom_id"] for lure in lures}
    if len(lure_ids) < 2 or len(set(lure_ids)) != len(lure_ids):
        raise ContractError("Seed 至少需要两个不同 lure")
    if seed["trigger_atom_id"] in lure_ids or not set(lure_ids).issubset(supplied_lure_ids):
        # 诱饵只能来自受控检索输入，防止模型插入跨 split 或不可追溯 atom。
        raise ContractError("Seed lure 必须来自受控输入且不同于 trigger")
    for lure in lures:
        if lure["atom_id"] in lure_ids and lure["split"] != seed["split"]:
            raise ContractError("Seed lure 与 trigger 必须同 split")
    if not clause_set(cue["normalized_predicate"]).issubset(clause_set(seed["trigger_predicate"])):
        raise ContractError("Seed trigger_predicate 必须包含 cue 的 all_of 谓词")
    window = seed["valid_window"]
    if window["end_offset_sec"] < window["start_offset_sec"]:
        raise ContractError("Seed 有效窗口结束不得早于开始")
    if not REQUIRED_TERMINAL_CONDITIONS.issubset(set(seed["terminal_silent_conditions"])):
        # 终止条件齐全才能让后续状态机在已完成、取消、过期和已提醒时保持不触发。
        raise ContractError("Seed 缺少必需终止不触发条件")
    audit = seed["audit"]
    if audit != {"status": "candidate", "reason": audit.get("reason"), "human_reviewer": None, "model_audit_run_id": None}:
        raise ContractError("候选阶段不得写入人工或模型审计决定")
    if not isinstance(audit["reason"], str) or not audit["reason"].strip():
        raise ContractError("候选 Seed 必须说明候选理由")
    if seed["current_trigger_leakage_checked"] is not True:
        raise ContractError("Seed 必须显式完成 current trigger leakage 检查")


def write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
    # 一次模型调用不合约时不会替换旧候选文件，因此下游不会读到半批结果。
    temporary.replace(path)


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    # 最后原子写成功标记，确保其哈希只对应已完整写入的候选 artifact。
    temporary.replace(path)


def run(args: argparse.Namespace) -> int:
    endpoint, api_key_name, region, model_settings = load_runtime_settings(args.model_registry)
    # 在任何 Plus 请求前检查整个血缘链，避免支付调用成本后才发现上游混版。
    source_marker = require_verified_success(args.source_atoms, args.source_success)
    cue_marker = require_verified_success(args.cue_library, args.cue_success)
    retrieval_marker = require_verified_success(args.trigger_lures, args.trigger_lures_success)
    require_direct_upstream(cue_marker, "source_atoms", source_marker["sha256"])
    require_direct_upstream(retrieval_marker, "source_atoms", source_marker["sha256"])
    require_direct_upstream(retrieval_marker, "cue_library", cue_marker["sha256"])
    source_rows = read_jsonl(args.source_atoms)
    cue_rows = read_jsonl(args.cue_library)
    retrieval_rows = read_jsonl(args.trigger_lures)
    validate_rows(source_rows, load_validator(args.source_schema), "source atom")
    validate_rows(cue_rows, load_validator(args.cue_schema), "cue")
    validate_retrieval_rows(retrieval_rows)
    seed_schema = read_json(args.seed_schema)
    seed_validator = load_validator(args.seed_schema)
    prompt = args.prompt.read_text(encoding="utf-8")
    if not prompt.strip():
        raise ContractError("Seed 提示词不能为空")

    atom_by_id = {atom["atom_id"]: atom for atom in source_rows}
    cue_by_id = {cue["cue_id"]: cue for cue in cue_rows if cue["validation_status"] == "accepted"}
    if len(atom_by_id) != len(source_rows):
        raise ContractError("source atoms 存在重复 atom_id")
    run_id = args.run_id or f"run_seed_{uuid.uuid4().hex[:16]}"
    request_time = utc_now()
    seeds: list[dict[str, Any]] = []
    retry_count = 0
    for index, retrieval in enumerate(retrieval_rows[: args.max_candidates], start=1):
        cue = cue_by_id.get(retrieval["cue_id"])
        trigger = atom_by_id.get(retrieval["trigger_atom_id"])
        if cue is None or trigger is None:
            raise ContractError("trigger/lure 集引用了不存在或未接受的 cue/atom")
        if retrieval["split"] != trigger["split"] or retrieval["source_group_id"] != trigger["source_group_id"]:
            raise ContractError("trigger/lure 集的 split 或 source_group 与 trigger 不一致")
        lures = []
        for lure_id in retrieval["lure_atom_ids"]:
            lure = atom_by_id.get(lure_id)
            if lure is None:
                raise ContractError(f"trigger/lure 集引用不存在 lure：{lure_id}")
            if lure["split"] != trigger["split"] or lure_id == trigger["atom_id"]:
                raise ContractError("trigger/lure 集含跨 split 或 trigger 自身")
            lures.append(lure)
        identifiers = seed_identifiers(index)
        payload = build_chat_request(
            prompt=prompt,
            schema=seed_schema,
            cue=cue,
            trigger=trigger,
            lures=lures,
            identifiers=identifiers,
            run_id=run_id,
            thinking_settings=model_settings,
        )
        seed, retries = call_structured_qwen(
            endpoint=endpoint,
            api_key_name=api_key_name,
            payload=payload,
            max_retries=args.max_retries,
            timeout_sec=args.timeout_sec,
        )
        retry_count += retries
        validate_rows([seed], seed_validator, "Seed candidate")
        validate_seed_semantics(
            seed=seed,
            cue=cue,
            trigger=trigger,
            lures=lures,
            identifiers=identifiers,
            run_id=run_id,
        )
        seeds.append(seed)

    write_jsonl_atomic(args.output, seeds)
    write_json_atomic(
        args.success_marker,
        {
            "artifact_path": str(args.output.resolve()),
            "sha256": sha256_file(args.output),
            "row_count": len(seeds),
            "contract_version": CONTRACT_VERSION,
            "config_version": CONFIG_VERSION,
            "schema_versions": {"reminder_seed": CONTRACT_VERSION},
            "generated_at": utc_now(),
            "upstream_hashes": {
                "source_atoms": source_marker["sha256"],
                "cue_library": cue_marker["sha256"],
                "trigger_lures": retrieval_marker["sha256"],
            },
            "run_id": run_id,
            "model_id": EXPECTED_MODEL_ID,
            "region": region,
            "endpoint": endpoint,
            "thinking_enabled": model_settings["thinking_enabled"],
            "reasoning_effort": model_settings["reasoning_effort"],
            "temperature": model_settings["temperature"],
            "prompt_version": PROMPT_VERSION,
            "request_time": request_time,
            "input_atom_ids": [row["trigger_atom_id"] for row in retrieval_rows[: args.max_candidates]],
            "raw_response_path": None,
            "parse_status": "validated",
            "retry_count": retry_count,
            "validation_errors": [],
        },
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-registry", type=Path, default=ROOT / "config" / "model_registry.yaml")
    parser.add_argument("--source-atoms", type=Path, default=ROOT / "source" / "source_video_atoms.jsonl")
    parser.add_argument("--source-success", type=Path, default=ROOT / "source" / "SOURCE_ATOMS_SUCCESS.json")
    parser.add_argument("--cue-library", type=Path, default=ROOT / "cues" / "cue_library.jsonl")
    parser.add_argument("--cue-success", type=Path, default=ROOT / "cues" / "CUE_LIBRARY_SUCCESS.json")
    parser.add_argument("--trigger-lures", type=Path, default=ROOT / "cues" / "trigger_lure_sets.jsonl")
    parser.add_argument("--trigger-lures-success", type=Path, default=ROOT / "cues" / "TRIGGER_LURES_SUCCESS.json")
    parser.add_argument("--source-schema", type=Path, default=ROOT / "schemas" / "source_video_atom.schema.json")
    parser.add_argument("--cue-schema", type=Path, default=ROOT / "schemas" / "cue_candidate.schema.json")
    parser.add_argument("--seed-schema", type=Path, default=ROOT / "schemas" / "reminder_seed.schema.json")
    parser.add_argument("--prompt", type=Path, default=ROOT / "prompts" / "seed_generator_v1.md")
    parser.add_argument("--output", type=Path, default=ROOT / "seeds" / "reminder_seed_candidates.jsonl")
    parser.add_argument("--success-marker", type=Path, default=ROOT / "seeds" / "SEED_CANDIDATES_SUCCESS.json")
    parser.add_argument("--run-id")
    parser.add_argument("--max-candidates", type=int, default=60)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--timeout-sec", type=float, default=60.0)
    args = parser.parse_args(argv)
    if args.max_candidates < 0 or args.max_retries < 0 or args.timeout_sec <= 0:
        parser.error("max-candidates/max-retries 必须非负，timeout-sec 必须大于零")
    return args


def main() -> int:
    try:
        return run(parse_args())
    except ContractError as error:
        print(f"合同门禁失败：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
