#!/usr/bin/env python3
"""第 05 阶段：从已验证来源原子提取线索候选并生成线索库。

职责是调用固定的千问 Flash 模型，将带有匹配 ``SOURCE_ATOMS_SUCCESS.json`` 的
``source_video_atoms.jsonl`` 转为 ``cue_library.jsonl`` 和其成功标记；脚本处在
来源建库之后、诱饵检索之前。输入包括冻结的来源原子、来源成功标记、模型登记、
线索 ``JSON Schema`` 与固定提示词；输出只包含通过结构和原文可追溯校验的线索。
模型原始响应不落盘，每条输出与成功标记保存模型、提示词、Schema 和运行元数据。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
EXPECTED_MODEL_ID = "qwen3.7-flash-2026-07-15"
PROMPT_VERSION = "cue_extractor_v1"
CONTRACT_VERSION = "v1.1.0"
CONFIG_VERSION = "v1.1.0"
SOURCE_SCHEMA_VERSION = "v1.1.0"
CUE_SCHEMA_VERSION = "v1.0.0"
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
        raise ContractError(f"JSON 对象必须是 object：{path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ContractError(f"无法读取 JSONL 文件：{path}") from error
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            raise ContractError(f"JSONL 不允许空行：{path}:{number}")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ContractError(f"JSONL 不是有效 JSON：{path}:{number}") from error
        if not isinstance(value, dict):
            raise ContractError(f"JSONL 行必须是 object：{path}:{number}")
        rows.append(value)
    return rows


def _declares_artifact(marker: dict[str, Any], artifact: Path, marker_path: Path) -> bool:
    declared = Path(str(marker["artifact_path"]))
    if declared.is_absolute():
        candidates = [declared]
    else:
        candidates = [marker_path.parent / declared, ROOT.parent / declared, artifact.parent / declared]
    expected = artifact.resolve()
    return any(candidate.resolve() == expected for candidate in candidates)


def require_verified_success(
    artifact: Path,
    marker_path: Path,
    expected_schema_version: str,
) -> dict[str, Any]:
    """验证输入 artifact 与 SUCCESS 标记的不可变边界。"""
    # 先验证标记再读取来源内容，避免把写到一半、被替换或被篡改的上游文件送入模型。
    if not artifact.is_file() or not marker_path.is_file():
        raise ContractError(f"缺少正式输入或 SUCCESS 标记：{artifact}；{marker_path}")
    marker = read_json(marker_path)
    missing = SUCCESS_REQUIRED_FIELDS.difference(marker)
    if missing:
        raise ContractError(f"SUCCESS 标记缺少字段：{sorted(missing)}")
    if marker["contract_version"] != CONTRACT_VERSION or marker["config_version"] != CONFIG_VERSION:
        raise ContractError("SUCCESS 标记的合同或配置版本不兼容")
    if not isinstance(marker["row_count"], int) or marker["row_count"] < 0:
        raise ContractError("SUCCESS 标记的 row_count 必须是非负整数")
    if not isinstance(marker["upstream_hashes"], (dict, list)):
        raise ContractError("SUCCESS 标记的 upstream_hashes 必须是 object 或 array")
    if expected_schema_version not in json.dumps(marker["schema_versions"], ensure_ascii=False):
        raise ContractError("SUCCESS 标记未声明预期 Schema 版本")
    if not _declares_artifact(marker, artifact, marker_path):
        raise ContractError("SUCCESS 标记的 artifact_path 与实际输入不一致")
    if marker["sha256"] != sha256_file(artifact):
        raise ContractError("SUCCESS 标记 SHA256 与输入文件不匹配")
    if marker["row_count"] != len(read_jsonl(artifact)):
        raise ContractError("SUCCESS 标记 row_count 与输入文件不匹配")
    return marker


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
    if registry.get("contract_version") != CONTRACT_VERSION:
        raise ContractError("model_registry 合同版本不兼容")
    cue_settings = registry.get("models", {}).get("cue_extraction", {})
    # 模型 ID 与运行参数必须双重钉死在代码和冻结登记中，防止配置漂移悄然改变候选分布。
    if cue_settings.get("model_id") != EXPECTED_MODEL_ID:
        raise ContractError("cue 模型必须固定为 qwen3.7-flash-2026-07-15")
    if cue_settings.get("prompt_version") != PROMPT_VERSION:
        raise ContractError("cue 提示词版本不兼容")
    if cue_settings.get("temperature") != 0 or cue_settings.get("thinking_enabled") is not False:
        raise ContractError("cue 的温度或 thinking 设置不兼容")
    endpoint = registry.get("default_endpoint")
    key_name = registry.get("credential_environment_variable")
    if not isinstance(endpoint, str) or not endpoint.startswith("https://"):
        raise ContractError("model_registry 的 endpoint 无效")
    if key_name != "DASHSCOPE_API_KEY" or registry.get("credential_policy") != "environment_only":
        raise ContractError("凭据配置必须是 DASHSCOPE_API_KEY 环境变量")
    region = registry.get("default_region")
    if not isinstance(region, str) or not region:
        raise ContractError("model_registry 的 region 无效")
    return endpoint.rstrip("/"), key_name, region, cue_settings


def load_validator(schema_path: Path) -> jsonschema.Draft202012Validator:
    schema = read_json(schema_path)
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as error:
        raise ContractError(f"Schema 无效：{schema_path}") from error
    return jsonschema.Draft202012Validator(schema)


def validate_instance(
    validator: jsonschema.Draft202012Validator, value: dict[str, Any], label: str
) -> None:
    errors = sorted(validator.iter_errors(value), key=lambda item: list(item.path))
    if errors:
        detail = "; ".join(error.message for error in errors[:3])
        raise ContractError(f"{label} 未通过 JSON Schema：{detail}")


def cue_id_for(atom_id: str) -> str:
    return f"cue_{atom_id.removeprefix('src_')}"


def make_run_id(prefix: str, requested: str | None) -> str:
    return requested or f"run_{prefix}_{uuid.uuid4().hex[:16]}"


def build_chat_request(
    *,
    prompt: str,
    schema: dict[str, Any],
    atom: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    """构造 DashScope OpenAI-compatible 严格 JSON Schema 请求。"""
    # 仅把可见文本给模型，避免 transcript、来源路径等非当前观察字段成为隐藏信息通道。
    expected = {
        "cue_id": cue_id_for(str(atom["atom_id"])),
        "atom_id": atom["atom_id"],
        "split": atom["split"],
        "source_text": atom["visible_text"],
        "model_id": EXPECTED_MODEL_ID,
        "prompt_version": PROMPT_VERSION,
        "schema_version": CUE_SCHEMA_VERSION,
        "run_id": run_id,
    }
    user_input = {
        "instruction": "请按系统提示词和 response_format 输出一个 cue candidate。",
        "prefilled_contract_fields": expected,
        "visible_text": atom["visible_text"],
    }
    return {
        "model": EXPECTED_MODEL_ID,
        "temperature": 0,
        "stream": False,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(user_input, ensure_ascii=False)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "cue_candidate", "strict": True, "schema": schema},
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
    """只从环境读取密钥，并对可恢复网络错误有限重试。"""
    # 密钥绝不能通过 CLI、文件或日志传递；环境变量使凭据不随运行产物进入仓库。
    api_key = os.environ.get(api_key_name)
    if not api_key:
        raise ContractError(f"未设置环境变量 {api_key_name}")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{endpoint}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    last_error: Exception | None = None
    for retry_count in range(max_retries + 1):
        try:
            with opener(request, timeout=timeout_sec) as handle:
                raw = handle.read().decode("utf-8")
            response = json.loads(raw)
            content = _response_content(response)
            value = json.loads(content)
            if not isinstance(value, dict):
                raise ContractError("结构化响应根节点必须是 object")
            return value, retry_count
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            # 只重试传输或 JSON 解码错误；Schema/语义错误必须立即暴露，不能掩盖模型越界输出。
            if retry_count == max_retries:
                break
            time.sleep(min(2**retry_count, 4))
    raise ContractError("千问结构化调用失败，已耗尽重试次数") from last_error


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def validate_cue_semantics(atom: dict[str, Any], cue: dict[str, Any]) -> None:
    expected = {
        "cue_id": cue_id_for(str(atom["atom_id"])),
        "atom_id": atom["atom_id"],
        "split": atom["split"],
        "source_text": atom["visible_text"],
        "model_id": EXPECTED_MODEL_ID,
        "prompt_version": PROMPT_VERSION,
        "schema_version": CUE_SCHEMA_VERSION,
    }
    for field, required in expected.items():
        if cue.get(field) != required:
            raise ContractError(f"cue 的 {field} 与受控输入或元数据不一致")
    if not isinstance(cue.get("run_id"), str) or not cue["run_id"]:
        raise ContractError("cue 缺少 run_id")
    source_text = str(atom["visible_text"])
    if cue["supporting_text_span"] not in source_text:
        # 该硬条件保证 T4 能从 cue 回指到同一条来源原文，而不是仅相信模型概述。
        raise ContractError("cue supporting_text_span 不是 visible_text 的连续原文子串")
    predicate = cue["normalized_predicate"]
    clauses = predicate.get("all_of", [])
    if not any(clause.get("slot") == cue["cue_type"] for clause in clauses):
        raise ContractError("cue 谓词必须含有与 cue_type 相同 slot 的 all_of 子句")
    if cue["validation_status"] == "accepted" and cue.get("validation_errors"):
        raise ContractError("accepted cue 不得带有 validation_errors")
    if _normalise(cue["source_text"]) != _normalise(source_text):
        raise ContractError("cue source_text 未保留输入原文")


def write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
    # 仅在整批内容写完后替换正式文件，避免下游观察到部分 JSONL。
    temporary.replace(path)


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    # 成功标记也原子替换，使其始终对应一个完整、已关闭的 artifact。
    temporary.replace(path)


def run(args: argparse.Namespace) -> int:
    endpoint, api_key_name, region, model_settings = load_runtime_settings(args.model_registry)
    # 此门在任何付费模型请求前执行；失败时保留旧输出而不产生新的模型调用。
    source_marker = require_verified_success(args.source_atoms, args.source_success, SOURCE_SCHEMA_VERSION)
    source_validator = load_validator(args.source_schema)
    cue_schema = read_json(args.cue_schema)
    cue_validator = load_validator(args.cue_schema)
    prompt = args.prompt.read_text(encoding="utf-8")
    if not prompt.strip():
        raise ContractError("cue 提示词不能为空")

    atoms = read_jsonl(args.source_atoms)
    for atom in atoms:
        validate_instance(source_validator, atom, "source atom")
    run_id = make_run_id("cue", args.run_id)
    request_time = utc_now()
    cues: list[dict[str, Any]] = []
    retry_count = 0
    for atom in atoms[: args.max_atoms]:
        payload = build_chat_request(prompt=prompt, schema=cue_schema, atom=atom, run_id=run_id)
        cue, retries = call_structured_qwen(
            endpoint=endpoint,
            api_key_name=api_key_name,
            payload=payload,
            max_retries=args.max_retries,
            timeout_sec=args.timeout_sec,
        )
        retry_count += retries
        validate_instance(cue_validator, cue, "cue candidate")
        validate_cue_semantics(atom, cue)
        if cue["validation_status"] == "accepted":
            cues.append(cue)

    write_jsonl_atomic(args.output, cues)
    # artifact 的 SHA256 必须在原子替换后计算，随后才允许写出表示“可消费”的成功标记。
    marker = {
        "artifact_path": str(args.output.resolve()),
        "sha256": sha256_file(args.output),
        "row_count": len(cues),
        "contract_version": CONTRACT_VERSION,
        "config_version": CONFIG_VERSION,
        "schema_versions": {"cue_candidate": CUE_SCHEMA_VERSION},
        "generated_at": utc_now(),
        "upstream_hashes": {"source_atoms": source_marker["sha256"]},
        "run_id": run_id,
        "model_id": EXPECTED_MODEL_ID,
        "region": region,
        "endpoint": endpoint,
        "thinking_enabled": model_settings["thinking_enabled"],
        "reasoning_effort": model_settings["reasoning_effort"],
        "temperature": model_settings["temperature"],
        "prompt_version": PROMPT_VERSION,
        "request_time": request_time,
        "input_atom_ids": [atom["atom_id"] for atom in atoms[: args.max_atoms]],
        "raw_response_path": None,
        "parse_status": "validated",
        "retry_count": retry_count,
        "validation_errors": [],
    }
    write_json_atomic(args.success_marker, marker)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-registry", type=Path, default=ROOT / "config" / "model_registry.yaml")
    parser.add_argument("--source-atoms", type=Path, default=ROOT / "source" / "source_video_atoms.jsonl")
    parser.add_argument("--source-success", type=Path, default=ROOT / "source" / "SOURCE_ATOMS_SUCCESS.json")
    parser.add_argument("--source-schema", type=Path, default=ROOT / "schemas" / "source_video_atom.schema.json")
    parser.add_argument("--cue-schema", type=Path, default=ROOT / "schemas" / "cue_candidate.schema.json")
    parser.add_argument("--prompt", type=Path, default=ROOT / "prompts" / "cue_extractor_v1.md")
    parser.add_argument("--output", type=Path, default=ROOT / "cues" / "cue_library.jsonl")
    parser.add_argument("--success-marker", type=Path, default=ROOT / "cues" / "CUE_LIBRARY_SUCCESS.json")
    parser.add_argument("--run-id")
    parser.add_argument("--max-atoms", type=int, default=sys.maxsize)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--timeout-sec", type=float, default=60.0)
    args = parser.parse_args(argv)
    if args.max_atoms < 0 or args.max_retries < 0 or args.timeout_sec <= 0:
        parser.error("max-atoms/max-retries 必须非负，timeout-sec 必须大于零")
    return args


def main() -> int:
    try:
        return run(parse_args())
    except ContractError as error:
        print(f"合同门禁失败：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
