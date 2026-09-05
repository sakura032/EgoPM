# T4：CR-2026-009 Cue v2.2 Batch File 无 API QA 交接

## 交接元数据

- 分支：`main`。
- 本次 T4 接收闭环提交：待 T0 合并后填写；基线 QA 提交为 `28461b7`。
- 治理合同版本：`v1.1.0`。
- 数据合同版本：Source Atom Schema 为 `v1.1.0`；最终 `cue_candidate` Schema 仍为 `v1.0.0`；Cue 执行协议为 `v2.2.1`，协议哈希 payload 为 `v2.0.0`，模型 ID 为 `qwen3.7-flash`。
- 修改文件：`scripts/11_validate_all.py`、`tests/test_validators.py`、本交接文件。
- 只读输入：T0 冻结的 `model_registry.yaml`、最终 Cue Schema、紧凑推理 Schema 与 pytest 临时目录中的合成 Source/Cue 标记和无正文 Batch 元数据。
- 正式输出：无。未读取或修改正式 Cue、Seed、Life Log、Decision、审计产物或模型原始响应。

## 已完成的 QA 门

- 保留按 stage 冻结的 Schema 校验：正式 Cue 仍必须声明 `cue_candidate: v1.0.0`，不能被全局合同版本误判。
- T4 从当前 registry、`cue_extractor_v3_compact.md` 与 `cue_inference_batch_compact_v1.schema.json` 独立计算完整 canonical 协议哈希；该哈希覆盖 payload 版本、模型、service、完整 `execution`、紧凑提示词 SHA256 与紧凑 Schema SHA256。
- 最终 `CUE_LIBRARY_SUCCESS.json` 除既有 Source、提示词、Schema、协议和 usage 字段外，必须声明 `batch_transport`、task 数、无正文 task 汇总清单 SHA256、请求数、原始响应禁止策略及远端清理责任状态。正式 Cue 只接受 `v2.2.1` 的 `batch_file`；历史实时 v2 标记不会放行。
- 固定读取 `cues/batch/batch_tasks_manifest.jsonl`。每行必须含 T0 冻结的 task 血缘、输入 SHA256、逻辑 shard 范围、远端输入 file ID、状态与无正文 `custom_id: package_id` 双向映射。QA 验证 SHA、文件请求数/分组上限、custom_id 格式、跨 task 唯一性和 package 双向唯一性。
- 递归拒绝任务元数据和账本中的 `body`、`request`、`response`、`error`、`visible_text`、`source_text` 等正文键；不读取或持久化 Batch 请求、结果或错误正文。
- 扫描 package ledger 并从冻结 `batch_ledger_policy` 读取必需字段和三种终态：`validated_success`、`service_line_failure_requeueable`、`local_validation_quarantine`。每个 custom ID 只能有一个终态；隔离 package 不得再次重排队或与成功混写；正式 SUCCESS 前所有 task 映射均须有唯一的 `validated_success` 终态。
- 新增接收 receipt 门：固定读取 `cues/batch/wave_{wave_index:02d}/task_{batch_task_index:03d}.batch_receipt.json`，以 task manifest 的波次和索引定位，不能由生产者提供任意路径。receipt 只能存 `batch_id`、远端文件 ID、计数、时间和结果/错误行流 SHA256；`raw_response_saved` 必须为 `false`。
- receipt 的 `received_line_count` 与三类终态计数必须完整覆盖提交请求数。远端输出或错误文件 ID 与其 SHA256 必须同时出现或同时为空。每条 ledger 新增 `batch_id`、远端结果/错误文件 ID、行 SHA256、`retry_eligible` 与 `failure_origin`；仅 `service_line_failure_requeueable` 可声明 `service_line` 与可重试，本地验证隔离绝不允许自动重排。
- 独立短码展开测试验证短码/默认值可得到最终 `cue_candidate` Schema；未知短码、跨 Atom 支撑片段、非法置信度和不对齐谓词均拒绝。

## Python 中文说明与关键注释验收

| 文件 | 中文模块说明 | 关键中文注释 | 结论 |
| --- | --- | --- | --- |
| `scripts/11_validate_all.py` | 说明第 11 步的只读输入、审计输出与流水线位置 | 说明 stage Schema 边界、完整协议哈希、无正文清单、输入哈希、远端清理、隔离不重试和原文子串防线的原因 | 通过 |
| `tests/test_validators.py` | 说明只使用临时合成输入与 pytest 输出 | 说明 task 元数据篡改、原始正文边界、价格/输出漂移和 quarantine 重排队的拒绝目的 | 通过 |

## 测试与结果

```powershell
python -m pytest -q egopm_bench_v1/tests/test_validators.py --basetemp .pytest_cache/t4-receiver
# 结果：20 passed

git diff --check
# 结果：通过
```

以上均为无 API synthetic 测试：未读取 `DASHSCOPE_API_KEY`、未联网、未上传/下载 Batch 文件、未创建远端任务，未写正式 Cue 或 SUCCESS。

## 未解决问题、CR 状态与下一门

- T4 范围内没有未解决 QA 设计问题；T2 必须使其 v2.2.1 无 API Batch 接收器输出与本交接的 task/receipt/ledger/SUCCESS 字段一致，之后由 T0 进行交叉审阅。特别是 task manifest 必须记录 `wave_index`，并与固定 receipt 路径一致。
- `CR-2026-009` 状态为“无 API 实施中；未获 Batch 生产授权”。
- 只有 T0 合并 T2/T4 代码并通过全仓无 API 测试、冻结 Source 预检和文件所有权审阅后，才能向用户申请 Batch File 生产授权。授权前禁止上传/下载文件、创建任务、调用千问、生成正式 Cue/Seed/Life Log。
