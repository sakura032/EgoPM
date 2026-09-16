# EgoPM-Bench v1 事实边界（FACT_RULES）

本文件是 Source Atom → Cue → Seed → Life Log → Decision/Evidence 全流程中，**事实正确性的唯一权威**。

总原则：任何人物、地点、物体、活动、状态与显式时间的事实性陈述，都必须能回查到同一个 Source Atom 的明确原文字段与连续证据 span。仅有 JSON / Schema 正确、或 span 字符串存在，不足以证明维度、关系、角色、否定、范围与时间语义正确。

## 十条规则

1. **Cue 只能来自同一个 Atom 的 `transcript` 或 `dense_caption`。**
   不得跨 Atom 拼接证据；`visible_text` 不得作为证据字段。

2. **evidence span 必须是连续原文。**
   最多只允许确定性的 Unicode 与空白规范化；不得改写、省略、重排或拼接。

3. **BGE 查询族不等于 Cue dimension。**
   六族（Person / Location / Object / Activity / State / Explicit-Time）只表示召回来源，不自动决定 Cue 的 dimension。

4. **人物「被提及」「说话」「实际在场」必须区分。**
   第一人称「我」只在 Atom participant 能确定 wearer 时可解析。

5. **不跨 Atom 消解代词。**
   单独的「他」「那里」「这个」「东西」「正在做」「发生变化」等，若无法在同一证据 span 与 Atom 元数据内唯一解析，必须 `no_cue`。物体不得反推地点；地点词出现不得自动证明进入或在场。

6. **否定、假设、将来、不确定的话语不能改写成已发生的事实。**
   视频或 session 时间戳也不得被写作显式事件时间，或直接当作未来提醒条件。

7. **一个 Atom 最多一条 Cue；一个 predicate 使用最少且充分的 1–3 个 clause。**
   只允许 `all_of`；不得为丰富度堆叠无关事实，也不得把同一事实拆成重复 clause。两到三个 clause 只用于同一 Atom 内必要的主体、对象、活动、地点或状态消歧。

8. **无法确认时输出 `no_cue`，不能猜。**
   不得以「合理推测」补足证据不足的事实。

9. **constructed 内容只能从 Seed / Life Log 开始。**
   构造内容必须显式标记，不得伪装成视频中发生的观察，也不得引入未经证明的现实人物、地点、物体、事件或关系。下游不得把 constructed 文本重新当作 Source 事实。

10. **最终 gold 由确定性状态机产生，禁止大模型写。**

## 每个 clause 的三层判断

每个 clause 由 `dimension`、`operator`、`value`、`anchor` 与自己的 `evidence.field` / `evidence.span` 构成，并依次通过三层：

- **第一层（程序可完全解决）**：span 是同一 `transcript` 或 `dense_caption` 字段中的连续原文；`evidence.field` 合法；clause 数量为 1–3；`dimension` / `operator` 合法；禁止空值与明显未解析的代词。
- **第二层（程序可大部分解决）**：`value` 能由该 span 直接支持，最多只允许确定性的 Unicode 与空白规范化；否定与时间语气没有被反转。
- **第三层（程序无法完全解决）**：「dimension + operator + value」整体被 span 的语义支持，并正确处理人物角色、主客体、否定、量词与范围、条件/假设、时态与时间语气。

任一层失败均不得进入正式 Cue。第三层的落法是 **prompt 严格约束 + 对 pilot 与正式结果做分层人工抽查 + 争议项直接 `no_cue`**，不再另建多模型审计流水线。

## `anchor` 与 `no_cue`

- 每个 clause 必须有可识别的指向对象或状态承载者，记在 `anchor` 里。
- Cue 是可判断的观察条件，不要求完整主谓宾（例如「手机出现」「厨房」「Jake 正在说话」都可以），但不能没有承载者。
- 无法确认时一律 `no_cue`，并给出 reason；不要为了产出更多 Cue 而放宽任何一条。
