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


def test_cue_execution_policy_freezes_no_api_recovery_contract() -> None:
    """Cue v2 必须冻结五条 package、回填字段和无 API 恢复边界。"""

    registry = yaml.safe_load((CONFIG_DIR / "model_registry.yaml").read_text(encoding="utf-8"))
    cue = registry["models"]["cue_extraction"]
    execution = cue["execution"]
    assert registry["registry_version"] == "v1.2.0"
    assert registry["raw_response_policy"] == "forbidden"
    assert cue["prompt_version"] == "cue_extractor_v2"
    assert execution["cue_execution_policy_version"] == "v2.0.0"
    assert execution["protocol_hash_payload_version"] == "v1.0.0"
    assert execution["mode"] == "explicit_execute_only"
    assert execution["shard_size_atoms"] == 500
    assert execution["max_retries"] == 2
    assert execution["transport"] == "realtime_chat_completions"
    assert execution["package_policy"] == {
        "maximum_atoms": 5,
        "maximum_request_utf8_bytes": 24000,
        "ordering": "atom_id_lexicographic",
        "output_tokens_per_atom": 128,
        "output_max_tokens_formula": "output_tokens_per_atom_times_package_atom_count",
        "inference_schema": "cue_inference_batch_v1.schema.json",
        "inference_schema_version": "v1.0.0",
        "response_top_level_field": "items",
        "response_correlation_field": "item_index",
    }
    assert execution["controlled_field_policy"] == {
        "model_input_fields": ["item_index", "text"],
        "model_output_fields": ["item_index", "entities", "scene_type", "activity_type", "cue_type", "normalized_predicate", "supporting_text_span", "confidence", "ambiguity_reason", "validation_status"],
        "program_backfilled_fields": ["cue_id", "atom_id", "split", "source_text", "model_id", "prompt_version", "schema_version", "run_id"],
        "raw_model_response_storage": "forbidden",
    }
    assert execution["pricing_snapshot"] == {
        "pricing_version": "2026-09-01_cn-beijing_list",
        "official_pricing_url": "https://help.aliyun.com/zh/model-studio/model-pricing",
        "input_price_cny_per_million_tokens": 0.2,
        "output_price_cny_per_million_tokens": 0.8,
        "price_region": "cn-beijing",
        "input_context_window_tokens": 32000,
        "retry_attempts_billed_independently": True,
    }
    assert execution["rate_limit_policy"] == {
        "target_requests_per_minute": 300,
        "target_total_tokens_per_minute": 1000000,
        "official_requests_per_minute": 30000,
        "official_total_tokens_per_minute": 5000000,
        "official_region": "cn-beijing",
    }
    assert execution["token_accounting"]["authoritative_source"] == "response_usage"
    assert execution["token_accounting"]["raw_response_storage"] == "forbidden"
    assert execution["recovery"] == {
        "require_matching_source_hash": True,
        "require_matching_protocol_hash": True,
        "rerun_only_incomplete_or_failed_packages": True,
        "completion_marker_requires_sha256": True,
    }
    assert {"cue_execution_policy_version", "cue_execution_protocol_sha256", "cue_prompt_sha256", "cue_inference_schema_sha256", "source_atoms_sha256", "package_maximum_atoms", "package_maximum_request_utf8_bytes", "output_tokens_per_atom", "package_count", "usage_summary"}.issubset(registry["run_manifest_required_fields"])


def test_cue_inference_schema_excludes_program_controlled_fields() -> None:
    """v2 推理 Schema 只能容纳模型推理字段，最终血缘字段必须留给程序回填。"""

    schema = json.loads((SCHEMA_DIR / "cue_inference_batch_v1.schema.json").read_text(encoding="utf-8"))
    item = schema["$defs"]["item"]
    controlled = {"cue_id", "atom_id", "split", "source_text", "model_id", "prompt_version", "schema_version", "run_id"}
    assert item["additionalProperties"] is False
    assert controlled.isdisjoint(item["properties"])
    jsonschema.Draft202012Validator(schema).validate({
        "items": [{"item_index": 0, "entities": ["手机"], "scene_type": None, "activity_type": "拿取", "cue_type": "object", "normalized_predicate": {"all_of": [{"slot": "object", "operator": "present", "value": "手机"}]}, "supporting_text_span": "拿着手机", "confidence": 0.9, "ambiguity_reason": None, "validation_status": "accepted"}]
    })
