"""EgoPM-Bench v1 的确定性单意图状态机。

职责：接收已冻结 Seed、trigger 锚点和按时间排序的 Life Log 事件，执行唯一的
生命周期转移与 remind/silent 判定。输入只包含合同字段，不读取模型输出，也不调用
网络服务；输出为带有前后状态、规则标识及有效窗口的 ``DecisionResult``。它位于
第八阶段 ``10_run_oracle.py`` 的核心，后者才负责把结果序列化为 benchmark 产物。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from typing import Any, Mapping


ACTIVE_UNREMINDED = "active_unreminded"
ACTIVE_REMINDED = "active_reminded"
COMPLETED = "completed"
CANCELLED = "cancelled"
EXPIRED = "expired"
NEVER_CREATED = "never_created"

TERMINAL_STATES = frozenset({COMPLETED, CANCELLED, EXPIRED})
LIFELOG_STATES = frozenset(
    {ACTIVE_UNREMINDED, ACTIVE_REMINDED, COMPLETED, CANCELLED, EXPIRED}
)
VIRTUAL_TIME_RE = re.compile(r"^D(?P<day>[0-9]{2}) (?P<hour>[0-2][0-9]):(?P<minute>[0-5][0-9])(?::(?P<second>[0-5][0-9]))?$")


class StateMachineError(ValueError):
    """当 Life Log 无法由冻结规则确定性解释时抛出。"""


def primary_rule_id(seed: Mapping[str, Any]) -> str:
    # 规则银行允许保留多个关联 rule_id，但 oracle 必须有唯一稳定的主规则，
    # 否则同一事件可能因遍历顺序不同得到不同 gold。
    rule_ids = seed.get("rule_ids")
    if not isinstance(rule_ids, list) or not rule_ids or not isinstance(rule_ids[0], str):
        raise StateMachineError("Seed 缺少可用的首要 rule_id")
    return rule_ids[0]


def parse_virtual_time(value: str) -> datetime:
    match = VIRTUAL_TIME_RE.fullmatch(value)
    if match is None:
        raise StateMachineError(f"非法 virtual_time：{value!r}")
    parts = {name: int(item or 0) for name, item in match.groupdict().items()}
    if not 0 <= parts["hour"] <= 23:
        raise StateMachineError(f"非法小时：{value!r}")
    # 使用固定虚拟基准年而不是机器当前日期，确保跨机器、跨运行的时间对齐和窗口
    # 比较完全一致；Dxx 只表示 Life Log 内的相对日序号，不声称真实日历日期。
    return datetime(2000, 1, 1) + timedelta(
        days=parts["day"] - 1,
        hours=parts["hour"],
        minutes=parts["minute"],
        seconds=parts["second"],
    )


def format_virtual_time(value: datetime) -> str:
    base = datetime(2000, 1, 1)
    delta = value - base
    if delta.days < 0 or delta.days > 99:
        raise StateMachineError("virtual_time 超出 D00–D99 的可表示范围")
    seconds = delta.seconds
    hour, seconds = divmod(seconds, 3600)
    minute, second = divmod(seconds, 60)
    return f"D{delta.days + 1:02d} {hour:02d}:{minute:02d}:{second:02d}"


def state_to_lifelog(state: str) -> str | None:
    return None if state == NEVER_CREATED else state


def trigger_matches(seed: Mapping[str, Any], event: Mapping[str, Any]) -> bool:
    """只依据冻结的 atom 标识与审计角色判断 trigger，绝不解释自由文本。"""

    # 不能通过 visible_text 或 predicate 自由解释来判断触发，因为那会把生成模型或
    # 文本启发式带入 gold。冻结 atom_id 加经审计的 event_role 才是可复算证据。
    return (
        event.get("event_role") == "trigger"
        and event.get("event_kind") == "source_video_atom"
        and event.get("atom_id") == seed.get("trigger_atom_id")
    )


def trigger_window(seed: Mapping[str, Any], anchor_virtual_time: str) -> tuple[datetime, datetime]:
    window = seed.get("valid_window")
    if not isinstance(window, Mapping) or window.get("relative_to") != "trigger_event":
        raise StateMachineError("Seed 的 valid_window 必须相对 trigger_event 定义")
    try:
        start = float(window["start_offset_sec"])
        end = float(window["end_offset_sec"])
    except (KeyError, TypeError, ValueError) as exc:
        raise StateMachineError("Seed 的 valid_window 偏移不合法") from exc
    if start < 0 or end < start:
        raise StateMachineError("Seed 的 valid_window 必须满足 0 <= start <= end")
    # 先解析锚点再加秒数，避免把分钟字符串直接拼接而造成跨小时、跨日窗口错误。
    anchor = parse_virtual_time(anchor_virtual_time)
    return anchor + timedelta(seconds=start), anchor + timedelta(seconds=end)


@dataclass(frozen=True)
class DecisionResult:
    """状态机对一个 event arrival 的可审计结果。"""

    state_before: str
    state_after: str
    action_kind: str
    rule_id: str
    window_start: str
    window_end: str


class DeterministicOracle:
    """按协议固定顺序处理事件：更新状态，然后在当前事件上决策。"""

    def __init__(self, seed: Mapping[str, Any], trigger_anchor_virtual_time: str) -> None:
        self.seed = seed
        self.rule_id = primary_rule_id(seed)
        self.state = NEVER_CREATED
        self.window_start, self.window_end = trigger_window(seed, trigger_anchor_virtual_time)

    def _transition_for_event(self, event: Mapping[str, Any]) -> None:
        role = event.get("event_role")
        # 只接受合同枚举的显式生命周期事件；不为未知事件猜测状态，才能使坏数据在
        # 生成 gold 前暴露，而不是被静默解释为一个看似合理的答案。
        if role == "intention_creation":
            if self.state != NEVER_CREATED:
                raise StateMachineError("同一 target intention 不可重复创建")
            self.state = ACTIVE_UNREMINDED
        elif role == "intention_completed":
            if self.state != ACTIVE_UNREMINDED:
                raise StateMachineError("只有 active_unreminded 的 intention 可以完成")
            self.state = COMPLETED
        elif role == "intention_cancelled":
            if self.state != ACTIVE_UNREMINDED:
                raise StateMachineError("只有 active_unreminded 的 intention 可以取消")
            self.state = CANCELLED
        elif role == "intention_expired":
            if self.state != ACTIVE_UNREMINDED:
                raise StateMachineError("只有 active_unreminded 的 intention 可以过期")
            self.state = EXPIRED
        elif role == "reminder_history":
            if self.state != ACTIVE_UNREMINDED:
                raise StateMachineError("提醒历史只能从 active_unreminded 转入")
            self.state = ACTIVE_REMINDED

    def process(self, event: Mapping[str, Any]) -> DecisionResult:
        """处理一个事件，并核对 Life Log 中的审计状态字段。"""

        before = self.state
        declared_before = event.get("intention_state_before")
        # Life Log 的状态字段仅是可审计声明，不能反向决定 oracle；先与内部状态核对
        # 可防止上游把期望的 gold 状态写进日志后仍被当作真相使用。
        if declared_before != state_to_lifelog(before):
            raise StateMachineError(
                f"事件 {event.get('event_id')} 的 state_before 与状态机不一致"
            )

        # 协议规定先更新持久状态、再对当前观察作答，因此取消、过期和既往提醒在
        # 同一事件到达时就已经能使动作保持 silent。
        self._transition_for_event(event)
        current_time = parse_virtual_time(str(event.get("virtual_time")))
        action_kind = "silent"
        if (
            trigger_matches(self.seed, event)
            and self.state == ACTIVE_UNREMINDED
            and self.window_start <= current_time <= self.window_end
        ):
            # 仅当冻结 trigger、未提醒的活动状态和有效窗口三个条件同时成立才提醒；
            # 任一条件失败维持默认 silent，以落实终态和窗口的硬门。
            action_kind = "remind"
            self.state = ACTIVE_REMINDED

        declared_after = event.get("intention_state_after")
        # 再次核对最终状态，尤其能捕获“触发后仍声称 active_unreminded”这类试图
        # 绕过提醒转移的日志错误。
        if declared_after != state_to_lifelog(self.state):
            raise StateMachineError(
                f"事件 {event.get('event_id')} 的 state_after 与状态机不一致"
            )

        return DecisionResult(
            state_before=before,
            state_after=self.state,
            action_kind=action_kind,
            rule_id=self.rule_id,
            window_start=format_virtual_time(self.window_start),
            window_end=format_virtual_time(self.window_end),
        )
