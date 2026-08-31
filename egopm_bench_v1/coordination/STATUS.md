# EgoPM-Bench v1 状态板

当前治理合同冻结版本：**v1.1.0**（2026-08-31）。数据 Schema 与配置合同保持 `v1.0.0`。

`DONE` 表示 T0 已审阅产物并确认通过必需验证。状态只能是 `TODO`、`IN_PROGRESS`、`BLOCKED` 或 `DONE`。

| 门禁 | 负责人 | 状态 | 冻结产物/哈希 | 阻断项 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| 治理合同 v1.1 | T0 | DONE | v1.1.0；CR-2026-001；`c719a03` | 无 | 允许 Wave 1 的 fixture-only 开发，并执行 Python 中文注释门禁 |
| Source atoms | T1 | TODO | — | 代码开发无阻断；正式输出前须经 T4 source QA | 实现并单测 01–04 |
| Source QA | T4 | BLOCKED | — | `SOURCE_ATOMS_SUCCESS` 哈希 | 以 synthetic fixture 实现验证器 |
| Cue library | T2 | BLOCKED | — | `SOURCE_ATOMS_SUCCESS` 哈希 + Source QA DONE | 仅实现客户端与合同 |
| Seed candidates | T2 | BLOCKED | — | `CUE_LIBRARY_SUCCESS` 哈希 + Cue QA | 禁止正式生成 |
| Seed audit | T0/T4 | BLOCKED | — | candidate 标记 + 人工审计 | 审核候选 |
| Frozen seeds | T3 | BLOCKED | — | 审计冻结 + T4 seed QA | 仅以 fixture 开发编译器 |
| Protocol parameters v1 | T0 | BLOCKED | — | 研究协议要求先有完整 source/seed 统计 | 冻结预算、冷却与重复提醒策略 |
| Families/oracle | T3 | BLOCKED | — | `SEEDS_FROZEN_SUCCESS` 哈希 + seed QA + 协议参数 | 编译六路 family 与 oracle gold |
| Final QA | T4 | BLOCKED | — | `DECISIONS_SUCCESS` 哈希 | 验证全部正式产物 |
| Release | T0 | BLOCKED | — | `FINAL_VALIDATION_SUCCESS` 哈希 | 审阅并发布 manifest |

## T0 审阅记录

- Wave 0 合同冻结提交为 `487fa9a`。`raw/` 中有 808 个 SRT 文件并已被忽略；没有源媒体或源数据加入 Git。
- 本合同冻结数据形状、路径语义、文件所有权、SUCCESS 标记语义、来源 split 策略、模型登记表和评测协议结构。
- 数值型记忆预算与重复提醒参数刻意保持待定。这符合研究规范，并阻断所有正式 oracle 输出。
- 全部 Markdown 正文必须中文撰写；字段名、命令、路径和不可翻译专名除外。T0 将以此作为合并硬门禁。
- CR-2026-001 已将 Python 中文模块说明与关键中文注释提升为治理合同 v1.1.0 的合并硬门禁；数据 Schema 与配置合同未变，故不要求重生成数据。
