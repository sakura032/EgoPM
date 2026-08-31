"""以冻结的确定性状态机编译 Decision Instance 与 Evidence Set。

职责：读取哈希受保护的冻结 Seed、Life Log 和反事实配对，逐事件调用确定性状态机，
输出 Schema 合法的 Decision Instance、分离的 Evidence Set 与
``DECISIONS_SUCCESS.json``。它处于第八阶段，gold action 的唯一来源是
``rules.state_machine``；本脚本不调用大模型，也不会由可见文本猜测 trigger。
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any, Mapping


BENCHMARK_ROOT = Path(__file__).resolve().parents[1]
if str(BENCHMARK_ROOT) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_ROOT))

from rules.compiler_io import (  # noqa: E402
    GateError,
    atomic_write_jsonl,
    benchmark_root,
    load_config,
    load_jsonl,
    require_protocol_parameters_frozen,
    require_success_marker,
    resolve_config_path,
    schema_validator,
    sha256_file,
    validate_rows,
    write_success_marker,
)
from rules.state_machine import (  # noqa: E402
    ACTIVE_REMINDED,
    CANCELLED,
    COMPLETED,
    EXPIRED,
    DeterministicOracle,
    StateMachineError,
    parse_virtual_time,
    trigger_matches,
)


POST_TERMINAL_DECISION_TYPES = {
    COMPLETED: "post_completion_lure",
    CANCELLED: "post_cancellation_lure",
    EXPIRED: "post_expiry_lure",
    ACTIVE_REMINDED: "already_reminded_lure",
}


def _tail(identifier: str, prefix: str) -> str:
    if not identifier.startswith(prefix):
        raise GateError(f"标识不符合 {prefix} 前缀：{identifier}")
    return identifier[len(prefix) :]


def _additional_artifact_matches(marker: Mapping[str, Any], name: str, path: Path) -> None:
    artifacts = marker.get("artifacts")
    if not isinstance(artifacts, Mapping) or not isinstance(artifacts.get(name), Mapping):
        raise GateError(f"LIFELOGS_SUCCESS 缺少 {name} 的受保护哈希")
    expected_hash = artifacts[name].get("sha256")
    # Life Log 主文件与 pair 文件必须来自同一次成功写入；只验证主哈希会允许把新的
    # logs 与旧 pairs 混用，进而破坏正负配对。
    if expected_hash != sha256_file(path):
        raise GateError(f"LIFELOGS_SUCCESS 中 {name} 的哈希不匹配")


def _trigger_event(seed: Mapping[str, Any], lifelog: Mapping[str, Any]) -> Mapping[str, Any]:
    matches = [event for event in lifelog["events"] if trigger_matches(seed, event)]
    declared = [event for event in lifelog["events"] if event.get("event_role") == "trigger"]
    if len(matches) != 1 or len(declared) != 1:
        # 一个 family 有零个或多个当前 trigger 都无法定义唯一锚点和 counterfactual gold。
        raise GateError(f"{lifelog['lifelog_id']} 必须恰有一个与冻结 atom 匹配的 trigger")
    return matches[0]


def _decision_type(event: Mapping[str, Any], result_state_before: str) -> str:
    if event["event_role"] == "trigger":
        return "trigger"
    if event["event_role"] == "lure":
        return POST_TERMINAL_DECISION_TYPES.get(result_state_before, "non_trigger_lure")
    return "ordinary_silence"


def _evidence_groups(
    *,
    decision_id: str,
    events: list[Mapping[str, Any]],
    current_index: int,
    event: Mapping[str, Any],
    state_before: str,
    state_after: str,
    action_kind: str,
) -> list[dict[str, Any]]:
    """构造最小可追溯证据；证据和模型当前输入保持分离。"""

    # 证据只截取当前事件及其之前的观察，绝不能把未来状态事件泄露给在线模型评测。
    prior = events[: current_index + 1]
    items: list[dict[str, str]] = []
    creation = next((item for item in prior if item["event_role"] == "intention_creation"), None)
    terminal = next(
        (
            item
            for item in reversed(prior)
            if item["event_role"]
            in {"intention_completed", "intention_cancelled", "intention_expired"}
        ),
        None,
    )
    reminder_history = next(
        (item for item in reversed(prior) if item["event_role"] == "reminder_history"),
        None,
    )
    if action_kind == "remind":
        if creation is None:
            raise GateError("remind 决策缺少目标 intention 的创建证据")
        items.append(
            {"event_id": creation["event_id"], "role": "intention_definition", "necessity": "essential"}
        )
    elif creation is not None:
        items.append(
            {"event_id": creation["event_id"], "role": "intention_definition", "necessity": "supporting"}
        )

    if terminal is not None and (state_before in {COMPLETED, CANCELLED, EXPIRED} or state_after in {COMPLETED, CANCELLED, EXPIRED}):
        items.append(
            {"event_id": terminal["event_id"], "role": "state_invalidation", "necessity": "essential"}
        )
    if reminder_history is not None and (state_before == ACTIVE_REMINDED or state_after == ACTIVE_REMINDED):
        items.append(
            {"event_id": reminder_history["event_id"], "role": "reminder_history", "necessity": "essential"}
        )

    if event["event_role"] == "trigger":
        items.append(
            {
                "event_id": event["event_id"],
                "role": "trigger_condition",
                "necessity": "essential" if action_kind == "remind" else "supporting",
            }
        )
    else:
        # 非 trigger 当前事件只作为排除性干扰证据，而不把构建期 event_role 放进模型输入。
        items.append(
            {"event_id": event["event_id"], "role": "distractor_exclusion", "necessity": "distractor"}
        )
    return [{"support_group_id": f"eg_{_tail(decision_id, 'dec_')}", "items": items}]


def compile_lifelog(
    seed: Mapping[str, Any], lifelog: Mapping[str, Any], counterfactual_pair_id: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """逐事件运行 oracle；这是 gold action 唯一产生点。"""

    # 先绑定 lineage，防止相同 split 的另一个 Seed 被误用于此 Life Log 的目标 intention。
    if lifelog["seed_id"] != seed["seed_id"] or lifelog["family_id"] != seed["family_id"]:
        raise GateError(f"Life Log 与 Seed 不匹配：{lifelog['lifelog_id']}")
    events = lifelog["events"]
    if lifelog["event_count"] != len(events):
        raise GateError(f"Life Log event_count 不匹配：{lifelog['lifelog_id']}")
    expected_positions = list(range(len(events)))
    if [event["event_position"] for event in events] != expected_positions:
        raise GateError(f"Life Log event_position 必须从零连续递增：{lifelog['lifelog_id']}")
    times = [parse_virtual_time(event["virtual_time"]) for event in events]
    if times != sorted(times):
        # 状态机只允许单向接收在线事件；时间倒退会使已经完成/取消的状态重新可见。
        raise GateError(f"Life Log virtual_time 不可倒退：{lifelog['lifelog_id']}")
    trigger = _trigger_event(seed, lifelog)
    oracle = DeterministicOracle(seed, trigger["virtual_time"])
    decisions: list[dict[str, Any]] = []
    evidence_sets: list[dict[str, Any]] = []
    log_tail = _tail(lifelog["lifelog_id"], "log_")
    for event in events:
        try:
            result = oracle.process(event)
        except StateMachineError as exc:
            # 将不能被冻结规则解释的状态转移提升为门禁错误，避免生成貌似合法但无来源的 gold。
            raise GateError(f"{lifelog['lifelog_id']} 无法通过状态机：{exc}") from exc
        decision_id = f"dec_{log_tail}_{event['event_position'] + 1:03d}"
        groups = _evidence_groups(
            decision_id=decision_id,
            events=events,
            current_index=event["event_position"],
            event=event,
            state_before=result.state_before,
            state_after=result.state_after,
            action_kind=result.action_kind,
        )
        decision = {
            "decision_id": decision_id,
            "lifelog_id": lifelog["lifelog_id"],
            "family_id": lifelog["family_id"],
            "split": lifelog["split"],
            "target_intention_id": seed["intention"]["intention_id"],
            "decision_type": _decision_type(event, result.state_before),
            "counterfactual_pair_id": counterfactual_pair_id,
            "difficulty": lifelog["difficulty"],
            "model_input": {
                # 仅写入协议允许的当前观察字段；状态、rule_id、event_role 与 gold 都留在
                # 审计字段中，避免答案泄漏到被评模型。
                "stream_position": event["event_position"],
                "current_event_id": event["event_id"],
                "virtual_time": event["virtual_time"],
                "visible_text": event["visible_text"],
            },
            "valid_window": {
                "start_virtual_time": result.window_start,
                "end_virtual_time": result.window_end,
            },
            "gold_action": {
                "kind": result.action_kind,
                "intention_ids": [seed["intention"]["intention_id"]] if result.action_kind == "remind" else [],
            },
            "oracle_annotation": {
                "state_before": result.state_before,
                "state_after": result.state_after,
                "rule_id": result.rule_id,
            },
            "evidence_support_groups": groups,
        }
        decisions.append(decision)
        evidence_sets.append(
            {
                "evidence_set_id": f"evidence_{_tail(decision_id, 'dec_')}",
                "decision_id": decision_id,
                "lifelog_id": lifelog["lifelog_id"],
                "family_id": lifelog["family_id"],
                "counterfactual_pair_id": counterfactual_pair_id,
                "support_groups": groups,
            }
        )
    return decisions, evidence_sets


def _pair_index(pairs: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    index: dict[str, Mapping[str, Any]] = {}
    for pair in pairs:
        pair_id = pair.get("counterfactual_pair_id")
        if not isinstance(pair_id, str) or pair_id in index:
            raise GateError("counterfactual_pair_id 缺失或重复")
        required = {"positive_lifelog_id", "negative_lifelog_id", "difficulty", "seed_id", "family_id"}
        if not required.issubset(pair):
            raise GateError(f"counterfactual pair 缺少字段：{pair_id}")
        index[pair_id] = pair
    return index


def _validate_counterfactual_gold(
    *,
    pairs: Mapping[str, Mapping[str, Any]],
    lifelog_by_id: Mapping[str, Mapping[str, Any]],
    decisions: list[Mapping[str, Any]],
) -> None:
    decisions_by_log: dict[str, list[Mapping[str, Any]]] = {}
    for decision in decisions:
        decisions_by_log.setdefault(str(decision["lifelog_id"]), []).append(decision)
    for pair_id, pair in pairs.items():
        positive_id = str(pair["positive_lifelog_id"])
        negative_id = str(pair["negative_lifelog_id"])
        if positive_id not in lifelog_by_id or negative_id not in lifelog_by_id:
            raise GateError(f"counterfactual pair 指向缺失 Life Log：{pair_id}")
        positive_trigger = [item for item in decisions_by_log.get(positive_id, []) if item["decision_type"] == "trigger"]
        negative_trigger = [item for item in decisions_by_log.get(negative_id, []) if item["decision_type"] == "trigger"]
        if len(positive_trigger) != 1 or len(negative_trigger) != 1:
            raise GateError(f"counterfactual pair 必须各有一个 trigger 决策：{pair_id}")
        if positive_trigger[0]["gold_action"]["kind"] != "remind":
            # 反事实的正支若不提醒，说明 family 或状态机已经失去题目要求的动作基线。
            raise GateError(f"正分支 trigger 必须为 remind：{pair_id}")
        if negative_trigger[0]["gold_action"]["kind"] != "silent":
            raise GateError(f"负分支 trigger 必须为 silent：{pair_id}")
        positive_event = positive_trigger[0]["model_input"]["current_event_id"]
        negative_event = negative_trigger[0]["model_input"]["current_event_id"]
        positive_log = lifelog_by_id[positive_id]
        negative_log = lifelog_by_id[negative_id]
        pos_atom = next(item["atom_id"] for item in positive_log["events"] if item["event_id"] == positive_event)
        neg_atom = next(item["atom_id"] for item in negative_log["events"] if item["event_id"] == negative_event)
        if pos_atom != neg_atom or pos_atom != pair.get("trigger_atom_id"):
            # gold 翻转只能归因于历史状态，绝不能通过替换当前观察或 trigger atom 实现。
            raise GateError(f"反事实 pair 未共享同一当前 trigger atom：{pair_id}")


def run(config_path: Path) -> dict[str, Any]:
    protocol = load_config(config_path)
    paths_path = config_path.with_name("paths.yaml")
    paths = load_config(paths_path)
    root = benchmark_root(paths_path, paths)
    artifacts = paths["artifacts"]
    markers = paths["success_markers"]
    frozen_path = resolve_config_path(paths_path, artifacts["frozen_seeds"])
    lifelogs_path = resolve_config_path(paths_path, artifacts["lifelogs"])
    pairs_path = resolve_config_path(paths_path, artifacts["counterfactual_pairs"])
    frozen_marker_path = resolve_config_path(paths_path, markers["frozen_seeds"])
    lifelog_marker_path = resolve_config_path(paths_path, markers["lifelogs"])
    decisions_path = resolve_config_path(paths_path, artifacts["decision_instances"])
    evidence_path = resolve_config_path(paths_path, artifacts["evidence_sets"])
    marker_path = resolve_config_path(paths_path, markers["decisions"])
    schema_dir = resolve_config_path(paths_path, paths["schema_dir"])

    # 两类上游 SUCCESS 都在读取内容前重新验哈希；这样中断、替换或跨批次混用会被阻断。
    frozen_marker = require_success_marker(frozen_marker_path, frozen_path)
    lifelog_marker = require_success_marker(lifelog_marker_path, lifelogs_path)
    _additional_artifact_matches(lifelog_marker, "counterfactual_pairs", pairs_path)
    require_protocol_parameters_frozen(protocol)
    seed_validator = schema_validator(schema_dir / "reminder_seed.schema.json")
    lifelog_validator = schema_validator(schema_dir / "lifelog.schema.json")
    decision_validator = schema_validator(schema_dir / "decision_instance.schema.json")
    seeds = load_jsonl(frozen_path)
    lifelogs = load_jsonl(lifelogs_path)
    pairs = load_jsonl(pairs_path)
    validate_rows(seeds, seed_validator, "冻结 Seed")
    validate_rows(lifelogs, lifelog_validator, "Life Log")
    seed_by_id = {seed["seed_id"]: seed for seed in seeds}
    if len(seed_by_id) != len(seeds):
        raise GateError("冻结 Seed 的 seed_id 不可重复")
    lifelog_by_id = {log["lifelog_id"]: log for log in lifelogs}
    if len(lifelog_by_id) != len(lifelogs):
        raise GateError("lifelog_id 不可重复")
    pair_by_id = _pair_index(pairs)

    pair_for_log: dict[str, str] = {}
    for pair_id, pair in pair_by_id.items():
        for log_id in (pair["positive_lifelog_id"], pair["negative_lifelog_id"]):
            if log_id in pair_for_log:
                raise GateError(f"Life Log 不可归属多个 counterfactual pair：{log_id}")
            pair_for_log[log_id] = pair_id
    if set(pair_for_log) != set(lifelog_by_id):
        # 没有唯一 pair 的日志不能证明正负 gold 翻转，因此不能单独进入 benchmark。
        raise GateError("每条 Life Log 必须且只能属于一个 counterfactual pair")

    decisions: list[dict[str, Any]] = []
    evidence_sets: list[dict[str, Any]] = []
    for lifelog in lifelogs:
        seed = seed_by_id.get(lifelog["seed_id"])
        if seed is None:
            raise GateError(f"Life Log 引用不存在的 Seed：{lifelog['seed_id']}")
        compiled, evidence = compile_lifelog(seed, lifelog, pair_for_log[lifelog["lifelog_id"]])
        decisions.extend(compiled)
        evidence_sets.extend(evidence)
    validate_rows(decisions, decision_validator, "Decision instance")
    _validate_counterfactual_gold(
        pairs=pair_by_id, lifelog_by_id=lifelog_by_id, decisions=decisions
    )

    # decisions 和 evidence 均在全量 Schema/配对检查后原子写入；SUCCESS 最后发布其哈希。
    decision_count = atomic_write_jsonl(decisions_path, decisions)
    atomic_write_jsonl(evidence_path, evidence_sets)
    return write_success_marker(
        marker_path=marker_path,
        artifact_path=decisions_path,
        row_count=decision_count,
        contract_version=protocol["contract_version"],
        config_version=protocol["config_version"],
        schema_versions={"decision_instance": "v1.0.0", "lifelog": "v1.0.0"},
        upstream_hashes={
            "frozen_seeds": frozen_marker["sha256"],
            "lifelogs": lifelog_marker["sha256"],
        },
        root=root,
        additional_artifacts={"evidence_sets": evidence_path},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="运行确定性 oracle 并写入 benchmark gold")
    parser.add_argument(
        "--config",
        type=Path,
        default=BENCHMARK_ROOT / "config" / "benchmark_protocol.yaml",
        help="冻结的 benchmark_protocol.yaml 路径",
    )
    args = parser.parse_args()
    try:
        marker = run(args.config.resolve())
    except GateError as exc:
        parser.error(str(exc))
    print(f"已生成 {marker['row_count']} 条 Decision Instance；SHA256={marker['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
