# Seed 与 Life Log 设计

本文件只记录设计意图。**当前不实现任何代码**：`scripts/seeds/`、`scripts/lifelogs/` 在真正开始时才建立，状态机在进入该阶段时按最终 Seed 与 Life Log 结构重写，并另写直接测试状态机的小测试（旧 `rules/state_machine.py` 与其测试已随旧治理合同删除）。

前置事实边界见 `FACT_RULES.md`；本文件不重复。

## Seed

- 每个 Seed 保存 `trigger_cue_id`，必须解析到某条 accepted Cue，并与 `trigger_atom_id`、`trigger_predicate` 建立可由程序验证的唯一血缘。
- `trigger_predicate` 必须与所引用 Cue 的 predicate 一致。若人工修改 predicate，必须改为引用另一条能精确支持它的 Cue，禁止仅靠模型解释补足血缘。
- 每个 Seed 至少有两个互不相同、且都不同于 trigger 的同 split lure：
  - 至少一个与 trigger 同 `source_group_id`，用于同上下文的困难干扰；
  - 至少一个来自不同 `source_group_id`，用于跨上下文的语义干扰。
- 每个 lure 必须明确记录**至少一个未满足的 predicate clause**。
- 同一个候选快照内，`trigger_cue_id`、`trigger_atom_id` 与所有 `lure_atom_id` 均不得跨 Seed 复用。被拒 Seed 释放的 Atom 只有在下一次新快照中才能重新分配。

## Life Log（六路结构）

- 同一个 Seed 的六条 Life Log 共享同一 trigger Atom/Cue 与同两条 lure。
- positive / negative 成对日志，在**相同的最终 trigger 观察**上只改变一条 constructed 生命周期控制事件，使 gold 在 `remind` / `silent` 之间翻转。不得替换 trigger、增删目标 Cue，或用不同事实输入制造答案差异。
- 每条日志固定包含：一条意图创建、一条生命周期控制、两条 lure、一条最终 trigger 观察；目标相关的 Source 观察数恒为 3。
- 同一难度采用固定的事件数与受控的 token 区间。

## 模型可见输入与隐藏标注

- **模型可见**：事件顺序、虚拟时间、原文观察或明确标记的 constructed 文本，以及必要的来源引用。
- **必须隐藏**：trigger / lure 的角色、predicate、状态前后值、反事实分支、gold、Evidence Set 与 oracle 理由。

## 状态机与 gold

- 输入：已冻结的 Seed、trigger 锚点、按时间排序的 Life Log 事件。不读取模型输出，不调用网络。
- 输出：带有前后状态、规则标识与有效窗口的决策结果，取值 `remind` / `silent`。
- 生命周期负分支只使用意图创建后的 `completed` / `cancelled` / `expired` / `already_reminded`。
- **gold 只能由该确定性状态机产生，禁止大模型写。**

## 待重新确认的数字

旧治理合同曾规定：Seed candidates 900–1,400 → 冻结 480 → 每条派生 6 条 Life Log ≈ 2,880 条。

这些数字随旧合同一并作废，**目前尚未重新确认**。进入 Seed 阶段前必须重新定稿，不要直接沿用旧数字，也不要为了让流程尽早放行而降低质量门。
