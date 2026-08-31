#!/usr/bin/env python3
"""EgoPM-Bench v1 的只读全量质检器。

职责：在 T1、T2、T3 的产物冻结后执行独立 QA，而不修改其脚本或 JSONL。
输入：`benchmark_protocol.yaml`、同目录路径/切分配置、SUCCESS 标记及已冻结 JSONL。
输出：`audit/validation_errors.jsonl`、`audit/leakage_report.json`，零阻断时才输出最终 SUCCESS 标记。
流水线位置：第 11 步，位于 source、cue、seed、lifelog/oracle 生产之后、统计与发布之前。

本脚本绝不修改生产者产物。它只会在某阶段的 SUCCESS 标记完整、哈希和
行数一致后读取该阶段的 JSONL；审计报告写入 audit/，且以原子替换完成。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import jsonschema
import yaml


BENCHMARK_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_VERSION = "v1.0.0"
REPRODUCTION_COMMAND = (
    "python egopm_bench_v1/scripts/11_validate_all.py "
    "--config egopm_bench_v1/config/benchmark_protocol.yaml"
)

STAGES: tuple[tuple[str, str, str, str, str], ...] = (
    ("source", "source_atoms", "source_atoms", "source_video_atom.schema.json", "T1 source"),
    ("cue", "cue_library", "cue_library", "cue_candidate.schema.json", "T2 cue"),
    ("candidate", "seed_candidates", "seed_candidates", "reminder_seed.schema.json", "T2 seed"),
    ("frozen", "frozen_seeds", "frozen_seeds", "reminder_seed.schema.json", "T3 compiler"),
    ("lifelog", "lifelogs", "lifelogs", "lifelog.schema.json", "T3 compiler"),
    ("decisions", "decisions", "decision_instances", "decision_instance.schema.json", "T3 compiler"),
)
STAGE_DEPENDENCIES = {
    "source": (),
    "cue": ("source",),
    "candidate": ("source", "cue"),
    "frozen": ("source", "candidate"),
    "lifelog": ("source", "frozen"),
    "decisions": ("source", "frozen", "lifelog"),
}
TERMINAL_STATES = {"completed", "cancelled", "expired"}
STATE_TRANSITIONS = {
    None: {None, "active_unreminded"},
    "active_unreminded": {
        "active_unreminded",
        "active_reminded",
        "completed",
        "cancelled",
        "expired",
    },
    "active_reminded": {"active_reminded", "completed", "cancelled", "expired"},
    "completed": {"completed"},
    "cancelled": {"cancelled"},
    "expired": {"expired"},
}
FORBIDDEN_INPUT_MARKERS = (
    "gold_action",
    "event_role",
    "rule_id",
    "intention_state_before",
    "intention_state_after",
    "oracle_annotation",
)
SRT_TIMESTAMP = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>[0-5]\d):(?P<s>[0-5]\d)[,.](?P<ms>\d{3})"
)
VIRTUAL_TIME = re.compile(r"^D(?P<d>\d{2}) (?P<h>[0-2]\d):(?P<m>[0-5]\d)(?::(?P<s>[0-5]\d))?$")


@dataclass(frozen=True)
class RunConfig:
    config_path: Path
    config_dir: Path
    project_root: Path
    benchmark_root: Path
    paths: dict[str, Any]
    protocol: dict[str, Any]
    split_policy: dict[str, Any]

    def artifact(self, key: str) -> Path:
        return (self.config_dir / self.paths["artifacts"][key]).resolve()

    def marker(self, key: str) -> Path:
        return (self.config_dir / self.paths["success_markers"][key]).resolve()

    def relative_artifact_names(self, path: Path) -> set[str]:
        """接受项目根或 benchmark 根相对路径，避免路径锚点产生歧义。"""
        names: set[str] = set()
        for root in (self.project_root, self.benchmark_root):
            try:
                names.add(path.relative_to(root).as_posix())
            except ValueError:
                continue
        return names

    def canonical_artifact_name(self, path: Path) -> str:
        """SUCCESS 标记优先使用 benchmark 根相对路径，保证跨次运行稳定。"""
        for root in (self.benchmark_root, self.project_root):
            try:
                return path.relative_to(root).as_posix()
            except ValueError:
                continue
        raise ValueError(f"产物不在受管项目路径内：{path}")


@dataclass
class IssueCollector:
    issues: list[dict[str, Any]] = field(default_factory=list)

    def add(
        self,
        severity: str,
        issue_type: str,
        failure_id: str,
        expected: str,
        actual: str,
        recommended_fix_stage: str,
    ) -> None:
        self.issues.append(
            {
                "severity": severity,
                "issue_type": issue_type,
                "failure_id": failure_id,
                "expected": expected,
                "actual": actual,
                "reproduction_command": REPRODUCTION_COMMAND,
                "recommended_fix_stage": recommended_fix_stage,
            }
        )

    @property
    def blockers(self) -> list[dict[str, Any]]:
        return [issue for issue in self.issues if issue["severity"] == "BLOCKER"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    # 审计文件也必须避免“读到半个文件”：先完整落盘临时文件，再原子替换正式结果。
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def load_run_config(config_path: Path) -> RunConfig:
    config_path = config_path.resolve()
    config_dir = config_path.parent
    protocol = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    paths_path = config_dir / "paths.yaml"
    split_path = config_dir / "split_policy.yaml"
    paths = yaml.safe_load(paths_path.read_text(encoding="utf-8"))
    split_policy = yaml.safe_load(split_path.read_text(encoding="utf-8"))
    for document_name, document in (
        ("评测协议", protocol),
        ("路径配置", paths),
        ("切分配置", split_policy),
    ):
        if document.get("contract_version") != CONTRACT_VERSION:
            raise ValueError(f"{document_name}合同版本不是 {CONTRACT_VERSION}")
        if document.get("config_version") != CONTRACT_VERSION:
            raise ValueError(f"{document_name}配置版本不是 {CONTRACT_VERSION}")
    return RunConfig(
        config_path=config_path,
        config_dir=config_dir,
        project_root=(config_dir / paths["project_root"]).resolve(),
        benchmark_root=(config_dir / paths["benchmark_root"]).resolve(),
        paths=paths,
        protocol=protocol,
        split_policy=split_policy,
    )


def load_json(path: Path, collector: IssueCollector, issue_prefix: str, owner: str) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        collector.add("BLOCKER", f"{issue_prefix}_unreadable", str(path), "可解析 JSON 对象", str(exc), owner)
        return None
    if not isinstance(value, dict):
        collector.add("BLOCKER", f"{issue_prefix}_shape", str(path), "JSON 对象", type(value).__name__, owner)
        return None
    return value


def jsonl_row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline=None) as handle:
        return sum(1 for line in handle if line.strip())


def read_jsonl(path: Path, collector: IssueCollector, stage: str, owner: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        handle = path.open("r", encoding="utf-8", newline=None)
    except OSError as exc:
        collector.add("BLOCKER", "artifact_unreadable", str(path), "可读取 JSONL", str(exc), owner)
        return records
    with handle:
        for line_number, line in enumerate(handle, start=1):
            # 空行会使 SUCCESS 行数与可解析记录数产生歧义，因此按错误而非忽略处理。
            if not line.strip():
                collector.add("BLOCKER", "jsonl_blank_line", f"{stage}:{line_number}", "每一行都是 JSON 对象", "空行", owner)
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                collector.add("BLOCKER", "jsonl_parse", f"{stage}:{line_number}", "合法 JSON", str(exc), owner)
                continue
            if not isinstance(record, dict):
                collector.add("BLOCKER", "jsonl_record_shape", f"{stage}:{line_number}", "JSON 对象", type(record).__name__, owner)
                continue
            records.append(record)
    if not records:
        collector.add("BLOCKER", "artifact_empty", stage, "至少一条正式记录", "0 条记录", owner)
    return records


def marker_is_valid(
    config: RunConfig,
    stage: str,
    marker_key: str,
    artifact_key: str,
    owner: str,
    collector: IssueCollector,
) -> bool:
    # SUCCESS 是生产者与 QA 之间唯一的稳定边界。先验证其元数据，再打开 JSONL，
    # 才不会把正在写入、被篡改或来自另一份上游数据的内容误判为正式产物。
    marker_path = config.marker(marker_key)
    expected_artifact = config.artifact(artifact_key)
    if not marker_path.is_file():
        collector.add(
            "BLOCKER",
            "success_marker_missing",
            stage,
            f"存在 {marker_path.name} 后才能读取正式产物",
            "SUCCESS 标记不存在",
            owner,
        )
        return False
    marker = load_json(marker_path, collector, "success_marker", owner)
    if marker is None:
        return False
    required = {
        "artifact_path",
        "sha256",
        "row_count",
        "contract_version",
        "config_version",
        "schema_versions",
        "generated_at",
        "upstream_hashes",
    }
    missing = sorted(required.difference(marker))
    if missing:
        collector.add("BLOCKER", "success_marker_fields", stage, "包含所有合同必需字段", f"缺少 {missing}", owner)
        return False
    valid = True
    expected_names = config.relative_artifact_names(expected_artifact)
    actual_name = str(marker["artifact_path"]).replace("\\", "/")
    if actual_name not in expected_names:
        collector.add("BLOCKER", "success_marker_artifact", stage, f"artifact_path 为 {sorted(expected_names)}", actual_name, owner)
        valid = False
    if marker["contract_version"] != CONTRACT_VERSION or marker["config_version"] != CONTRACT_VERSION:
        collector.add(
            "BLOCKER",
            "success_marker_version",
            stage,
            f"contract_version/config_version 均为 {CONTRACT_VERSION}",
            f"{marker['contract_version']}/{marker['config_version']}",
            owner,
        )
        valid = False
    schema_versions = marker["schema_versions"]
    if isinstance(schema_versions, dict):
        declared_versions = set(str(value) for value in schema_versions.values())
    elif isinstance(schema_versions, list):
        declared_versions = set(str(value) for value in schema_versions)
    else:
        declared_versions = set()
    if CONTRACT_VERSION not in declared_versions:
        collector.add("BLOCKER", "success_marker_schema_versions", stage, f"声明 schema 版本 {CONTRACT_VERSION}", repr(schema_versions), owner)
        valid = False
    try:
        timestamp = str(marker["generated_at"]).replace("Z", "+00:00")
        datetime.fromisoformat(timestamp)
    except ValueError:
        collector.add("BLOCKER", "success_marker_timestamp", stage, "ISO 8601 时间戳", repr(marker["generated_at"]), owner)
        valid = False
    if not isinstance(marker["upstream_hashes"], dict):
        collector.add("BLOCKER", "success_marker_upstream_hashes", stage, "对象类型的 upstream_hashes", type(marker["upstream_hashes"]).__name__, owner)
        valid = False
    else:
        # 仅校验自身文件不足以保证谱系正确；下游必须显式携带每个已验证上游的哈希，
        # 否则相同文件名也可能悄悄引用了另一次生成结果。
        declared_hashes = set(flatten_string_values(marker["upstream_hashes"]))
        for dependency in STAGE_DEPENDENCIES[stage]:
            dependency_spec = next(spec for spec in STAGES if spec[0] == dependency)
            dependency_marker = load_json(config.marker(dependency_spec[1]), collector, "success_marker", dependency_spec[4])
            expected_hash = dependency_marker.get("sha256") if dependency_marker else None
            if not isinstance(expected_hash, str) or expected_hash not in declared_hashes:
                collector.add(
                    "BLOCKER",
                    "success_marker_upstream_hash",
                    stage,
                    f"upstream_hashes 包含已验证 {dependency} 的 SHA256 {expected_hash}",
                    repr(marker["upstream_hashes"]),
                    owner,
                )
                valid = False
    if not expected_artifact.is_file():
        collector.add("BLOCKER", "success_marker_artifact_missing", stage, str(expected_artifact), "正式产物不存在", owner)
        return False
    actual_hash = sha256_file(expected_artifact)
    if marker["sha256"] != actual_hash:
        collector.add("BLOCKER", "success_marker_hash", stage, actual_hash, str(marker["sha256"]), owner)
        valid = False
    actual_rows = jsonl_row_count(expected_artifact)
    if marker["row_count"] != actual_rows:
        collector.add("BLOCKER", "success_marker_row_count", stage, str(actual_rows), repr(marker["row_count"]), owner)
        valid = False
    return valid


def flatten_string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for nested in value.values() for item in flatten_string_values(nested)]
    if isinstance(value, list):
        return [item for nested in value for item in flatten_string_values(nested)]
    return []


def validate_schema(
    records: Iterable[dict[str, Any]], schema_path: Path, stage: str, owner: str, collector: IssueCollector
) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for position, record in enumerate(records, start=1):
        record_id = next((str(record[key]) for key in ("atom_id", "cue_id", "seed_id", "lifelog_id", "decision_id") if key in record), f"{stage}:{position}")
        for error in sorted(validator.iter_errors(record), key=lambda item: list(item.absolute_path)):
            location = ".".join(str(part) for part in error.absolute_path) or "$"
            collector.add("BLOCKER", "schema", record_id, f"{location} 满足 schema", error.message, owner)


def normalized_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def char_3grams(value: str) -> set[str]:
    compact = normalized_text(value)
    if len(compact) < 3:
        return {compact} if compact else set()
    return {compact[index : index + 3] for index in range(len(compact) - 2)}


def jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return 1.0 if not union else len(left & right) / len(union)


def session_is_same_or_adjacent(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("session_id") == right.get("session_id"):
        return True
    if left.get("participant_source_id") != right.get("participant_source_id") or left.get("source_day") != right.get("source_day"):
        return False
    left_tail = re.search(r"(\d+)$", str(left.get("session_id", "")))
    right_tail = re.search(r"(\d+)$", str(right.get("session_id", "")))
    return bool(left_tail and right_tail and abs(int(left_tail.group(1)) - int(right_tail.group(1))) == 1)


def resolve_source_path(value: str, config: RunConfig) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return (config.project_root / candidate).resolve()


def srt_duration_seconds(path: Path) -> float | None:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    values = []
    for match in SRT_TIMESTAMP.finditer(text):
        values.append(
            int(match.group("h")) * 3600
            + int(match.group("m")) * 60
            + int(match.group("s"))
            + int(match.group("ms")) / 1000
        )
    return max(values) if values else None


def validate_unique(records: Iterable[dict[str, Any]], field_name: str, stage: str, owner: str, collector: IssueCollector) -> None:
    seen: set[str] = set()
    for record in records:
        value = record.get(field_name)
        if not isinstance(value, str):
            continue
        if value in seen:
            collector.add("BLOCKER", "duplicate_id", value, f"{field_name} 在全体数据中唯一", "发现重复 ID", owner)
        seen.add(value)


def validate_source(records: list[dict[str, Any]], config: RunConfig, collector: IssueCollector) -> None:
    owner = "T1 source"
    validate_unique(records, "atom_id", "source", owner, collector)
    groups: dict[str, set[str]] = defaultdict(set)
    world_events: dict[str, set[str]] = defaultdict(set)
    duration_cache: dict[Path, float | None] = {}
    text_grams: dict[str, set[str]] = {}
    for atom in records:
        atom_id = str(atom.get("atom_id", "source:unknown"))
        start = atom.get("local_start_sec")
        end = atom.get("local_end_sec")
        normalized_start = atom.get("normalized_start_sec")
        normalized_end = atom.get("normalized_end_sec")
        # 本地时间用于回溯 SRT，规范化时间用于组装虚拟日志；两者各自倒序都会破坏证据定位。
        if all(isinstance(value, (int, float)) for value in (start, end)) and start >= end:
            collector.add("BLOCKER", "source_time_order", atom_id, "local_start_sec < local_end_sec", f"{start} >= {end}", owner)
        if all(isinstance(value, (int, float)) for value in (normalized_start, normalized_end)) and normalized_start >= normalized_end:
            collector.add("BLOCKER", "source_normalized_time_order", atom_id, "normalized_start_sec < normalized_end_sec", f"{normalized_start} >= {normalized_end}", owner)
        split = atom.get("split")
        if isinstance(atom.get("source_group_id"), str) and isinstance(split, str):
            groups[atom["source_group_id"]].add(split)
        if isinstance(atom.get("world_event_id"), str) and isinstance(split, str):
            world_events[atom["world_event_id"]].add(split)
        paths = atom.get("source_srt_paths")
        if isinstance(paths, dict):
            for modality in ("transcript", "dense_caption"):
                raw_path = paths.get(modality)
                if not isinstance(raw_path, str):
                    continue
                path = resolve_source_path(raw_path, config)
                if not path.is_file():
                    collector.add("BLOCKER", "source_srt_missing", atom_id, f"存在 {modality} SRT", str(path), owner)
                    continue
                # SRT 文件存在仍不足以证明引用有效，必须确保 atom 终点没有超出最后时间戳。
                duration = duration_cache.setdefault(path, srt_duration_seconds(path))
                if duration is None:
                    collector.add("BLOCKER", "source_srt_timestamp", atom_id, "SRT 含可解析时间戳", str(path), owner)
                elif isinstance(end, (int, float)) and end > duration + 0.001:
                    collector.add("BLOCKER", "source_time_out_of_srt", atom_id, f"local_end_sec <= {duration}", str(end), owner)
        video_path = atom.get("source_video_path")
        if isinstance(video_path, str):
            resolved_video = resolve_source_path(video_path, config)
            if atom.get("video_mapping_status") != "verified" or not resolved_video.is_file():
                collector.add(
                    "BLOCKER",
                    "fabricated_video_path",
                    atom_id,
                    "仅 verified 且存在的 MP4 路径可出现；否则为 null",
                    f"{video_path} ({atom.get('video_mapping_status')})",
                    owner,
                )
        text_grams[atom_id] = char_3grams(str(atom.get("visible_text", "")))
    for group_id, splits in groups.items():
        if len(splits) > 1:
            collector.add("BLOCKER", "split_source_group", group_id, "同一 source_group_id 仅一个 split", str(sorted(splits)), owner)
    for event_id, splits in world_events.items():
        if len(splits) > 1:
            collector.add("BLOCKER", "split_world_event", event_id, "同一 world_event_id 仅一个 split", str(sorted(splits)), owner)
    # 高相似字幕跨 split 会使模型通过记住改写文本获益，因此按冻结策略在同/相邻 session 内复查。
    threshold = float(config.split_policy["grouping"]["near_duplicate"]["similarity_threshold"])
    for index, left in enumerate(records):
        for right in records[index + 1 :]:
            if left.get("split") == right.get("split") or not session_is_same_or_adjacent(left, right):
                continue
            similarity = jaccard(text_grams.get(str(left.get("atom_id")), set()), text_grams.get(str(right.get("atom_id")), set()))
            if similarity >= threshold:
                collector.add(
                    "BLOCKER",
                    "split_near_duplicate",
                    f"{left.get('atom_id')}|{right.get('atom_id')}",
                    f"跨 split 字幕相似度 < {threshold}",
                    f"{similarity:.4f}",
                    owner,
                )


def validate_cues(records: list[dict[str, Any]], atoms: dict[str, dict[str, Any]], collector: IssueCollector) -> None:
    owner = "T2 cue"
    validate_unique(records, "cue_id", "cue", owner, collector)
    for cue in records:
        cue_id = str(cue.get("cue_id", "cue:unknown"))
        atom = atoms.get(cue.get("atom_id"))
        if atom is None:
            collector.add("BLOCKER", "cue_atom_missing", cue_id, "atom_id 指向已验证 source atom", repr(cue.get("atom_id")), owner)
            continue
        if cue.get("split") != atom.get("split"):
            collector.add("BLOCKER", "cue_split", cue_id, f"split={atom.get('split')}", repr(cue.get("split")), owner)
        source_text = normalized_text(" ".join(str(atom.get(field) or "") for field in ("transcript", "dense_caption", "visible_text")))
        for field_name in ("source_text", "supporting_text_span"):
            claimed = normalized_text(str(cue.get(field_name, "")))
            if claimed and claimed not in source_text:
                collector.add("BLOCKER", "cue_source_trace", cue_id, f"{field_name} 可在 atom 原文中找到", repr(cue.get(field_name)), owner)


def validate_seeds(
    records: list[dict[str, Any]], atoms: dict[str, dict[str, Any]], frozen: bool, collector: IssueCollector
) -> None:
    owner = "T3 compiler" if frozen else "T2 seed"
    validate_unique(records, "seed_id", "frozen" if frozen else "candidate", owner, collector)
    ids = set(atoms)
    for seed in records:
        seed_id = str(seed.get("seed_id", "seed:unknown"))
        trigger = seed.get("trigger_atom_id")
        lures = seed.get("lure_atom_ids", [])
        if trigger not in ids:
            collector.add("BLOCKER", "seed_trigger_missing", seed_id, "trigger_atom_id 指向已验证 atom", repr(trigger), owner)
            continue
        if trigger in lures:
            collector.add("BLOCKER", "seed_trigger_as_lure", seed_id, "trigger 不能同时是 lure", repr(trigger), owner)
        for lure in lures:
            if lure not in ids:
                collector.add("BLOCKER", "seed_lure_missing", seed_id, "每个 lure 指向已验证 atom", repr(lure), owner)
            elif atoms[lure].get("split") != seed.get("split"):
                collector.add("BLOCKER", "seed_lure_split", seed_id, f"lure split={seed.get('split')}", f"{lure}={atoms[lure].get('split')}", owner)
        trigger_atom = atoms[trigger]
        if trigger_atom.get("split") != seed.get("split"):
            collector.add("BLOCKER", "seed_trigger_split", seed_id, f"trigger split={seed.get('split')}", repr(trigger_atom.get("split")), owner)
        if seed.get("source_group_id") != trigger_atom.get("source_group_id"):
            collector.add("BLOCKER", "seed_source_group", seed_id, f"source_group_id={trigger_atom.get('source_group_id')}", repr(seed.get("source_group_id")), owner)
        required_silent = {"completed", "cancelled", "expired", "already_reminded"}
        supplied_silent = set(seed.get("terminal_silent_conditions", []))
        if not required_silent.issubset(supplied_silent):
            collector.add("BLOCKER", "seed_terminal_silence", seed_id, f"包含 {sorted(required_silent)}", repr(sorted(supplied_silent)), owner)
        if seed.get("current_trigger_leakage_checked") is not True:
            collector.add("BLOCKER", "seed_trigger_leakage_check", seed_id, "current_trigger_leakage_checked=true", repr(seed.get("current_trigger_leakage_checked")), owner)
        if frozen:
            audit = seed.get("audit", {})
            if audit.get("status") != "accept" or not isinstance(audit.get("human_reviewer"), str) or not audit["human_reviewer"].strip():
                collector.add("BLOCKER", "frozen_seed_human_audit", seed_id, "冻结 seed 具有 accept 和人工审阅者", repr(audit), owner)
    if frozen and not 35 <= len(records) <= 40:
        collector.add("BLOCKER", "frozen_seed_count", "frozen_seeds", "35–40 个冻结 seed", str(len(records)), owner)


def parse_virtual_time(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    match = VIRTUAL_TIME.fullmatch(value)
    if not match:
        return None
    return (
        int(match.group("d")) * 24 * 3600
        + int(match.group("h")) * 3600
        + int(match.group("m")) * 60
        + int(match.group("s") or 0)
    )


def source_event_duration(event: dict[str, Any]) -> float:
    source_time = event.get("source_time")
    if not isinstance(source_time, dict):
        return 0.0
    return float(source_time.get("local_end_sec", 0)) - float(source_time.get("local_start_sec", 0))


def validate_lifelogs(
    records: list[dict[str, Any]], atoms: dict[str, dict[str, Any]], seeds: dict[str, dict[str, Any]], config: RunConfig, collector: IssueCollector
) -> None:
    owner = "T3 compiler"
    validate_unique(records, "lifelog_id", "lifelog", owner, collector)
    seen_event_ids: set[str] = set()
    policies = config.protocol["difficulties"]
    families: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for log in records:
        log_id = str(log.get("lifelog_id", "lifelog:unknown"))
        families[str(log.get("family_id"))].append(log)
        if log.get("seed_id") not in seeds:
            collector.add("BLOCKER", "lifelog_seed_missing", log_id, "seed_id 指向已冻结 seed", repr(log.get("seed_id")), owner)
        elif log.get("split") != seeds[log["seed_id"]].get("split"):
            collector.add("BLOCKER", "lifelog_seed_split", log_id, f"split={seeds[log['seed_id']].get('split')}", repr(log.get("split")), owner)
        events = log.get("events", [])
        if log.get("event_count") != len(events):
            collector.add("BLOCKER", "lifelog_event_count", log_id, f"event_count={len(events)}", repr(log.get("event_count")), owner)
        positions = [event.get("event_position") for event in events]
        if positions != list(range(len(events))):
            collector.add("BLOCKER", "lifelog_positions", log_id, "event_position 从 0 连续递增", repr(positions[:10]), owner)
        times = [parse_virtual_time(event.get("virtual_time")) for event in events]
        if any(value is None for value in times) or any(later < earlier for earlier, later in zip(times, times[1:])):
            collector.add("BLOCKER", "lifelog_virtual_time", log_id, "虚拟时间可解析且不倒退", repr([event.get("virtual_time") for event in events[:5]]), owner)
        difficulty = log.get("difficulty")
        policy = policies.get(difficulty, {})
        event_range = policy.get("event_count", [0, 0])
        if isinstance(event_range, list) and len(event_range) == 2 and not event_range[0] <= len(events) <= event_range[1]:
            collector.add("BLOCKER", "difficulty_event_count", log_id, f"{difficulty} 事件数在 {event_range}", str(len(events)), owner)
        if times and all(value is not None for value in times):
            span_minutes = (times[-1] - times[0]) / 60
            span_range = policy.get("virtual_span_minutes", [0, float("inf")])
            if not span_range[0] <= span_minutes <= span_range[1]:
                collector.add("BLOCKER", "difficulty_virtual_span", log_id, f"{difficulty} 虚拟跨度在 {span_range} 分钟", f"{span_minutes:.3f}", owner)
        # 背景或桥接事件可不声明状态；一旦声明就必须承接上一个状态，防止终态被悄然重新激活。
        carried_state: str | None = None
        source_seconds = 0.0
        source_session_last_start: dict[str, float] = {}
        for event in events:
            event_id = str(event.get("event_id", f"{log_id}:event"))
            if event_id in seen_event_ids:
                collector.add("BLOCKER", "duplicate_event_id", event_id, "event_id 在全部 life log 中唯一", "发现重复", owner)
            seen_event_ids.add(event_id)
            before, after = event.get("intention_state_before"), event.get("intention_state_after")
            if before is not None and carried_state is not None and before != carried_state:
                collector.add("BLOCKER", "state_chain", event_id, f"state_before={carried_state}", repr(before), owner)
            if before in STATE_TRANSITIONS and after not in STATE_TRANSITIONS[before]:
                collector.add("BLOCKER", "state_transition", event_id, f"{before} 的合法后继状态", repr(after), owner)
            if after is not None:
                carried_state = after
            kind = event.get("event_kind")
            if kind in {"constructed_intention", "constructed_observation"} and not isinstance(event.get("rule_id"), str):
                collector.add("BLOCKER", "constructed_rule_id", event_id, "构造事件含 rule_id", repr(event.get("rule_id")), owner)
            if kind == "source_video_atom":
                atom = atoms.get(event.get("atom_id"))
                if atom is None:
                    collector.add("BLOCKER", "lifelog_atom_missing", event_id, "atom_id 指向已验证 source atom", repr(event.get("atom_id")), owner)
                    continue
                if atom.get("split") != log.get("split"):
                    collector.add("BLOCKER", "lifelog_atom_split", event_id, f"atom split={log.get('split')}", repr(atom.get("split")), owner)
                for field_name in ("visible_text", "source_srt_paths", "source_video_path"):
                    if event.get(field_name) != atom.get(field_name):
                        collector.add("BLOCKER", "lifelog_source_trace", event_id, f"{field_name} 与 atom 完全一致", repr(event.get(field_name)), owner)
                source_time = event.get("source_time")
                if not isinstance(source_time, dict):
                    collector.add("BLOCKER", "lifelog_source_time", event_id, "source atom 具有 source_time", repr(source_time), owner)
                else:
                    expected_time = {
                        "local_start_sec": atom.get("local_start_sec"),
                        "local_end_sec": atom.get("local_end_sec"),
                        "normalized_start_sec": atom.get("normalized_start_sec"),
                        "normalized_end_sec": atom.get("normalized_end_sec"),
                    }
                    if source_time != expected_time:
                        collector.add("BLOCKER", "lifelog_source_time", event_id, "source_time 与 atom 完全一致", repr(source_time), owner)
                start = atom.get("normalized_start_sec")
                session = str(atom.get("session_id"))
                # 虚拟时间可重排不同来源，但同一 session 内 atom 不能倒放，否则会伪造 SRT 顺序。
                if isinstance(start, (int, float)) and session in source_session_last_start and start < source_session_last_start[session]:
                    collector.add("BLOCKER", "lifelog_source_order", event_id, "同一 session 的 source atom 不倒序", f"{start} < {source_session_last_start[session]}", owner)
                if isinstance(start, (int, float)):
                    source_session_last_start[session] = float(start)
                source_seconds += source_event_duration(event)
            video_path = event.get("source_video_path")
            if isinstance(video_path, str):
                resolved_video = resolve_source_path(video_path, config)
                if event.get("video_mapping_status") != "verified" or not resolved_video.is_file():
                    collector.add("BLOCKER", "fabricated_video_path", event_id, "仅 verified 且存在的 MP4 路径可出现；否则为 null", repr(video_path), owner)
        if abs(float(log.get("referenced_source_seconds", 0)) - source_seconds) > 0.001:
            collector.add("BLOCKER", "lifelog_referenced_seconds", log_id, f"{source_seconds:.3f}", repr(log.get("referenced_source_seconds")), owner)
    expected_variants = {(branch, difficulty) for branch in ("positive", "negative") for difficulty in policies}
    for family_id, logs in families.items():
        variants = {(log.get("counterfactual_branch"), log.get("difficulty")) for log in logs}
        if variants != expected_variants or len(logs) != 6:
            collector.add("BLOCKER", "family_six_variants", family_id, f"恰好具有 {sorted(expected_variants)}", repr(sorted(variants)), owner)
            continue
        seed_ids = {log.get("seed_id") for log in logs}
        splits = {log.get("split") for log in logs}
        if len(seed_ids) != 1 or len(splits) != 1:
            collector.add("BLOCKER", "family_integrity", family_id, "同 family 的 seed/split 一致", f"seeds={seed_ids}, splits={splits}", owner)
        trigger_atoms: set[Any] = set()
        metrics: dict[str, tuple[int, float]] = {}
        for log in logs:
            triggers = [event.get("atom_id") for event in log.get("events", []) if event.get("event_role") == "trigger"]
            if len(triggers) != 1 or not isinstance(triggers[0], str):
                collector.add("BLOCKER", "family_trigger", str(log.get("lifelog_id")), "每条 log 恰有一个 source trigger", repr(triggers), owner)
                continue
            trigger_atoms.add(triggers[0])
            parsed = [parse_virtual_time(event.get("virtual_time")) for event in log["events"]]
            metrics[str(log.get("lifelog_id"))] = (
                len(log["events"]),
                float(parsed[-1] - parsed[0]) if all(value is not None for value in parsed) else -1.0,
            )
        if len(trigger_atoms) != 1:
            collector.add("BLOCKER", "family_trigger_consistency", family_id, "六条 family log 使用同一 trigger atom", repr(sorted(str(value) for value in trigger_atoms)), owner)
        for branch in ("positive", "negative"):
            branch_logs = {log["difficulty"]: log for log in logs if log["counterfactual_branch"] == branch}
            if len(branch_logs) == 3:
                short = metrics.get(str(branch_logs["short"]["lifelog_id"]))
                medium = metrics.get(str(branch_logs["medium"]["lifelog_id"]))
                long = metrics.get(str(branch_logs["long"]["lifelog_id"]))
                if short and medium and long and not (short[0] < medium[0] < long[0] and short[1] < medium[1] < long[1]):
                    collector.add("BLOCKER", "difficulty_monotonicity", family_id, "short < medium < long 的事件数和虚拟跨度", f"{short}, {medium}, {long}", owner)


def expected_oracle_kind(decision: dict[str, Any]) -> str:
    # 直接重算冻结协议，而非相信生产者写入的 gold，防止 LLM 或人工标签替代确定性 oracle。
    annotation = decision.get("oracle_annotation", {})
    current_time = parse_virtual_time(decision.get("model_input", {}).get("virtual_time"))
    window = decision.get("valid_window", {})
    start = parse_virtual_time(window.get("start_virtual_time"))
    end = parse_virtual_time(window.get("end_virtual_time"))
    active_trigger = decision.get("decision_type") == "trigger" and annotation.get("state_before") == "active_unreminded"
    inside_window = current_time is not None and start is not None and end is not None and start <= current_time <= end
    return "remind" if active_trigger and inside_window else "silent"


def validate_decisions(
    records: list[dict[str, Any]], lifelogs: dict[str, dict[str, Any]], collector: IssueCollector
) -> None:
    owner = "T3 compiler"
    validate_unique(records, "decision_id", "decisions", owner, collector)
    for decision in records:
        decision_id = str(decision.get("decision_id", "decision:unknown"))
        log = lifelogs.get(decision.get("lifelog_id"))
        if log is None:
            collector.add("BLOCKER", "decision_lifelog_missing", decision_id, "lifelog_id 指向已验证 life log", repr(decision.get("lifelog_id")), owner)
            continue
        for field_name in ("family_id", "split", "difficulty"):
            if decision.get(field_name) != log.get(field_name):
                collector.add("BLOCKER", "decision_lifelog_consistency", decision_id, f"{field_name}={log.get(field_name)}", repr(decision.get(field_name)), owner)
        model_input = decision.get("model_input", {})
        event_map = {event.get("event_id"): event for event in log.get("events", [])}
        event = event_map.get(model_input.get("current_event_id"))
        if event is None:
            collector.add("BLOCKER", "decision_current_event", decision_id, "current_event_id 出现在对应 life log", repr(model_input.get("current_event_id")), owner)
        else:
            for input_field, event_field in (("stream_position", "event_position"), ("virtual_time", "virtual_time"), ("visible_text", "visible_text")):
                if model_input.get(input_field) != event.get(event_field):
                    collector.add("BLOCKER", "decision_observation_trace", decision_id, f"{input_field} 与当前事件一致", repr(model_input.get(input_field)), owner)
        # 决策模型只能看当前可见文本。内部字段、规则 ID 和状态进入文本会直接泄露答案。
        visible = str(model_input.get("visible_text", "")).casefold()
        leaked = [marker for marker in FORBIDDEN_INPUT_MARKERS if marker in visible]
        if leaked or re.search(r"\b(?:int|rule)_[A-Za-z0-9_]+\b", str(model_input.get("visible_text", ""))):
            collector.add("BLOCKER", "answer_leakage", decision_id, "模型输入不含 gold、状态、role、rule 或内部 ID", repr(leaked or "内部 ID"), owner)
        expected_kind = expected_oracle_kind(decision)
        gold = decision.get("gold_action", {})
        if gold.get("kind") != expected_kind:
            collector.add("BLOCKER", "oracle_action", decision_id, f"gold_action.kind={expected_kind}", repr(gold.get("kind")), owner)
        expected_ids = [decision.get("target_intention_id")] if expected_kind == "remind" else []
        if gold.get("intention_ids") != expected_ids:
            collector.add("BLOCKER", "oracle_intention_ids", decision_id, f"intention_ids={expected_ids}", repr(gold.get("intention_ids")), owner)
        annotation = decision.get("oracle_annotation", {})
        if expected_kind == "remind" and annotation.get("state_after") != "active_reminded":
            collector.add("BLOCKER", "oracle_state_transition", decision_id, "remind 后 state_after=active_reminded", repr(annotation.get("state_after")), owner)
        for group in decision.get("evidence_support_groups", []):
            for item in group.get("items", []):
                if item.get("event_id") not in event_map:
                    collector.add("BLOCKER", "evidence_event_missing", decision_id, "证据 event_id 位于同一 life log", repr(item.get("event_id")), owner)


def validate_counterfactual_pairs(records: list[dict[str, Any]], lifelogs: dict[str, dict[str, Any]], collector: IssueCollector) -> None:
    owner = "T3 compiler"
    pairs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for decision in records:
        pairs[str(decision.get("counterfactual_pair_id"))].append(decision)
    for pair_id, pair in pairs.items():
        # 反事实必须在相同当前 trigger 上仅凭历史状态翻转；先固定当前观察，
        # 再检查正负动作，避免通过删除当前 cue 制造“负例”。
        if len(pair) != 2:
            collector.add("BLOCKER", "counterfactual_pair_cardinality", pair_id, "每个 pair 恰有正负两个 decision", f"{len(pair)} 条", owner)
            continue
        left, right = pair
        left_log, right_log = lifelogs.get(left.get("lifelog_id")), lifelogs.get(right.get("lifelog_id"))
        if left_log is None or right_log is None:
            continue
        if {left_log.get("counterfactual_branch"), right_log.get("counterfactual_branch")} != {"positive", "negative"}:
            collector.add("BLOCKER", "counterfactual_branches", pair_id, "一条 positive 与一条 negative", repr([left_log.get("counterfactual_branch"), right_log.get("counterfactual_branch")]), owner)
        for field_name in ("family_id", "difficulty", "split", "target_intention_id"):
            if left.get(field_name) != right.get(field_name):
                collector.add("BLOCKER", "counterfactual_pair_consistency", pair_id, f"两个 decision 的 {field_name} 相同", f"{left.get(field_name)!r}/{right.get(field_name)!r}", owner)
        def current_atom(decision: dict[str, Any], log: dict[str, Any]) -> Any:
            event_id = decision.get("model_input", {}).get("current_event_id")
            return next((event.get("atom_id") for event in log.get("events", []) if event.get("event_id") == event_id), None)
        if current_atom(left, left_log) != current_atom(right, right_log) or current_atom(left, left_log) is None:
            collector.add("BLOCKER", "counterfactual_trigger_match", pair_id, "正负分支当前 trigger atom 完全相同", f"{current_atom(left, left_log)!r}/{current_atom(right, right_log)!r}", owner)
        if left.get("model_input", {}).get("visible_text") != right.get("model_input", {}).get("visible_text"):
            collector.add("BLOCKER", "counterfactual_current_leakage", pair_id, "正负分支当前可见文本相同", "当前文本不同", owner)
        positive = left if left_log.get("counterfactual_branch") == "positive" else right
        negative = right if positive is left else left
        if positive.get("gold_action", {}).get("kind") != "remind" or negative.get("gold_action", {}).get("kind") != "silent":
            collector.add("BLOCKER", "counterfactual_gold_flip", pair_id, "positive=remind 且 negative=silent", f"{positive.get('gold_action')!r}/{negative.get('gold_action')!r}", owner)


def counterfactual_delta_contract_issue(config: RunConfig, collector: IssueCollector) -> None:
    """冻结合同没有为“声明的历史差异”定义可哈希、可验证的结构。"""
    pair_path = config.artifact("counterfactual_pairs")
    collector.add(
        "WARNING",
        "contract_counterfactual_delta_unverifiable",
        "counterfactual_pairs",
        "冻结且有哈希的 pair manifest，逐对声明唯一历史差异与两侧 log ID",
        f"v1.0.0 未定义该文件 schema/SUCCESS 哈希；T4 不能安全读取 {pair_path.name}",
        "T0 contract CHANGE_REQUEST",
    )


def write_audit_outputs(config: RunConfig, collector: IssueCollector, all_ready: bool) -> None:
    error_path = config.artifact("validation_errors")
    error_text = "".join(json.dumps(issue, ensure_ascii=False, sort_keys=True) + "\n" for issue in collector.issues)
    atomic_write_text(error_path, error_text)
    leakage = {
        "contract_version": CONTRACT_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(),
        "blocker_count": len(collector.blockers),
        "answer_leakage_count": sum(issue["issue_type"] == "answer_leakage" for issue in collector.issues),
        "split_leakage_count": sum(issue["issue_type"].startswith("split_") for issue in collector.issues),
        "issues_by_type": dict(sorted(Counter(issue["issue_type"] for issue in collector.issues).items())),
    }
    leakage_path = config.artifact("leakage_report")
    atomic_write_text(leakage_path, json.dumps(leakage, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    final_marker = config.marker("final_validation")
    if all_ready and not collector.blockers:
        upstream_hashes = {
            stage: json.loads(config.marker(marker_key).read_text(encoding="utf-8"))["sha256"]
            for stage, marker_key, _, _, _ in STAGES
        }
        marker = {
            "artifact_path": config.canonical_artifact_name(error_path),
            "sha256": sha256_file(error_path),
            "row_count": jsonl_row_count(error_path),
            "contract_version": CONTRACT_VERSION,
            "config_version": CONTRACT_VERSION,
            "schema_versions": {"audit": CONTRACT_VERSION},
            "generated_at": datetime.now().astimezone().isoformat(),
            "upstream_hashes": upstream_hashes,
        }
        atomic_write_text(final_marker, json.dumps(marker, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    elif final_marker.exists():
        # 这是 T4 自己的成功标记；新的阻断错误出现时不能保留过期的通过结论，
        # 否则下游会把已经失效的“通过”当作仍可发布的依据。
        final_marker.unlink()


def run_validation(config_path: Path, write: bool = True) -> tuple[IssueCollector, dict[str, list[dict[str, Any]]], dict[str, bool]]:
    config = load_run_config(config_path)
    collector = IssueCollector()
    data: dict[str, list[dict[str, Any]]] = {}
    readiness: dict[str, bool] = {}
    for stage, marker_key, artifact_key, schema_name, owner in STAGES:
        dependencies = STAGE_DEPENDENCIES[stage]
        if not all(readiness.get(dependency, False) for dependency in dependencies):
            collector.add("BLOCKER", "upstream_stage_unavailable", stage, f"上游阶段 {list(dependencies)} 的 SUCCESS/哈希均通过", "上游标记或哈希未通过", owner)
            readiness[stage] = False
            continue
        # 每一阶段独立守住 SUCCESS/哈希边界；依赖未冻结时只记录门禁问题，绝不窥读下游 JSONL。
        ready = marker_is_valid(config, stage, marker_key, artifact_key, owner, collector)
        readiness[stage] = ready
        if not ready:
            continue
        records = read_jsonl(config.artifact(artifact_key), collector, stage, owner)
        validate_schema(records, config.config_dir.parent / "schemas" / schema_name, stage, owner, collector)
        data[stage] = records
    if readiness.get("source"):
        validate_source(data.get("source", []), config, collector)
    atoms = {record.get("atom_id"): record for record in data.get("source", []) if isinstance(record.get("atom_id"), str)}
    if readiness.get("cue") and readiness.get("source"):
        validate_cues(data.get("cue", []), atoms, collector)
    if readiness.get("candidate") and readiness.get("source"):
        validate_seeds(data.get("candidate", []), atoms, False, collector)
    if readiness.get("frozen") and readiness.get("source"):
        validate_seeds(data.get("frozen", []), atoms, True, collector)
    frozen = {record.get("seed_id"): record for record in data.get("frozen", []) if isinstance(record.get("seed_id"), str)}
    if readiness.get("lifelog") and readiness.get("source") and readiness.get("frozen"):
        validate_lifelogs(data.get("lifelog", []), atoms, frozen, config, collector)
    lifelogs = {record.get("lifelog_id"): record for record in data.get("lifelog", []) if isinstance(record.get("lifelog_id"), str)}
    if readiness.get("decisions") and readiness.get("lifelog"):
        validate_decisions(data.get("decisions", []), lifelogs, collector)
        validate_counterfactual_pairs(data.get("decisions", []), lifelogs, collector)
        counterfactual_delta_contract_issue(config, collector)
    all_ready = all(readiness.get(stage[0], False) for stage in STAGES)
    if write:
        write_audit_outputs(config, collector, all_ready)
    return collector, data, readiness


def main() -> int:
    parser = argparse.ArgumentParser(description="EgoPM-Bench v1 全量独立 QA")
    parser.add_argument("--config", type=Path, required=True, help="benchmark_protocol.yaml 的路径")
    parser.add_argument("--no-write", action="store_true", help="仅检查，不写 audit 输出")
    args = parser.parse_args()
    try:
        collector, _, readiness = run_validation(args.config, write=not args.no_write)
    except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
        print(f"验证器启动失败：{exc}", file=sys.stderr)
        return 2
    print(json.dumps({"readiness": readiness, "blocker_count": len(collector.blockers), "issue_count": len(collector.issues)}, ensure_ascii=False))
    return 1 if collector.blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
