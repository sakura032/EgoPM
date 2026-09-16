"""Source 流水线第 03 步：按时间窗口对齐两种字幕，输出草稿 Source Atom 与报告。

输入为第 02 步 `raw_srt_segments.jsonl` 和冻结配置中的对齐容差；输出为
`source_video_atoms_draft.jsonl` 草稿及 `atom_build_report.json`。本步以 Dense Caption
为可观察动作主窗口、宽松保留单模态文本；split 只会由第 04 步冻结，故不能发布
SUCCESS 标记。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml
import jsonschema


def _load_paths(config_path: Path) -> tuple[dict[str, Any], Path, Path, Path, Path]:
    config_path = config_path.resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError(f"配置不是对象：{config_path}")
    config_dir = config_path.parent

    def resolve(value: str) -> Path:
        candidate = Path(value)
        return candidate if candidate.is_absolute() else (config_dir / candidate).resolve()

    return (
        config,
        resolve(str(config["artifacts"]["raw_srt_segments"])),
        resolve(str(config["artifacts"]["source_atoms_draft"])),
        resolve(str(config["artifacts"]["source_report"])),
        resolve(str(config["schema_dir"])) / "source_video_atom_draft.schema.json",
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_identifier(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    return result or "unknown"


def _interval_gap(left: dict[str, Any], right: dict[str, Any]) -> float:
    # 重叠的间隔为零；非重叠时取最近端点距离，才能用同一容差一致处理“重叠或近邻”。
    return max(0.0, float(left["start_sec"]) - float(right["end_sec"]), float(right["start_sec"]) - float(left["end_sec"]))


def _join_text(segments: Iterable[dict[str, Any]]) -> str:
    return " ".join(segment["text"] for segment in segments)


def _visible_text(transcript: str | None, dense_caption: str | None) -> str:
    if transcript and dense_caption:
        return f"Dense caption: {dense_caption}\nTranscript: {transcript}"
    if dense_caption:
        return dense_caption
    if transcript:
        return transcript
    raise ValueError("atom 至少需要一种非空模态文本")


def _source_path(segments: list[dict[str, Any]]) -> str | None:
    paths = sorted({str(segment["relative_path"]) for segment in segments})
    if len(paths) > 1:
        # 一个 session/modality 原子跨多个文件会让 schema 中单一路径失真，必须显式中止。
        raise ValueError(f"一个 atom 的同一模态不应来自多个 SRT：{paths}")
    return paths[0] if paths else None


def _make_atom(
    *,
    participant: str,
    source_day: str,
    session_id: str,
    ordinal: int,
    transcript_segments: list[dict[str, Any]],
    dense_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    if dense_segments:
        start_sec = min(float(segment["start_sec"]) for segment in dense_segments)
        end_sec = max(float(segment["end_sec"]) for segment in dense_segments)
    else:
        start_sec = min(float(segment["start_sec"]) for segment in transcript_segments)
        end_sec = max(float(segment["end_sec"]) for segment in transcript_segments)

    transcript = _join_text(transcript_segments) if transcript_segments else None
    dense_caption = _join_text(dense_segments) if dense_segments else None
    coverage = "both" if transcript and dense_caption else "transcript_only" if transcript else "dense_caption_only"
    session_token = _safe_identifier(session_id)
    atom_id = f"src_{_safe_identifier(participant)}_{_safe_identifier(source_day)}_{session_token}_{ordinal:06d}"
    return {
        "atom_id": atom_id,
        "atom_kind": "source_video_atom",
        "atom_stage": "draft",
        "participant_source_id": participant,
        "source_day": source_day,
        "session_id": session_id,
        "source_group_id": f"group_{session_token}",
        "world_event_id": None,
        "source_srt_paths": {
            "transcript": _source_path(transcript_segments),
            "dense_caption": _source_path(dense_segments),
        },
        "source_video_path": None,
        "video_mapping_status": "pending",
        "local_start_sec": start_sec,
        "local_end_sec": end_sec,
        # SRT 没有跨文件的全局时钟；在 v1 中 normalized 表示 session 相对时钟，故与 local 相同，
        # 而不是虚构跨视频的绝对时间。
        "normalized_start_sec": start_sec,
        "normalized_end_sec": end_sec,
        "transcript_segment_ids": [segment["segment_id"] for segment in transcript_segments],
        "dense_caption_segment_ids": [segment["segment_id"] for segment in dense_segments],
        "transcript": transcript,
        "dense_caption": dense_caption,
        "visible_text": _visible_text(transcript, dense_caption),
        "modality_coverage": coverage,
        "provenance": "egolife_srt",
        # 草稿绝不能伪装为训练集：只有第 04 步冻结 split 后，才会形成可被下游读取的最终原子。
        "split": None,
    }


def _build_atoms(records: list[dict[str, Any]], tolerance_seconds: float) -> list[dict[str, Any]]:
    # 错误与过滤记录已被第 02 步审计保存，但没有合法时间/文本，绝不能参与时间对齐。
    successful = [record for record in records if record.get("parse_status") == "ok"]
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in successful:
        grouped[(record["participant_source_id"], record["source_day"], record["session_id"])].append(record)

    atoms: list[dict[str, Any]] = []
    for group_key in sorted(grouped):
        participant, source_day, session_id = group_key
        segments = grouped[group_key]
        transcripts = sorted(
            (segment for segment in segments if segment["modality"] == "transcript"),
            key=lambda segment: (float(segment["start_sec"]), float(segment["end_sec"]), segment["segment_id"]),
        )
        dense_captions = sorted(
            (segment for segment in segments if segment["modality"] == "dense_caption"),
            key=lambda segment: (float(segment["start_sec"]), float(segment["end_sec"]), segment["segment_id"]),
        )
        attached_transcript_ids: set[str] = set()
        candidates: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []
        for dense_caption in dense_captions:
            # Dense Caption 是主动作窗口；一个 Transcript 可挂接多个窗口，符合一对多对齐规则。
            matched_transcripts = [
                transcript
                for transcript in transcripts
                if _interval_gap(dense_caption, transcript) <= tolerance_seconds
            ]
            attached_transcript_ids.update(segment["segment_id"] for segment in matched_transcripts)
            candidates.append((matched_transcripts, [dense_caption]))

        for transcript in transcripts:
            if transcript["segment_id"] not in attached_transcript_ids:
                # 宽松保留未命中的 Transcript，防止为后续 cue 检索过早丢失生活事实。
                candidates.append(([transcript], []))

        candidates.sort(
            key=lambda candidate: (
                min(
                    float(segment["start_sec"])
                    for segment in [*candidate[0], *candidate[1]]
                ),
                min(segment["segment_id"] for segment in [*candidate[0], *candidate[1]]),
            )
        )
        for ordinal, (matched_transcripts, dense_segments) in enumerate(candidates, start=1):
            atoms.append(
                _make_atom(
                    participant=participant,
                    source_day=source_day,
                    session_id=session_id,
                    ordinal=ordinal,
                    transcript_segments=matched_transcripts,
                    dense_segments=dense_segments,
                )
            )
    return atoms


def _duration_summary(atoms: list[dict[str, Any]]) -> dict[str, float | int]:
    durations = [float(atom["local_end_sec"]) - float(atom["local_start_sec"]) for atom in atoms]
    if not durations:
        return {"count": 0, "total": 0.0, "minimum": 0.0, "maximum": 0.0, "mean": 0.0}
    return {
        "count": len(durations),
        "total": round(sum(durations), 6),
        "minimum": round(min(durations), 6),
        "maximum": round(max(durations), 6),
        "mean": round(statistics.fmean(durations), 6),
    }


def _build_report(
    config: dict[str, Any], raw_segments_path: Path, records: list[dict[str, Any]], atoms: list[dict[str, Any]], tolerance_seconds: float
) -> dict[str, Any]:
    successful_segments = [record for record in records if record.get("parse_status") == "ok"]
    dense_count = sum(record["modality"] == "dense_caption" for record in successful_segments)
    both_count = sum(atom["modality_coverage"] == "both" for atom in atoms)
    coverage = Counter(atom["modality_coverage"] for atom in atoms)
    errors = [record for record in records if record.get("parse_status") == "error"]
    return {
        "contract_version": config["contract_version"],
        "config_version": config["config_version"],
        "schema_version": "v1.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stage": "alignment_draft_pending_split_freeze",
        "input_hashes": {"raw_srt_segments": _sha256(raw_segments_path)},
        "time_coordinate_system": {
            "local_start_sec": "单个 SRT 文件内的相对秒",
            "normalized_start_sec": "v1 当前使用 session 相对秒；缺少跨文件全局时钟时与 local 相同",
        },
        "alignment": {
            "tolerance_seconds": tolerance_seconds,
            "dense_caption_primary_windows": dense_count,
            "dense_caption_windows_with_transcript": both_count,
            "pairing_rate": round(both_count / dense_count, 6) if dense_count else 0.0,
            "atom_merging": "已由冻结配置禁用；保留最小可追溯字幕窗口",
        },
        "counts": {
            "raw_segment_records": len(records),
            "successful_segments": len(successful_segments),
            "source_atoms": len(atoms),
            "modality_coverage": dict(sorted(coverage.items())),
        },
        "single_modality_atom_ratio": round(
            (coverage["transcript_only"] + coverage["dense_caption_only"]) / len(atoms), 6
        )
        if atoms
        else 0.0,
        "duration_seconds": _duration_summary(atoms),
        "anomalies": {
            "atoms_longer_than_30_seconds": [
                atom["atom_id"]
                for atom in atoms
                if float(atom["local_end_sec"]) - float(atom["local_start_sec"]) > 30
            ],
            "unparsed_files": sorted({record.get("relative_path", "") for record in errors}),
        },
        "split_status": "pending_04_make_source_splits",
    }


def _write_json_atomically(output_path: Path, payload: Any) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(output_path.name + ".tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        # 报告与草稿都通过临时文件替换，防止 T4 或人工检查时读到不完整统计。
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary_path, output_path)


def _write_jsonl_atomically(output_path: Path, records: Iterable[dict[str, Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(output_path.name + ".tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary_path, output_path)


def _frozen_alignment_tolerance(config: dict[str, Any]) -> float:
    """读取并校验 T0 冻结的 v1 对齐策略，拒绝运行时覆盖。"""

    source_build = config.get("source_build")
    if not isinstance(source_build, dict):
        raise ValueError("paths.yaml 缺少冻结的 source_build 配置")
    alignment = source_build.get("alignment")
    atom_merging = source_build.get("atom_merging")
    if not isinstance(alignment, dict) or not isinstance(atom_merging, dict):
        raise ValueError("source_build 缺少 alignment 或 atom_merging 配置")
    tolerance = alignment.get("transcript_dense_caption_tolerance_seconds")
    if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool) or tolerance < 0:
        # 负数、布尔值或缺失值都无法表达可复现的字幕时间窗口，必须在写草稿前中止。
        raise ValueError("冻结的 transcript_dense_caption_tolerance_seconds 必须为非负数")
    if alignment.get("primary_window_modality") != "dense_caption":
        raise ValueError("v1 对齐主窗口必须为 dense_caption")
    if atom_merging.get("enabled") is not False:
        raise ValueError("v1 禁止合并相邻字幕窗口")
    return float(tolerance)


def _validate_draft_atoms(atoms: list[dict[str, Any]], schema_path: Path) -> None:
    """在原子替换前验证草稿边界，避免把带最终 split 的记录写入草稿路径。"""

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = [
        f"{atom.get('atom_id', '<missing>')}: {error.message}"
        for atom in atoms
        for error in validator.iter_errors(atom)
    ]
    if errors:
        raise ValueError("Source Atom 草稿 Schema 验证失败：" + "; ".join(errors))


def run(config_path: Path) -> tuple[Path, Path]:
    """按 T0 冻结容差生成独立草稿；运行时不接受可漂移的对齐参数。"""

    config, raw_segments_path, output_path, report_path, schema_path = _load_paths(config_path)
    tolerance_seconds = _frozen_alignment_tolerance(config)
    records = _read_jsonl(raw_segments_path)
    atoms = _build_atoms(records, tolerance_seconds)
    _validate_draft_atoms(atoms, schema_path)
    report = _build_report(config, raw_segments_path, records, atoms, tolerance_seconds)
    _write_jsonl_atomically(output_path, atoms)
    _write_json_atomically(report_path, report)
    return output_path, report_path


def main() -> None:
    parser = argparse.ArgumentParser(description="对齐 Transcript 与 Dense Caption SRT 文本")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "config" / "paths.yaml",
        help="冻结的 paths.yaml 路径",
    )
    arguments = parser.parse_args()
    run(arguments.config)


if __name__ == "__main__":
    main()
