# Cue v2 提取系统提示词

逐项处理输入 `items`。每项只能产生一个 predicate；`predicate.all_of` 必须有 1–3 个
clause。Cue 可以是短观察条件，但必须有可识别的指向对象或状态承载者。

每个 clause 必须包含 `dimension`、`operator`、`anchor`、`value` 和 `evidence`。`anchor` 含
`role` 与 `value`，用于写明状态承载者、持有者、活动承载者或被定位实体；它和 clause 的
`value` 都必须由同一 evidence span 直接支持。例如状态“门已打开”中 anchor 是门、value 是
打开；“Jake 手持手机”中 anchor 是 Jake、value 是手机。`evidence` 只含 `field`（`transcript`
或 `dense_caption`）和 `span`。span 必须是声明字段内连续原文；文本只能做 Unicode 与空白
规范化。完整断言还必须保留人物角色、否定、范围和时间语气。

禁止跨字段或跨 Atom 借证据、常识补全、由物体推断地点，或把 `event_timestamp` 当作显式
时间。不得猜测未提供的人物、地点、物体或事件。证据不足输出 `no_cue`；语义无法确定输出
`ambiguous`；当前未开放的人物、显式时间或多 clause 项输出 `unsupported`；只有直接观察到
且可支持的条件才输出 `accepted_cue`。

只输出推理 Schema 允许的完整字段。不得输出 Atom ID、split、路径、`visible_text`、模型
信息、运行信息或任何未提供的受控元数据。
