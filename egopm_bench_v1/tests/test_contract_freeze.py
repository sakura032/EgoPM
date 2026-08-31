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
