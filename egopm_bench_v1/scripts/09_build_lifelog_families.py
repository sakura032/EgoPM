"""由冻结 Seed 构造 positive/negative × short/medium/long 六路 Life Log。

职责：读取已经通过 SUCCESS/哈希门的冻结 Seed、source atom 和协议，派生每 Seed 六条
可追溯 Life Log、family spec 与反事实配对清单，并最后写入
``LIFELOGS_SUCCESS.json``。它位于正式 oracle 之前的第七阶段；所有构造事件仅表达
意图或生命周期，真实观察始终从 source atom 的文本与时间字段复制而来。
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timedelta
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
    validate_rows,
    write_success_marker,
)
from rules.state_machine import (  # noqa: E402
    ACTIVE_REMINDED,
    ACTIVE_UNREMINDED,
    CANCELLED,
    COMPLETED,
    EXPIRED,
    NEVER_CREATED,
    format_virtual_time,
    primary_rule_id,
    state_to_lifelog,
)


TERMINAL_ROLE_TO_STATE = {
    "completed": ("intention_completed", COMPLETED, "目标意图已完成。"),
    "cancelled": ("intention_cancelled", CANCELLED, "目标意图已取消。"),
    "expired": ("intention_expired", EXPIRED, "目标意图已过期。"),
    "already_reminded": ("reminder_history", ACTIVE_REMINDED, "此前已针对目标意图发送过提醒。"),
}


def _id_tail(value: str, prefix: str) -> str:
    if not value.startswith(prefix):
        raise GateError(f"标识不符合前缀 {prefix}：{value}")
    return value[len(prefix) :]


def _source_event(
    *,
    event_id: str,
    position: int,
    virtual_time: str,
    atom: Mapping[str, Any],
    role: str,
    state_before: str | None,
    state_after: str | None,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "event_position": position,
        "virtual_time": virtual_time,
        "source_time": {
            "local_start_sec": atom["local_start_sec"],
            "local_end_sec": atom["local_end_sec"],
            "normalized_start_sec": atom["normalized_start_sec"],
            "normalized_end_sec": atom["normalized_end_sec"],
        },
        "atom_id": atom["atom_id"],
        "event_kind": "source_video_atom",
        "visible_text": atom["visible_text"],
        "source_srt_paths": copy.deepcopy(atom["source_srt_paths"]),
        "source_video_path": atom["source_video_path"],
        "video_mapping_status": atom["video_mapping_status"],
        "rule_id": None,
        "intention_state_before": state_before,
        "intention_state_after": state_after,
        "event_role": role,
        "provenance": "egolife_srt",
    }


def _constructed_event(
    *,
    event_id: str,
    position: int,
    virtual_time: str,
    text: str,
    role: str,
    rule_id: str,
    state_before: str | None,
    state_after: str | None,
    kind: str = "constructed_observation",
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "event_position": position,
        "virtual_time": virtual_time,
        "source_time": None,
        "atom_id": None,
        "event_kind": kind,
        "visible_text": text,
        "source_srt_paths": None,
        "source_video_path": None,
        "video_mapping_status": "not_applicable",
        "rule_id": rule_id,
        "intention_state_before": state_before,
        "intention_state_after": state_after,
        "event_role": role,
        "provenance": "constructed_intention" if kind == "constructed_intention" else "constructed_observation",
    }


def _difficulty_values(protocol: Mapping[str, Any], difficulty: str) -> tuple[int, int, int]:
    try:
        spec = protocol["difficulties"][difficulty]
        event_count = int(spec["event_count"][0])
        background_intentions = int(spec["background_intentions"][0])
        span_minutes = int(spec["virtual_span_minutes"][0])
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise GateError(f"协议中缺少 {difficulty} 难度的完整范围") from exc
    if event_count < 4 or span_minutes <= 0 or background_intentions < 0:
        raise GateError(f"{difficulty} 难度参数不合法")
    # 取冻结范围的下界是确定性选择：同一协议和 Seed 在不同机器上必须产生同一长度，
    # 而不是在范围内随机采样造成 hash 和难度不可复现。
    return event_count, background_intentions, span_minutes


def _variant_plan(
    *,
    seed: Mapping[str, Any],
    branch: str,
    difficulty: str,
    protocol: Mapping[str, Any],
    atom_index: Mapping[str, Mapping[str, Any]],
) -> list[tuple[str, Any]]:
    """生成不含时间的事件计划；负分支只在一个历史位置替换状态条件。"""

    event_count, background_intentions, _ = _difficulty_values(protocol, difficulty)
    negative_type = seed["counterfactual_negative_type"]
    if branch not in {"positive", "negative"}:
        raise GateError(f"未知 counterfactual branch：{branch}")
    if branch == "positive":
        negative_type = "positive"
    lure_ids = list(seed["lure_atom_ids"])
    if len(lure_ids) < 2 or seed["trigger_atom_id"] in lure_ids:
        raise GateError(f"Seed 的 lure 不能少于两个或与 trigger 相同：{seed['seed_id']}")
    if any(atom_id not in atom_index for atom_id in lure_ids + [seed["trigger_atom_id"]]):
        raise GateError(f"Seed 引用了不存在的 source atom：{seed['seed_id']}")

    # 先用固定槽位规划事件，再填背景：正负分支因此保持同一触发、干扰项与事件数，
    # 只在一个历史槽位替换为 never_created 或终态条件。
    plans: list[tuple[str, Any] | None] = [None] * event_count
    rule_id = primary_rule_id(seed)
    if negative_type == "never_created":
        plans[0] = ("background", "一段与目标意图无关的日常观察。")
    else:
        plans[0] = ("intention_creation", f"请在满足条件时提醒我：{seed['intention']['action_content']}")
    lure_positions = [1, event_count // 2]
    # 两个已冻结 lure 分布在早期和中段，保证每条日志包含合同要求的最低干扰条件，
    # 同时不会与最后的当前 trigger 竞争位置。
    plans[lure_positions[0]] = ("lure", lure_ids[0])
    plans[lure_positions[1]] = ("lure", lure_ids[1])

    if negative_type in TERMINAL_ROLE_TO_STATE:
        # 负分支以单个显式状态历史取代同位置背景观察，从而是可审计的 gold 翻转原因。
        terminal_position = 2
        if terminal_position in lure_positions:
            terminal_position = 3
        plans[terminal_position] = ("terminal", negative_type)

    available = [index for index in range(1, event_count - 1) if plans[index] is None]
    if len(available) < background_intentions:
        raise GateError(f"{difficulty} 没有足够位置放置背景意图")
    for index in available[:background_intentions]:
        # 背景意图只使用无来源断言的构造文本，避免把未见于 SRT 的视觉事实伪装成 source。
        plans[index] = ("background_intention", "记录一项与目标无关的独立待办。")
    for index, plan in enumerate(plans[:-1]):
        if plan is None:
            plans[index] = ("background", "一段与目标意图无关的日常观察。")
    plans[-1] = ("trigger", seed["trigger_atom_id"])
    return [plan for plan in plans if plan is not None]


def build_family(
    seed: Mapping[str, Any],
    atom_index: Mapping[str, Mapping[str, Any]],
    protocol: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """为一个 Seed 派生恰好六条 Life Log 与三个匹配 counterfactual pair。"""

    seed_id = str(seed["seed_id"])
    family_id = str(seed["family_id"])
    seed_tail = _id_tail(seed_id, "seed_")
    family_tail = _id_tail(family_id, "family_")
    rule_id = primary_rule_id(seed)
    variants: list[dict[str, Any]] = []
    logs: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []

    for difficulty in ("short", "medium", "long"):
        event_count, _, span_minutes = _difficulty_values(protocol, difficulty)
        pair_id = f"cf_{family_tail}_{difficulty}"
        pair_members: dict[str, str] = {}
        for branch in ("positive", "negative"):
            plan = _variant_plan(
                seed=seed,
                branch=branch,
                difficulty=difficulty,
                protocol=protocol,
                atom_index=atom_index,
            )
            if len(plan) != event_count:
                raise GateError(f"{seed_id}/{branch}/{difficulty} 的事件数偏离协议")
            log_id = f"log_{seed_tail}_{branch}_{difficulty}"
            start = datetime(2000, 1, 1, 8, 0, 0)
            state = NEVER_CREATED
            events: list[dict[str, Any]] = []
            referenced_seconds = 0.0
            for position, (kind, payload) in enumerate(plan):
                # virtual_time 是按冻结跨度均匀放置的合成时间轴；source_time 在 source
                # 事件中仍逐字段保留原始值，二者不能混用为声称真实连续视频经历。
                offset_seconds = round(span_minutes * 60 * position / (event_count - 1))
                virtual_time = format_virtual_time(start + timedelta(seconds=offset_seconds))
                event_id = f"evt_{seed_tail}_{branch}_{difficulty}_{position + 1:03d}"
                before = state_to_lifelog(state)
                if kind == "intention_creation":
                    state = ACTIVE_UNREMINDED
                    event = _constructed_event(
                        event_id=event_id, position=position, virtual_time=virtual_time,
                        text=str(payload), role="intention_creation", rule_id=rule_id,
                        state_before=before, state_after=state_to_lifelog(state), kind="constructed_intention",
                    )
                elif kind == "terminal":
                    role, state, text = TERMINAL_ROLE_TO_STATE[str(payload)]
                    event = _constructed_event(
                        event_id=event_id, position=position, virtual_time=virtual_time,
                        text=text, role=role, rule_id=rule_id,
                        state_before=before, state_after=state_to_lifelog(state), kind="constructed_intention",
                    )
                elif kind == "trigger":
                    atom = atom_index[str(payload)]
                    if state == ACTIVE_UNREMINDED:
                        # 这里写入的是 Life Log 的审计后态；10 阶段会独立重算同一转移，
                        # 不把此字段当作 gold 输入。
                        state = ACTIVE_REMINDED
                    event = _source_event(
                        event_id=event_id, position=position, virtual_time=virtual_time,
                        atom=atom, role="trigger", state_before=before, state_after=state_to_lifelog(state),
                    )
                    referenced_seconds += float(atom["local_end_sec"]) - float(atom["local_start_sec"])
                elif kind == "lure":
                    atom = atom_index[str(payload)]
                    event = _source_event(
                        event_id=event_id, position=position, virtual_time=virtual_time,
                        atom=atom, role="lure", state_before=before, state_after=state_to_lifelog(state),
                    )
                    referenced_seconds += float(atom["local_end_sec"]) - float(atom["local_start_sec"])
                elif kind == "background_intention":
                    event = _constructed_event(
                        event_id=event_id, position=position, virtual_time=virtual_time,
                        text=str(payload), role="background", rule_id=rule_id,
                        state_before=before, state_after=state_to_lifelog(state), kind="constructed_intention",
                    )
                else:
                    event = _constructed_event(
                        event_id=event_id, position=position, virtual_time=virtual_time,
                        text=str(payload), role="background", rule_id=rule_id,
                        state_before=before, state_after=state_to_lifelog(state),
                    )
                events.append(event)

            logs.append(
                {
                    "lifelog_id": log_id,
                    "family_id": family_id,
                    "seed_id": seed_id,
                    "split": seed["split"],
                    "counterfactual_branch": branch,
                    "difficulty": difficulty,
                    "referenced_source_seconds": referenced_seconds,
                    "event_count": len(events),
                    "events": events,
                }
            )
            pair_members[branch] = log_id
            variants.append(
                {
                    "lifelog_id": log_id,
                    "counterfactual_branch": branch,
                    "difficulty": difficulty,
                    "counterfactual_pair_id": pair_id,
                    "event_count": len(events),
                    "virtual_span_minutes": span_minutes,
                }
            )
        pairs.append(
            {
                "counterfactual_pair_id": pair_id,
                "family_id": family_id,
                "seed_id": seed_id,
                "split": seed["split"],
                "difficulty": difficulty,
                "positive_lifelog_id": pair_members["positive"],
                "negative_lifelog_id": pair_members["negative"],
                "trigger_atom_id": seed["trigger_atom_id"],
                "negative_history_type": seed["counterfactual_negative_type"],
                "required_gold_flip": True,
            }
        )

    family_spec = {
        "family_id": family_id,
        "seed_id": seed_id,
        "split": seed["split"],
        "source_group_id": seed["source_group_id"],
        "intention_id": seed["intention"]["intention_id"],
        "trigger_atom_id": seed["trigger_atom_id"],
        "lure_atom_ids": list(seed["lure_atom_ids"]),
        "trigger_predicate": copy.deepcopy(seed["trigger_predicate"]),
        "counterfactual_negative_type": seed["counterfactual_negative_type"],
        "variants": variants,
    }
    return family_spec, logs, pairs


def _validate_seed_sources(
    seeds: list[Mapping[str, Any]], atom_index: Mapping[str, Mapping[str, Any]]
) -> None:
    for seed in seeds:
        for atom_id in [seed["trigger_atom_id"], *seed["lure_atom_ids"]]:
            atom = atom_index.get(atom_id)
            if atom is None:
                raise GateError(f"冻结 Seed 引用缺失的 source atom：{atom_id}")
            if atom.get("split") != seed.get("split"):
                # split 不一致会让一个 family 把训练/验证/测试来源混在一起，构成泄漏。
                raise GateError(f"Seed 与 source atom split 不一致：{seed['seed_id']} / {atom_id}")
            if (
                atom_id == seed["trigger_atom_id"]
                and atom.get("source_group_id") != seed.get("source_group_id")
            ):
                # source_group 只绑定核心 trigger；lure 的合同要求是同 split，不额外缩窄
                # 为同 group，以免拒绝本来合法的同 split 对照干扰项。
                raise GateError(f"Seed 与 trigger source_group 不一致：{seed['seed_id']} / {atom_id}")


def run(config_path: Path) -> dict[str, Any]:
    protocol = load_config(config_path)
    paths_path = config_path.with_name("paths.yaml")
    paths = load_config(paths_path)
    root = benchmark_root(paths_path, paths)
    artifacts = paths["artifacts"]
    markers = paths["success_markers"]
    frozen_path = resolve_config_path(paths_path, artifacts["frozen_seeds"])
    source_path = resolve_config_path(paths_path, artifacts["source_atoms"])
    frozen_marker_path = resolve_config_path(paths_path, markers["frozen_seeds"])
    source_marker_path = resolve_config_path(paths_path, markers["source_atoms"])
    family_specs_path = resolve_config_path(paths_path, artifacts["family_specs"])
    lifelogs_path = resolve_config_path(paths_path, artifacts["lifelogs"])
    pairs_path = resolve_config_path(paths_path, artifacts["counterfactual_pairs"])
    marker_path = resolve_config_path(paths_path, markers["lifelogs"])
    schema_dir = resolve_config_path(paths_path, paths["schema_dir"])

    # 不存在或哈希失配的冻结 Seed 绝不可被当作输入；它是六路 family 的可追溯根。
    frozen_marker = require_success_marker(frozen_marker_path, frozen_path)
    source_marker = require_success_marker(source_marker_path, source_path)
    # 数值协议仍待定时，任何正式难度或提醒语义都不可复现，故在写入前阻断。
    require_protocol_parameters_frozen(protocol)
    seed_validator = schema_validator(schema_dir / "reminder_seed.schema.json")
    atom_validator = schema_validator(schema_dir / "source_video_atom.schema.json")
    log_validator = schema_validator(schema_dir / "lifelog.schema.json")
    seeds = load_jsonl(frozen_path)
    atoms = load_jsonl(source_path)
    validate_rows(seeds, seed_validator, "冻结 Seed")
    validate_rows(atoms, atom_validator, "Source atom")
    if any(seed["audit"]["status"] != "accept" for seed in seeds):
        # 冻结文件即使哈希正确，也不能混入非 accept 条目绕过 08 阶段筛选。
        raise GateError("冻结 Seed 中存在未接受的审计状态")
    atom_index = {atom["atom_id"]: atom for atom in atoms}
    if len(atom_index) != len(atoms):
        raise GateError("source atom_id 不可重复")
    _validate_seed_sources(seeds, atom_index)

    family_specs: list[dict[str, Any]] = []
    lifelogs: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    for seed in seeds:
        family_spec, logs, family_pairs = build_family(seed, atom_index, protocol)
        family_specs.append(family_spec)
        lifelogs.extend(logs)
        pairs.extend(family_pairs)
    validate_rows(lifelogs, log_validator, "Life Log")
    if len(lifelogs) != len(seeds) * 6:
        # 这是 family 结构硬约束；少一条会破坏难度或反事实配对，不能发布部分 family。
        raise GateError("每个冻结 Seed 必须且只能派生六条 Life Log")

    # 先完成全量 Schema 和六路数量检查，再原子落盘所有伴生产物，并由 SUCCESS 最后发布。
    atomic_write_jsonl(family_specs_path, family_specs)
    lifelog_count = atomic_write_jsonl(lifelogs_path, lifelogs)
    atomic_write_jsonl(pairs_path, pairs)
    return write_success_marker(
        marker_path=marker_path,
        artifact_path=lifelogs_path,
        row_count=lifelog_count,
        contract_version=protocol["contract_version"],
        config_version=protocol["config_version"],
        schema_versions={"lifelog": "v1.0.0", "reminder_seed": "v1.0.0"},
        upstream_hashes={
            "frozen_seeds": frozen_marker["sha256"],
            "source_atoms": source_marker["sha256"],
        },
        root=root,
        additional_artifacts={"family_specs": family_specs_path, "counterfactual_pairs": pairs_path},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="从冻结 Seed 构造六路 Life Log family")
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
    print(f"已生成 {marker['row_count']} 条 Life Log；SHA256={marker['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
