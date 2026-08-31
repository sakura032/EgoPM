# EgoPM-Bench v1 状态板

当前治理合同冻结版本：**v1.1.0**（2026-08-31）。数据 Schema 与配置合同保持 `v1.0.0`。

`DONE` 表示 T0 已审阅产物并确认通过必需验证。状态只能是 `TODO`、`IN_PROGRESS`、`BLOCKED` 或 `DONE`。

| 门禁 | 负责人 | 状态 | 冻结产物/哈希 | 阻断项 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| 治理合同 v1.1 | T0 | DONE | v1.1.0；CR-2026-001；`c719a03` | 无 | 允许 Wave 1 的 fixture-only 开发，并执行 Python 中文注释门禁 |
| Source atoms | T1 | BLOCKED | Wave 1 代码已合并；无正式产物 | `CR-2026-002`–`CR-2026-004` 尚未决定，无法冻结 Source 参数与语义 | T0 决定请求并发布相应数据合同后，才可运行 01–04 |
| Source QA | T4 | BLOCKED | Wave 1 验证器已合并；无正式产物 | `SOURCE_ATOMS_SUCCESS` 哈希不存在 | T1 正式产物就绪后由 T4 执行 Source QA，T0 审阅后才可 DONE |
| Cue library | T2 | BLOCKED | Wave 1 客户端与合同测试已合并；无正式产物 | `SOURCE_ATOMS_SUCCESS` 哈希 + Source QA DONE | 仅在 Source 门完成后运行第 05 步 |
| Seed candidates | T2 | BLOCKED | Wave 1 客户端与合同测试已合并；无正式产物 | `CUE_LIBRARY_SUCCESS` 哈希 + Cue QA + `CR-2026-005` 决定 | 禁止正式生成 |
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
- Wave 1 已按 `T1 → T4 → T2 → T3` 审阅并合并到 `main`：T1 为 `4d3b5b6`，T4 为 `174fa32`，T2 为 `7d99aaf`，T3 为 `abc0424`。所有改动均在各自文件所有权范围内；未合并 `.codex/`、原始语料、媒体或正式数据产物。
- Wave 1 合并后以仓库内已忽略的 pytest 临时目录执行 `python -m pytest -q --basetemp .pytest_cache/wave1`，结果为 `25 passed in 0.82s`；`git diff --check` 通过。测试仅使用 synthetic fixture，未运行正式 SRT 建库、未调用千问、未生成 Life Log。
- 已登记待决请求 `CR-2026-002` 至 `CR-2026-006`。其中 `CR-2026-002`、`CR-2026-003` 与 `CR-2026-004` 直接阻断正式 Source Atom 建库；`CR-2026-005` 阻断正式 trigger/lure 与 Seed candidates；`CR-2026-006` 阻断最终反事实与 Evidence Set 的完整可审计发布。
