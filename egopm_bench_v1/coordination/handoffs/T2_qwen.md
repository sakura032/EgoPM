# T2 千问候选生成交接

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
