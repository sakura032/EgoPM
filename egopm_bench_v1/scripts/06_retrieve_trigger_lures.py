#!/usr/bin/env python3
"""第 06 阶段：为已验证线索检索触发项与同 split 的诱饵集合。

职责是在第 05 阶段线索库成功后，读取带哈希匹配成功标记的来源原子和线索库，生成
``trigger_lure_sets.jsonl`` 与其成功标记，供第 07 阶段产生种子候选。输入为来源、
线索及二者的成功标记；输出为严格 JSON Schema 校验的检索集合，不含提醒或静默金标。
检索使用本地可复现的词项 Jaccard 排序，不调用模型，也不建立跨运行的隐藏索引。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_VERSION = "v1.1.0"
CONFIG_VERSION = "v1.1.0"
SOURCE_SCHEMA_VERSION = "v1.1.0"
CUE_SCHEMA_VERSION = "v1.0.0"
TRIGGER_LURE_SCHEMA_VERSION = "v1.0.0"
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
TRIGGER_LURE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "EgoPM-Bench v1 Trigger Lure Set (T2 temporary contract)",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "retrieval_id",
        "cue_id",
        "trigger_atom_id",
        "split",
        "source_group_id",
        "lure_atom_ids",
        "lure_scores",
        "retrieval_method",
        "run_id",
        "schema_version",
    ],
    "properties": {
        "retrieval_id": {"type": "string", "pattern": "^retrieval_[A-Za-z0-9_]+$"},
        "cue_id": {"type": "string", "pattern": "^cue_[A-Za-z0-9_]+$"},
        "trigger_atom_id": {"type": "string", "pattern": "^src_[A-Za-z0-9_]+$"},
        "split": {"enum": ["train", "dev", "test"]},
        "source_group_id": {"type": "string", "minLength": 1},
        "lure_atom_ids": {
            "type": "array",
            "minItems": 2,
            "uniqueItems": True,
            "items": {"type": "string", "pattern": "^src_[A-Za-z0-9_]+$"},
        },
        "lure_scores": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["atom_id", "score"],
                "properties": {
                    "atom_id": {"type": "string", "pattern": "^src_[A-Za-z0-9_]+$"},
                    "score": {"type": "number", "minimum": 0},
                },
            },
        },
        "retrieval_method": {"const": "lexical_jaccard_v1"},
        "run_id": {"type": "string", "minLength": 1},
        "schema_version": {"const": TRIGGER_LURE_SCHEMA_VERSION},
    },
}


class ContractError(RuntimeError):
    """输入或输出违背冻结合同。"""


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
    expected = artifact.resolve()
    return any(candidate.resolve() == expected for candidate in candidates)


def require_verified_success(artifact: Path, marker_path: Path) -> dict[str, Any]:
    # 哈希和行数共同约束输入，防止线索或来源在上游成功后被静默重写。
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
    if not isinstance(marker["schema_versions"], (dict, list, str)):
        raise ContractError("SUCCESS 标记 schema_versions 无效")
    if not isinstance(marker["upstream_hashes"], (dict, list)):
        raise ContractError("SUCCESS 标记 upstream_hashes 无效")
    if not _declares_artifact(marker, artifact, marker_path):
        raise ContractError("SUCCESS 标记的 artifact_path 与输入不一致")
    if marker["sha256"] != sha256_file(artifact):
        raise ContractError("SUCCESS 标记 SHA256 与输入不匹配")
    if marker["row_count"] != len(read_jsonl(artifact)):
        raise ContractError("SUCCESS 标记 row_count 与输入不匹配")
    return marker


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


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[\w]+", text.casefold(), flags=re.UNICODE))


def cue_query_terms(cue: dict[str, Any]) -> set[str]:
    parts = [cue["source_text"], cue["cue_type"]]
    parts.extend(cue["entities"])
    if cue.get("scene_type"):
        parts.append(cue["scene_type"])
    if cue.get("activity_type"):
        parts.append(cue["activity_type"])
    for clause in cue["normalized_predicate"]["all_of"]:
        parts.extend([clause["slot"], clause["value"]])
    return tokens(" ".join(parts))


def lure_score(query_terms: set[str], atom: dict[str, Any], cue_type: str) -> float:
    atom_terms = tokens(atom["visible_text"])
    union = query_terms | atom_terms
    lexical = len(query_terms & atom_terms) / len(union) if union else 0.0
    type_bonus = 0.05 if cue_type in atom_terms else 0.0
    return round(lexical + type_bonus, 8)


def build_lure_sets(
    *,
    atoms: list[dict[str, Any]],
    cues: list[dict[str, Any]],
    lures_per_trigger: int,
    run_id: str,
) -> list[dict[str, Any]]:
    by_id = {atom["atom_id"]: atom for atom in atoms}
    if len(by_id) != len(atoms):
        raise ContractError("source atoms 存在重复 atom_id")
    rows: list[dict[str, Any]] = []
    for cue in cues:
        if cue["validation_status"] != "accepted":
            continue
        trigger = by_id.get(cue["atom_id"])
        if trigger is None:
            raise ContractError(f"cue 引用了不存在的 atom：{cue['atom_id']}")
        if cue["split"] != trigger["split"]:
            raise ContractError(f"cue 与 trigger split 不一致：{cue['cue_id']}")
        query = cue_query_terms(cue)
        ranked = []
        for candidate in atoms:
            # 诱饵必须与 trigger 不同且同 split，才能避免自引用与跨 split 泄漏。
            if candidate["atom_id"] == trigger["atom_id"] or candidate["split"] != trigger["split"]:
                continue
            ranked.append((lure_score(query, candidate, cue["cue_type"]), candidate["atom_id"]))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        selected = ranked[:lures_per_trigger]
        # 少于两个诱饵的 trigger 不能进入下游，因为 Seed 合同将此作为硬性最小条件。
        if len(selected) < 2:
            continue
        rows.append(
            {
                "retrieval_id": f"retrieval_{cue['cue_id'].removeprefix('cue_')}",
                "cue_id": cue["cue_id"],
                "trigger_atom_id": trigger["atom_id"],
                "split": trigger["split"],
                "source_group_id": trigger["source_group_id"],
                "lure_atom_ids": [atom_id for _, atom_id in selected],
                "lure_scores": [
                    {"atom_id": atom_id, "score": score} for score, atom_id in selected
                ],
                "retrieval_method": "lexical_jaccard_v1",
                "run_id": run_id,
                "schema_version": TRIGGER_LURE_SCHEMA_VERSION,
            }
        )
    return rows


def validate_retrieval_set_semantics(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        lure_ids = row["lure_atom_ids"]
        score_ids = [item["atom_id"] for item in row["lure_scores"]]
        if row["trigger_atom_id"] in lure_ids:
            raise ContractError("检索输出的 lure 不得包含 trigger 自身")
        if score_ids != lure_ids:
            # 分数与 ID 顺序一一对应，保证审计时可重现“为什么选中该诱饵”。
            raise ContractError("检索输出的 lure_scores 必须与 lure_atom_ids 同序对应")


def write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
    # 检索结果作为下一阶段输入，必须整批完成后才可替换正式文件。
    temporary.replace(path)


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    # 成功标记最后写入，保证它宣告的哈希只能指向完整检索结果。
    temporary.replace(path)


def run(args: argparse.Namespace) -> int:
    # 先锁定两个上游边界，再做本地排序，避免把不同版本的来源与线索混合检索。
    source_marker = require_verified_success(args.source_atoms, args.source_success)
    cue_marker = require_verified_success(args.cue_library, args.cue_success)
    source_rows = read_jsonl(args.source_atoms)
    cue_rows = read_jsonl(args.cue_library)
    validate_rows(source_rows, load_validator(args.source_schema), "source atom")
    validate_rows(cue_rows, load_validator(args.cue_schema), "cue")
    run_id = args.run_id or f"run_retrieval_{uuid.uuid4().hex[:16]}"
    rows = build_lure_sets(
        atoms=source_rows,
        cues=cue_rows,
        lures_per_trigger=args.lures_per_trigger,
        run_id=run_id,
    )
    try:
        # 合同尚未冻结该中间产物 Schema，开发期仍须在写入前执行严格结构校验。
        jsonschema.Draft202012Validator.check_schema(TRIGGER_LURE_SCHEMA)
    except jsonschema.SchemaError as error:
        raise ContractError("内置 trigger/lure Schema 无效") from error
    validate_rows(
        rows,
        jsonschema.Draft202012Validator(TRIGGER_LURE_SCHEMA),
        "trigger/lure 集",
    )
    validate_retrieval_set_semantics(rows)
    write_jsonl_atomic(args.output, rows)
    write_json_atomic(
        args.success_marker,
        {
            "artifact_path": str(args.output.resolve()),
            "sha256": sha256_file(args.output),
            "row_count": len(rows),
            "contract_version": CONTRACT_VERSION,
            "config_version": CONFIG_VERSION,
            "schema_versions": {
                "source_video_atom": SOURCE_SCHEMA_VERSION,
                "cue_candidate": CUE_SCHEMA_VERSION,
                "trigger_lure_set": TRIGGER_LURE_SCHEMA_VERSION,
            },
            "generated_at": utc_now(),
            "upstream_hashes": {
                "source_atoms": source_marker["sha256"],
                "cue_library": cue_marker["sha256"],
            },
            "run_id": run_id,
            "retrieval_method": "lexical_jaccard_v1",
            "validation_errors": [],
        },
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-atoms", type=Path, default=ROOT / "source" / "source_video_atoms.jsonl")
    parser.add_argument("--source-success", type=Path, default=ROOT / "source" / "SOURCE_ATOMS_SUCCESS.json")
    parser.add_argument("--cue-library", type=Path, default=ROOT / "cues" / "cue_library.jsonl")
    parser.add_argument("--cue-success", type=Path, default=ROOT / "cues" / "CUE_LIBRARY_SUCCESS.json")
    parser.add_argument("--source-schema", type=Path, default=ROOT / "schemas" / "source_video_atom.schema.json")
    parser.add_argument("--cue-schema", type=Path, default=ROOT / "schemas" / "cue_candidate.schema.json")
    parser.add_argument("--output", type=Path, default=ROOT / "cues" / "trigger_lure_sets.jsonl")
    parser.add_argument("--success-marker", type=Path, default=ROOT / "cues" / "TRIGGER_LURES_SUCCESS.json")
    parser.add_argument("--lures-per-trigger", type=int, default=4)
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    if args.lures_per_trigger < 2:
        parser.error("lures-per-trigger 至少为 2")
    return args


def main() -> int:
    try:
        return run(parse_args())
    except ContractError as error:
        print(f"合同门禁失败：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
