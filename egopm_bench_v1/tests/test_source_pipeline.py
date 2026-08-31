"""T1 Wave 1 单元测试：以临时 synthetic SRT 验证 Source 流水线 01–04。

输入由 pytest 的临时目录构造，输出也只写入该目录；测试覆盖 inventory、解析、
时间对齐、来源 split、Schema 与 SUCCESS 哈希，不会创建或计入任何正式数据。
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
from itertools import combinations
from pathlib import Path
from types import ModuleType

import jsonschema
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _load_script(script_name: str) -> ModuleType:
    module_name = f"test_{script_name.replace('-', '_')}"
    specification = importlib.util.spec_from_file_location(module_name, SCRIPTS / f"{script_name}.py")
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module
    specification.loader.exec_module(module)
    return module


def _write_srt(path: Path, blocks: list[tuple[str, str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n\n".join(
            f"{index}\n{start} --> {end}\n{text}"
            for index, (start, end, text) in enumerate(blocks, start=1)
        )
        + "\n",
        encoding="utf-8",
    )


def _write_test_config(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    source_dir = tmp_path / "source"
    config_dir.mkdir(parents=True)
    paths = {
        "contract_version": "v1.1.0",
        "config_version": "v1.1.0",
        "raw_root": "../raw/EgoLifeCap",
        "transcript_root": "../raw/EgoLifeCap/Transcript",
        "dense_caption_root": "../raw/EgoLifeCap/DenseCaption",
        "source_dir": "../source",
        "schema_dir": str((ROOT / "schemas").resolve()),
        "artifacts": {
            "source_inventory": "../source/srt_inventory.csv",
            "raw_srt_segments": "../source/raw_srt_segments.jsonl",
            "source_atoms_draft": "../source/source_video_atoms_draft.jsonl",
            "source_atoms": "../source/source_video_atoms.jsonl",
            "source_split_map": "../source/source_split_map.jsonl",
            "source_report": "../source/atom_build_report.json",
        },
        "success_markers": {"source_atoms": "../source/SOURCE_ATOMS_SUCCESS.json"},
        "source_build": {
            "alignment": {
                "transcript_dense_caption_tolerance_seconds": 2.0,
                "primary_window_modality": "dense_caption",
                "retain_unmatched_single_modality_atoms": True,
            },
            "atom_merging": {
                "enabled": False,
                "report_longer_than_seconds": 30,
            },
            "staging": {
                "draft_atom_stage": "draft",
                "draft_split": None,
                "final_atom_stage": "final",
                "final_split_labels": ["train", "dev", "test"],
            },
        },
    }
    policy = {
        "contract_version": "v1.1.0",
        "config_version": "v1.1.0",
        "policy_version": "v1.1.0",
        "random_seed": 20260829,
        "ratios": {"train": 0.7, "dev": 0.15, "test": 0.15},
        "split_labels": ["train", "dev", "test"],
        "grouping": {
            "hard_group_keys": ["session_id", "world_event_id"],
            "near_duplicate": {
                "enabled": True,
                "normalized_text": "unicode_nfkc_lowercase_collapse_whitespace",
                "algorithm": "char_3gram_jaccard",
                "similarity_threshold": 0.92,
                "comparison_scope": "all_sessions_same_participant_source_day",
                "cross_session_time_order": "prohibited",
                "max_gap_seconds": None,
            },
        },
    }
    config_path = config_dir / "paths.yaml"
    config_path.write_text(yaml.safe_dump(paths, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (config_dir / "split_policy.yaml").write_text(
        yaml.safe_dump(policy, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    source_dir.mkdir()
    return config_path


def _write_synthetic_srt_tree(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw" / "EgoLifeCap"
    _write_srt(
        raw_root / "Transcript" / "P01" / "DAY1" / "session_alpha_transcript.srt",
        [
            ("00:00:01,000", "00:00:03,000", "Hello\nthere"),
            ("00:00:05,000", "00:00:08,000", "Need milk"),
            ("00:00:08,100", "00:00:09,000", "Need milk"),
        ],
    )
    _write_srt(
        raw_root / "DenseCaption" / "P01" / "DAY1" / "session_alpha_dense_caption.srt",
        [
            ("00:00:00,500", "00:00:02,000", "A person greets another person."),
            ("00:00:05,500", "00:00:07,000", "A person checks a shopping list."),
        ],
    )
    _write_srt(
        raw_root / "Transcript" / "P01" / "DAY1" / "only_transcript.srt",
        [("00:00:10,000", "00:00:12,000", "I will wash the cup.")],
    )
    _write_srt(
        raw_root / "DenseCaption" / "P01" / "DAY1" / "only_dense_caption.srt",
        [("00:00:16,000", "00:00:18,000", "A person opens a cupboard.")],
    )
    broken = raw_root / "Transcript" / "P02" / "DAY2" / "broken_transcript.srt"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("1\nnot-a-timecode\nBroken subtitle\n", encoding="utf-8")
    for session_name in ("session_one", "session_two"):
        _write_srt(
            raw_root / "Transcript" / "P99" / "DAY2" / f"{session_name}.srt",
            [("00:00:00,000", "00:00:02,000", "The keys are on the table.")],
        )


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_source_pipeline_fixture_only_end_to_end(tmp_path: Path) -> None:
    """库存、解析、对齐、split 与 SUCCESS 均在 pytest 临时目录验证。"""

    _write_synthetic_srt_tree(tmp_path)
    config_path = _write_test_config(tmp_path)
    inventory = _load_script("01_inventory_srt")
    parser = _load_script("02_parse_srt")
    aligner = _load_script("03_align_modal_text")
    splitter = _load_script("04_make_source_splits")

    inventory_path = inventory.run(config_path)
    with inventory_path.open("r", encoding="utf-8", newline="") as handle:
        inventory_rows = list(csv.DictReader(handle))
    assert len(inventory_rows) == 7
    alpha_rows = [row for row in inventory_rows if "session_alpha" in row["file_name"]]
    assert len(alpha_rows) == 2
    assert {row["has_counterpart"] for row in alpha_rows} == {"True"}
    assert all(not Path(row["relative_path"]).is_absolute() for row in inventory_rows)

    segments_path = parser.run(config_path)
    segments = _read_jsonl(segments_path)
    assert any(record["parse_status"] == "error" for record in segments)
    assert any(record["parse_status"] == "discarded_duplicate_adjacent" for record in segments)
    hello = next(record for record in segments if record.get("text") == "Hello there")
    assert hello["raw_text"] == "Hello\nthere"
    assert not segments_path.with_name(segments_path.name + ".tmp").exists()

    draft_atoms_path, report_path = aligner.run(config_path)
    draft_atoms = _read_jsonl(draft_atoms_path)
    assert draft_atoms_path.name == "source_video_atoms_draft.jsonl"
    assert all(atom["atom_stage"] == "draft" and atom["split"] is None for atom in draft_atoms)
    draft_schema = json.loads((ROOT / "schemas" / "source_video_atom_draft.schema.json").read_text(encoding="utf-8"))
    draft_validator = jsonschema.Draft202012Validator(draft_schema)
    for atom in draft_atoms:
        draft_validator.validate(atom)
    assert {atom["modality_coverage"] for atom in draft_atoms} == {
        "both",
        "transcript_only",
        "dense_caption_only",
    }
    both_atom = next(atom for atom in draft_atoms if atom["modality_coverage"] == "both")
    assert "Dense caption:" in both_atom["visible_text"]
    assert "Transcript:" in both_atom["visible_text"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["alignment"]["tolerance_seconds"] == 2.0
    assert report["anomalies"]["unparsed_files"]

    finalized_atoms_path, split_map_path, success_path = splitter.run(config_path)
    finalized_atoms = _read_jsonl(finalized_atoms_path)
    assert finalized_atoms_path.name == "source_video_atoms.jsonl"
    assert finalized_atoms_path != draft_atoms_path
    assert all(atom["atom_stage"] == "final" for atom in finalized_atoms)
    split_map = _read_jsonl(split_map_path)
    assert len(finalized_atoms) == len(split_map)
    schema = json.loads((ROOT / "schemas" / "source_video_atom.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for atom in finalized_atoms:
        validator.validate(atom)

    duplicate_atoms = [
        atom
        for atom in finalized_atoms
        if atom["participant_source_id"] == "P99" and atom["source_day"] == "DAY2"
    ]
    assert len(duplicate_atoms) == 2
    assert len({atom["source_group_id"] for atom in duplicate_atoms}) == 1
    assert len({atom["split"] for atom in duplicate_atoms}) == 1
    final_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert final_report["split_assignment"]["near_duplicate_component_links"] >= 1

    marker = json.loads(success_path.read_text(encoding="utf-8"))
    assert marker["row_count"] == len(finalized_atoms)
    expected_hash = hashlib.sha256(finalized_atoms_path.read_bytes()).hexdigest()
    assert marker["sha256"] == expected_hash
    assert marker["artifact_hashes"]["source_split_map"] == hashlib.sha256(split_map_path.read_bytes()).hexdigest()
    assert not success_path.with_name(success_path.name + ".tmp").exists()


def test_alignment_rejects_negative_frozen_tolerance(tmp_path: Path) -> None:
    """冻结配置中的负容差必须在写出草稿前被拒绝。"""

    _write_synthetic_srt_tree(tmp_path)
    config_path = _write_test_config(tmp_path)
    _load_script("01_inventory_srt").run(config_path)
    _load_script("02_parse_srt").run(config_path)
    aligner = _load_script("03_align_modal_text")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["source_build"]["alignment"]["transcript_dense_caption_tolerance_seconds"] = -0.01
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="必须为非负数"):
        aligner.run(config_path)


def test_indexed_near_duplicate_pairs_equal_naive_reference() -> None:
    """精确索引必须与同人同日跨 session 的朴素 Jaccard 全对参考完全等价。"""

    splitter = _load_script("04_make_source_splits")
    atoms = [
        {
            "atom_id": "a_same_session",
            "participant_source_id": "P01",
            "source_day": "DAY1",
            "session_id": "session_a",
            "visible_text": "the person opens the kitchen cabinet and puts the blue cup on the table",
        },
        {
            "atom_id": "b_exact_cross_session",
            "participant_source_id": "P01",
            "source_day": "DAY1",
            "session_id": "session_b",
            "visible_text": "the person opens the kitchen cabinet and puts the blue cup on the table",
        },
        {
            "atom_id": "c_near_cross_session",
            "participant_source_id": "P01",
            "source_day": "DAY1",
            "session_id": "session_c",
            "visible_text": "the person opens the kitchen cabinet and puts the blue cup on a table",
        },
        {
            "atom_id": "d_different_cross_session",
            "participant_source_id": "P01",
            "source_day": "DAY1",
            "session_id": "session_d",
            "visible_text": "the person leaves the building and walks toward the bus stop",
        },
        {
            "atom_id": "e_other_participant",
            "participant_source_id": "P02",
            "source_day": "DAY1",
            "session_id": "session_e",
            "visible_text": "the person opens the kitchen cabinet and puts the blue cup on the table",
        },
        {
            "atom_id": "f_other_day",
            "participant_source_id": "P01",
            "source_day": "DAY2",
            "session_id": "session_f",
            "visible_text": "the person opens the kitchen cabinet and puts the blue cup on the table",
        },
        {
            "atom_id": "g_empty_text",
            "participant_source_id": "P01",
            "source_day": "DAY1",
            "session_id": "session_g",
            "visible_text": "",
        },
    ]
    threshold = 0.92
    expected: set[tuple[str, str]] = set()
    for left_session, right_session in splitter._same_person_day_cross_session_pairs(atoms):
        for left_atom, right_atom in ((left, right) for left in left_session for right in right_session):
            left_grams = splitter._char_3grams(left_atom["visible_text"])
            right_grams = splitter._char_3grams(right_atom["visible_text"])
            if not left_grams or not right_grams:
                continue
            if min(len(left_grams), len(right_grams)) / max(len(left_grams), len(right_grams)) < threshold:
                continue
            if splitter._jaccard(left_grams, right_grams) >= threshold:
                expected.add(tuple(sorted((left_atom["atom_id"], right_atom["atom_id"]))))

    observed = {tuple(sorted(pair)) for pair in splitter._indexed_near_duplicate_pairs(atoms, threshold)}
    assert observed == expected
