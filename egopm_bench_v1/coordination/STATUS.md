# EgoPM-Bench v1 状态板

当前治理合同冻结版本：**v1.1.0**（2026-08-31）。配置合同与 Source Atom Schema 为 `v1.1.0`；其余数据 Schema 保持 `v1.0.0`。

`DONE` 表示 T0 已审阅产物并确认通过必需验证。状态只能是 `TODO`、`IN_PROGRESS`、`BLOCKED` 或 `DONE`。

| 门禁 | 负责人 | 状态 | 冻结产物/哈希 | 阻断项 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| 治理合同 v1.1 | T0 | DONE | v1.1.0；CR-2026-001；`c719a03` | 无 | 允许 Wave 1 的 fixture-only 开发，并执行 Python 中文注释门禁 |
| Source atoms | T1 | DONE | `SOURCE_ATOMS_SUCCESS.json`；`source_video_atoms.jsonl` SHA256 `be5f36b77970cb5147b88551c566f081589fe00fcf5ef912d8468a037e92960e`；370799 行 | 无 | Source 哈希已冻结，禁止重写；供 T4/T2 按 SUCCESS 门只读 |
| Source QA | T4 | DONE | 审计 `7ea18b8`；Source 阻断 0；答案/split 泄漏均为 0 | 无 | T2 可启动第 05 步正式 Cue library；T0 审阅其 SUCCESS 后启动 Cue QA |
| Cue library | T2 | BLOCKED | 已冻结 Source SHA256 `be5f36b77970cb5147b88551c566f081589fe00fcf5ef912d8468a037e92960e`；无 API 预检为 370799 Atom、742 个 shard | 等待用户确认预算、执行范围和分批方案 | 确认后方可显式 `--execute`；完成全部 shard 后才可合并并写入 `CUE_LIBRARY_SUCCESS.json` |
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
- `CR-2026-002`、`CR-2026-003` 与 `CR-2026-004` 已由 T0 批准并落实为配置合同与 Source Atom Schema `v1.1.0`：对齐容差固定为 `2.0` 秒，v1 禁止合并窗口，草稿与最终原子使用独立工件/Schema，跨 session 去重比较同一人同一天的全部 session 对。`CR-2026-005` 仍阻断正式 trigger/lure 与 Seed candidates；`CR-2026-006` 仍阻断最终反事实与 Evidence Set 的完整可审计发布。
- 本次合同升级后以 synthetic fixture 执行 `python -m pytest -q --basetemp .pytest_cache/contract-v11`，结果为 `27 passed in 0.81s`；`git diff --check` 通过。未运行正式 01–04，未调用千问，未生成 Life Log。
- T1 已在主项目 `main` 正式运行 01–04，仅读取 808 个 EgoLife SRT（Transcript 402、Dense Caption 406），未读取、下载、复制、拼接或处理 MP4。正式 Source 产物提交为 `ada03ec`；近重复精确索引修复为 `f730cdf`。最终原子为 370799 行，冻结 SHA256 为 `be5f36b77970cb5147b88551c566f081589fe00fcf5ef912d8468a037e92960e`。
- T4 已以 `4c81eec` 将 Source QA 对齐 v1.1 的 Dense Caption 主时间窗口与全 session 精确近重复规则，并在 `7ea18b8` 写入新的只读审计。T0 已独立复算 SUCCESS 原子哈希与行数，结果一致；Source blocker 为 0，`answer_leakage_count` 与 `split_leakage_count` 均为 0。审计中的 5 个 blocker 都仅表示 Cue、candidate、frozen、lifelog、decisions 尚未生成，不归责 Source。
- T0 已审阅并合并第 05 步无 API 启动修复：T4 的阶段化 Schema 版本校验为 `d2a1c67`；T2 的项目根相对路径、确定性 shard、无正文账本与显式执行守卫为 `310195f`，账本 SHA 恢复门为 `9d44f46`，RPM/TPM 无突发限流为 `a437c02`。文件均在各自所有权范围内；无 API 回归共 `39 passed`，未调用千问、未读取密钥、未写 Cue library 或 SUCCESS。
- Cue 执行配置已冻结：每 shard `500` Atom，`max_tokens=512`，最多重试 `2` 次，目标为 `300 RPM` 与 `1000000 TPM`，并且仅记录服务端 `response_usage`；禁止保存原始模型响应。`2026-09-01` 无 API 预检实际读取已冻结的 370799 Atom，得到 `742` 个 shard（末 shard `299`），序列化输入字节上界 `1779240532`、输出 token 上界 `189849088`、总上界 `1969089620`，估计最短时长 `1969.08962` 分钟。按冻结的北京 `<=32K` 价格快照，基准单次尝试费用上界为 `¥507.7273768`，每条均耗尽两次重试的保守上界为 `¥1523.1821304`。Cue 门保持 `BLOCKED`，直至用户明确确认预算、执行范围与分批方案。
