# EgoPM-Bench v1 统筹合同

治理合同版本：**v1.1.0**（2026-08-31）。本文件仅由 T0 维护。数据 Schema 与配置合同仍为 `v1.0.0`，因为本次仅新增代码协作规范，不改变数据结构。

## 不可变规则

### Markdown 中文规则（硬门禁）

- 本仓库全部 Markdown 文件必须用中文撰写，包括 `README.md`、状态板、交接、变更请求、数据集卡和提示词说明。
- 唯一例外是不可翻译的代码、命令、路径、URL、JSON/YAML 字段名、模型 ID、哈希、版本号和必要专有名词；它们必须原样置于代码格式或代码块中。
- T0 在审阅时发现 Markdown 正文不是中文，必须拒绝合并；责任对话须先改为中文，才可通过对应门禁。
- 本规则属于合同内容。任何放宽、删除或新增例外均须作为破坏性 `CHANGE_REQUEST`，不得由工作对话自行决定。

### Python 中文模块说明与注释规则（硬门禁）

- 每个 Python 代码文件的首个有效内容必须是中文模块说明（允许在 shebang 与编码声明之后）。说明必须明确：该文件负责什么、输入是什么、输出是什么，以及它位于哪一个流水线阶段。
- 关键步骤、关键判断、时间对齐、过滤、状态转移、哈希/SUCCESS 门和异常处理必须具有充分的中文注释。注释必须解释“为什么这样做”及其数据或评测约束，不能机械复述代码字面行为。
- 禁止只写英文注释、无意义注释、空泛的 TODO 注释或以英文替代中文模块说明。代码、路径、字段名、命令、模型 ID 和不可翻译专名可按 Markdown 中文规则保留原文。
- T0 审阅任何 Python 交接时必须检查该规则；不满足者不得合并，也不得将相应阶段标记为 `DONE`。既有代码在首次合并或修改时必须补齐该要求。

### 数据与执行规则

- v1 是“视频可追溯、文本优先”轨道。源 SRT 只读；v1 生产不复制、下载或拼接 MP4。
- 严禁提交 API Key、`.env` 文件、原始语料/媒体或模型原始响应日志。`DASHSCOPE_API_KEY` 只能从环境变量读取。
- 不得手改任何生成的 JSONL。生产者必须写入 `*.tmp`，完成内部验证后原子替换正式文件，最后写入 SUCCESS 标记。标记必须包含 SHA256、行数、合同/配置/Schema 版本、时间戳及上游哈希。
- 下游正式运行仅可读取同时满足以下条件的产物：SUCCESS 标记存在、哈希匹配且 T4 已通过必需的验证门。手写 synthetic fixture 只可用于单元测试，永不计入基准数据。
- 缺字段或不兼容修改一律视作 `CHANGE_REQUEST`；工作对话不得改动 `config/**` 或 `schemas/**`。

## 文件所有权与允许写入范围

| 负责人 | 允许写入 | 允许读取 | 正式启动门 |
| --- | --- | --- | --- |
| T0 | `AGENTS.md`、`.gitignore`、`README.md`、`pyproject.toml`、`egopm_bench_v1/config/**`、`egopm_bench_v1/schemas/**`、`egopm_bench_v1/coordination/STATUS.md`、`CHANGE_REQUESTS.md`、`tests/fixtures/**`、`tests/test_contract_freeze.py` | 全部 | Contract v1 DONE |
| T1 | `scripts/01_inventory_srt.py`–`04_make_source_splits.py`、`source/**`、`tests/test_source_pipeline.py`、`coordination/handoffs/T1_source.md` | config/schema/源 SRT | Contract v1 DONE；正式 source 输出还须通过 T4 source QA |
| T2 | `prompts/*`、`scripts/05_extract_cues.py`–`07_generate_seed_candidates.py`、`cues/**`、`seeds/reminder_seed_candidates.jsonl`、`tests/test_qwen_contracts.py`、`coordination/handoffs/T2_qwen.md` | 已冻结的 source/cues/config/schema | `SOURCE_ATOMS_SUCCESS` 哈希冻结且 T4 source QA DONE |
| T3 | `scripts/08_freeze_seed_audit.py`–`10_run_oracle.py`、`rules/**`、`lifelogs/**`、`benchmark/decision_instances.jsonl`、`benchmark/evidence_sets.jsonl`、`tests/test_state_machine.py`、`coordination/handoffs/T3_compiler.md` | 已冻结 seeds/config/schema | `SEEDS_FROZEN_SUCCESS` 哈希冻结且 T4 seed QA DONE |
| T4 | `scripts/11_validate_all.py`、`12_build_statistics.py`、`tests/test_validators.py`、`audit/**`、`benchmark/dataset_card.md`、`coordination/handoffs/T4_qa.md` | 所有已完成产物 | 对应生产者 SUCCESS 哈希存在；T4 永不修改生产者输出 |

只有 T0 可以将门禁提升为 `DONE`、合并工作、冻结哈希或变更本合同。治理合同 v1.1.0 DONE 后，T0 可以允许 T1–T4 以 synthetic fixture 独立开发代码；这不构成运行正式生产或读取未完成上游产物的授权。

## 必需输入、输出与门禁

| 门禁 | 必需输入 SUCCESS 标记 | 必需正式输出 | 负责人 | 验收条件 |
| --- | --- | --- | --- | --- |
| Source atoms | 治理合同 v1.1.0 | `source/SOURCE_ATOMS_SUCCESS.json`，以及 inventory、segments、atoms、split map、report | T1 | T4 通过 Schema、来源时间、路径与 split 检查 |
| Cue library | source 标记、冻结哈希、T4 source QA | `cues/CUE_LIBRARY_SUCCESS.json` 与已验证 cue library | T2 | 每条 cue 可追到 source 文本；T4 通过 Schema 与幻觉检查 |
| Seed candidates | cue 标记、冻结哈希、T4 cue QA | `seeds/SEED_CANDIDATES_SUCCESS.json` | T2 | 每候选有一个 trigger、至少两个同 split lure、可执行 predicate 和终止沉默条件 |
| Seed freeze | candidate 标记、T4 candidate QA、人工审计 | `seeds/SEEDS_FROZEN_SUCCESS.json` | T3（在 T0 冻结审计后） | 35–40 个接受且可状态机化的 seed；不足则退回 T2 |
| Families and oracle | frozen seed 标记、T4 seed QA | `lifelogs/LIFELOGS_SUCCESS.json`、`benchmark/DECISIONS_SUCCESS.json` | T3 | 2 个分支 × 3 种难度；gold 仅来自 oracle；T4 通过状态与配对检查 |
| Final validation | 所有上游标记及其哈希 | `audit/FINAL_VALIDATION_SUCCESS.json` | T4 | 零阻断错误、无泄漏、哈希与统计可复现 |
| Release | final validation 标记、T0 审阅 | 发布 manifest 与数据集卡 | T0 | 可从冻结配置完整重建 |

Contract v1 暂不冻结最终数值型评测参数：研究协议要求先获得 source 和 seed 统计后才能选择。其结构、候选值与冻结门已在 `benchmark_protocol.yaml` 固化；在后续协议参数门达到 DONE 前，严禁产生正式 oracle 输出。

## CHANGE_REQUEST 与交接协议

工作对话在自身 handoff 中提出请求，必须写明受影响字段、现有合同为何无法表达、兼容性影响与建议迁移方式。T0 在 `CHANGE_REQUESTS.md` 分配编号，并拒绝请求或创建语义化版本合同发布。破坏性 Schema/配置修改必须提升 major/minor 版本，并重生所有受影响的下游产物。

每份交接必须写明 branch/commit、治理合同版本、数据合同版本、修改文件、只读输入哈希、输出哈希、测试命令与结果、未解决问题、`CHANGE_REQUEST` 状态和下一门能否启动；所有解释性正文均须中文。涉及 Python 文件时，还必须逐文件说明中文模块说明与关键中文注释的验收结果。

## 统一命令

```powershell
python -m pytest -q
python egopm_bench_v1/scripts/11_validate_all.py --config egopm_bench_v1/config/benchmark_protocol.yaml
git status --short
```

工作对话交接前必须通过测试命令。完整验证器仅由 T4 在声明的 SUCCESS/哈希边界可用后运行。
