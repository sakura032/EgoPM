"""T0 合同回归测试：验证冻结配置、Schema 与手写 fixture 的可复现边界。

输入为 T0 管理的配置、Schema 与 synthetic fixture；输出为 pytest 断言结果。
本文件位于合同冻结阶段，确保 Source 正式建库只能使用已批准的 v1.1 语义。
"""

import json
from pathlib import Path

import jsonschema
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
CONFIG_DIR = ROOT / "config"
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "contract"


def test_all_contract_schemas_compile() -> None:
    for schema_path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        jsonschema.Draft202012Validator.check_schema(
            json.loads(schema_path.read_text(encoding="utf-8"))
        )


def test_configs_share_frozen_contract_version() -> None:
    for config_path in sorted(CONFIG_DIR.glob("*.yaml")):
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert config["contract_version"] == "v1.1.0"
        assert config["config_version"] == "v1.1.0"


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


def test_split_policy_forbids_cross_session_relative_time_order() -> None:
    """跨 session 去重必须穷举同人同日 session 对，不能比较相对秒或时间间隙。"""

    policy = yaml.safe_load((CONFIG_DIR / "split_policy.yaml").read_text(encoding="utf-8"))
    duplicate_policy = policy["grouping"]["near_duplicate"]
    assert duplicate_policy["comparison_scope"] == "all_sessions_same_participant_source_day"
    assert duplicate_policy["cross_session_time_order"] == "prohibited"
    assert duplicate_policy["max_gap_seconds"] is None


def test_cue_execution_policy_freezes_v3_realtime_compact_contract() -> None:
    """Cue v3 必须冻结实时限流、成本熔断、短码与无正文恢复边界。"""

    registry = yaml.safe_load((CONFIG_DIR / "model_registry.yaml").read_text(encoding="utf-8"))
    cue = registry["models"]["cue_extraction"]
    execution = cue["execution"]
    assert registry["registry_version"] == "v1.6.0"
    assert registry["raw_response_policy"] == "forbidden"
    assert cue["model_id"] == "qwen3.7-flash"
    assert cue["prompt_version"] == "cue_extractor_v3_5_compact"
    assert cue["schema_version"] == "v1.1.0"
    assert execution["cue_execution_policy_version"] == "v3.5.0"
    assert execution["protocol_hash_payload_version"] == "v3.5.0"
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
        "model_output_fields": ["n", "f", "start", "end", "p", "c", "v", "e", "s", "a", "r"],
        "program_backfilled_fields": ["cue_id", "atom_id", "split", "source_text", "supporting_text_field", "model_id", "prompt_version", "schema_version", "run_id"],
        "raw_model_response_storage": "forbidden",
    }
    assert execution["compact_inference_policy"] == {
        "cue_type_codes": {"T": "time", "P": "person", "L": "place", "O": "object", "A": "activity", "S": "state_change"},
        "supporting_text_field_codes": {"T": "transcript", "D": "dense_caption", "V": "visible_text"},
        "operator_codes": {"=": "eq", "!": "not_eq", "+": "present", "-": "absent", "^": "starts", "$": "ends", "~": "contains"},
        "required_fields": ["n", "f", "start", "end", "p", "c", "v"],
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


def test_compact_cue_inference_schema_excludes_controlled_fields_and_stays_small() -> None:
    """v2.2 短码 Schema 必须严格、可展开且不超过 1000 字节序列化预算。"""

    schema = json.loads((SCHEMA_DIR / "cue_inference_batch_compact_v1.schema.json").read_text(encoding="utf-8"))
    item = schema["$defs"]["i"]
    controlled = {"cue_id", "atom_id", "split", "source_text", "model_id", "prompt_version", "schema_version", "run_id"}
    assert item["additionalProperties"] is False
    assert controlled.isdisjoint(item["properties"])
    assert len(json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= 1100
    jsonschema.Draft202012Validator(schema).validate({
        "items": [{"n": 0, "f": "V", "start": 0, "end": 4, "p": [["O", "+", "手机"]], "c": 90, "v": "A"}]
    })
