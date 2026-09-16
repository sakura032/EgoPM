"""T0 合同回归测试：验证冻结配置、Schema 与手写 fixture 的可复现边界。

输入为 T0 管理的配置、Schema 与 synthetic fixture；输出为 pytest 断言结果。
本文件位于合同冻结阶段，确保 Source 正式建库只能使用已批准的 v1.1 语义。
"""

import json
from pathlib import Path

import jsonschema
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
CONFIG_DIR = ROOT / "config"
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "contract"

# 本文件验证旧冻结合同与多层工件，不再代表当前 Cue v2 开发路径。
pytestmark = pytest.mark.legacy_v36


@pytest.mark.legacy_v36
def test_all_contract_schemas_compile() -> None:
    for schema_path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        jsonschema.Draft202012Validator.check_schema(
            json.loads(schema_path.read_text(encoding="utf-8"))
        )


@pytest.mark.legacy_v36
def test_configs_share_frozen_contract_version() -> None:
    for config_path in sorted(CONFIG_DIR.glob("*.yaml")):
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert config["contract_version"] == "v1.1.0"
        assert config["config_version"] == "v1.1.0"


@pytest.mark.legacy_v36
def test_handwritten_fixtures_validate_against_contracts() -> None:
    fixture_to_schema = {
        "source_video_atom.valid.json": "source_video_atom.schema.json",
        "source_video_atom_draft.valid.json": "source_video_atom_draft.schema.json",
        "cue_candidate.valid.json": "cue_candidate.schema.json",
        "reminder_seed.valid.json": "reminder_seed.schema.json",
        "lifelog.valid.json": "lifelog.schema.json",
        "decision_instance.valid.json": "decision_instance.schema.json",
    }
    for fixture_name, schema_name in fixture_to_schema.items():
        instance = json.loads((FIXTURE_DIR / fixture_name).read_text(encoding="utf-8"))
        schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(instance)


@pytest.mark.legacy_v36
def test_source_build_contract_freezes_alignment_and_staging() -> None:
    """v1.1 必须禁止运行时猜测对齐、合并和草稿 split 语义。"""

    paths = yaml.safe_load((CONFIG_DIR / "paths.yaml").read_text(encoding="utf-8"))
    source_build = paths["source_build"]
    assert paths["artifacts"]["source_atoms_draft"] == "../source/source_video_atoms_draft.jsonl"
    assert paths["artifacts"]["source_atoms"] == "../source/source_video_atoms.jsonl"
    assert source_build["alignment"]["transcript_dense_caption_tolerance_seconds"] == 2.0
    assert source_build["alignment"]["primary_window_modality"] == "dense_caption"
    assert source_build["atom_merging"]["enabled"] is False
    assert source_build["staging"] == {
        "draft_atom_stage": "draft",
        "draft_split": None,
        "final_atom_stage": "final",
        "final_split_labels": ["train", "dev", "test"],
    }


@pytest.mark.legacy_v36
def test_split_policy_forbids_cross_session_relative_time_order() -> None:
    """跨 session 去重必须穷举同人同日 session 对，不能比较相对秒或时间间隙。"""

    policy = yaml.safe_load((CONFIG_DIR / "split_policy.yaml").read_text(encoding="utf-8"))
    duplicate_policy = policy["grouping"]["near_duplicate"]
    assert duplicate_policy["comparison_scope"] == "all_sessions_same_participant_source_day"
    assert duplicate_policy["cross_session_time_order"] == "prohibited"
    assert duplicate_policy["max_gap_seconds"] is None


@pytest.mark.legacy_v36
def test_cue_execution_policy_freezes_v3_realtime_compact_contract() -> None:
    """Cue v3 必须冻结实时限流、成本熔断、短码与无正文恢复边界。"""

    registry = yaml.safe_load((CONFIG_DIR / "model_registry.yaml").read_text(encoding="utf-8"))
    cue = registry["models"]["cue_extraction"]
    execution = cue["execution"]
    assert registry["registry_version"] == "v1.6.0"
    assert registry["raw_response_policy"] == "forbidden"
    assert cue["model_id"] == "qwen3.7-flash"
    assert cue["prompt_version"] == "cue_extractor_v3_6_compact"
    assert cue["schema_version"] == "v1.1.0"
    assert execution["cue_execution_policy_version"] == "v3.6.0"
    assert execution["protocol_hash_payload_version"] == "v3.6.0"
    assert execution["mode"] == "explicit_realtime_execute_only"
    assert execution["shard_size_atoms"] == 500
    assert execution["max_retries"] == 2
    assert execution["transport"] == "realtime_chat_completions"
    assert execution["package_policy"] == {
        "maximum_atoms": 5,
        "maximum_request_utf8_bytes": 24000,
        "ordering": "atom_id_lexicographic",
        "output_tokens_per_atom": 96,
        "output_max_tokens_formula": "output_tokens_per_atom_times_package_atom_count",
        "inference_schema": "cue_inference_batch_compact_v1.schema.json",
        "inference_schema_version": "v1.1.0",
        "response_top_level_field": "items",
        "response_correlation_field": "n",
    }
    assert execution["controlled_field_policy"] == {
        "model_input_fields": ["item_index", "transcript", "dense_caption", "visible_text"],
        "model_output_fields": ["n", "f", "x", "p", "c", "v", "e", "s", "a", "r"],
        "program_backfilled_fields": ["cue_id", "atom_id", "split", "source_text", "supporting_text_field", "model_id", "prompt_version", "schema_version", "run_id"],
        "raw_model_response_storage": "forbidden",
    }
    assert execution["compact_inference_policy"] == {
        "cue_type_codes": {"T": "time", "P": "person", "L": "place", "O": "object", "A": "activity", "S": "state_change"},
        "supporting_text_field_codes": {"T": "transcript", "D": "dense_caption", "V": "visible_text"},
        "operator_codes": {"=": "eq", "!": "not_eq", "+": "present", "-": "absent", "^": "starts", "$": "ends", "~": "contains"},
        "required_fields": ["n", "f", "x", "p", "c", "v"],
        "optional_defaults": {"e": [], "s": None, "a": None, "r": None},
        "confidence_scale": 100,
    }
    assert execution["realtime_api_policy"] == {
        "request_endpoint": "/chat/completions", "maximum_in_flight": 10,
        "requests_per_minute": 300, "tokens_per_minute": 1000000,
        "token_reservation": "serialized_utf8_request_bytes_plus_max_tokens",
        "retryable_http_statuses": [408, 429, 500, 502, 503, 504],
        "retry_backoff_initial_seconds": 2, "retry_backoff_max_seconds": 60,
        "request_timeout_seconds": 60, "request_body_storage": "temporary_memory_only",
        "raw_response_storage": "forbidden_stream_only",
        "successful_local_validation_failure": "quarantine_no_auto_retry",
    }
    assert execution["realtime_ledger_policy"]["terminal_outcomes"] == ["validated_success", "service_transport_exhausted", "local_validation_quarantine", "budget_stopped"]
    assert execution["realtime_ledger_policy"]["local_validation_diagnostic"] == {"format": "code_path_v1", "raw_content": "forbidden"}
    assert execution["realtime_execution_policy"]["execution_confirmation"] == "START_REALTIME_CUE_API"
    assert execution["realtime_execution_policy"]["wave_task_counts"] == [1, 10, 10, 10, 10, 10, 10, 14]
    assert execution["realtime_execution_policy"]["logical_shards_per_task"] == 10
    assert execution["realtime_execution_policy"]["progress_update_interval_seconds"] == 15
    assert execution["shard_layout"]["root"] == "cues/realtime"
    assert execution["shard_layout"]["run_directory"] == "runs"
    assert execution["shard_layout"]["realtime_shards_manifest"] == "realtime_shards_manifest.jsonl"
    assert execution["shard_layout"]["progress_filename"] == "progress.json"
    assert execution["pricing_snapshot"] == {
        "pricing_version": "2026-09-05_cn-beijing_realtime_list",
        "official_pricing_url": "https://help.aliyun.com/zh/model-studio/model-pricing",
        "input_price_cny_per_million_tokens": 0.2,
        "output_price_cny_per_million_tokens": 0.8,
        "price_region": "cn-beijing",
        "input_context_window_tokens": 32000,
        "successful_requests_only_billed": False,
        "context_cache_supported": False,
    }
    assert execution["token_accounting"]["authoritative_source"] == "response_usage"
    assert execution["token_accounting"]["preflight_upper_bound"] == "serialized_utf8_realtime_request_bytes"
    assert execution["token_accounting"]["raw_response_storage"] == "forbidden"
    assert execution["recovery"] == {
        "require_matching_source_hash": True,
        "require_matching_protocol_hash": True,
        "rerun_only_incomplete_or_failed_packages": True,
        "completion_marker_requires_sha256": True,
        "require_package_id_bijection": True,
        "prohibit_automatic_local_validation_retry": True,
    }
    assert {"cue_execution_policy_version", "cue_execution_protocol_sha256", "cue_prompt_sha256", "cue_inference_schema_sha256", "source_atoms_sha256", "package_maximum_atoms", "package_maximum_request_utf8_bytes", "output_tokens_per_atom", "package_count", "usage_summary"}.issubset(registry["run_manifest_required_fields"])


@pytest.mark.legacy_v36
def test_compact_cue_inference_schema_excludes_controlled_fields_and_stays_small() -> None:
    """v2.2 短码 Schema 必须严格、可展开且不超过 1000 字节序列化预算。"""

    schema = json.loads((SCHEMA_DIR / "cue_inference_batch_compact_v1.schema.json").read_text(encoding="utf-8"))
    item = schema["$defs"]["i"]
    controlled = {"cue_id", "atom_id", "split", "source_text", "model_id", "prompt_version", "schema_version", "run_id"}
    assert item["additionalProperties"] is False
    assert controlled.isdisjoint(item["properties"])
    assert len(json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= 1100
    jsonschema.Draft202012Validator(schema).validate({
        "items": [{"n": 0, "f": "V", "x": "手机", "p": [["O", "+", "手机"]], "c": 90, "v": "A"}]
    })


@pytest.mark.cue_v2
def test_cue_v2_artifact_schema_freezes_minimal_grounded_cue_shape() -> None:
    """正式 Cue 只能保存 Atom 身份与逐 clause 证据，阻断旧运行元数据和无证据事实。"""

    schema = json.loads((SCHEMA_DIR / "cue_v2_artifacts.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    one_clause = {"cue_id": "cue_phone_01", "atom_id": "src_phone_01", "predicate": {"all_of": [{"dimension": "object", "operator": "present", "value": "手机", "evidence": {"field": "dense_caption", "span": "手机出现在桌上"}}]}}
    three_clauses = {"cue_id": "cue_jake_01", "atom_id": "src_jake_01", "predicate": {"all_of": [
        {"dimension": "person", "operator": "speaking", "value": "Jake", "evidence": {"field": "transcript", "span": "Jake: 我在说话"}},
        {"dimension": "object", "operator": "held", "value": "杯子", "evidence": {"field": "dense_caption", "span": "Jake 手持杯子"}},
        {"dimension": "location", "operator": "at", "value": "厨房", "evidence": {"field": "dense_caption", "span": "厨房中的 Jake"}}
    ]}}
    validator.validate(one_clause)
    validator.validate(three_clauses)

    for clause_count in (0, 4):
        invalid = {"cue_id": "cue_invalid", "atom_id": "src_invalid", "predicate": {"all_of": one_clause["predicate"]["all_of"] * clause_count}}
        assert not validator.is_valid(invalid)
    for legacy_field in ("cue_type", "confidence", "primary_cue_type", "entities", "source_text", "model_id"):
        invalid = dict(one_clause)
        invalid[legacy_field] = "forbidden"
        assert not validator.is_valid(invalid)
    invalid_evidence = {**one_clause, "predicate": {"all_of": [{"dimension": "object", "operator": "present", "value": "手机", "evidence": {"field": "visible_text", "span": "手机"}}]}}
    assert not validator.is_valid(invalid_evidence)


@pytest.mark.cue_v2
def test_cue_v2_dimension_operator_matrix_rejects_legacy_and_cross_pairs() -> None:
    """矩阵将关系语义固定在维度内，避免 legacy 名称或任意组合掩盖事实关系。"""

    schema = json.loads((SCHEMA_DIR / "cue_v2_artifacts.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    examples = {
        "person": ("present", "李明"), "location": ("entering", "办公室"), "object": ("placed", "钥匙"),
        "activity": ("ongoing", "洗碗"), "state": ("changes_to", "门打开"), "explicit_time": ("hypothetical", "明天上午"),
    }
    for dimension, (operator, value) in examples.items():
        validator.validate({"cue_id": f"cue_{dimension}", "atom_id": f"src_{dimension}", "predicate": {"all_of": [{"dimension": dimension, "operator": operator, "value": value, "evidence": {"field": "transcript", "span": value}}]}})
    for dimension in ("time", "place", "state_change"):
        invalid = {"cue_id": "cue_legacy", "atom_id": "src_legacy", "predicate": {"all_of": [{"dimension": dimension, "operator": "present", "value": "值", "evidence": {"field": "transcript", "span": "值"}}]}}
        assert not validator.is_valid(invalid)
    invalid_pair = {"cue_id": "cue_cross", "atom_id": "src_cross", "predicate": {"all_of": [{"dimension": "person", "operator": "held", "value": "李明", "evidence": {"field": "transcript", "span": "李明"}}]}}
    assert not validator.is_valid(invalid_pair)


@pytest.mark.cue_v2
def test_cue_v2_inference_interface_preserves_parser_boundary() -> None:
    """模型接口使用完整字段名；跨字段终态约束留给后续本地 parser，不能由 Schema 伪装完成。"""

    schema = json.loads((SCHEMA_DIR / "cue_v2_inference.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    item = schema["$defs"]["item"]
    assert set(item["properties"]) == {"item_index", "disposition", "predicate", "reason_codes"}
    assert item["properties"]["disposition"]["enum"] == ["accepted_cue", "no_cue", "ambiguous"]
    assert schema["properties"]["items"]["maxItems"] == 5
    assert schema["$defs"]["predicate"]["properties"]["all_of"]["maxItems"] == 3
    assert schema["$defs"]["clause"]["properties"]["operator"]["enum"] == ["present", "absent", "speaking", "mentioned", "at", "not_at", "entering", "leaving", "held", "placed", "starts", "ongoing", "ends", "not_occurring", "is", "is_not", "changes_to", "stated", "planned", "hypothetical"]
    assert schema["$defs"]["item"]["properties"]["reason_codes"]["maxItems"] == 3
    validator.validate({"items": [{"item_index": 0, "disposition": "no_cue", "predicate": {"all_of": []}, "reason_codes": ["NO_OBSERVABLE_CONDITION"]}]})
    assert validator.is_valid({"items": [{"item_index": index, "disposition": "no_cue", "predicate": {"all_of": []}, "reason_codes": ["NO_OBSERVABLE_CONDITION"]} for index in range(5)]})
    assert not validator.is_valid({"items": [{"item_index": index, "disposition": "no_cue", "predicate": {"all_of": []}, "reason_codes": ["NO_OBSERVABLE_CONDITION"]} for index in range(6)]})
    assert not validator.is_valid({"items": [{"item_index": 0, "disposition": "no_cue", "predicate": {"all_of": []}, "reason_codes": ["FREE_TEXT"]}]})
    assert not validator.is_valid({"items": [{"item_index": 0, "disposition": "no_cue", "predicate": {"all_of": []}, "reason_codes": ["NO_OBSERVABLE_CONDITION"] * 4}]})
    # 后续 parser 必须额外拒绝 accepted_cue 的零 clause 或非空 reason_codes，并拒绝 no_cue/ambiguous 的事实 clause 或空原因。


@pytest.mark.cue_v2
def test_cue_v2_manifest_success_and_disposition_defs_are_executable() -> None:
    """工件 defs 必须可独立校验，防止只有字段声明却无法闭合哈希与终态接口。"""

    schema = json.loads((SCHEMA_DIR / "cue_v2_artifacts.schema.json").read_text(encoding="utf-8"))
    defs = schema["$defs"]
    def validator(name: str) -> jsonschema.Draft202012Validator:
        return jsonschema.Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": defs})
    digest = "a" * 64
    disposition = {"atom_id": "src_item_01", "terminal_disposition": "excluded_no_cue", "reason_codes": ["INSUFFICIENT_EVIDENCE"]}
    manifest = {"campaign_id": "campaign_01", "source_atoms_success_sha256": digest, "bge_selection_success_sha256": digest, "model_id": "qwen3.7-flash", "prompt_sha256": digest, "inference_schema_id": "cue_v2_inference.schema.json", "inference_schema_sha256": digest, "formal_schema_id": "cue_v2_artifacts.schema.json", "formal_schema_sha256": digest, "formal_shards": [{"path": "cues/v2/formal/part_000.jsonl", "sha256": digest, "row_count": 1, "byte_count": 10, "order_key": "atom_id", "coverage": {"first_atom_id": "src_item_01"}}], "disposition_ledger_sha256": digest, "disposition_counts": {"excluded_no_cue": 1}, "distribution_manifest_sha256": digest, "contract_version": "v1.1.0", "config_version": "v1.1.0", "schema_versions": {"cue": "v2.0.0"}, "generated_at": "2026-09-15T00:00:00Z", "upstream_hashes": {"source": digest}}
    success = {"manifest_sha256": digest, "shard_count": 1, "total_row_count": 1, "distribution_manifest_sha256": digest, "contract_version": "v1.1.0", "config_version": "v1.1.0", "schema_versions": {"cue": "v2.0.0"}, "generated_at": "2026-09-15T00:00:00Z", "upstream_hashes": {"manifest": digest}}
    for name, instance in (("disposition", disposition), ("cue_library_manifest", manifest), ("cue_library_success", success)):
        current = validator(name)
        current.validate(instance)
        missing = dict(instance); missing.pop(next(iter(instance)))
        assert not current.is_valid(missing)
        assert not current.is_valid({**instance, "unexpected": True})


@pytest.mark.cue_v2
def test_cue_v2_config_and_paths_are_current_without_legacy_fallback() -> None:
    """配置和路径须显式指向 Cue v2，防止生产者悄然回读旧 V9 formal、manifest 或 SUCCESS。"""

    registry = yaml.safe_load((CONFIG_DIR / "model_registry.yaml").read_text(encoding="utf-8"))
    cue_v2 = registry["models"]["cue_v2_extraction"]
    assert cue_v2["model_id"] == "qwen3.7-flash"
    assert cue_v2["thinking_enabled"] is False and cue_v2["temperature"] == 0
    assert cue_v2["clause_minimum"] == 1 and cue_v2["clause_maximum"] == 3
    assert cue_v2["maximum_atoms_per_request"] == 5
    assert cue_v2["raw_response_policy"] == "forbidden"
    assert cue_v2["visible_text_evidence"] == "forbidden"
    assert cue_v2["legacy_fallback"] == "forbidden"
    assert cue_v2["dimension_operators"] == {
        "person": ["present", "absent", "speaking", "mentioned"], "location": ["at", "not_at", "entering", "leaving", "mentioned"],
        "object": ["present", "absent", "held", "placed"], "activity": ["starts", "ongoing", "ends", "not_occurring"],
        "state": ["is", "is_not", "changes_to"], "explicit_time": ["stated", "planned", "hypothetical"],
    }
    paths = yaml.safe_load((CONFIG_DIR / "paths.yaml").read_text(encoding="utf-8"))["cue_v2"]
    assert set(paths) == {"cue_v2_root", "cue_v2_source_selection_root", "cue_v2_protocol_acceptance_root", "cue_v2_worker_staging_root", "cue_v2_formal_root", "cue_v2_disposition_ledger", "cue_v2_library_manifest", "cue_v2_library_success", "cue_v2_distribution_report_root"}
    assert all("../cues/formal" not in path and "../cues/cue_library_manifest.json" not in path and "../cues/CUE_LIBRARY_SUCCESS.json" not in path for path in paths.values())
