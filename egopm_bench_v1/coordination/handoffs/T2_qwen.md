# T2 千问候选生成交接

## 第 05 步离线分片建设补充（未调用 API）

- 本次只实现第 05 步的离线启动修复和可恢复分片框架；没有读取 `DASHSCOPE_API_KEY`，没有调用千问，也没有写入 `cues/cue_library.jsonl`、`CUE_LIBRARY_SUCCESS.json`、任何正式 Cue 或 Seed。
- `05_extract_cues.py` 现在将 `SOURCE_ATOMS_SUCCESS.json` 的相对 `artifact_path` 严格解释为 `egopm_bench_v1` 项目根相对路径，接受已冻结的 `source/source_video_atoms.jsonl`，拒绝绝对错误目标、`..` 越界和以 SUCCESS 所在目录猜测路径的旧行为。
- 模型与执行参数全部从 T0 冻结的 `models.cue_extraction.execution` 读取并逐字段校验：`explicit_execute_only`、每 shard `500` 个 Atom、`max_tokens=512`、`max_retries=2`、目标 `300` RPM / `1,000,000` TPM、服务端 `response_usage` 为权威、原始响应禁止落盘，以及固定的 shard 文件后缀和数值顺序合并规则。
- 实际执行分支在每一个 HTTP 尝试（包括重试）之前执行保守无突发节流：token 预留为该次实际序列化 UTF-8 请求字节数加 `max_tokens`，间隔取 `60/RPM` 与 `预留 token×60/TPM` 中较严格者。逐请求账本持久化单次/累计预留 token、累计实际等待秒数和尝试数；该信息不含模型正文，也不替代服务端 `response_usage` 的实际结算统计。
- `pricing_snapshot` 现由第 05 步精确校验：`2026-09-01_cn-beijing_list`、官方价格页、北京不超过 `32K` 输入窗口、输入 `¥0.2/百万 token`、输出 `¥0.8/百万 token` 与重试独立计费均不可漂移。只读预检在每个请求 UTF-8 token 上界不超过该窗口时，显式给出基准每 Atom 一次尝试以及每 Atom 均耗尽 `2` 次重试（共 `3` 次尝试）的输入、输出和总计 `CNY` 保守上界；超出窗口则拒绝把该快照用于费用估算。
- 默认启动为只读 `preflight`：验证 SUCCESS/Schema、按 `atom_id` 排序、核算 shard 与严格的请求 UTF-8 字节 token 上界，并打印报告；该路径不会读取环境变量、不会网络访问、不会创建运行目录。只有显式传入 `--execute` 才允许进入读取凭据和模型调用的分支。
- 正式执行分片时，每个 shard 独立保存输入 Atom ID/规范行哈希清单、输出 JSONL、逐请求账本和完成标记；完成标记绑定来源哈希、输入清单 SHA256、输出 SHA256 和账本 SHA256。恢复时只跳过完全匹配当前清单与哈希的完成 shard，缺失、失败或失配 shard 会被单独重跑；合并拒绝任何未完成 shard，并按数字 shard 编号固定顺序进行。
- 恢复完整性补丁：完成判定现在强制要求账本文件存在，且完成标记的 `ledger_sha256` 必须匹配当前账本；账本缺失或任一字节被篡改都会把 shard 重新列为待处理，不能被恢复逻辑跳过。对应合成测试覆盖这两种情况。
- 账本逐请求记录 `usage.prompt_tokens`、`usage.completion_tokens`、`usage.total_tokens`、重试次数、失败类别/截断摘要、模型和 Atom 身份；缺少服务端 usage 显式写为 `null`。账本不写 `choices`、模型正文或原始 HTTP 响应。
- 新增无 API 合成测试覆盖：项目内相对路径与越界拒绝、固定请求参数、服务端 usage 选择、确定性分片覆盖及顺序、完成 shard 跳过、未完成 shard 拒绝合并、账本无正文、预检只读和冻结执行配置读取。所有测试文件均在 `pytest` 临时目录，不会写正式输出。

## 仍需 T0 决策

该项已由 T0 的 `pricing_snapshot` 冻结并由第 05 步校验；预检可在价格窗口覆盖时给出可审计费用上界。无新增 `CHANGE_REQUEST`。

## 当前状态

- 治理合同版本：`v1.1.0`。
- 数据合同版本：`v1.0.0`。
- 分支 / 基线提交：游离 `HEAD` / `be6f05f`；T2 Wave 1 实现提交：`484945a`；本交接回填提交会在该实现提交之后创建。
- 已遵守治理合同 `v1.1.0` 的代码说明门禁：本次维护的每个 Python 文件均以中文模块说明交代职责、输入/输出与流水线位置；SUCCESS/哈希门、过滤、检索、模型调用、异常处理与原子写入均补充了说明其原因的中文注释。未修改 `AGENTS.md`、`config/**` 或 `schemas/**`。
- 第 1 波的接口与 `Schema` 合同开发已完成；没有读取 `source/`，没有调用远端千问，也没有创建任何正式线索、种子或 `SUCCESS` 产物。
- 当前门禁：线索库与种子候选仍为 `BLOCKED`，原因是不存在 `SOURCE_ATOMS_SUCCESS.json`，且来源质检尚未由 T4 标记为 `DONE`。

## 修改文件

- `prompts/cue_extractor_v1.md`
- `prompts/seed_generator_v1.md`
- `prompts/seed_auditor_v1.md`
- `scripts/05_extract_cues.py`
- `scripts/06_retrieve_trigger_lures.py`
- `scripts/07_generate_seed_candidates.py`
- `tests/test_qwen_contracts.py`
- 本交接文件。

## 治理说明验收

- `scripts/05_extract_cues.py`：中文模块说明已写明第 05 阶段职责、来源输入、线索库输出与前后门；SUCCESS/哈希门、固定模型、可见文本过滤、异常重试、原文可追溯检查与原子写入均有中文“为什么”注释。
- `scripts/06_retrieve_trigger_lures.py`：中文模块说明已写明第 06 阶段的来源/线索输入、检索集合输出和第 07 阶段关系；SUCCESS/哈希门、同 split 过滤、至少两个诱饵、排序可重现性、临时 JSON Schema 与原子写入均有中文“为什么”注释。
- `scripts/07_generate_seed_candidates.py`：中文模块说明已写明第 07 阶段的三类上游输入、种子候选输出和人工审计前位置；血缘哈希链、固定模型、环境凭据、触发/诱饵过滤、终止条件、异常重试与原子写入均有中文“为什么”注释。
- `tests/test_qwen_contracts.py`：中文模块说明已写明合成输入、断言输出和仅用于来源冻结前的开发位置；测试通过假的 HTTP 调用器保证不会访问远端模型。

## 实现与验证

- `05_extract_cues.py` 仅在 `SOURCE_ATOMS_SUCCESS.json` 存在、`artifact_path`、行数和 `SHA256` 均匹配时读取来源原子；以 `qwen3.7-flash-2026-07-15` 和严格 `json_schema` 逐 `atom` 生成线索，并验证原文连续子串、`split`、`Schema` 和受控元数据。
- `06_retrieve_trigger_lures.py` 同时验证来源与线索的成功标记，以可复现的词项 `Jaccard` 排序生成至少两个不同的同 `split` 诱饵；写入前以脚本内严格 `JSON Schema` 验证，其输出仅是受控的候选输入，不包含金标。
- `07_generate_seed_candidates.py` 验证来源、线索和检索输入的 `SUCCESS` 哈希链，以 `qwen3.7-plus-2026-05-26` 和严格 `json_schema` 生成 `candidate` 种子，并检查 `trigger`、两个同 `split lure`、谓词包含关系、有效窗口和四种终止不触发条件。
- `API Key` 没有命令行参数、配置文件回退或日志回显；调用代码只读取 `DASHSCOPE_API_KEY`。成功标记及每条 `Schema` 记录保存 `model`、`prompt`、`schema`、`run` 等元数据；原始模型响应不写入仓库。
- 手写合成对象仅位于 `test_qwen_contracts.py` 与 `pytest` 临时目录，用假的 `HTTP opener` 验证请求和响应；它们不属于 `P0`、`P1`、`smoke` 或正式数据。

## 只读输入哈希

| 输入 | `SHA256` |
| --- | --- |
| `config/model_registry.yaml` | `e65af16b73f831e170cb17625fe2df375c3189b8fcbf9ceba857f217c4ec6a9f` |
| `schemas/source_video_atom.schema.json` | `a97d72984a0b41fccca87832f79d38f3b15d8c1e54c24e439f38005b2d0967e6` |
| `schemas/cue_candidate.schema.json` | `d92316a1202470c20402ed855563c8b20d42b58d885eb06b5575f6ace81b1b5d` |
| `schemas/reminder_seed.schema.json` | `a5e7ba9d34d7e0f38a83e943d8032144d49e57204acb15b335cab12015c58e95` |

## 输出哈希

本次没有正式输出，因此没有 `CUE_LIBRARY_SUCCESS.json`、`SEED_CANDIDATES_SUCCESS.json` 或正式 `JSONL` 哈希。测试临时文件在 `pytest` 结束后已删除。

## 测试

```powershell
python -m py_compile egopm_bench_v1/scripts/05_extract_cues.py egopm_bench_v1/scripts/06_retrieve_trigger_lures.py egopm_bench_v1/scripts/07_generate_seed_candidates.py
# 通过

python -m pytest -q egopm_bench_v1/tests/test_qwen_contracts.py
# 6 passed

python -m pytest -q --basetemp .pytest_cache/t2
# 9 passed

git diff --check
# 通过
```

## CHANGE_REQUEST 状态

以下建议尚未登记，等待 T0 按数据合同 `v1.0.0` 的变更流程分配编号与决定：

### CR-2026-待分配：生产级触发/诱饵语义检索合同

- 提出者 / handoff：T2 / `coordination/handoffs/T2_qwen.md`。
- 当前合同版本：治理合同 `v1.1.0`；数据合同 `v1.0.0`。
- 受影响字段与产物：`config/model_registry.yaml` 中的检索模型、版本、端点与凭据策略；`config/paths.yaml` 中的 `trigger_lure_sets.jsonl` 路径及 SUCCESS 标记；新增或冻结的检索集合 `JSON Schema`；`cues/trigger_lure_sets.jsonl` 与其成功标记；依赖该集合的候选 Seed。
- 现有合同无法表达该需求的原因：生产指南提到 `BGE-M3`，但冻结 config 未登记模型 ID、版本、端点、依赖、嵌入/排序参数或可复现性设置；现有 schemas 与 paths 也未定义 `trigger_lure_sets.jsonl`、其 Schema 或 SUCCESS 哈希血缘。因此 T2 无法把该中间产物视为冻结的正式语义检索结果。
- 建议的兼容修改或迁移方式：T0 明确并登记生产检索模型（若选择 `BGE-M3`，须包括精确模型版本）、端点/凭据、依赖锁定、候选池、相似度、排序与并列规则；在 paths 和 schemas 中冻结检索 artifact、SUCCESS 标记和上游哈希字段。若不采用语义模型，应正式登记确定性词项检索算法及其全部参数。`06` 当前的 `Jaccard` 实现仅可用于接口 fixture 开发，不能作为冻结的正式语义检索方案。
- 必须重新生成的上游/下游产物：合同接受后重新生成检索集合及其成功标记；若模型或格式发生变化，重新生成受影响的正式 Seed candidates、后续审计冻结、规则、life log、decision 与 QA 产物。
- 证明该问题的测试：`python -m pytest -q egopm_bench_v1/tests/test_qwen_contracts.py` 验证当前临时严格结构与同 split 条件；该测试不能证明未登记的生产语义模型、版本、端点或排序参数。

## 下一门

当前下一门不能启动。仅在 T0 冻结 `SOURCE_ATOMS_SUCCESS.json` 的哈希且 T4 的来源质检为 `DONE` 后，T2 才可运行 `05_extract_cues.py` 生成正式线索库；在线索成功标记经 T4 线索质检通过、且上述检索 CHANGE_REQUEST 已由 T0 决定后，才可运行 `06` 和 `07`。T2 不负责冻结种子或生成提醒/静默金标。
