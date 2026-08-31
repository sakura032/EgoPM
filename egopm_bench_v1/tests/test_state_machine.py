"""T3 的纯合成 fixture 回归：不读取或写入任何正式 benchmark 产物。

职责：在内存中构造手写 Seed、source atom 和协议片段，验证阶段 08 的审计过滤、阶段
09 的六路 family 生成及阶段 10 的确定性 gold 翻转。输入是本文件中的 fixture，输出
只是 pytest 断言结果；它位于正式 SUCCESS 门之外，绝不计入基准数据或写入正式目录。
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import jsonschema
import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_script(filename: str, module_name: str) -> Any:
    # 编号脚本名不能作为普通 Python 标识符导入；显式加载使测试覆盖真实 CLI 模块，
    # 而不是复制一份容易与生产实现漂移的测试专用逻辑。
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "scripts" / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


FREEZE = _load_script("08_freeze_seed_audit.py", "t3_freeze_seed_audit")
FAMILIES = _load_script("09_build_lifelog_families.py", "t3_build_lifelog_families")
ORACLE = _load_script("10_run_oracle.py", "t3_run_oracle")


def _seed(negative_type: str = "cancelled") -> dict[str, Any]:
    # 手写 fixture 固定为同一 trigger 与两个 lure；参数只改变历史失效原因，以测试
    # 反事实 gold 是否确实由状态而非当前文本翻转。
    return {
        "seed_id": "seed_SYNTH_T3_000001",
        "family_id": "family_SYNTH_T3_000001",
        "split": "train",
        "source_group_id": "group_SYNTH_T3_DAY1",
        "intention": {
            "intention_id": "int_SYNTH_T3_000001",
            "action_content": "在开始做饭时服用药物",
        },
        "primary_cue_type": "activity",
        "trigger_atom_id": "src_SYNTH_T3_000001",
        "lure_atom_ids": ["src_SYNTH_T3_000002", "src_SYNTH_T3_000003"],
        "trigger_predicate": {
            "all_of": [
                {"slot": "place", "operator": "eq", "value": "kitchen"},
                {"slot": "activity", "operator": "starts", "value": "cooking"},
            ]
        },
        "valid_window": {
            "relative_to": "trigger_event",
            "start_offset_sec": 0,
            "end_offset_sec": 60,
        },
        "terminal_silent_conditions": ["completed", "cancelled", "expired", "already_reminded"],
        "counterfactual_negative_type": negative_type,
        "rule_ids": ["rule_SYNTH_T3_000001"],
        "current_trigger_leakage_checked": True,
        "audit": {
            "status": "candidate",
            "reason": "仅用于 T3 单元测试的手写合成 fixture。",
            "human_reviewer": None,
            "model_audit_run_id": None,
        },
        "generation_record": {
            "run_id": "run_synth_t3",
            "model_id": "synthetic-fixture",
            "prompt_version": "fixture",
            "schema_version": "v1.0.0",
        },
    }


def _atom(atom_id: str, text: str, start: float) -> dict[str, Any]:
    return {
        "atom_id": atom_id,
        "atom_kind": "source_video_atom",
        "participant_source_id": "SYNTH_T3",
        "source_day": "DAY1",
        "session_id": "SESSION1",
        "source_group_id": "group_SYNTH_T3_DAY1",
        "world_event_id": None,
        "source_srt_paths": {
            "transcript": "synthetic/Transcript/SYNTH_T3/DAY1/example.srt",
            "dense_caption": "synthetic/DenseCaption/SYNTH_T3/DAY1/example.srt",
        },
        "source_video_path": None,
        "video_mapping_status": "pending",
        "local_start_sec": start,
        "local_end_sec": start + 5.0,
        "normalized_start_sec": start,
        "normalized_end_sec": start + 5.0,
        "transcript_segment_ids": [f"seg_{atom_id}_t"],
        "dense_caption_segment_ids": [f"seg_{atom_id}_d"],
        "transcript": text,
        "dense_caption": text,
        "visible_text": text,
        "modality_coverage": "both",
        "provenance": "egolife_srt",
        "split": "train",
    }


def _atoms() -> dict[str, dict[str, Any]]:
    return {
        "src_SYNTH_T3_000001": _atom("src_SYNTH_T3_000001", "有人在厨房开始做饭。", 30.0),
        "src_SYNTH_T3_000002": _atom("src_SYNTH_T3_000002", "有人在厨房交谈。", 10.0),
        "src_SYNTH_T3_000003": _atom("src_SYNTH_T3_000003", "有人在餐桌旁用餐。", 20.0),
    }


def _protocol() -> dict[str, Any]:
    return {
        "difficulties": {
            "short": {"event_count": [12, 20], "background_intentions": [0, 1], "virtual_span_minutes": [30, 90]},
            "medium": {"event_count": [35, 60], "background_intentions": [2, 4], "virtual_span_minutes": [120, 480]},
            "long": {"event_count": [90, 150], "background_intentions": [5, 10], "virtual_span_minutes": [720, 2880]},
        }
    }


def _log_by_variant(logs: list[dict[str, Any]], branch: str, difficulty: str) -> dict[str, Any]:
    return next(log for log in logs if log["counterfactual_branch"] == branch and log["difficulty"] == difficulty)


def _trigger_decision(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    return next(item for item in decisions if item["decision_type"] == "trigger")


def test_accepted_audit_is_the_only_freeze_authority() -> None:
    candidate = _seed()
    audit = [
        {
            "seed_id": candidate["seed_id"],
            "status": "accept",
            "human_reviewer": "reviewer_t0",
            "reason": "触发、干扰项和生命周期均可确定性执行。",
        }
    ]
    frozen = FREEZE.apply_frozen_audit([candidate], audit, minimum=1, maximum=1)
    assert frozen[0]["audit"]["status"] == "accept"
    assert frozen[0]["audit"]["human_reviewer"] == "reviewer_t0"
    assert candidate["audit"]["status"] == "candidate"
    rules = FREEZE.build_rule_bank(frozen)
    assert rules[0]["gold_authority"] == "deterministic_state_machine_only"


def test_each_seed_derives_six_schema_valid_lifelogs_and_matched_gold_flip() -> None:
    seed = _seed()
    family, logs, pairs = FAMILIES.build_family(seed, _atoms(), _protocol())
    assert family["seed_id"] == seed["seed_id"]
    assert len(logs) == 6
    assert len(pairs) == 3

    schema = json.loads((ROOT / "schemas" / "lifelog.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for log in logs:
        validator.validate(log)
        assert log["event_count"] == len(log["events"])
        assert log["events"][-1]["atom_id"] == seed["trigger_atom_id"]

    decision_schema = json.loads((ROOT / "schemas" / "decision_instance.schema.json").read_text(encoding="utf-8"))
    decision_validator = jsonschema.Draft202012Validator(decision_schema)
    for pair in pairs:
        positive = next(log for log in logs if log["lifelog_id"] == pair["positive_lifelog_id"])
        negative = next(log for log in logs if log["lifelog_id"] == pair["negative_lifelog_id"])
        pos_decisions, pos_evidence = ORACLE.compile_lifelog(seed, positive, pair["counterfactual_pair_id"])
        neg_decisions, neg_evidence = ORACLE.compile_lifelog(seed, negative, pair["counterfactual_pair_id"])
        assert _trigger_decision(pos_decisions)["gold_action"]["kind"] == "remind"
        assert _trigger_decision(neg_decisions)["gold_action"]["kind"] == "silent"
        assert _trigger_decision(pos_decisions)["model_input"]["visible_text"] == _trigger_decision(neg_decisions)["model_input"]["visible_text"]
        assert len(pos_evidence) == len(pos_decisions)
        assert len(neg_evidence) == len(neg_decisions)
        for decision in [*pos_decisions, *neg_decisions]:
            decision_validator.validate(decision)
            assert set(decision["model_input"]) == {"stream_position", "current_event_id", "virtual_time", "visible_text"}


@pytest.mark.parametrize(
    ("negative_type", "expected_state"),
    [
        ("never_created", "never_created"),
        ("completed", "completed"),
        ("cancelled", "cancelled"),
        ("expired", "expired"),
        ("already_reminded", "active_reminded"),
    ],
)
def test_all_negative_history_types_are_deterministically_silent(
    negative_type: str, expected_state: str
) -> None:
    seed = _seed(negative_type)
    _, logs, pairs = FAMILIES.build_family(seed, _atoms(), _protocol())
    short_pair = next(pair for pair in pairs if pair["difficulty"] == "short")
    positive = _log_by_variant(logs, "positive", "short")
    negative = _log_by_variant(logs, "negative", "short")
    pos_decisions, _ = ORACLE.compile_lifelog(seed, positive, short_pair["counterfactual_pair_id"])
    neg_decisions, _ = ORACLE.compile_lifelog(seed, negative, short_pair["counterfactual_pair_id"])
    assert _trigger_decision(pos_decisions)["gold_action"]["kind"] == "remind"
    negative_trigger = _trigger_decision(neg_decisions)
    assert negative_trigger["gold_action"]["kind"] == "silent"
    assert negative_trigger["oracle_annotation"]["state_before"] == expected_state


def test_oracle_rejects_a_lifelog_that_claims_non_state_machine_gold_transition() -> None:
    seed = _seed()
    _, logs, pairs = FAMILIES.build_family(seed, _atoms(), _protocol())
    positive = copy.deepcopy(_log_by_variant(logs, "positive", "short"))
    positive["events"][-1]["intention_state_after"] = "active_unreminded"
    pair = next(item for item in pairs if item["difficulty"] == "short")
    with pytest.raises(ORACLE.GateError, match="state_after"):
        ORACLE.compile_lifelog(seed, positive, pair["counterfactual_pair_id"])
