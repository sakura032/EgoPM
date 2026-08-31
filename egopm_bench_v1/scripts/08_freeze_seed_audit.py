"""将 T0 冻结的人工审计编译为不可变的 Seed 与规则银行。

职责：读取经 SUCCESS/哈希保护的候选 Seed 与 T0 冻结的人工审计 CSV，只保留明确
``accept`` 的记录，输出冻结 Seed、规则银行、状态机策略和
``SEEDS_FROZEN_SUCCESS.json``。它位于 Seed 审计后的第五阶段，是 Life Log 编译前
唯一可以把人工审计结论固化为 T3 规则工件的入口。
"""

from __future__ import annotations

import argparse
import copy
from pathlib import Path
import sys
from typing import Any, Mapping


BENCHMARK_ROOT = Path(__file__).resolve().parents[1]
if str(BENCHMARK_ROOT) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_ROOT))

from rules.compiler_io import (  # noqa: E402
    GateError,
    atomic_write_jsonl,
    atomic_write_yaml,
    benchmark_root,
    load_config,
    load_csv,
    load_jsonl,
    require_success_marker,
    resolve_config_path,
    schema_validator,
    sha256_file,
    validate_rows,
    write_success_marker,
)


AUDIT_STATUSES = frozenset({"accept", "revise", "reject"})


def _audit_status(row: Mapping[str, str]) -> str:
    for field in ("status", "audit_status", "decision"):
        value = row.get(field)
        if value is not None and value.strip():
            return value.strip().lower()
    # 不猜测缺失列的含义；审计列名不明确时若继续筛选，可能错误冻结未审样本。
    raise GateError("审计 CSV 缺少 status、audit_status 或 decision 列")


def _audit_value(row: Mapping[str, str], field: str, fallback: str = "") -> str:
    value = row.get(field)
    return value.strip() if value is not None and value.strip() else fallback


def apply_frozen_audit(
    candidates: list[dict[str, Any]], audit_rows: list[dict[str, str]], *, minimum: int = 35, maximum: int = 40
) -> list[dict[str, Any]]:
    """仅接受人工 CSV 明确签字的 candidate，绝不从 T3 推断审计结论。"""

    # 先建立唯一索引，才能检测候选与审计两侧的重复或孤儿记录，避免最后一行静默覆盖
    # 前一行而改变人工审计结论。
    candidate_by_id: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        seed_id = candidate.get("seed_id")
        if not isinstance(seed_id, str) or not seed_id:
            raise GateError("candidate 缺少 seed_id")
        if seed_id in candidate_by_id:
            raise GateError(f"candidate seed_id 重复：{seed_id}")
        candidate_by_id[seed_id] = candidate

    audit_by_id: dict[str, dict[str, str]] = {}
    for row_number, row in enumerate(audit_rows, start=2):
        seed_id = _audit_value(row, "seed_id")
        if not seed_id:
            raise GateError(f"审计 CSV 第 {row_number} 行缺少 seed_id")
        if seed_id not in candidate_by_id:
            raise GateError(f"审计 CSV 引用了未知 seed_id：{seed_id}")
        if seed_id in audit_by_id:
            raise GateError(f"审计 CSV 的 seed_id 重复：{seed_id}")
        status = _audit_status(row)
        if status not in AUDIT_STATUSES:
            raise GateError(f"审计状态不合法：{seed_id} -> {status}")
        audit_by_id[seed_id] = row

    missing = sorted(set(candidate_by_id).difference(audit_by_id))
    if missing:
        # 必须覆盖候选池中的每个 Seed；否则“未出现在 CSV”会被错误地当作拒绝或接受。
        raise GateError(f"审计 CSV 未覆盖全部候选 Seed：{', '.join(missing[:5])}")

    frozen: list[dict[str, Any]] = []
    for candidate in candidates:
        seed_id = candidate["seed_id"]
        row = audit_by_id[seed_id]
        if _audit_status(row) != "accept":
            # T3 只编译人工已签字的接受结论，绝不把 revise/reject 重新解释为可用 Seed。
            continue
        reviewer = _audit_value(row, "human_reviewer", _audit_value(row, "reviewer"))
        reason = _audit_value(row, "reason", _audit_value(row, "audit_reason"))
        if not reviewer or not reason:
            raise GateError(f"接受的 Seed 必须有 reviewer 与 reason：{seed_id}")
        # 深复制避免测试或调用方看到 candidate 被原地改写；冻结工件应是独立快照。
        accepted = copy.deepcopy(candidate)
        accepted["audit"] = {
            "status": "accept",
            "reason": reason,
            "human_reviewer": reviewer,
            "model_audit_run_id": _audit_value(row, "model_audit_run_id") or None,
        }
        window = accepted.get("valid_window", {})
        if window.get("end_offset_sec", -1) < window.get("start_offset_sec", 0):
            # 倒置窗口没有确定的“当前时刻是否有效”语义，不能进入后续 oracle。
            raise GateError(f"Seed 的 valid_window 终点早于起点：{seed_id}")
        if accepted.get("current_trigger_leakage_checked") is not True:
            # 该标志是上游已完成当前 trigger 泄漏审查的唯一合同证明，缺失即阻断冻结。
            raise GateError(f"Seed 尚未完成 current trigger 泄漏检查：{seed_id}")
        frozen.append(accepted)

    if not minimum <= len(frozen) <= maximum:
        # 35–40 是合同冻结门；T3 不可为了继续流水线而放宽样本规模。
        raise GateError(f"接受 Seed 数必须位于 {minimum}–{maximum}，当前为 {len(frozen)}")
    family_ids = [seed.get("family_id") for seed in frozen]
    if len(set(family_ids)) != len(family_ids):
        raise GateError("冻结 Seed 的 family_id 必须一一对应")
    return frozen


def build_rule_bank(frozen_seeds: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """将每个 Seed 的冻结 predicate 与 terminal policy 复制到纯规则工件。"""

    rules: list[dict[str, Any]] = []
    seen_rule_ids: set[str] = set()
    for seed in frozen_seeds:
        for rule_id in seed["rule_ids"]:
            if rule_id in seen_rule_ids:
                # 一个 rule_id 若映射到多个 Seed，oracle 的主规则归属将变得不确定。
                raise GateError(f"rule_id 不可跨 Seed 重复：{rule_id}")
            seen_rule_ids.add(rule_id)
            rules.append(
                {
                    "rule_id": rule_id,
                    "seed_id": seed["seed_id"],
                    "family_id": seed["family_id"],
                    "split": seed["split"],
                    "intention_id": seed["intention"]["intention_id"],
                    "trigger_atom_id": seed["trigger_atom_id"],
                    "trigger_predicate": copy.deepcopy(seed["trigger_predicate"]),
                    "valid_window": copy.deepcopy(seed["valid_window"]),
                    "terminal_silent_conditions": list(seed["terminal_silent_conditions"]),
                    "counterfactual_negative_type": seed["counterfactual_negative_type"],
                    "gold_authority": "deterministic_state_machine_only",
                }
            )
    return rules


def state_machine_policy(contract_version: str, config_version: str) -> dict[str, Any]:
    return {
        "contract_version": contract_version,
        "config_version": config_version,
        "policy_version": "v1.0.0",
        "gold_authority": "deterministic_state_machine_only",
        "states": [
            "never_created",
            "active_unreminded",
            "active_reminded",
            "completed",
            "cancelled",
            "expired",
        ],
        "event_transitions": {
            "intention_creation": ["never_created", "active_unreminded"],
            "intention_completed": ["active_unreminded", "completed"],
            "intention_cancelled": ["active_unreminded", "cancelled"],
            "intention_expired": ["active_unreminded", "expired"],
            "reminder_history": ["active_unreminded", "active_reminded"],
            "trigger_remind": ["active_unreminded", "active_reminded"],
        },
        "decision_order": [
            "update_persistent_memory",
            "evaluate_frozen_trigger_atom",
            "check_active_unreminded",
            "check_valid_window",
            "emit_remind_or_silent",
        ],
    }


def run(config_path: Path, audit_path: Path | None = None) -> dict[str, Any]:
    protocol = load_config(config_path)
    paths_path = config_path.with_name("paths.yaml")
    paths = load_config(paths_path)
    root = benchmark_root(paths_path, paths)
    artifacts = paths["artifacts"]
    markers = paths["success_markers"]
    candidates_path = resolve_config_path(paths_path, artifacts["seed_candidates"])
    candidates_marker_path = resolve_config_path(paths_path, markers["seed_candidates"])
    audit_path = audit_path or resolve_config_path(paths_path, artifacts["seed_audit"])
    frozen_path = resolve_config_path(paths_path, artifacts["frozen_seeds"])
    rule_bank_path = resolve_config_path(paths_path, artifacts["rule_bank"])
    policy_path = resolve_config_path(paths_path, artifacts["state_machine_policy"])
    marker_path = resolve_config_path(paths_path, markers["frozen_seeds"])
    schema_dir = resolve_config_path(paths_path, paths["schema_dir"])

    # 先验证候选 SUCCESS/哈希，再读取内容，避免在上游部分写入或被篡改时冻结错误快照。
    candidates_marker = require_success_marker(candidates_marker_path, candidates_path)
    candidates = load_jsonl(candidates_path)
    validator = schema_validator(schema_dir / "reminder_seed.schema.json")
    validate_rows(candidates, validator, "Seed candidate")
    frozen = apply_frozen_audit(candidates, load_csv(audit_path))
    validate_rows(frozen, validator, "冻结 Seed")
    rules = build_rule_bank(frozen)

    # 所有内容先完成 Schema 与审计检查，再以原子替换写工件；SUCCESS 永远最后出现。
    frozen_count = atomic_write_jsonl(frozen_path, frozen)
    atomic_write_jsonl(rule_bank_path, rules)
    atomic_write_yaml(policy_path, state_machine_policy(protocol["contract_version"], protocol["config_version"]))
    return write_success_marker(
        marker_path=marker_path,
        artifact_path=frozen_path,
        row_count=frozen_count,
        contract_version=protocol["contract_version"],
        config_version=protocol["config_version"],
        schema_versions={"reminder_seed": "v1.0.0", "state_machine_policy": "v1.0.0"},
        upstream_hashes={
            "seed_candidates": candidates_marker["sha256"],
            "seed_audit": sha256_file(audit_path),
        },
        root=root,
        additional_artifacts={"rule_bank": rule_bank_path, "state_machine_policy": policy_path},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="冻结经人工审计接受的 Reminder Seed")
    parser.add_argument(
        "--config",
        type=Path,
        default=BENCHMARK_ROOT / "config" / "benchmark_protocol.yaml",
        help="冻结的 benchmark_protocol.yaml 路径",
    )
    parser.add_argument("--audit", type=Path, help="T0 冻结的 reminder_seed_audit.csv 路径")
    args = parser.parse_args()
    try:
        marker = run(args.config.resolve(), args.audit.resolve() if args.audit else None)
    except GateError as exc:
        parser.error(str(exc))
    print(f"已冻结 {marker['row_count']} 个 Seed；SHA256={marker['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
