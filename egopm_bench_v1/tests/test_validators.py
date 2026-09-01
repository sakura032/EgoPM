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

import yaml


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


def write_valid_marker(qa, config, stage: str, artifact_key: str, marker_key: str, upstream_hashes: dict[str, str]) -> dict:
    """按阶段冻结表构造测试用 SUCCESS，避免测试把全局版本当作 Schema 版本。"""

    artifact = config.artifact(artifact_key)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text('{"synthetic":true}\n', encoding="utf-8")
    versions = qa.STAGE_ARTIFACT_VERSIONS[stage]
    marker = {
        "artifact_path": config.canonical_artifact_name(artifact),
        "sha256": qa.sha256_file(artifact),
        "row_count": 1,
        "contract_version": versions["contract_version"],
        "config_version": versions["config_version"],
        "schema_versions": dict(versions["schema_versions"]),
        "generated_at": "2026-08-31T00:00:00+00:00",
        "upstream_hashes": upstream_hashes,
    }
    marker_path = config.marker(marker_key)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    return marker


def write_cue_v2_contract_artifacts(config: object) -> None:
    """在临时 benchmark 根建立 v2.2 紧凑工件替身，不依赖生产提示词。"""

    benchmark_root = config.benchmark_root
    prompt = benchmark_root / "prompts" / "cue_extractor_v3_compact.md"
    schema = benchmark_root / "schemas" / "cue_inference_batch_compact_v1.schema.json"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    schema.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("合成 v2.2 紧凑提示词。\n", encoding="utf-8")
    schema.write_text('{"$id":"synthetic-v2.2","type":"object"}\n', encoding="utf-8")


def write_valid_batch_manifest(qa, config, marker: dict) -> None:
    """写入无正文 Batch task 清单，模拟已完成任务的最小可审计血缘。"""

    custom_id = "v22_s00000_p000_1234abcd"
    row = {
        "run_id": "run_synthetic_v22",
        "batch_task_index": 0,
        "source_atoms_sha256": marker["source_atoms_sha256"],
        "cue_execution_protocol_sha256": marker["cue_execution_protocol_sha256"],
        "batch_input_sha256": "a" * 64,
        "request_count": 1,
        "custom_ids_sha256": qa.canonical_sha256([custom_id]),
        "logical_shard_start": 0,
        "logical_shard_end": 0,
        "remote_file_id": "file-synthetic-input",
        "status": "completed",
        "custom_id_to_package_id": {custom_id: "pkg_s00000_p000"},
    }
    path = qa.batch_tasks_manifest_path(config, marker)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    ledger = path.parent / "packages" / "pkg_s00000_p000" / "pkg_s00000_p000.ledger.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        json.dumps(
            {
                "package_id": "pkg_s00000_p000",
                "batch_task_index": 0,
                "batch_custom_id": custom_id,
                "batch_input_sha256": "a" * 64,
                "remote_file_id": "file-synthetic-input",
                "remote_cleanup_status": "pending_t4_cue_qa",
                "outcome": "validated_success",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    marker.update(
        {
            "batch_transport": "batch_file",
            "batch_task_count": 1,
            "batch_tasks_manifest_sha256": qa.sha256_file(path),
            "batch_input_total_request_count": 1,
            "batch_local_raw_response_storage": "forbidden",
            "remote_cleanup_required": True,
            "remote_cleanup_status": "pending_t4_cue_qa",
        }
    )


def write_valid_cue_v2_marker(qa, config, source_hash: str) -> dict:
    """构造通过最终 Cue Schema 与 v2.2 Batch 血缘门的临时 SUCCESS 标记。"""

    write_cue_v2_contract_artifacts(config)
    marker = write_valid_marker(
        qa,
        config,
        "cue",
        "cue_library",
        "cue_library",
        {"source_atoms": source_hash},
    )
    contract_collector = qa.IssueCollector()
    contract = qa.cue_v2_execution_contract(config, contract_collector, "T2 cue")
    assert contract is not None
    marker.update(contract)
    marker["source_atoms_sha256"] = source_hash
    marker["usage_summary"] = {
        "package_count": 1,
        "attempt_count": 1,
        "successful_attempt_count": 1,
        "failed_attempt_count": 0,
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "total_tokens": 18,
        "missing_usage_count": 0,
        "retry_count": 0,
        "rate_limit_wait_seconds": 0.0,
    }
    write_valid_batch_manifest(qa, config, marker)
    config.marker("cue_library").write_text(json.dumps(marker), encoding="utf-8")
    return marker


def test_success_marker_hash_is_a_strict_read_gate(tmp_path: Path) -> None:
    qa = load_validator()
    config_path = copy_config_tree(tmp_path)
    config = qa.load_run_config(config_path)
    marker = write_valid_marker(qa, config, "source", "source_atoms", "source_atoms", {})
    artifact = config.artifact("source_atoms")
    collector = qa.IssueCollector()
    assert qa.marker_is_valid(config, "source", "source_atoms", "source_atoms", "T1 source", collector)
    cue_marker = write_valid_marker(qa, config, "cue", "cue_library", "cue_library", {})
    upstream_collector = qa.IssueCollector()
    assert not qa.marker_is_valid(config, "cue", "cue_library", "cue_library", "T2 cue", upstream_collector)
    assert any(issue["issue_type"] == "success_marker_upstream_hash" for issue in upstream_collector.issues)
    artifact.write_text('{"atom_id":"src_tampered"}\n', encoding="utf-8")
    tampered_collector = qa.IssueCollector()
    assert not qa.marker_is_valid(config, "source", "source_atoms", "source_atoms", "T1 source", tampered_collector)
    assert any(issue["issue_type"] == "success_marker_hash" for issue in tampered_collector.issues)


def test_stage_version_map_accepts_frozen_source_and_cue_schema_versions(tmp_path: Path) -> None:
    """Source v1.1 与 Cue v1.0 应各自按冻结版本通过，不能由全局版本混淆。"""

    qa = load_validator()
    config = qa.load_run_config(copy_config_tree(tmp_path))
    source_marker = write_valid_marker(qa, config, "source", "source_atoms", "source_atoms", {})
    source_collector = qa.IssueCollector()
    assert qa.marker_is_valid(config, "source", "source_atoms", "source_atoms", "T1 source", source_collector)

    write_valid_cue_v2_marker(qa, config, source_marker["sha256"])
    cue_collector = qa.IssueCollector()
    assert qa.marker_is_valid(config, "cue", "cue_library", "cue_library", "T2 cue", cue_collector)


def test_stage_version_map_rejects_wrong_cue_schema_version(tmp_path: Path) -> None:
    """Cue 标记若把其 v1.0 Schema 声明成 v1.1，必须在读取 JSONL 前被阻断。"""

    qa = load_validator()
    config = qa.load_run_config(copy_config_tree(tmp_path))
    source_marker = write_valid_marker(qa, config, "source", "source_atoms", "source_atoms", {})
    cue_marker = write_valid_cue_v2_marker(qa, config, source_marker["sha256"])
    cue_marker["schema_versions"] = {"cue_candidate": "v1.1.0"}
    config.marker("cue_library").write_text(json.dumps(cue_marker), encoding="utf-8")
    collector = qa.IssueCollector()
    assert not qa.marker_is_valid(config, "cue", "cue_library", "cue_library", "T2 cue", collector)
    assert any(issue["issue_type"] == "success_marker_schema_versions" for issue in collector.issues)


def test_cue_v2_success_requires_frozen_execution_lineage(tmp_path: Path) -> None:
    """最终 Cue 保持 Schema v1.0.0，但必须完整声明并匹配 v2 执行协议。"""

    qa = load_validator()
    config = qa.load_run_config(copy_config_tree(tmp_path))
    source_marker = write_valid_marker(qa, config, "source", "source_atoms", "source_atoms", {})
    write_valid_cue_v2_marker(qa, config, source_marker["sha256"])
    collector = qa.IssueCollector()
    assert qa.marker_is_valid(config, "cue", "cue_library", "cue_library", "T2 cue", collector)


def test_cue_v2_success_rejects_missing_or_tampered_execution_lineage(tmp_path: Path) -> None:
    """协议哈希、Source 哈希或用量汇总缺失/不符时，T4 必须在读 Cue 前阻断。"""

    qa = load_validator()
    config = qa.load_run_config(copy_config_tree(tmp_path))
    source_marker = write_valid_marker(qa, config, "source", "source_atoms", "source_atoms", {})
    marker = write_valid_cue_v2_marker(qa, config, source_marker["sha256"])
    marker.pop("cue_execution_protocol_sha256")
    marker["source_atoms_sha256"] = "wrong-source-hash"
    marker["usage_summary"]["total_tokens"] = 999
    config.marker("cue_library").write_text(json.dumps(marker), encoding="utf-8")
    collector = qa.IssueCollector()
    assert not qa.marker_is_valid(config, "cue", "cue_library", "cue_library", "T2 cue", collector)
    assert "cue_execution_lineage_fields" in {issue["issue_type"] for issue in collector.issues}


def test_cue_v2_success_rejects_wrong_hash_version_and_usage_totals(tmp_path: Path) -> None:
    """字段齐全仍不足够：提示词哈希、推理版本、协议哈希和用量算术都必须可信。"""

    qa = load_validator()
    config = qa.load_run_config(copy_config_tree(tmp_path))
    source_marker = write_valid_marker(qa, config, "source", "source_atoms", "source_atoms", {})
    marker = write_valid_cue_v2_marker(qa, config, source_marker["sha256"])
    marker["cue_prompt_sha256"] = "wrong-prompt-hash"
    marker["cue_inference_schema_version"] = "v9.9.9"
    marker["cue_execution_protocol_sha256"] = "wrong-protocol-hash"
    marker["usage_summary"]["total_tokens"] = 999
    config.marker("cue_library").write_text(json.dumps(marker), encoding="utf-8")
    collector = qa.IssueCollector()
    assert not qa.marker_is_valid(config, "cue", "cue_library", "cue_library", "T2 cue", collector)
    issue_types = {issue["issue_type"] for issue in collector.issues}
    assert {"cue_execution_lineage_mismatch", "cue_usage_summary_tokens"}.issubset(issue_types)


def test_cue_v2_success_rejects_frozen_execution_contract_drift(tmp_path: Path) -> None:
    """限流等 execution 语义变化即使不改最终 Cue Schema，也必须令旧协议哈希失效。"""

    qa = load_validator()
    config = qa.load_run_config(copy_config_tree(tmp_path))
    source_marker = write_valid_marker(qa, config, "source", "source_atoms", "source_atoms", {})
    write_valid_cue_v2_marker(qa, config, source_marker["sha256"])
    registry_path = config.config_dir / "model_registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["models"]["cue_extraction"]["execution"]["batch_file_policy"]["max_requests_per_file"] = 49999
    registry_path.write_text(yaml.safe_dump(registry, allow_unicode=True, sort_keys=False), encoding="utf-8")
    collector = qa.IssueCollector()
    assert not qa.marker_is_valid(config, "cue", "cue_library", "cue_library", "T2 cue", collector)
    assert any(
        issue["issue_type"] == "cue_execution_lineage_mismatch"
        and issue["failure_id"] == "cue:cue_execution_protocol_sha256"
        for issue in collector.issues
    )


def update_batch_manifest(qa, config, marker: dict, mutate) -> None:
    """修改临时无正文 task 清单并同步其哈希，以测试内容门而非只测试文件哈希。"""

    path = qa.batch_tasks_manifest_path(config, marker)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    mutate(rows)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    marker["batch_tasks_manifest_sha256"] = qa.sha256_file(path)
    config.marker("cue_library").write_text(json.dumps(marker), encoding="utf-8")


def test_compact_short_codes_expand_to_final_cue_schema_and_reject_unknown_code(tmp_path: Path) -> None:
    """短码仅是推理层优化；独立展开必须仍合成最终 Cue，并拒绝任何未知码。"""

    qa = load_validator()
    config = qa.load_run_config(copy_config_tree(tmp_path))
    write_cue_v2_contract_artifacts(config)
    contract = qa.cue_v2_execution_contract(config, qa.IssueCollector(), "T2 cue")
    assert contract is not None
    atom = {
        "atom_id": "src_SYNTH_DAY1_000001",
        "split": "train",
        "visible_text": "A person starts preparing food in a kitchen.",
    }
    compact = {"n": 0, "t": "A", "p": [["A", "^", "preparing food"]], "x": "preparing food", "c": 80, "v": "A"}
    expanded = qa.expand_compact_cue_for_qa(compact, atom, contract, "run_synthetic_v22", config)
    collector = qa.IssueCollector()
    qa.validate_schema([expanded], ROOT / "schemas" / "cue_candidate.schema.json", "cue", "T2 cue", collector)
    assert not collector.blockers
    unknown = dict(compact)
    unknown["t"] = "?"
    try:
        qa.expand_compact_cue_for_qa(unknown, atom, contract, "run_synthetic_v22", config)
    except ValueError as error:
        assert "未知" in str(error)
    else:
        raise AssertionError("未知短码不得被静默展开")


def test_cue_v22_rejects_tampered_custom_id_and_raw_content_metadata(tmp_path: Path) -> None:
    """task 映射必须双向唯一且不含正文，防止 Batch 结果错配或原文越过保留边界。"""

    qa = load_validator()
    config = qa.load_run_config(copy_config_tree(tmp_path))
    source_marker = write_valid_marker(qa, config, "source", "source_atoms", "source_atoms", {})
    marker = write_valid_cue_v2_marker(qa, config, source_marker["sha256"])

    def duplicate_custom_id(rows: list[dict]) -> None:
        existing_package = next(iter(rows[0]["custom_id_to_package_id"].values()))
        rows[0]["custom_id_to_package_id"]["v22_s00000_p001_1234abcd"] = existing_package
        rows[0]["request_count"] = 2
        rows[0]["custom_ids_sha256"] = qa.canonical_sha256(list(rows[0]["custom_id_to_package_id"]))
        marker["batch_input_total_request_count"] = 2
        marker["usage_summary"]["package_count"] = 2

    update_batch_manifest(qa, config, marker, duplicate_custom_id)
    collector = qa.IssueCollector()
    assert not qa.marker_is_valid(config, "cue", "cue_library", "cue_library", "T2 cue", collector)
    assert any(issue["issue_type"] == "cue_batch_custom_id_bijection" for issue in collector.issues)

    marker = write_valid_cue_v2_marker(qa, config, source_marker["sha256"])

    def insert_forbidden_body(rows: list[dict]) -> None:
        rows[0]["response"] = "不得保存的合成正文"

    update_batch_manifest(qa, config, marker, insert_forbidden_body)
    collector = qa.IssueCollector()
    assert not qa.marker_is_valid(config, "cue", "cue_library", "cue_library", "T2 cue", collector)
    assert any(issue["issue_type"] == "cue_batch_raw_content" for issue in collector.issues)


def test_cue_v22_rejects_cleanup_or_batch_price_and_output_policy_drift(tmp_path: Path) -> None:
    """远端清理、Batch 单价和 96 token 上限同属执行合同，任何漂移都必须阻断。"""

    qa = load_validator()
    config = qa.load_run_config(copy_config_tree(tmp_path))
    source_marker = write_valid_marker(qa, config, "source", "source_atoms", "source_atoms", {})
    marker = write_valid_cue_v2_marker(qa, config, source_marker["sha256"])
    marker["remote_cleanup_status"] = "not_required"
    config.marker("cue_library").write_text(json.dumps(marker), encoding="utf-8")
    collector = qa.IssueCollector()
    assert not qa.marker_is_valid(config, "cue", "cue_library", "cue_library", "T2 cue", collector)
    assert any(issue["issue_type"] == "cue_batch_remote_cleanup" for issue in collector.issues)

    marker = write_valid_cue_v2_marker(qa, config, source_marker["sha256"])
    registry_path = config.config_dir / "model_registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    execution = registry["models"]["cue_extraction"]["execution"]
    execution["package_policy"]["output_tokens_per_atom"] = 97
    execution["pricing_snapshot"]["input_price_cny_per_million_tokens"] = 0.2
    registry_path.write_text(yaml.safe_dump(registry, allow_unicode=True, sort_keys=False), encoding="utf-8")
    collector = qa.IssueCollector()
    assert not qa.marker_is_valid(config, "cue", "cue_library", "cue_library", "T2 cue", collector)
    assert any(issue["issue_type"] == "cue_execution_lineage_mismatch" for issue in collector.issues)


def test_cue_v22_rejects_quarantine_followed_by_requeue(tmp_path: Path) -> None:
    """服务端成功但本地验证失败已产生费用；同 package 隔离后自动重排队必须阻断。"""

    qa = load_validator()
    config = qa.load_run_config(copy_config_tree(tmp_path))
    source_marker = write_valid_marker(qa, config, "source", "source_atoms", "source_atoms", {})
    marker = write_valid_cue_v2_marker(qa, config, source_marker["sha256"])
    ledger = qa.batch_tasks_manifest_path(config, marker).parent / "packages" / "pkg_s00000_p000" / "pkg_s00000_p000.ledger.jsonl"
    events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    events[0]["outcome"] = "local_validation_quarantine"
    retried = dict(events[0])
    retried["outcome"] = "validated_success"
    ledger.write_text("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in [events[0], retried]), encoding="utf-8")
    collector = qa.IssueCollector()
    assert not qa.marker_is_valid(config, "cue", "cue_library", "cue_library", "T2 cue", collector)
    issue_types = {issue["issue_type"] for issue in collector.issues}
    assert {"cue_batch_quarantine_requeued", "cue_batch_ledger_terminal_duplicate"}.issubset(issue_types)


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
    # 使用不相邻的 session 编号，防止 QA 错把“相邻 session”当成 v1.1.0 的比较范围。
    first["session_id"] = "session_1"
    first["source_group_id"] = "group_session_1"
    second["session_id"] = "session_3"
    second["source_group_id"] = "group_session_3"
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
    assert {"source_time_order", "split_near_duplicate"}.issubset(issue_types)


def test_source_time_boundary_uses_dense_caption_primary_window(tmp_path: Path) -> None:
    """Dense 主窗口可合法超过较短 Transcript，Transcript-only 仍必须在自身 SRT 内。"""

    qa = load_validator()
    transcript = tmp_path / "raw" / "transcript.srt"
    dense = tmp_path / "raw" / "dense.srt"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("1\n00:00:00,000 --> 00:00:10,000\nTranscript\n", encoding="utf-8")
    dense.write_text("1\n00:00:00,000 --> 00:00:20,000\nDense caption\n", encoding="utf-8")
    atom = fixture("source_video_atom.valid.json")
    atom.update(
        {
            "source_srt_paths": {"transcript": "raw/transcript.srt", "dense_caption": "raw/dense.srt"},
            "transcript": "short transcript evidence",
            "dense_caption": "dense primary window evidence",
            "modality_coverage": "both",
            "local_start_sec": 12.0,
            "local_end_sec": 18.0,
        }
    )
    config = SimpleNamespace(
        project_root=tmp_path,
        split_policy={"grouping": {"near_duplicate": {"similarity_threshold": 0.92}}},
    )
    collector = qa.IssueCollector()
    qa.validate_source([atom], config, collector)
    assert not any(issue["issue_type"] == "source_time_out_of_srt" for issue in collector.issues)

    transcript_only = copy.deepcopy(atom)
    transcript_only.update(
        {
            "atom_id": "src_SYNTH_DAY1_000099",
            "source_srt_paths": {"transcript": "raw/transcript.srt", "dense_caption": None},
            "transcript": "transcript primary window evidence",
            "dense_caption": None,
            "modality_coverage": "transcript_only",
            "local_start_sec": 8.0,
            "local_end_sec": 12.0,
        }
    )
    transcript_collector = qa.IssueCollector()
    qa.validate_source([transcript_only], config, transcript_collector)
    assert any(issue["issue_type"] == "source_time_out_of_srt" for issue in transcript_collector.issues)


def test_source_cross_session_duplicate_index_equals_naive_reference() -> None:
    """精确索引必须完整覆盖同一人同日的全部不同 session，而非只覆盖相邻编号。"""

    qa = load_validator()
    records = [
        {"atom_id": "src_P01_DAY1_000001", "participant_source_id": "P01", "source_day": "DAY1", "session_id": "session_1", "split": "train", "visible_text": "the person puts the blue cup on the kitchen table"},
        {"atom_id": "src_P01_DAY1_000002", "participant_source_id": "P01", "source_day": "DAY1", "session_id": "session_3", "split": "dev", "visible_text": "the person puts the blue cup on the kitchen table"},
        {"atom_id": "src_P01_DAY1_000003", "participant_source_id": "P01", "source_day": "DAY1", "session_id": "session_9", "split": "dev", "visible_text": "the person places a blue cup onto the kitchen table"},
        {"atom_id": "src_P01_DAY1_000004", "participant_source_id": "P01", "source_day": "DAY1", "session_id": "session_9", "split": "train", "visible_text": "the person puts the blue cup on the kitchen table"},
        {"atom_id": "src_P02_DAY1_000001", "participant_source_id": "P02", "source_day": "DAY1", "session_id": "session_1", "split": "test", "visible_text": "the person puts the blue cup on the kitchen table"},
        {"atom_id": "src_P01_DAY2_000001", "participant_source_id": "P01", "source_day": "DAY2", "session_id": "session_1", "split": "test", "visible_text": "the person puts the blue cup on the kitchen table"},
    ]
    threshold = 0.92
    grams = {record["atom_id"]: qa.char_3grams(record["visible_text"]) for record in records}
    expected = {
        tuple(sorted((left["atom_id"], right["atom_id"])))
        for index, left in enumerate(records)
        for right in records[index + 1 :]
        if left["participant_source_id"] == right["participant_source_id"]
        and left["source_day"] == right["source_day"]
        and left["session_id"] != right["session_id"]
        and qa.jaccard(grams[left["atom_id"]], grams[right["atom_id"]]) >= threshold
    }
    observed = {
        tuple(sorted((left["atom_id"], right["atom_id"])))
        for left, right in qa.source_cross_session_near_duplicate_pairs(records, grams, threshold)
    }
    assert observed == expected
    expected_cross_split = {
        pair
        for pair in expected
        if next(record for record in records if record["atom_id"] == pair[0])["split"]
        != next(record for record in records if record["atom_id"] == pair[1])["split"]
    }
    observed_cross_split = {
        tuple(sorted((left["atom_id"], right["atom_id"])))
        for left, right in qa.source_cross_session_near_duplicate_pairs(records, grams, threshold, cross_split_only=True)
    }
    assert observed_cross_split == expected_cross_split


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
