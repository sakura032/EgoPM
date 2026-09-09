# T4：CR-2026-011 Cue v3 实时执行无 API QA 交接

> **2026-09-09 v1.3 接续说明**：旧 V9 的“0 blocker”仅表示旧合同下结构、哈希、证据片段和覆盖 QA 通过，不再代表 Cue 语义可供 Seed 使用。T4 必须为 Cue v2 新增 clause-level 语义门、三账号账本/租约一致性、模型同质性和 `audit/distributions/<stage>/<snapshot_id>/` 报告验证；旧 V9 文件保持只读审计。

## 交接元数据

- 分支：`main`。
- 提交：待 T0 审阅后填写。
- 治理合同版本：`v1.1.0`。
- 数据合同版本：Source Atom Schema 为 `v1.1.0`；最终 `cue_candidate` Schema 仍为 `v1.0.0`；实时 Cue 执行协议为 `v3.0.0`，协议哈希 payload 为 `v3.0.0`，模型 ID 为 `qwen3.7-flash`。
- 修改文件：`scripts/11_validate_all.py`、`tests/test_validators.py`、本交接文件。
- 只读输入：T0 冻结的 `model_registry.yaml`、最终 Cue Schema、紧凑推理 Schema，以及 pytest 临时目录中的合成 Source/Cue 标记与无正文实时状态。
- 正式输出：无。未读取或修改正式 Cue、Seed、Life Log、Decision、审计产物、已取消 Batch 结果或模型原始响应。

## 已完成的 QA 门

- 以 `execution.transport` 为唯一分支条件。实时协议只读取 `cues/realtime`；若配置不是 `realtime_chat_completions` 或运行根不是该固定目录，立即阻断。`cues/batch`、`batch_id`、`batch_task_index`、远端文件 ID 等取消 Batch 状态不能混入实时恢复。
- `CUE_LIBRARY_SUCCESS.json` 必须绑定 Source 哈希、完整 v3 协议哈希、实时 transport、分片清单 SHA256、运行状态 SHA256、运行账本 SHA256 与“原始响应禁止”声明；最终 Cue Schema 仍为 `v1.0.0`。
- 固定验证 `realtime_shards_manifest.jsonl`、`realtime_run_state.json`、`realtime_run_ledger.jsonl`。它们只能含包 ID、请求 SHA256、协议/Source 血缘、usage、重试、费用和终态等无正文元数据；请求、响应、错误、Atom 文本和 Batch 字段均被递归拒绝。
- 运行时 `progress.json` 必须是原子写入的无正文快照。最终审计检查其波次严格属于冻结的 `1 + 6×10 + 14` task 范围、最多 `10` 个在飞 package、终态计数守恒，并与同波 run-state 一致；任一跨波、超并发或正文键都会阻断。
- T2 的每波子目录与根级累计账本设计经过合成测试：Wave 2 从 Wave 1 的无正文 usage 恢复实际费用，`¥80` 是跨八波的唯一累计上限，不能按波重置；不同 run、Source、协议或授权预算的累计状态必须阻断恢复。
- 若运行根存在任一 `wave_XX` 子目录，最终 QA 自动切换到八波聚合门：必须同时存在 `wave_01` 至 `wave_08`、全部 `completed`，其 task 范围必须恰好覆盖 `0..74` 且不重叠；根级 `realtime_cumulative_ledger.jsonl` 必须按 `realtime_request_id` 与八个波次账本并集逐行一致。任一缺波、重复、遗漏或累计账本不一致均禁止 `CUE_LIBRARY_SUCCESS.json`。
- 每个 package 的 `realtime_state.json`、`*.ledger.jsonl`、`*.complete.json` 由固定路径定位。完成标记必须校验实际 `result`、ledger、state 的 SHA256，防止片段被替换后复用旧完成状态。
- ledger 只接受 T0 冻结的终态集。最终 `CUE_LIBRARY_SUCCESS` 仅接受每个 package 的唯一 `validated_success`；`local_validation_quarantine`、`budget_stopped` 或服务传输失败都不能自动重排、不能产生最终成功标记。
- run-state 中实际估算费用不得超过已授权预算；超过即由费用熔断阻断。usage 必须保持无正文且 `prompt_tokens + completion_tokens = total_tokens`。
- 独立合成测试覆盖：协议/限流/价格漂移、Source/协议错配、实时标记伪装为 Batch、包请求摘要错配、正文键泄露、本地隔离伪装为可重试、预算超额、跨八波累计预算、波次范围、十并发上限、进度计数及完成片段哈希篡改。

## Python 中文说明与关键注释验收

| 文件 | 中文模块说明 | 关键中文注释 | 结论 |
| --- | --- | --- | --- |
| `scripts/11_validate_all.py` | 说明第 11 阶段只读验证职责、输入输出和流水线位置 | 说明 transport 隔离、无正文边界、完成哈希、唯一终态与预算熔断的评测原因 | 通过 |
| `tests/test_validators.py` | 说明合成临时测试的职责、输入输出和位置 | 说明实时包映射、取消 Batch 隔离、预算与账本篡改拒绝原因 | 通过 |

## 测试与结果

```powershell
python -m pytest -q
# 结果：47 passed

git diff --check
# 结果：通过
```

上述均为无 API synthetic 测试：未读取 `DASHSCOPE_API_KEY`、未联网、未创建实时请求、未读取已取消 Batch 结果，未写正式 Cue 或 SUCCESS。

## CR-016/017 正式 Cue QA 交接（2026-09-09）

- T4 验证器已支持从 `cue_library_manifest.json` 读取 75 个正式 task 分片，并独立复算分片 SHA256、字节数、行数、Cue ID 唯一性、Cue→Source 血缘和四类 disposition 覆盖。
- 正式输入固定为 `realtime_v9_01`、370799 个 Source Atom、294839 条 accepted Cue；`excluded_no_cue`、`excluded_after_repair`、`excluded_content_filtered` 只作为已闭合 coverage 审计终态，不得重跑。
- Cue manifest SHA256 为 `a7ccd99e629d185911084bb654f79ca6891711b7874cd950c07b0bc7972fdf75`，协议 SHA256 为 `c7d809927f9cca4ff7d4501a0121c419768cd95c1d3c05d13b156000c50fbbb5`。
- CR-017 的 Schema、Seed 生成器和检索输出 Schema 已升级；T4 应继续检查 `trigger_cue_id` 精确血缘、同组/跨组 lure、失败子句和候选快照内全局不复用。
- 本次分支为 `main`，工作区未提交；尚未运行 API。BGE 固定依赖缺失时必须报告 blocker，不得把 lexical 检索当替代实现。

## 未解决问题、CR 状态与下一门

- T2 必须使实时生产者的全局 manifest、package state、ledger 与 complete 字段严格匹配本交接；其中全局分片清单须包含 `realtime_shard_index`，每个 package 的 complete 须包含结果/账本/状态三份实际 SHA256。
- T0 已冻结 registry `v1.5.0` / v3 实时配置；T0 合并 T2/T4 后还需运行全仓无 API 测试、文件所有权与协议哈希审阅。
- 在 T0 合并、全仓无 API 测试通过、冻结实时授权和预算后，才可由用户在本机设置 API Key 并显式启动实时生产。授权前禁止调用千问、生成正式 Cue/Seed/Life Log 或 `CUE_LIBRARY_SUCCESS.json`。
