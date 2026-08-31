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
    """Cue 运行前必须冻结可恢复 shard、用量账本和保守限流，而非由执行时临时猜测。"""

    registry = yaml.safe_load((CONFIG_DIR / "model_registry.yaml").read_text(encoding="utf-8"))
    execution = registry["models"]["cue_extraction"]["execution"]
    assert registry["registry_version"] == "v1.1.0"
    assert execution["cue_execution_policy_version"] == "v1.0.0"
    assert execution["mode"] == "explicit_execute_only"
    assert execution["shard_size_atoms"] == 500
    assert execution["max_tokens"] == 512
    assert execution["max_retries"] == 2
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
        "rerun_only_incomplete_or_failed_shards": True,
        "completion_marker_requires_sha256": True,
    }
