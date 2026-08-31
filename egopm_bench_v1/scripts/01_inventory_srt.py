"""Source 流水线第 01 步：清点只读 EgoLife SRT，输出 `srt_inventory.csv`。

输入为 `paths.yaml` 指向的 Transcript 与 DenseCaption 根目录；输出是后续解析步骤
唯一读取的可追溯文件清单。本脚本不读取或修改字幕内容，也不发布 SUCCESS 标记：
正式 Source 门仅能在第 04 步完成原子分组与 split 后发布。
"""

from __future__ import annotations

import argparse
import csv
import os
import re
from pathlib import Path
from typing import Any

import yaml


INVENTORY_COLUMNS = [
    "modality",
    "participant_source_id",
    "source_day",
    "file_name",
    "relative_path",
    "file_size_bytes",
    "parse_status",
    "session_uid",
    "session_id",
    "has_counterpart",
]


def _load_paths(config_path: Path) -> tuple[dict[str, Any], Path, Path]:
    config_path = config_path.resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError(f"配置不是对象：{config_path}")
    config_dir = config_path.parent

    def resolve(value: str) -> Path:
        candidate = Path(value)
        return candidate if candidate.is_absolute() else (config_dir / candidate).resolve()

    # 所有路径都以冻结配置所在目录为锚点，避免调用工作目录改变可追溯相对路径。
    raw_root = resolve(str(config["raw_root"]))
    output_path = resolve(str(config["artifacts"]["source_inventory"]))
    return config, raw_root, output_path


def _safe_identifier(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    return normalized or "unknown"


def _session_uid(path: Path, day_relative_parts: tuple[str, ...]) -> str:
    """从文件名及其 day 下的子目录构造跨模态一致的会话 UID。"""

    stem = path.stem
    # 一些导出工具把模态名称附在相同会话文件名中；移除它们才能让双模态文件匹配，
    # 又不会把“Transcript”或“DenseCaption”本身误当作不同的现实来源会话。
    stem = re.sub(r"(?i)(?:^|[_\-\s])(transcript|dense[_\-\s]?caption)(?:$|[_\-\s])", "_", stem)
    parts = [*day_relative_parts, stem]
    return _safe_identifier("_".join(parts))


def _metadata_for_path(modality: str, modality_root: Path, path: Path) -> dict[str, str]:
    relative = path.relative_to(modality_root)
    parts = relative.parts
    if len(parts) < 3:
        raise ValueError("SRT 路径必须至少包含 <participant>/DAYx/<file>.srt")

    participant = parts[0]
    day_index = next(
        (index for index, item in enumerate(parts[:-1]) if re.fullmatch(r"DAY[1-7]", item, re.IGNORECASE)),
        None,
    )
    if day_index is None or day_index == 0:
        raise ValueError("SRT 路径中缺少 participant 后的 DAY1–DAY7 目录")

    day = parts[day_index].upper()
    session_uid = _session_uid(path, tuple(parts[day_index + 1 : -1]))
    participant_id = _safe_identifier(participant)
    session_id = f"ses_{participant_id}_{day}_{session_uid}"
    return {
        "participant_source_id": participant,
        "source_day": day,
        "session_uid": session_uid,
        "session_id": session_id,
    }


def _discover_modality(
    modality: str, modality_root: Path, raw_root: Path
) -> list[dict[str, str | int | bool]]:
    if not modality_root.exists():
        # 单模态 Source Atom 合法，缺失一个根目录不能伪造失败文件或阻断另一模态清点。
        return []
    if not modality_root.is_dir():
        raise NotADirectoryError(f"模态根目录不是目录：{modality_root}")

    records: list[dict[str, str | int | bool]] = []
    for path in sorted(
        (candidate for candidate in modality_root.rglob("*") if candidate.is_file() and candidate.suffix.lower() == ".srt"),
        key=lambda candidate: candidate.as_posix().casefold(),
    ):
        try:
            metadata = _metadata_for_path(modality, modality_root, path)
            records.append(
                {
                    "modality": modality,
                    **metadata,
                    "file_name": path.name,
                    "relative_path": path.relative_to(raw_root.parent).as_posix(),
                    "file_size_bytes": path.stat().st_size,
                    "parse_status": "discovered",
                    "has_counterpart": False,
                }
            )
        except (OSError, ValueError) as error:
            try:
                relative_path = path.relative_to(raw_root.parent).as_posix()
            except ValueError:
                relative_path = path.as_posix()
            records.append(
                {
                    "modality": modality,
                    "participant_source_id": "",
                    "source_day": "",
                    "file_name": path.name,
                    "relative_path": relative_path,
                    "file_size_bytes": path.stat().st_size,
                    "parse_status": f"inventory_error:{error}",
                    "session_uid": "",
                    "session_id": "",
                    "has_counterpart": False,
                }
            )
    return records


def _write_csv_atomically(output_path: Path, rows: list[dict[str, str | int | bool]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(output_path.name + ".tmp")
    with temporary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INVENTORY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
        # 先落盘临时文件再替换，防止解析步骤读取到清单半写入状态。
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary_path, output_path)


def run(config_path: Path) -> Path:
    """生成 inventory；该函数不会修改任何原始 SRT。"""

    config, raw_root, output_path = _load_paths(config_path)
    config_dir = config_path.resolve().parent

    def resolve(value: str) -> Path:
        candidate = Path(value)
        return candidate if candidate.is_absolute() else (config_dir / candidate).resolve()

    modality_roots = {
        "transcript": resolve(str(config["transcript_root"])),
        "dense_caption": resolve(str(config["dense_caption_root"])),
    }
    records = [
        record
        for modality, root in modality_roots.items()
        for record in _discover_modality(modality, root, raw_root)
    ]

    key_to_modalities: dict[tuple[str, str, str], set[str]] = {}
    for record in records:
        if record["parse_status"] != "discovered":
            continue
        # counterpart 只由 participant/day/session UID 决定，不按文本或生成质量猜测配对。
        key = (
            str(record["participant_source_id"]),
            str(record["source_day"]),
            str(record["session_uid"]),
        )
        key_to_modalities.setdefault(key, set()).add(str(record["modality"]))

    for record in records:
        if record["parse_status"] == "discovered":
            key = (
                str(record["participant_source_id"]),
                str(record["source_day"]),
                str(record["session_uid"]),
            )
            record["has_counterpart"] = len(key_to_modalities[key]) > 1

    records.sort(
        key=lambda row: (
            str(row["modality"]),
            str(row["participant_source_id"]),
            str(row["source_day"]),
            str(row["relative_path"]),
        )
    )
    _write_csv_atomically(output_path, records)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="清点 EgoLife Transcript 与 Dense Caption SRT 文件")
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
