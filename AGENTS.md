# EgoPM-Bench v1 统筹合同

治理合同版本：**v1.3.0**（2026-09-09）。本文件仅由 T0 维护。配置合同与已冻结 Source Atom Schema 保持 `v1.1.0`；本次冻结 Cue/Seed v2 的方向调整、480 个 Frozen Seed、900–1,400 个候选 Seed、三个阿里云账号使用同一 Flash 协议并行、WSL BGE-M3 筛选和阶段级分布报告。Cue/Seed v2 Schema、配置与执行代码尚未实施；必须通过对应 CHANGE_REQUEST 和验证后才能开始正式生产。

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

### 逻辑快照、分片与并行写入规则

- “阶段合并”指形成一个不可变的逻辑快照，不等同于必须生成一个物理巨型 JSONL。大规模正式产物可以由一个有序 manifest、若干互不重叠的正式分片和一个阶段级 SUCCESS 组成。
- manifest 必须逐分片绑定相对路径、SHA256、行数、字节数、顺序键、覆盖范围及全部必要上游哈希；SUCCESS 必须绑定 manifest SHA256、分片数、总行数、合同版本和上游哈希。任一分片缺失、重复、越界或哈希不符时，整个阶段均不可读。
- Source 与 Cue 采用上述大规模布局；已冻结的 Source 单文件作为兼容特例，不得仅为改变布局而重建。旧 V9 Cue 的 75 个 task 分片只保留不可变审计身份，不再作为 Seed 上游。Cue v2 使用 `cues/v2/formal/` 下的正式分片、一个 manifest 和一个阶段 SUCCESS，具体分片数在候选规模冻结后确定；package 级结果只属于执行审计。
- Seed candidates 规模调整为 900–1,400，是否继续采用单文件必须在实现 CR 时按实际字节数冻结；480 个 Frozen seeds 可保持单文件。Life Log 预计 2,880 条，必须在正式生成前通过 CHANGE_REQUEST 冻结单文件或 manifest+分片布局。Decision/Evidence 同样按规模提前冻结，不得运行中临时决定。
- 多终端并行生产只允许写入预先静态分配、互不重叠的 `*.tmp` 分区。每个分区完成内部验证后原子替换自己的正式分片；只有一个协调器可以执行全局唯一性、覆盖和哈希检查并写 manifest 与 SUCCESS。
- 单文件便利导出可以从 manifest 确定性重建，但只属于缓存，不是权威输入，不得被 SUCCESS 单独绑定。

### 多账号执行、账本与恢复规则

- 同一生产阶段只能有一个固定模型、一个 prompt hash、一个 Schema hash 和一套采样参数；多个账号只扩展吞吐，禁止按账号改变模型或协议。
- Cue v2 允许三个阿里云账号并行，分别固定绑定 `worker_00`、`worker_01`、`worker_02` 和互不重叠的静态 partition。每个 worker 使用独立授权、独立预算上限、独立 ledger、独立费用快照和独立 staging 目录。
- 禁止多个 worker 追加同一个累计账本、状态文件、manifest 或 SUCCESS。协调器只读聚合已关闭的 worker 账本；发现重复 request ID、终态冲突、费用缺失或身份不一致必须立即阻断，禁止自动重发。
- request ID 必须确定性绑定 campaign、worker、partition、package、Atom 集合 SHA 和 attempt。网络层幂等重试复用 idempotency key；模型修复必须增加 attempt 并产生新 request ID。
- 恢复只能处理本 worker、本 partition 的未终态请求。任何已计费、已成功、已排除或已有终态的 Atom 均不得自动重发。账本迁移只能由确定性工具原子完成并保留全部费用事件，严禁手改或删除 JSONL 行。
- 每个 partition 必须有独占租约；协调器只有在确认无进程、无在飞请求后才能释放失效租约。

### Cue v2、Seed 血缘、lure 与模型政策

- Cue v2 只表达单个 Source Atom 中可直接观察的事实，只允许 `all_of` 合取；`any_of`、虚拟时间、跨 Atom 关系和生命周期规则必须在 Seed/Rule 阶段表达。
- Cue v2 批量抽取沿用 `qwen3.7-flash`。三个阿里云账号必须使用相同地域、端点、模型 ID、prompt、Schema 和参数；模型在阶段中途发生不可证明的一致性变化时必须停批并创建新 campaign。
- Cue v2 扩量前必须从 BGE selection 分层冻结 800–1,000 个协议验收 Atom，其中至少 120 个重叠 Atom 由三个账号分别处理。该集合只验证协议与账号同质性，永不进入正式数据；任一验收门失败必须产生新协议 SHA 和新验收集 ID，禁止沿用旧结果扩量。
- 不同生产阶段可以使用不同的固定模型。Seed 生成、Seed 审计和 Life Log 生成的具体模型在各阶段执行前分别通过 CHANGE_REQUEST 冻结；DeepSeek 只可少量用于独立审计或争议第三意见，不做全量高成本审计。任何模型意见均不得替代人工终审。
- Cue v2 正式行删除顶层 `cue_type`、`confidence` 及可由 Source/manifest 派生的冗余字段；每个 predicate clause 自带 `dimension/operator/value/evidence`。正式行只包含 accepted Cue；`no_cue`、闭环后仍不确定的 `excluded_ambiguous` 和其他排除终态只写无正文 disposition ledger。
- 每个正式 Seed 必须保存 `trigger_cue_id`。该 ID 必须解析到 Cue v2 manifest 中的 `accepted_cue`，并与 `trigger_atom_id` 和 `trigger_predicate` 建立可由程序验证的唯一血缘；顶层 `primary_cue_type` 不再是正式血缘字段，需要分析维度时从 predicate clauses 确定性派生。
- `trigger_predicate` 必须与所引用 Cue 的规范化 predicate 完全一致；若人工修改 predicate，必须改为引用一个能精确支持该 predicate 的 Cue，禁止仅靠模型解释补足血缘。
- 每个 Seed 至少有两个互不相同且不同于 trigger 的同 split lure：至少一个与 trigger 同 `source_group_id`，用于同上下文困难干扰；至少一个来自不同 `source_group_id`，用于跨上下文语义干扰。每个 lure 必须明确记录至少一个未满足的 predicate 子句。
- 一个正式候选快照内，`trigger_cue_id`、`trigger_atom_id` 和所有 `lure_atom_id` 均不得跨 Seed 复用；被拒 Seed 释放的 Atom 只有在下一次有新 SUCCESS 的候选快照中才能重新分配。任何复用、组别构成或失败子句不合格都必须阻断 Seed SUCCESS。
- Seed candidates 目标为 900–1,400；只有覆盖门满足且至少 576 个候选通过机器门后才可停止扩充。最终 Frozen Seed 固定为 480，每个 Seed 派生 6 条 Life Log，预计共 2,880 条。不得降低质量门凑数。

### 分布报告硬门

- Cue v2、Seed candidates、Seed audit 和 Life Log 必须分别在 `audit/distributions/<stage>/<snapshot_id>/` 生成机器可读分布报告、人工可读摘要、manifest 和 `DISTRIBUTION_SUCCESS.json`。
- 报告至少按模型、split、参与者、模态、分片和阶段特有维度统计。即使阶段只有一个模型，也必须生成 `by_model.json` 证明阶段同质；多账号阶段还必须生成去账号标识化的 `by_worker.json` 检查成功率、终态、费用和语义分布漂移。
- 阶段 SUCCESS 必须绑定 `distribution_manifest_sha256`。没有报告、报告哈希不符、单一维度异常塌缩、字段覆盖归零或未解释的跨分片漂移时，阶段不得成功。

## 文件所有权与允许写入范围

| 负责人 | 允许写入 | 允许读取 | 正式启动门 |
| --- | --- | --- | --- |
| T0 | `AGENTS.md`、`.gitignore`、`README.md`、`pyproject.toml`、`egopm_bench_v1/config/**`、`egopm_bench_v1/schemas/**`、`egopm_bench_v1/coordination/STATUS.md`、`egopm_bench_v1/coordination/CUE_SEED_V2_PLAN.md`、`CHANGE_REQUESTS.md`、`wsl_BGE-M3_filter/**`、`tests/fixtures/**`、`tests/test_contract_freeze.py` | 全部 | Contract v1 DONE |
| T1 | `scripts/01_inventory_srt.py`–`04_make_source_splits.py`、`source/**`、`tests/test_source_pipeline.py`、`coordination/handoffs/T1_source.md` | config/schema/源 SRT | Contract v1 DONE；正式 source 输出还须通过 T4 source QA |
| T2 | `prompts/*`、`scripts/05_extract_cues.py`–`07_generate_seed_candidates.py`、`cues/**`、`seeds/reminder_seed_candidates.jsonl`、`tests/test_qwen_contracts.py`、`coordination/handoffs/T2_qwen.md` | 已冻结的 source/cues/config/schema | `SOURCE_ATOMS_SUCCESS` 哈希冻结且 T4 source QA DONE |
| T3 | `scripts/08_freeze_seed_audit.py`–`10_run_oracle.py`、`rules/**`、`lifelogs/**`、`benchmark/decision_instances.jsonl`、`benchmark/evidence_sets.jsonl`、`tests/test_state_machine.py`、`coordination/handoffs/T3_compiler.md` | 已冻结 seeds/config/schema | `SEEDS_FROZEN_SUCCESS` 哈希冻结且 T4 seed QA DONE |
| T4 | `scripts/11_validate_all.py`、`12_build_statistics.py`、`tests/test_validators.py`、`audit/**`、`benchmark/dataset_card.md`、`coordination/handoffs/T4_qa.md` | 所有已完成产物 | 对应生产者 SUCCESS 哈希存在；T4 永不修改生产者输出 |

只有 T0 可以将门禁提升为 `DONE`、合并工作、冻结哈希或变更本合同。治理合同 v1.3.0 DONE 后，T0 可以允许 T1–T4 以 synthetic fixture 独立开发代码；这不构成运行正式生产或读取未完成上游产物的授权。

## 必需输入、输出与门禁

| 门禁 | 必需输入 SUCCESS 标记 | 必需正式输出 | 负责人 | 验收条件 |
| --- | --- | --- | --- | --- |
| Source atoms | 治理合同 v1.1.0 | `source/SOURCE_ATOMS_SUCCESS.json`，以及 inventory、segments、atoms、split map、report | T1 | T4 通过 Schema、来源时间、路径与 split 检查 |
| BGE candidate selection | source 标记、冻结哈希、T4 source QA | `cues/v2/source_selection/<selection_id>/candidate_manifest.json` 与 `BGE_FILTER_SUCCESS.json` | T2/WSL | 固定 revision、环境和参数；8,000–12,000 个候选 Atom；分布报告与 Source 血缘通过 |
| Cue v2 protocol acceptance | BGE selection 标记、冻结协议与验收集 manifest | 协议验收报告与 `PROTOCOL_ACCEPTANCE_SUCCESS.json` | T2/T4 | 800–1,000 个分层 Atom；至少 120 个三账号重叠 Atom；证据、Schema、语义精度和账号漂移门全部通过；验收数据不进入正式 Cue |
| Cue v2 library | BGE selection 标记、Source 标记 | `cues/v2/cue_library_manifest.json`、正式分片与 `cues/v2/CUE_LIBRARY_SUCCESS.json` | T2 | 约 3,000–5,000 条高质量 accepted Cue；旧 V9 不混入；T4 通过 clause 语义、证据、覆盖、分布与血缘检查 |
| Seed candidates | Cue v2 标记、冻结哈希、T4 Cue v2 QA | `seeds/SEED_CANDIDATES_SUCCESS.json` | T2 | 900–1,400 个候选；每候选有唯一 Cue 血缘、一个 trigger、至少两个不跨 Seed 复用且满足同组/跨组构成的同 split lure、可执行 predicate 和终止沉默条件 |
| Seed freeze | candidate 标记、T4 candidate QA、人工审计 | `seeds/SEEDS_FROZEN_SUCCESS.json` | T3（在 T0 冻结审计后） | 480 个接受且可状态机化的 Seed；不足则扩大候选池，不降低门禁 |
| Families and oracle | frozen seed 标记、T4 seed QA | `lifelogs/LIFELOGS_SUCCESS.json`、`benchmark/DECISIONS_SUCCESS.json` | T3 | 480 × 2 个分支 × 3 种难度，预计 2,880 条 Life Log；gold 仅来自 oracle；T4 通过状态与配对检查 |
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
