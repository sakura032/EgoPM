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


def write_valid_realtime_artifacts(qa, config, marker: dict) -> None:
    """写入完全合成的实时无正文状态，证明 T4 不依赖已取消的 Batch 工件。"""

    root = qa.realtime_root(config)
    package_id = "pkg_s00000_p000"
    request_sha = "a" * 64
    package_dir = root / "packages" / package_id
    package_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "run_id": "run_synthetic_v30", "transport": "realtime_chat_completions", "realtime_shard_index": 0,
        "package_id": package_id, "source_atoms_sha256": marker["source_atoms_sha256"],
        "cue_execution_protocol_sha256": marker["cue_execution_protocol_sha256"], "request_sha256": request_sha,
        "attempt": 1, "retry_count": 0, "status": "validated_success",
    }
    state_path = package_dir / "realtime_state.json"
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    ledger = {
        "realtime_shard_index": 0, "package_id": package_id, "request_sha256": request_sha,
        "attempt": 1, "outcome": "validated_success", "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        "retry_eligible": False, "failure_origin": None, "transport": "realtime_chat_completions",
        "source_atoms_sha256": marker["source_atoms_sha256"], "cue_execution_protocol_sha256": marker["cue_execution_protocol_sha256"],
    }
    ledger_path = package_dir / f"{package_id}.ledger.jsonl"
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False) + "\n", encoding="utf-8")
    result_path = package_dir / f"{package_id}.result.jsonl"
    result_path.write_text('{"synthetic":true}\n', encoding="utf-8")
    complete = dict(state)
    complete.update({"result_sha256": qa.sha256_file(result_path), "ledger_sha256": qa.sha256_file(ledger_path), "state_sha256": qa.sha256_file(state_path)})
    complete_path = package_dir / f"{package_id}.complete.json"
    complete_path.write_text(json.dumps(complete, ensure_ascii=False), encoding="utf-8")
    row = {
        "run_id": "run_synthetic_v30", "transport": "realtime_chat_completions", "realtime_shard_index": 0,
        "source_atoms_sha256": marker["source_atoms_sha256"], "cue_execution_protocol_sha256": marker["cue_execution_protocol_sha256"],
        "package_count": 1, "package_ids_sha256": qa.canonical_sha256([package_id]),
        "package_id_to_request_sha256": {package_id: request_sha}, "status": "completed", "completion_sha256": qa.sha256_file(complete_path),
    }
    manifest = qa.realtime_shards_manifest_path(config)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    run_state = {
        "run_id": "run_synthetic_v30", "transport": "realtime_chat_completions", "source_atoms_sha256": marker["source_atoms_sha256"],
        "cue_execution_protocol_sha256": marker["cue_execution_protocol_sha256"], "status": "completed", "authorized_budget_cny": 40.0,
        "estimated_cost_cny": 0.01, "usage_summary": marker["usage_summary"], "wave_index": 1, "wave_task_indexes": [0],
    }
    run_state_path = root / "realtime_run_state.json"
    run_state_path.write_text(json.dumps(run_state, ensure_ascii=False), encoding="utf-8")
    # 进度文件只记录数值、波次和费用；此合成快照验证 T4 会拒绝扩大到其他波次、
    # 超过十个在飞 package 或混入原始模型正文的运行状态。
    progress = {
        "status": "completed", "wave_index": 1, "wave_task_indexes": [0],
        "total_packages": 1, "completed_packages": 1, "validated_success_packages": 1,
        "local_validation_quarantine_packages": 0, "service_transport_exhausted_packages": 0,
        "budget_stopped_packages": 0, "in_flight_packages": 0, "authorized_budget_cny": 40.0,
        "spent_cny": 0.01, "elapsed_seconds": 1.0, "eta_seconds": 0.0,
        "raw_response_saved": False, "updated_at": "2026-08-31T00:00:00+00:00",
    }
    (root / "progress.json").write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    run_ledger = dict(ledger)
    run_ledger["run_id"] = "run_synthetic_v30"
    run_ledger_path = root / "realtime_run_ledger.jsonl"
    run_ledger_path.write_text(json.dumps(run_ledger, ensure_ascii=False) + "\n", encoding="utf-8")
    marker.update({
        "realtime_transport": "realtime_chat_completions", "realtime_shard_count": 1,
        "realtime_shards_manifest_sha256": qa.sha256_file(manifest), "realtime_run_state_sha256": qa.sha256_file(run_state_path),
        "realtime_run_ledger_sha256": qa.sha256_file(run_ledger_path), "realtime_local_raw_response_storage": "forbidden",
    })


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
    write_valid_realtime_artifacts(qa, config, marker)
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
    assert "cue_realtime_lineage_fields" in {issue["issue_type"] for issue in collector.issues}


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
    registry["models"]["cue_extraction"]["execution"]["realtime_api_policy"]["requests_per_minute"] = 299
    registry_path.write_text(yaml.safe_dump(registry, allow_unicode=True, sort_keys=False), encoding="utf-8")
    collector = qa.IssueCollector()
    assert not qa.marker_is_valid(config, "cue", "cue_library", "cue_library", "T2 cue", collector)
    assert any(
        issue["issue_type"] == "cue_execution_lineage_mismatch"
        and issue["failure_id"] == "cue:cue_execution_protocol_sha256"
        for issue in collector.issues
    )


def update_realtime_manifest(qa, config, marker: dict, mutate) -> None:
    """修改临时实时清单并同步哈希，保证测试覆盖内容门而非仅文件摘要。"""

    path = qa.realtime_shards_manifest_path(config)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    mutate(rows)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    marker["realtime_shards_manifest_sha256"] = qa.sha256_file(path)
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


def test_cue_v30_rejects_tampered_package_mapping_and_raw_content(tmp_path: Path) -> None:
    """实时 package 映射必须唯一且无正文，防止取消 Batch 或文本混入实时结果。"""

    qa = load_validator()
    config = qa.load_run_config(copy_config_tree(tmp_path))
    source_marker = write_valid_marker(qa, config, "source", "source_atoms", "source_atoms", {})
    marker = write_valid_cue_v2_marker(qa, config, source_marker["sha256"])

    def duplicate_package(rows: list[dict]) -> None:
        rows[0]["package_id_to_request_sha256"]["pkg_s00000_p000"] = "b" * 64

    update_realtime_manifest(qa, config, marker, duplicate_package)
    collector = qa.IssueCollector()
    assert not qa.marker_is_valid(config, "cue", "cue_library", "cue_library", "T2 cue", collector)
    assert any(issue["issue_type"] == "cue_realtime_package_lineage" for issue in collector.issues)

    marker = write_valid_cue_v2_marker(qa, config, source_marker["sha256"])

    def insert_forbidden_body(rows: list[dict]) -> None:
        rows[0]["response"] = "不得保存的合成正文"

    update_realtime_manifest(qa, config, marker, insert_forbidden_body)
    collector = qa.IssueCollector()
    assert not qa.marker_is_valid(config, "cue", "cue_library", "cue_library", "T2 cue", collector)
    assert any(issue["issue_type"] == "cue_realtime_raw_content" for issue in collector.issues)


def test_cue_v30_rejects_realtime_price_rate_and_output_policy_drift(tmp_path: Path) -> None:
    """实时单价、限流和输出上限同属执行合同，任何漂移都必须阻断旧运行恢复。"""

    qa = load_validator()
    config = qa.load_run_config(copy_config_tree(tmp_path))
    source_marker = write_valid_marker(qa, config, "source", "source_atoms", "source_atoms", {})
    marker = write_valid_cue_v2_marker(qa, config, source_marker["sha256"])
    marker["realtime_transport"] = "batch_file"
    config.marker("cue_library").write_text(json.dumps(marker), encoding="utf-8")
    collector = qa.IssueCollector()
    assert not qa.marker_is_valid(config, "cue", "cue_library", "cue_library", "T2 cue", collector)
    assert any(issue["issue_type"] == "cue_realtime_transport" for issue in collector.issues)

    marker = write_valid_cue_v2_marker(qa, config, source_marker["sha256"])
    registry_path = config.config_dir / "model_registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    execution = registry["models"]["cue_extraction"]["execution"]
    execution["package_policy"]["output_tokens_per_atom"] = 97
    execution["pricing_snapshot"]["input_price_cny_per_million_tokens"] = 0.19
    registry_path.write_text(yaml.safe_dump(registry, allow_unicode=True, sort_keys=False), encoding="utf-8")
    collector = qa.IssueCollector()
    assert not qa.marker_is_valid(config, "cue", "cue_library", "cue_library", "T2 cue", collector)
    assert any(issue["issue_type"] == "cue_execution_lineage_mismatch" for issue in collector.issues)


def test_cue_v30_rejects_non_success_or_requeued_package(tmp_path: Path) -> None:
    """本地隔离或预算停止不得自动重排，最终 SUCCESS 仅接受唯一 validated_success。"""

    qa = load_validator()
    config = qa.load_run_config(copy_config_tree(tmp_path))
    source_marker = write_valid_marker(qa, config, "source", "source_atoms", "source_atoms", {})
    marker = write_valid_cue_v2_marker(qa, config, source_marker["sha256"])
    ledger = qa.realtime_root(config) / "packages" / "pkg_s00000_p000" / "pkg_s00000_p000.ledger.jsonl"
    events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    events[0]["outcome"] = "local_validation_quarantine"
    events[0]["retry_eligible"] = True
    events[0]["failure_origin"] = "transport"
    ledger.write_text(json.dumps(events[0], ensure_ascii=False) + "\n", encoding="utf-8")
    collector = qa.IssueCollector()
    assert not qa.marker_is_valid(config, "cue", "cue_library", "cue_library", "T2 cue", collector)
    assert any(issue["issue_type"] == "cue_realtime_ledger_terminal" for issue in collector.issues)


def test_cue_v30_rejects_progress_outside_frozen_wave_or_inflight_limit(tmp_path: Path) -> None:
    """最终实时 QA 必须拒绝跨波、超十并发和含正文的进度快照。"""

    qa = load_validator()
    config = qa.load_run_config(copy_config_tree(tmp_path))
    source_marker = write_valid_marker(qa, config, "source", "source_atoms", "source_atoms", {})
    write_valid_cue_v2_marker(qa, config, source_marker["sha256"])
    progress_path = qa.realtime_root(config) / "progress.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    progress.update({"wave_index": 2, "wave_task_indexes": [0], "in_flight_packages": 11})
    progress_path.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    collector = qa.IssueCollector()
    assert not qa.marker_is_valid(config, "cue", "cue_library", "cue_library", "T2 cue", collector)
    issue_types = {issue["issue_type"] for issue in collector.issues}
    assert {"cue_realtime_progress_wave", "cue_realtime_progress_inflight"}.issubset(issue_types)

    write_valid_cue_v2_marker(qa, config, source_marker["sha256"])
    progress_path = qa.realtime_root(config) / "progress.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    progress["error"] = "不得保存的合成服务端正文"
    progress_path.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
    collector = qa.IssueCollector()
    assert not qa.marker_is_valid(config, "cue", "cue_library", "cue_library", "T2 cue", collector)
    assert any(issue["issue_type"] == "cue_realtime_progress_raw_content" for issue in collector.issues)


def test_cue_v30_rejects_budget_overrun_and_batch_artifact_mix(tmp_path: Path) -> None:
    """预算熔断必须真实生效，实时 run-state 也不得借 Batch 字段/正文绕过审计。"""

    qa = load_validator()
    config = qa.load_run_config(copy_config_tree(tmp_path))
    source_marker = write_valid_marker(qa, config, "source", "source_atoms", "source_atoms", {})
    marker = write_valid_cue_v2_marker(qa, config, source_marker["sha256"])
    state = qa.realtime_root(config) / "realtime_run_state.json"
    state_data = json.loads(state.read_text(encoding="utf-8"))
    state_data["estimated_cost_cny"] = 99.0
    state.write_text(json.dumps(state_data), encoding="utf-8")
    marker["realtime_run_state_sha256"] = qa.sha256_file(state)
    config.marker("cue_library").write_text(json.dumps(marker), encoding="utf-8")
    collector = qa.IssueCollector()
    assert not qa.marker_is_valid(config, "cue", "cue_library", "cue_library", "T2 cue", collector)
    assert any(issue["issue_type"] == "cue_realtime_budget_fuse" for issue in collector.issues)


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
