"""Source 流水线第 02 步：解析清单中的 SRT，输出 `raw_srt_segments.jsonl`。

输入是第 01 步 inventory 和其中指向的只读 SRT；输出既保留可用字幕块，也保留
失败或过滤记录及其 `error`，供第 03 步和审计报告追踪。该步骤不做模态对齐、
不分 split，也不发布 SUCCESS 标记。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

import yaml


TIMECODE_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s+-->\s+"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})(?:\s+.*)?$"
)


def _load_paths(config_path: Path) -> tuple[dict[str, Any], Path, Path, Path]:
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
        resolve(str(config["raw_root"])),
        resolve(str(config["artifacts"]["source_inventory"])),
        resolve(str(config["artifacts"]["raw_srt_segments"])),
    )


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _seconds(timecode: str) -> float:
    hours, minutes, seconds_and_millis = timecode.replace(",", ".").split(":")
    seconds, milliseconds = seconds_and_millis.split(".")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(milliseconds.ljust(3, "0")[:3]) / 1000


def _record_id(row: dict[str, str], block_ordinal: int) -> str:
    prefix = "tr" if row["modality"] == "transcript" else "dc"
    identity = "_".join(
        re.sub(r"[^A-Za-z0-9]+", "_", row[key]).strip("_")
        for key in ("participant_source_id", "source_day", "session_uid")
    )
    # 同名 SRT 可位于不同子目录；加入稳定路径摘要可避免不同现实来源的字幕 ID 冲突。
    path_digest = hashlib.sha256(row["relative_path"].encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{identity}_{path_digest}_{block_ordinal:06d}"


def _base_record(row: dict[str, str], block_ordinal: int) -> dict[str, Any]:
    return {
        "segment_id": _record_id(row, block_ordinal),
        "modality": row["modality"],
        "participant_source_id": row["participant_source_id"],
        "source_day": row["source_day"],
        "session_id": row["session_id"],
        "session_uid": row["session_uid"],
        "relative_path": row["relative_path"],
        "srt_block_index": block_ordinal,
    }


def _parse_blocks(contents: str) -> Iterable[tuple[int, list[str]]]:
    normalized_newlines = contents.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    for block_ordinal, raw_block in enumerate(re.split(r"\n[\t ]*\n+", normalized_newlines), start=1):
        lines = [line.strip() for line in raw_block.split("\n")]
        if any(line for line in lines):
            yield block_ordinal, lines


def _parse_file(row: dict[str, str], raw_root: Path) -> list[dict[str, Any]]:
    if row["parse_status"] != "discovered":
        record = _base_record(row, 0)
        record.update(
            {
                "parse_status": "error",
                "error": f"inventory_status:{row['parse_status']}",
            }
        )
        return [record]

    srt_path = raw_root.parent / Path(row["relative_path"])
    try:
        contents = srt_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        # 失败不能静默跳过：保留一条 error 记录才可量化来源缺失且支持之后复现。
        record = _base_record(row, 0)
        record.update({"parse_status": "error", "error": f"read_error:{error}"})
        return [record]

    records: list[dict[str, Any]] = []
    previous_normalized_text: str | None = None
    for block_ordinal, lines in _parse_blocks(contents):
        record = _base_record(row, block_ordinal)
        time_line_index = next(
            (index for index, line in enumerate(lines) if TIMECODE_RE.fullmatch(line)),
            None,
        )
        if time_line_index is None:
            record.update({"parse_status": "error", "error": "missing_or_invalid_timecode"})
            records.append(record)
            continue

        timecode_match = TIMECODE_RE.fullmatch(lines[time_line_index])
        assert timecode_match is not None
        try:
            start_sec = _seconds(timecode_match.group("start"))
            end_sec = _seconds(timecode_match.group("end"))
        except ValueError as error:
            record.update({"parse_status": "error", "error": f"invalid_timecode:{error}"})
            records.append(record)
            continue

        if end_sec <= start_sec:
            # 零或负时长无法形成有效可观察窗口，保留错误而不是让下游自行猜测时间。
            record.update({"parse_status": "error", "error": "non_positive_duration"})
            records.append(record)
            continue

        raw_text = "\n".join(lines[time_line_index + 1 :]).strip()
        text = _normalize_text(raw_text)
        if not text:
            # 空块不提供可检索事实，因此不进入对齐；其过滤理由仍写入 JSONL。
            record.update({"parse_status": "discarded_empty", "error": "empty_text"})
            records.append(record)
            previous_normalized_text = text
            continue

        if previous_normalized_text == text:
            # 仅丢弃紧邻且规范化文本完全相同的块，避免把相似但语义可能不同的字幕误删。
            record.update(
                {
                    "parse_status": "discarded_duplicate_adjacent",
                    "error": "duplicate_adjacent_text",
                    "raw_text": raw_text,
                    "text": text,
                }
            )
            records.append(record)
            continue

        record.update(
            {
                "parse_status": "ok",
                "error": None,
                "start_sec": start_sec,
                "end_sec": end_sec,
                "raw_text": raw_text,
                "text": text,
            }
        )
        records.append(record)
        previous_normalized_text = text

    if not records:
        record = _base_record(row, 0)
        record.update({"parse_status": "error", "error": "no_srt_blocks"})
        records.append(record)
    return records


def _write_jsonl_atomically(output_path: Path, records: Iterable[dict[str, Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(output_path.name + ".tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        # 原子替换让第 03 步只可能读取完整 JSONL，而非生产过程中的中间内容。
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary_path, output_path)


def run(config_path: Path) -> Path:
    """解析 inventory；所有失败均保留为具有 ``error`` 的记录。"""

    _, raw_root, inventory_path, output_path = _load_paths(config_path)
    with inventory_path.open("r", encoding="utf-8", newline="") as handle:
        inventory_rows = list(csv.DictReader(handle))
    records = [
        record
        for row in inventory_rows
        for record in _parse_file(row, raw_root)
    ]
    _write_jsonl_atomically(output_path, records)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="解析 inventory 中的 SRT 字幕块")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "config" / "paths.yaml",
        help="冻结的 paths.yaml 路径",
    )
    arguments = parser.parse_args()
    run(arguments.config)


if __name__ == "__main__":
    main()
