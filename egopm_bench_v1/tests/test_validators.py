"""T4 验证器的合成单元测试；不读取或生成正式基准产物。

职责：故意构造违反合同的微型记录，证明第 11、12 步会拒绝篡改、泄露和状态错误。
输入：T0 冻结的 contract fixture，以及测试运行时创建的临时文件。
输出：pytest 的断言结果；临时目录随测试清理，绝不形成正式 SUCCESS 或基准数据。
流水线位置：Wave 1 的 QA 开发阶段，用于在生产产物尚不可读取时验证 T4 逻辑。
"""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "contract"


def load_validator():
    path = ROOT / "scripts" / "11_validate_all.py"
    spec = importlib.util.spec_from_file_location("egopm_validator_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def copy_config_tree(destination: Path) -> Path:
    benchmark = destination / "egopm_bench_v1"
    shutil.copytree(ROOT / "config", benchmark / "config")
    return benchmark / "config" / "benchmark_protocol.yaml"


def test_success_marker_hash_is_a_strict_read_gate(tmp_path: Path) -> None:
    qa = load_validator()
    config_path = copy_config_tree(tmp_path)
    config = qa.load_run_config(config_path)
    artifact = config.artifact("source_atoms")
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"atom_id":"src_test"}\n', encoding="utf-8")
    marker = {
        "artifact_path": "source/source_video_atoms.jsonl",
        "sha256": qa.sha256_file(artifact),
        "row_count": 1,
        "contract_version": "v1.0.0",
        "config_version": "v1.0.0",
        "schema_versions": {"source_video_atom": "v1.0.0"},
        "generated_at": "2026-08-31T00:00:00+00:00",
        "upstream_hashes": {},
    }
    marker_path = config.marker("source_atoms")
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    collector = qa.IssueCollector()
    assert qa.marker_is_valid(config, "source", "source_atoms", "source_atoms", "T1 source", collector)
    cue_artifact = config.artifact("cue_library")
    cue_artifact.parent.mkdir(parents=True)
    cue_artifact.write_text('{"cue_id":"cue_test"}\n', encoding="utf-8")
    cue_marker = dict(marker)
    cue_marker.update(
        {
            "artifact_path": "cues/cue_library.jsonl",
            "sha256": qa.sha256_file(cue_artifact),
            "upstream_hashes": {},  # 故意漏掉已验证的 source SHA256。
        }
    )
    config.marker("cue_library").write_text(json.dumps(cue_marker), encoding="utf-8")
    upstream_collector = qa.IssueCollector()
    assert not qa.marker_is_valid(config, "cue", "cue_library", "cue_library", "T2 cue", upstream_collector)
    assert any(issue["issue_type"] == "success_marker_upstream_hash" for issue in upstream_collector.issues)
    artifact.write_text('{"atom_id":"src_tampered"}\n', encoding="utf-8")
    tampered_collector = qa.IssueCollector()
    assert not qa.marker_is_valid(config, "source", "source_atoms", "source_atoms", "T1 source", tampered_collector)
    assert any(issue["issue_type"] == "success_marker_hash" for issue in tampered_collector.issues)


def test_source_validator_rejects_time_and_cross_split_near_duplicates(tmp_path: Path) -> None:
    qa = load_validator()
    srt = tmp_path / "raw" / "example.srt"
    srt.parent.mkdir(parents=True)
    srt.write_text("1\n00:00:00,000 --> 00:00:20,000\nSynthetic caption\n", encoding="utf-8")
    first = fixture("source_video_atom.valid.json")
    first["source_srt_paths"] = {"transcript": "raw/example.srt", "dense_caption": None}
    first["modality_coverage"] = "transcript_only"
    first["local_start_sec"] = 10.0
    first["local_end_sec"] = 8.0
    second = copy.deepcopy(first)
    second["atom_id"] = "src_SYNTH_DAY1_000002"
    second["split"] = "dev"
    second["local_start_sec"] = 10.0
    second["local_end_sec"] = 18.0
    second["normalized_start_sec"] = 10.0
    second["normalized_end_sec"] = 18.0
    config = SimpleNamespace(
        project_root=tmp_path,
        split_policy={"grouping": {"near_duplicate": {"similarity_threshold": 0.92}}},
    )
    collector = qa.IssueCollector()
    qa.validate_source([first, second], config, collector)
    issue_types = {issue["issue_type"] for issue in collector.issues}
    assert {"source_time_order", "split_source_group", "split_near_duplicate"}.issubset(issue_types)


def test_decision_validator_rejects_answer_labels_in_model_input() -> None:
    qa = load_validator()
    log = fixture("lifelog.valid.json")
    decision = fixture("decision_instance.valid.json")
    decision["model_input"]["visible_text"] = "gold_action: remind; event_role: trigger"
    collector = qa.IssueCollector()
    qa.validate_decisions([decision], {log["lifelog_id"]: log}, collector)
    assert any(issue["issue_type"] == "answer_leakage" for issue in collector.issues)


def test_schema_state_and_duration_validators_reject_independent_failures() -> None:
    qa = load_validator()
    schema_collector = qa.IssueCollector()
    qa.validate_schema([{}], ROOT / "schemas" / "source_video_atom.schema.json", "source", "T1 source", schema_collector)
    assert any(issue["issue_type"] == "schema" for issue in schema_collector.issues)

    config = qa.load_run_config(ROOT / "config" / "benchmark_protocol.yaml")
    atom = fixture("source_video_atom.valid.json")
    frozen_seed = fixture("reminder_seed.valid.json")
    frozen_seed["audit"] = {"status": "accept", "reason": "Synthetic test.", "human_reviewer": "reviewer"}
    log = fixture("lifelog.valid.json")
    log["events"][1]["virtual_time"] = "D01 09:10"
    log["events"][1]["intention_state_before"] = "completed"
    log["events"][1]["intention_state_after"] = "active_unreminded"
    collector = qa.IssueCollector()
    qa.validate_lifelogs([log], {atom["atom_id"]: atom}, {frozen_seed["seed_id"]: frozen_seed}, config, collector)
    issue_types = {issue["issue_type"] for issue in collector.issues}
    assert {"state_transition", "difficulty_event_count", "difficulty_virtual_span"}.issubset(issue_types)


def test_counterfactual_validator_rejects_missing_action_flip() -> None:
    qa = load_validator()
    positive_log = fixture("lifelog.valid.json")
    negative_log = copy.deepcopy(positive_log)
    negative_log["lifelog_id"] = "log_SYNTH_negative_short"
    negative_log["counterfactual_branch"] = "negative"
    positive = fixture("decision_instance.valid.json")
    negative = copy.deepcopy(positive)
    negative["decision_id"] = "dec_SYNTH_000002"
    negative["lifelog_id"] = negative_log["lifelog_id"]
    # 故意保留 remind，验证器必须要求 matched-negative 翻转为 silent。
    collector = qa.IssueCollector()
    qa.validate_counterfactual_pairs(
        [positive, negative],
        {positive_log["lifelog_id"]: positive_log, negative_log["lifelog_id"]: negative_log},
        collector,
    )
    assert any(issue["issue_type"] == "counterfactual_gold_flip" for issue in collector.issues)


def test_missing_success_marker_blocks_without_reading_or_writing_formal_data(tmp_path: Path) -> None:
    qa = load_validator()
    config_path = copy_config_tree(tmp_path)
    collector, data, readiness = qa.run_validation(config_path, write=False)
    assert data == {}
    assert readiness["source"] is False
    assert any(issue["issue_type"] == "success_marker_missing" for issue in collector.issues)
    assert not (tmp_path / "egopm_bench_v1" / "audit" / "validation_errors.jsonl").exists()
