# T4：CR-2026-007 Cue v2 无 API QA 交接

## 交接元数据

- 分支：`main`。
- 本次相关 T4 提交：`da38f78`（Cue v2 执行血缘与用量汇总 QA）和 `d67aab7`（完整执行合同协议哈希 QA）。
- 治理合同版本：`v1.1.0`。
- 数据合同版本：Source Atom Schema 为 `v1.1.0`；最终 `cue_candidate` Schema 保持 `v1.0.0`；Cue v2 协议哈希 payload version 为 `v1.0.0`。
- 修改文件：`scripts/11_validate_all.py`、`tests/test_validators.py`、本交接文件。
- 只读输入：仅使用 T0 冻结的配置与 Schema 定义，以及 pytest 临时目录中的 synthetic 配置、提示词、推理 Schema、Source/Cue 标记和 JSONL；未读取正式 Cue、Seed、Life Log 或模型原始响应。
- 正式输出：无。未生成或修改任何正式 Cue JSONL、SUCCESS、审计、Seed、Life Log 或 Decision 产物。

## 已完成的 QA 实现

- 保留按阶段校验的最终 Cue Schema 边界：Cue SUCCESS 必须声明 `cue_candidate: v1.0.0`，不能被全局 `v1.1.0` 合同版本误判。
- 对 `CUE_LIBRARY_SUCCESS.json` 增加 v2 血缘门。标记必须含冻结 Source SHA256、`model_id`、`prompt_version`、`cue_execution_policy_version`、`protocol_hash_payload_version`、提示词和推理 Schema 的名称/版本/SHA256、`cue_execution_protocol_sha256` 与无正文 `usage_summary`。
- T4 会从冻结 `model_registry.yaml`、`cue_extractor_v2.md` 和 `cue_inference_batch_v1.schema.json` 独立计算，而不信任生产者自报的哈希。
- 协议哈希采用 UTF-8、`sort_keys=True`、紧凑分隔符的稳定 JSON SHA256。其 canonical payload 固定包含：payload version；模型 ID、非思考设置、温度、提示词版本、最终 Cue Schema/版本；服务 endpoint、region、凭据策略、原始响应策略；完整 `cue_extraction.execution`（package、受控字段、限流、token 口径、价格、布局和恢复）；提示词 SHA256 与推理 Schema SHA256。运行时数据和 Source 哈希不进入协议哈希，Source 哈希由标记的独立字段验证。
- 用量汇总必须含 package、尝试、成功/失败、输入/输出/总 token、缺失 usage、重试和限流等待；所有数值非负，且成功加失败等于尝试、输入加输出等于总 token、重试不超过尝试。
- 缺少字段、错 Source/提示词/推理 Schema/协议哈希、错版本、错用量算术或冻结执行语义漂移均为 `BLOCKER`，并发生在读取最终 Cue JSONL 前。

## Python 中文说明与关键注释验收

| 文件 | 中文模块说明 | 关键中文注释 | 结论 |
| --- | --- | --- | --- |
| `scripts/11_validate_all.py` | 首个有效内容说明第 11 步职责、输入、输出与流水线位置 | 已说明阶段 Schema 边界、SUCCESS/哈希门、完整执行合同哈希、Source 血缘和用量账本算术为何必须独立校验 | 通过 |
| `tests/test_validators.py` | 首个有效内容说明 synthetic 输入、pytest 输出与非生产边界 | 已说明临时 v2 合同替身、错误哈希/版本/账本与 RPM 漂移的拒绝目的 | 通过 |

## 测试与结果

```powershell
python -m pytest -q egopm_bench_v1/tests/test_validators.py --basetemp .pytest_cache/t4-v2p-validators
# 结果：14 passed

python -m pytest -q --basetemp .pytest_cache/t4-v2p-all
# 结果：37 passed

git diff --check
# 结果：通过
```

上述测试均为无 API synthetic 测试：未读取 `DASHSCOPE_API_KEY`、未访问网络、未调用千问，未写生产输出。

## 未解决问题、CR 状态与下一门

- T4 QA 代码没有未解决问题。
- `CR-2026-007` 状态为“已接受无 API 实施准备；未获正式 API 生产授权”。
- 下一门仍是用户明确确认预算、执行范围、运行时间窗和失败重跑范围后，T2 才能以 v2 五条 package 方案执行正式第 05 步；在此之前 Cue 门保持 `BLOCKED`。
- 正式 `CUE_LIBRARY_SUCCESS.json` 出现后，T4 才能执行独立 Cue QA；T0 未提升 Cue QA 为 `DONE` 前，不得启动 Seed 阶段。
