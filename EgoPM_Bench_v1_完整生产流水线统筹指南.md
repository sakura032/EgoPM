# EgoPM-Bench v1 完整生产流水线统筹指南

> 版本：v1.5
> 更新日期：2026-09-15
> 数据定位：video-referenced, text-first, decision-first, counterfactual  
> 本文面向第一次制作数据集的执行者，说明每一步为什么做、输入是什么、输出是什么、怎样判断可以进入下一步。

> **v1.5 优先级说明**：Cue/Seed v2、事实性三层门、统一 Life Log 骨架与 BGE selection v3.1 的详细执行合同以 `egopm_bench_v1/coordination/CUE_SEED_V2_PLAN.md` 为准。本文中作为历史说明保留的旧 V9、约 60 个候选、35–40 个 Seed、统一 Plus 审计、全量 Cue、仅凭 span 验收或正负分支替换 trigger 的描述，不再授权正式生产。

---

## 一、先把最终目标说清楚

EgoPM-Bench v1 的研究对象不是“给视频写摘要”，而是：

> 在连续生活记录中，系统必须记住用户此前提出的未来意图；当后来出现满足触发条件的场景时主动提醒；如果任务已经完成、取消、过期或已经提醒，则应保持沉默。

第一版仍然以 EgoLife 视频时间段为可回到的媒体原子，但暂时不读取和拼接 MP4。当前模型实际看到的是同一时间段的 Transcript 与 Dense Caption 文本，manifest 同时保存 SRT 来源和未来 MP4 定位信息。这样做的意义是先把“记忆、状态与主动决策”做对，后面可以在 atom ID、Episode 和 gold 不变的情况下替换为视觉输入。

本项目不使用 Natural Intention，不声称提醒意图和生命周期天然发生在 EgoLife。真实 EgoLife 只提供可观察的生活场景原子；意图、完成、取消、过期等历史由显式规则构造，并保存 provenance。

核心生产公式为：

> 全量 Source → BGE-M3 selection 形成 10,000 条核心候选并按新颖度补样至 10,000–12,000 条 → Flash 形成约 3,000–5,000 条高质量 Cue → 生成 900–1,400 个候选 Reminder Seed → 审计冻结 480 个基础任务 → 每个任务生成 2 个反事实分支 × 3 个记忆难度 → 2,880 条 Life Log。

480 是预注册的正式目标，不允许通过降低质量门凑数。候选通过数不足时扩大 Cue/Seed 候选池；达到各层覆盖门且至少 576 个候选通过机器门后，才允许停止扩充并进入全部人工终审。数据时长必须同时报告 manifest 引用时长、去重真实来源时长和虚拟时间跨度。

本项目不建立会混入 benchmark 的 P0、P1 或 smoke 数据集。大规模调用前必须建立独立的协议验收集，用来证明 prompt、Schema、语义门和三个账号同质；验收集永不进入正式 Cue、Seed 或 benchmark。每条正式数据仍必须通过同一套完整质量门，并分阶段冻结 schema、规则和协议。

---

## 二、必须区分的五个数据单位

### 1. Source Video Atom

来自 EgoLife 某个真实时间段的原子事件。v1 用 SRT 文本表示，未来可通过同一媒体定位字段加载 MP4。

### 2. Reminder Seed

一个可复用的基础提醒任务定义，包含：

- 用户意图；
- trigger predicate；
- 一个真实 trigger atom；
- 至少两个真实 lure/distractor atom；
- completed、cancelled、expired、already_reminded 等沉默条件；
- 可执行的状态机规则；
- 数据 split 与审计记录。

### 3. Life-log Family

同一个 Reminder Seed 派生的全部 6 条 Life Log。它们共享核心任务和 trigger，但分别具有 positive/negative 历史以及 short/medium/long 难度。一个 family 必须整体进入同一个 split。

### 4. Life Log

一条按 virtual_time 排列的完整事件流，由真实 Source Video Atom 与明确标记的构造事件共同组成。它不是一个真实 EgoLife 人物自然发生的一整天。

### 5. Decision Instance

Life Log 每到达一个规定决策点，就产生一次模型输入和 gold action。gold 只能由冻结的 oracle 状态机产生，动作是 remind(intent_id) 或 silent。

---

## 三、模型到底怎么选

### 1. 最终选型

本项目采用“阶段内单模型、阶段间可换模型”的政策。Cue v2 由三个阿里云账号使用同一 Flash 协议并行；Seed、审计和 Life Log 可在各自阶段选择不同中国厂商模型，但必须在生产前冻结固定模型并通过独立 CR：

| 工作 | 固定模型 | 模式 | 原因 |
| --- | --- | --- | --- |
| Cue v2 候选抽取 | `qwen3.7-flash` | 同一固定协议；JSON Schema | 三个百炼账号只扩展静态分区吞吐，不改变模型语义 |
| Reminder Seed、trigger predicate、lure 与生命周期候选生成 | 待阶段 CR 冻结；首选候选为 `qwen3.7-plus-2026-05-26` | 思考；中等推理；JSON Schema | 900–1,400 个候选需要单独核算质量、成本和并发 |
| Cue/Seed 独立模型审计 | Plus 为低成本主审；DeepSeek 仅少量争议第三意见 | 分层抽检；结构化输出 | 不对全量候选使用昂贵模型，人工仍独立终审 |
| Life Log 组装 | 确定性编排与受控 constructed 模板为默认；模型仅可选用于模板润色 | 不得改写 Source 事实、引入新现实实体或决定状态/gold |
| SRT 解析、时间对齐、去重、划分、状态转移与 gold | Python 确定性脚本 | 不调用大模型 | 必须可复现，不能让模型猜 |
| 相似 trigger/lure 检索 | `BAAI/bge-m3` 固定修订 | 稠密+稀疏混合检索；确定性 RRF | 比词面 Jaccard 更适合跨表达语义；v1 不增加 reranker |

旧 `realtime_v9_01` 继续受原 Flash 协议约束并只作审计，不得重跑或混入 Cue v2。Cue v2 新 campaign 沿用 `qwen3.7-flash`，但使用重新设计的完整词字段、clause evidence、语义门和三账号隔离账本。不同阶段的模型选择不沿用旧“全部 Plus”政策，也不使用 Max；任何生成或审计模型都不能替代程序验证与人工签字。

### 2. 模型绝对不能做什么

千问可以提出候选标签、候选规则和语言表达，但不得直接决定：

- source_start_sec 与 source_end_sec；
- Transcript 与 Dense Caption 是否在时间上重合；
- train/dev/test；
- remind 或 silent 金标；
- completed/cancelled/expired 状态迁移；
- 反事实两支是否满足“只改变一个历史条件”；
- 数据是否通过最终验证。

这些都由脚本和人工审计决定。

### 3. 每次调用必须记录

建立 model registry、campaign manifest 和 worker run manifest，至少记录：

- model_id；
- region 与 API endpoint；
- thinking_enabled；
- reasoning_effort；
- temperature；
- prompt_version；
- schema_version；
- request_time；
- input_atom_ids；
- 原始响应保存策略，正式生产必须为 `forbidden`；
- parse_status；
- retry_count；
- validation_errors。

正式抽取任务尽量使用平台允许的最低稳定采样。API Key 只从各 worker 的环境变量读取，不能写进脚本、Markdown、JSON、账本或 Git，也不能打印。模型、prompt、Schema、run 等运行元数据写入 manifest/账本，不在每条正式 Cue 中重复。

型号与能力以阿里云百炼官方页面为准：

- [文本生成模型列表](https://help.aliyun.com/zh/model-studio/text-generation-model)
- [结构化输出说明](https://help.aliyun.com/zh/model-studio/qwen-structured-output)
- [模型发布与更新记录](https://help.aliyun.com/zh/model-studio/newly-released-models)

---

## 四、推荐目录结构

不要移动已经下载好的 SRT，也不要在各个生成脚本中复制多份。新建一个生产目录，只引用现有原始数据：

~~~text
D:\scientific\EgoPM\
├─ AGENTS.md
├─ .gitignore
├─ pyproject.toml
├─ Egolife/
│  └─ raw/
│     └─ EgoLifeCap/
│        ├─ Transcript/<person>/DAYx/*.srt
│        └─ DenseCaption/<person>/DAYx/*.srt
└─ egopm_bench_v1/
   ├─ README.md
   ├─ config/
   │  ├─ paths.yaml
   │  ├─ model_registry.yaml
   │  ├─ split_policy.yaml
   │  └─ benchmark_protocol.yaml
   ├─ schemas/
   │  ├─ source_video_atom.schema.json
   │  ├─ cue_candidate.schema.json
   │  ├─ reminder_seed.schema.json
   │  ├─ lifelog.schema.json
   │  └─ decision_instance.schema.json
   ├─ prompts/
   │  ├─ cue_extractor_v1.md
   │  ├─ seed_generator_v1.md
   │  └─ seed_auditor_v1.md
   ├─ source/
   │  ├─ srt_inventory.csv
   │  ├─ raw_srt_segments.jsonl
   │  ├─ source_video_atoms.jsonl
   │  ├─ source_split_map.jsonl
   │  └─ atom_build_report.json
   ├─ cues/
   │  ├─ formal/task_000.jsonl ... task_074.jsonl
   │  ├─ cue_library_manifest.json
   │  ├─ CUE_LIBRARY_SUCCESS.json
   │  └─ cue_library.jsonl（可选便利缓存，不是权威输入）
   ├─ seeds/
   │  ├─ reminder_seed_candidates.jsonl
   │  ├─ reminder_seed_audit.csv
   │  └─ reminder_seeds_frozen.jsonl
   ├─ rules/
   │  ├─ rule_bank.jsonl
   │  └─ state_machine_policy.yaml
   ├─ lifelogs/
   │  ├─ family_specs.jsonl
   │  ├─ lifelogs.jsonl
   │  └─ counterfactual_pairs.jsonl
   ├─ benchmark/
   │  ├─ decision_instances.jsonl
   │  ├─ evidence_sets.jsonl
   │  └─ dataset_card.md
   ├─ audit/
   │  ├─ human_review.csv
   │  ├─ validation_errors.jsonl
   │  ├─ leakage_report.json
   │  └─ final_statistics.json
   ├─ logs/
   │  └─ model_runs/
   ├─ coordination/
   │  ├─ STATUS.md
   │  ├─ CHANGE_REQUESTS.md
   │  └─ handoffs/
   │     ├─ T1_source.md
   │     ├─ T2_qwen.md
   │     ├─ T3_compiler.md
   │     └─ T4_qa.md
   ├─ tests/
   │  ├─ fixtures/
   │  ├─ test_source_pipeline.py
   │  ├─ test_qwen_contracts.py
   │  ├─ test_state_machine.py
   │  └─ test_validators.py
   └─ scripts/
      ├─ 01_inventory_srt.py
      ├─ 02_parse_srt.py
      ├─ 03_align_modal_text.py
      ├─ 04_make_source_splits.py
      ├─ 05_extract_cues.py
      ├─ 06_retrieve_trigger_lures.py
      ├─ 07_generate_seed_candidates.py
      ├─ 08_freeze_seed_audit.py
      ├─ 09_build_lifelog_families.py
      ├─ 10_run_oracle.py
      ├─ 11_validate_all.py
      └─ 12_build_statistics.py
~~~

脚本编号表示正式数据的依赖顺序：前一步没有通过质量门，就不能运行下一步正式生产。不同模块的代码和单元测试可以按下一节并行开发。

### Python 文件的中文模块说明与注释（协作硬规范）

每个 Python 代码文件的首个有效内容必须是中文模块说明；若有 shebang 或编码声明，模块说明紧随其后。该说明必须交代文件职责、输入、输出以及对应的流水线阶段。关键步骤、关键判断、时间对齐、过滤、状态转移、哈希/SUCCESS 门和异常处理必须写充分的中文注释。

注释的作用是解释“为什么这样做”及其数据、可追溯性或评测约束，而不是逐字复述代码。禁止只写英文注释、无意义注释、空泛 TODO 或以英文替代中文模块说明；代码、路径、字段名、命令、模型 ID 与不可翻译专名除外。T0 将其作为所有 Python 代码审阅、合并和阶段 `DONE` 的硬门禁；既有代码在首次合并或修改时必须补齐。

---

## 五、多对话与多终端的实际协作方案

### 1. 最合适的数量：5 个长期对话，最多 4 个同时运行

建议在 Codex 中为 D:\scientific\EgoPM 建立 5 个固定对话，不要为每个脚本新开一个对话：

| 对话编号 | 对话名称 | 核心职责 | 是否直接生成正式数据 |
| --- | --- | --- | --- |
| T0 | EgoPM-统筹与合并 | 冻结 schema/config、分配任务、审阅交付、处理变更、合并代码 | 只负责最终提升和冻结 |
| T1 | EgoPM-SourceAtoms | SRT 清点、解析、时间对齐、去重、source split | 是，负责 source/ |
| T2 | EgoPM-QwenCuesSeeds | 千问客户端、cue 抽取、检索、Seed 候选生成 | 是，负责 cues/ 和未冻结 seeds |
| T3 | EgoPM-CompilerOracle | Seed 冻结编译、状态机、反事实、难度、Life Log、oracle | 是，负责 rules/、lifelogs/、benchmark 中间产物 |
| T4 | EgoPM-QARelease | 独立测试、全量验证、泄漏检查、统计与发布检查 | 不修改生产者结果，只报告问题和生成审计产物 |

开始：       T0
写代码阶段： T1 + T2 + T3 + T4
建原子库：   T1 + T4
抽 Cue：     T2 + T4
审计 Seed：  T0 + T2 + T4
编译数据：   T3 + T4
发布：       T0 + T4

建立 5 个对话是为了让每个对话长期保留自己那部分上下文；“最多 4 个同时运行”是为了避免你同时处理太多审批和冲突。T0 大部分时间处于等待/审阅状态，因此常见并行状态是 T1、T2、T3、T4 编写互不重叠的代码，或者 T0 合并时只让另外 2–3 个工作对话继续。

不建议建立 8–12 个对话。这个项目真正能够独立并行的工作流只有四条；继续拆分会让 schema、路径和字段约定反复合并，节省的运行时间小于沟通成本。

### 2. 先把项目变成 Git 仓库

生产数据统一在 `D:\scientific\EgoPM` 的 `main` 分支完成，不使用 worktree。为兼顾直接主目录工作和并行效率，必须区分“合同/代码写入”和“数据分区写入”：

1. T0 是合同、配置、Schema 和阶段提升的唯一写入者；同一时间不得由多个终端修改同一个代码或 Markdown 文件。
2. 数据生产可以开多个普通 PowerShell 终端，但启动前由协调器静态分配互不重叠的 task/partition 范围。
3. Cue v2 的三个百炼账号分别绑定一个固定 worker；三个 worker 必须使用同一模型、prompt、Schema、参数和 campaign ID。
4. 每个 worker 只能写自己的 `*.tmp`、ledger、费用快照和 staging 分区，不得追加共享正式文件、累计账本，也不得写 manifest/SUCCESS。
5. worker 完成后退出；协调器只读聚合已关闭账本，独占运行全局唯一性、覆盖、费用、哈希、Schema 和语义检查，再原子写 manifest/SUCCESS。
6. request ID 绑定 campaign、worker、partition、package、Atom 集合 SHA 与 attempt；重复 ID、费用缺失或终态冲突必须停批，禁止自动重发。
7. 所有 Windows 生产命令均使用项目 `.venv` 的 Python；API 密钥只由执行进程读取环境变量，绝不写入、打印或保存。

### 3. 唯一文件所有权

| 路径或文件 | 唯一写入者 | 其他对话权限 |
| --- | --- | --- |
| AGENTS.md、README.md、pyproject.toml、.gitignore | T0 | 只读；提出 change request |
| config/**、schemas/** | T0 | 只读；不得私自加字段 |
| scripts/01–04、source/**、tests/test_source_pipeline.py | T1 | T4 可读和验证 |
| prompts/cue_extractor*、prompts/seed_generator*、scripts/05–07、cues/**、seeds/reminder_seed_candidates.jsonl | T2 | T0/T4 只读审计 |
| scripts/08–10、rules/**、lifelogs/**、benchmark/decision_instances.jsonl、benchmark/evidence_sets.jsonl | T3 | T4 只读验证 |
| scripts/11–12、tests/test_validators.py、audit/**、benchmark/dataset_card.md | T4 | T0 审阅并提升 |
| seeds/reminder_seed_audit.csv | T0/人工负责人 | T2、T3、T4 只读 |
| seeds/reminder_seeds_frozen.jsonl | T3 依据已冻结 audit 编译 | T0 审批，其他只读 |
| coordination/STATUS.md | 仅 T0 | 所有人读取 |
| coordination/CHANGE_REQUESTS.md、tests/fixtures/** | 仅 T0 | 工作对话在自己的 handoff 中提出请求 |
| coordination/handoffs/T*.md | 对应对话 | T0 读取 |

最重要的规则是：任何工作对话如果发现 schema 或 config 不够用，不能顺手修改。它必须把需求写入自己的 handoff 或在 T0 对话中说明；只有 T0 可以汇总到 coordination/CHANGE_REQUESTS.md 并判断是否修改合同。合同改变后，T0 通知受影响的工作对话同步。

### 4. 生产输出采用“临时文件 → 原子替换 → 成功标记”

不能让 T4 在 T1/T2/T3 正在写一半 JSONL 时开始验证。每个生产脚本应遵循：

1. 先写同目录的 filename.tmp；
2. 完成全部写入并关闭文件；
3. 执行本阶段内部校验；
4. 用原子重命名替换自己的正式文件或分片；
5. 大规模产物由协调器生成有序 manifest，逐分片记录相对路径、SHA256、行数、字节数、顺序键和覆盖范围；
6. 最后由协调器写 stage_name_SUCCESS.json，绑定 manifest SHA256、总行数、分片数、schema_version、config_version、生成时间和上游输入哈希。

下游对话只在看到 SUCCESS 文件，并核对 SUCCESS→manifest→全部分片的完整哈希链后读取正式产物。上游重新生成时先产生新临时文件，不能先清空正式文件。单文件并不天然比 manifest 更严谨；科学完整性来自覆盖唯一、稳定排序、逐分片哈希和唯一阶段 SUCCESS。

Source 与 Cue 采用大规模布局，其中已冻结 Source 单文件作为兼容特例保留，不因布局变化重建；旧 V9 Cue 的 75 个 task 分片只作审计，Cue v2 的分片数按 3,000–5,000 条目标规模在实现前冻结。Seed candidates 为 900–1,400 条，Life Log 预计 2,880 条；这些阶段及 Decision/Evidence 是否分片都必须在正式生成前依据实际字节数另行冻结。

建议成功标记：

~~~text
source/SOURCE_ATOMS_SUCCESS.json
cues/CUE_LIBRARY_SUCCESS.json
seeds/SEED_CANDIDATES_SUCCESS.json
seeds/SEEDS_FROZEN_SUCCESS.json
lifelogs/LIFELOGS_SUCCESS.json
benchmark/DECISIONS_SUCCESS.json
audit/FINAL_VALIDATION_SUCCESS.json
~~~

### 5. 五个对话可直接复制的首条提示词

#### T0：统筹与合并

~~~text
你负责 D:\scientific\EgoPM 的统筹、数据合同与合并。你是 AGENTS.md、
pyproject.toml、config/**、schemas/** 和 coordination/STATUS.md 的唯一写入者。
不要替其他工作流大规模实现脚本，也不要直接手改生成 JSONL。

你的任务是：
1. 读取完整生产指南；
2. 建立并冻结目录、schema、配置和测试命令；
3. 为 T1–T4 明确输入、输出、允许写入路径和验收门；
4. 审阅各对话提交，按依赖顺序合并；
5. 处理 CHANGE_REQUEST，记录协议版本；
6. 只有在上游 SUCCESS 哈希和 T4 验证通过后，才允许下游开始。

每次答复都报告：当前冻结版本、已完成门、阻断问题、下一项可启动任务。
禁止把 API Key、原始大文件或模型原始日志提交到 Git。
~~~

#### T1：Source Video Atom

~~~text
你只负责 Source Video Atom 流水线。允许写：
scripts/01_inventory_srt.py、02_parse_srt.py、03_align_modal_text.py、
04_make_source_splits.py、source/**、tests/test_source_pipeline.py
以及 coordination/handoffs/T1_source.md。

config/** 和 schemas/** 只读；发现合同问题时停止相关字段实现并向 T0
提交 change request，不得自己修改。原始 SRT 只读，不移动、不改名。

完成全量 inventory、SRT block 解析、Transcript/Dense Caption 时间对齐、
宽松保留、来源分组和 split。先写单元测试，再运行全量正式数据。
输出 SOURCE_ATOMS_SUCCESS.json、atom_build_report.json 和交接说明。
不得调用千问，不得生成 cue、Seed 或 Life Log。
~~~

#### T2：千问 Cue 与 Seed 候选

~~~text
你只负责千问调用与候选生成。允许写：
prompts/cue_extractor_v1.md、seed_generator_v1.md、seed_auditor_v1.md，
scripts/05_extract_cues.py、06_retrieve_trigger_lures.py、
07_generate_seed_candidates.py、cues/**、
seeds/reminder_seed_candidates.jsonl、tests/test_qwen_contracts.py
以及 coordination/handoffs/T2_qwen.md。

只能读取已带 SOURCE_ATOMS_SUCCESS.json 的 source 输出。
使用固定模型：qwen3.7-flash-2026-07-15 做 cue 候选，
qwen3.7-plus-2026-05-26 做 Seed 候选。
所有输出强制 JSON Schema，并保存 model/prompt/schema/run 元数据。
API Key 只从环境变量读取。

不要修改 schema/config，不要冻结 Seed，不要写 remind/silent 金标。
先使用人工编写的合成 fixture 验证接口与 schema；fixture 只用于单元测试，
不属于 P0、P1、smoke 或正式数据。上游冻结后再全量运行。
~~~

#### T3：编译器与 Oracle

~~~text
你只负责确定性 benchmark 编译。允许写：
scripts/08_freeze_seed_audit.py、09_build_lifelog_families.py、
10_run_oracle.py、rules/**、lifelogs/**、
benchmark/decision_instances.jsonl、benchmark/evidence_sets.jsonl、
tests/test_state_machine.py 以及 coordination/handoffs/T3_compiler.md。

你可以在真实 Seed 冻结前，用纯手写合成 fixture 开发状态机和反事实生成器；
fixture 只做单元测试，不计入数据集。正式运行必须等待
SEEDS_FROZEN_SUCCESS.json。

gold 只能由状态机生成，不能调用任何大模型决定 remind/silent。
每个 Seed 必须派生 positive/negative × short/medium/long 六条 Life Log。
不要修改上游 source/cues/candidate Seed，不要修改 schema/config。
~~~

#### T4：独立质检与发布

~~~text
你是独立 QA，不替生产者修改其实现。允许写：
scripts/11_validate_all.py、12_build_statistics.py、tests/test_validators.py、
audit/**、benchmark/dataset_card.md 和 coordination/handoffs/T4_qa.md。

你可以读取所有产物，但只有在对应 SUCCESS 文件存在且哈希一致时才验证。
发现问题时在 validation_errors.jsonl 和交接说明中记录：
严重度、复现命令、失败 ID、预期、实际、建议修复阶段。
把问题退回唯一生产者，不直接修改 scripts/01–10 或生成 JSONL。

必须覆盖 schema、来源时间、状态迁移、反事实动作翻转、难度一致性、
split 泄漏、近重复、答案泄露、三种时长和可复现哈希。
FINAL_VALIDATION_SUCCESS.json 只能在零阻断错误时生成。
~~~

### 6. 实际并行波次

#### Wave 0：合同冻结，只运行 T0

T0 完成：

- Git、目录与 .gitignore；
- Python 环境与统一测试命令；
- 五个 JSON Schema；
- paths、model registry、split policy、benchmark protocol；
- AGENTS.md 文件所有权；
- 少量手写 synthetic fixtures；
- contract_version=v1.0.0 提交。

这一阶段不要让 T1–T4提前创建各自理解的字段，否则后面会大量返工。

#### Wave 1：四条代码线并行，不运行正式数据

可以同时进行：

- T1：开发并测试 scripts/01–04；
- T2：开发百炼客户端、JSON Schema 解析、重试和 scripts/05–07；
- T3：开发状态机、反事实与难度生成器、scripts/08–10；
- T4：开发 validators、统计器和故意错误的测试用例。

这一波使用的 synthetic fixtures 只是程序单元测试，不是小规模数据集，不进入论文规模，也不是 smoke。四个对话只写自己的文件，不依赖真实下游产物。

Wave 1 合并顺序：

1. T1 的单元测试与脚本；
2. T4 针对 source 的验证器；
3. T2 的 API/结构化输出客户端；
4. T3 的状态机与编译器；
5. T4 其余验证器。

每次由 T0 合并，工作对话之间不要彼此 merge。

#### Wave 2：全量 Atom 建库

同时运行上限为 3 个：

- T1：对全部 SRT 运行 inventory、parse、align、split；
- T4：等待 T1 产生每个阶段 SUCCESS 后做独立验证；
- T2：只完善 prompt 和成本估算，不读取未冻结 atom；
- T3：继续扩大状态机边界测试，不运行正式 Life Log。

T1 通过后，T0 冻结 SOURCE_ATOMS_SUCCESS 哈希。若 T4 报错，只退回 T1 修复；T4 不改 source 文件。

#### Wave 3：BGE selection、Cue v2 与候选 Seed

依赖顺序是先 Cue、后检索、再 Seed，不能让三个对话各自生成一份：

1. 在 WSL2 中用固定 BGE-M3 对全量 Source 单进程编码，执行冻结的 10,000–12,000 个候选 Atom selection；
2. T4 在 Windows 导入五文件快照，从 proof 与 Source 验证离散选择逻辑、manifest、模型 revision、分布和人工样本；不重跑 BGE；
3. 协调器把候选 Atom 静态分给三个阿里云 worker；
4. 三个 worker 使用同一 `qwen3.7-flash` Cue v2 协议并行写各自 staging 和独立账本；
5. 协调器闭合 ambiguous、运行 clause 语义门并生成约 3,000–5,000 条 accepted Cue 的正式分片、manifest 和 SUCCESS；
6. T4 验证 Cue v2 Schema、原字段证据、predicate 语义、分布、账本和三账号同质性；
7. T2 基于 Cue v2 与 BGE-M3 结果生成 900–1,400 个 Seed candidates；
8. T4 运行候选硬条件验证；至少 576 个候选通过机器门后才允许停止扩充；
9. T0 接收全部候选供人工审核。

此时 T1 可以补充来源统计，T3 可以准备编译环境，但都不能修改 cues 或 candidates。

#### Wave 4：Seed 审计，减少并行

这一阶段质量比速度重要，建议只让 T0、T2、T4 工作：

- T2 使用另行冻结的低成本模型提供审计意见；DeepSeek 只处理少量争议项或第三意见，不做全量高成本调用；
- T0/人工逐个给出 accept、revise、reject；
- T4 检查每个 Seed 的 trigger、两个 lure、terminal/silent 与 split 硬条件；
- revise 只退回 T2 修改候选；
- T0 冻结 reminder_seed_audit.csv；
- T3 运行 08_freeze_seed_audit.py，生成 SEEDS_FROZEN_SUCCESS。

目标冻结 480 个 Seed。若人工与机器门通过数少于 480，T2 在预注册分层和排序下扩大 Cue/Seed 候选池；不允许 T3 或 T4 降低规则。

#### Wave 5：Life Log 与 Gold 全量编译

可以同时进行：

- T3：生成所有 6-way families、预计 2,880 条 Life Log、Decision Instance 和 Evidence Set；
- T4：只验证已完成并带 SUCCESS 的批次；
- T2：整理模型运行元数据、成本与拒绝原因；
- T1：整理 source 覆盖和 unique_source_hours。

正式输出可按 family_id 分 shard，例如 part-000.jsonl、part-001.jsonl。每个 shard 完成后写独立哈希，最终再由 T3 生成总 manifest。T4 不能读取 .tmp 或未完成 shard。

#### Wave 6：最终验收与发布

- T4 全量运行验证器、泄漏检查和统计；
- T0 审阅所有阻断错误；
- 问题按所有权退回 T1、T2 或 T3；
- 修复后只重跑受影响阶段及其全部下游；
- T4 零阻断后生成 FINAL_VALIDATION_SUCCESS，并更新 dataset card；
- T0 更新 README、发布版本和最终 manifest。

### 7. 哪些事情可以同步，哪些绝对不能

| 工作组合 | 是否可并行 | 原因 |
| --- | --- | --- |
| SRT parser 与状态机代码开发 | 可以 | 文件和数据依赖独立 |
| 千问 API 客户端与 validator 开发 | 可以 | 都可使用 synthetic fixtures |
| 全量 SRT 解析与状态机单元测试 | 可以 | 一个主要用磁盘/CPU，一个规模很小 |
| T1 写 atom 与 T4读取同一未完成 JSONL | 不可以 | 会读到半文件 |
| Cue 抽取与 Seed 生成 | 不可以 | Seed 依赖冻结 cue library |
| Seed 生成与 Seed 终审 | 不可以对同一批同时进行 | 审计对象必须稳定 |
| 模型审计与人工独立阅读 | 可以 | 两者先独立判断，再汇总；昂贵模型只做分层抽检和争议项 |
| Life Log 生成与已完成 shard 验证 | 可以 | 以 SUCCESS/hash 为边界 |
| 三个终端调用同一 Flash 处理静态不重叠 partition | 可以 | 同一 campaign、同一协议；worker 账本和预算完全隔离 |
| 多个终端处理同一 Atom 或追加同一账本 | 绝对不可以 | 会重复计费、碰撞 request ID 并破坏恢复终态 |
| T3 生成 gold 与千问生成 gold | 不可以 | gold 只有 oracle 一条来源 |
| T4 报错与生产者修复 | 可以 | T4写 issue，生产者写自己的代码 |
| 多个对话同时改 config/schema | 绝对不可以 | 数据合同会失控 |

### 8. 终端如何分配

全部终端使用同一个 `D:\scientific\EgoPM` 主目录与 `main` 分支，但写入范围必须预先静态隔离：

| 终端 | 工作目录 | 用途 |
| --- | --- | --- |
| Terminal 0 | D:\scientific\EgoPM | 协调器、合同、全局验证、manifest/SUCCESS |
| Terminal 1 | D:\scientific\EgoPM | 百炼账号 A / `worker_00`；只写静态 partition A 的 staging 与独立账本 |
| Terminal 2 | D:\scientific\EgoPM | 百炼账号 B / `worker_01`；只写静态 partition B 的 staging 与独立账本 |
| Terminal 3 | D:\scientific\EgoPM | 百炼账号 C / `worker_02`；只写静态 partition C 的 staging 与独立账本 |
| Terminal 4 | D:\scientific\EgoPM | 对已完成且哈希稳定的分片做只读验证 |

多个普通 PowerShell 窗口可以并行写不同 partition，但禁止同时写同一分片、同一临时文件、累计账本、manifest 或 SUCCESS。每个 worker 具有独立授权、预算、租约、request ledger 和费用快照。任何范围重叠或 request ID 重复都必须先停止，不得用“最后合并时去重”补救。

本地 BGE-M3 移至 WSL2，使用 `wsl_BGE-M3_filter/` 中的专用 `.venv-bge-m3`、单 GPU 和单编码进程；三个 Windows API 终端不承担 BGE 编码。不要同时在 WSL 启动第二个 BGE 或视觉/VLM 进程争抢 GPU。

### 9. 每个对话结束时必须交接

对应 handoff 文件使用统一模板：

~~~text
# Tn Handoff

- branch / commit:
- contract_version:
- 完成内容:
- 修改文件:
- 只读输入及 SHA256:
- 输出及 SHA256:
- 测试命令:
- 测试结果:
- 未解决问题:
- 是否产生 CHANGE_REQUEST:
- 下一阶段是否可启动: yes / no
~~~

T0 不接受“已经弄好了”这种交接。没有 commit、命令、测试结果、输入输出哈希和已知问题，就不算完成。

所有 Python 文件的交接还必须逐文件报告：中文模块说明是否存在、关键中文注释是否覆盖时间对齐/过滤/状态转移/哈希-SUCCESS 门/异常处理，以及尚未满足的项。缺失即退回责任对话修复。

### 10. 状态板

coordination/STATUS.md 只由 T0 更新，建议使用：

| Gate | Owner | Status | Frozen artifact/hash | Blocker | Next |
| --- | --- | --- | --- | --- | --- |
| Contract v1 | T0 | TODO | — | — | freeze schemas |
| Source atoms | T1 | BLOCKED | — | Contract v1 | implement 01–04 |
| Source QA | T4 | BLOCKED | — | Source atoms | validate |
| BGE candidate selection | T2/WSL | BLOCKED | selection v3.1 request/查询/策略/两个必要 Schema 已冻结 | WSL 实现、运行与导入 QA | 生成并验证 10,000–12,000 个候选 Atom 和 proof |
| Cue v2 library | T2 | BLOCKED | — | BGE selection + 三账号协议 | 生成约 3,000–5,000 条高质量 Cue |
| Seed candidates | T2 | BLOCKED | — | Cue v2 library | 生成 900–1,400 个候选 |
| Seed audit | T0/T4 | BLOCKED | — | Candidates | audit |
| Families/oracle | T3 | BLOCKED | — | Frozen Seeds | compile |
| Final QA | T4 | BLOCKED | — | Decisions | validate |
| Release | T0 | BLOCKED | — | Final QA | publish |

状态只能使用 TODO、IN_PROGRESS、BLOCKED、DONE。只有 T0 能把 Gate 改成 DONE。

---

## 六、第一阶段：从全部 SRT 得到 Source Video Atom 库

这是现在最先要完成的工作。

### 1. atom 里到底保存 SRT 还是 MP4 路径

两者都保存，作用不同：

- source_srt_paths：当前 v1 真正读取的 Transcript/Dense Caption 文件和文本时间戳来源，用于追溯、纠错和复现；
- source_video_path：未来恢复视觉输入时对应的 MP4 媒体定位信息；
- source_video_path 不代表当前已经下载了 MP4，也不代表文件一定存在；
- 如果暂时不能由文件名可靠推断视频路径，就设为 null，并记录 video_mapping_status=pending，不能编造路径；
- 构造意图、取消、完成等事件没有 EgoLife 原视频，source_srt_paths 与 source_video_path 都是 null，同时必须保存 rule_id 和 generation_record。

建议的 atom 示例：

~~~json
{
  "atom_id": "src_A1_JAKE_DAY1_000123",
  "atom_kind": "source_video_atom",
  "participant_source_id": "A1_JAKE",
  "source_day": "DAY1",
  "session_id": "DAY1_A1_JAKE_11000000",
  "source_srt_paths": {
    "transcript": "EgoLifeCap/Transcript/A1_JAKE/DAY1/example.srt",
    "dense_caption": "EgoLifeCap/DenseCaption/A1_JAKE/DAY1/example.srt"
  },
  "source_video_path": null,
  "video_mapping_status": "pending",
  "source_start_sec": 587.1,
  "source_end_sec": 595.7,
  "transcript_segment_ids": ["tr_00124", "tr_00125"],
  "dense_caption_segment_ids": ["dc_00087"],
  "transcript": "Okay, then we need a stopwatch.",
  "dense_caption": "Jake is speaking with the others at a table.",
  "visible_text": "Jake is speaking with others at a table. They mention needing a stopwatch.",
  "provenance": "egolife_srt",
  "split": "train"
}
~~~

source_start_sec/source_end_sec 必须说明是文件内相对秒、session 相对秒还是全局秒。推荐同时保存 local_start_sec 与 normalized_start_sec，绝不能只留一个含义不明的数字。

### 2. 具体生成步骤

#### A. 清点文件

01_inventory_srt.py 递归扫描 Transcript 与 DenseCaption，输出 srt_inventory.csv。每行包括：

- modality；
- participant；
- day；
- file_name；
- relative_path；
- file_size；
- parse_status；
- 从文件名解析出的 session/video UID；
- 是否找到同 session 的另一种 SRT。

输出后先检查所有已下载 SRT 都出现在清单中。

#### B. 解析每个 SRT block

02_parse_srt.py 把每个字幕块转成 raw_srt_segments.jsonl。程序负责：

- 读取字幕序号；
- 把 HH:MM:SS,mmm 转成秒；
- 保留原始文本；
- 规范空白字符；
- 删除空块和完全重复的相邻块；
- 保留原文件相对路径和原字幕序号；
- 解析失败写 error，不静默跳过。

这一阶段不调用千问。

#### C. 对齐 Transcript 与 Dense Caption

03_align_modal_text.py 先按 participant、day、session_id 分组，再按时间重叠对齐：

- Dense Caption 时间段作为主要可观察动作窗口；
- 把与其重叠或在允许容差内的 Transcript 片段挂到同一 atom；
- 允许一对多和多对一，不要求每条字幕严格一一对应；
- 如果只有一种模态，也可以保留为 atom，并标记 modality_coverage；
- 相邻短描述若场景与动作连续，可按明确规则合并成 5–30 秒的 atom；
- 不让千问修改原始起止时间。

对齐阈值写入 config，不要散落在代码里。需要输出配对率、单模态 atom 比例、时长分布、异常长片段与未解析文件列表。

#### D. 宽松保留

只删除：

- 空字幕；
- 严重乱码；
- 无法恢复有效时间；
- 完全无法理解的噪声；
- 相邻完全重复描述。

只要具有可理解的人物、地点、物体、活动、对话、时间或环境状态之一就保留。不要因为它暂时“不像提醒 cue”而删除。原子库的职责是提供可检索生活事实，不是提前筛完整提醒故事。

#### E. 来源去重并先划分

04_make_source_splits.py 在生成任务前冻结 train/dev/test：

- 同一 session、相邻片段和近重复文本不得跨 split；
- 同一共享世界事件的多参与者视角整体分组；
- 同一 atom 只能有一个 split；
- 后续一个 family 中所有 trigger、lure 和派生数据必须来自同一 split；
- split 不能根据模型生成质量反复挪动。

### 3. 本阶段通过标准

- 全部 SRT 文件都有 inventory 记录；
- 每个成功 atom 都可追溯到至少一个真实 SRT 字幕块；
- 起止时间合法且 start < end；
- source_srt_paths 实际存在；
- video_mapping_status 不得缺失；
- 所有解析错误有日志；
- 不存在跨 split 的相同或近重复来源组；
- atom_build_report.json 完整报告数量、时长、对齐率和失败原因。

---

## 七、第二阶段：建立高精度 Cue v2 Library

### 1. Cue 的 clause dimension

一个 Atom 最多形成一个正式 Cue；一条 Cue 只含一个 predicate，并包含 1–3 个由各自原字段证据直接支持的 `all_of` clause：

- explicit_time：只允许 Source 文本中明确出现且可逐字引用的日期、时刻、频率、期限或先后关系；视频/session 时间戳不是该证据；
- person：某人出现、离开、靠近、开始交互；
- location：进入或处于某地点；
- object：某物体出现、拿起、放下、缺失或改变状态；
- activity：开始、持续、结束或切换某活动；
- state：可观察的环境、人物或物体状态成立、否定或变化。

Cue v2 不再保存顶层 `cue_type`，需要统计时从 clauses 的 dimension 确定性派生。`event_timestamp` 只表示 Source 视频/session 的位置，用于定位和事件顺序；未来提醒使用独立 `temporal_condition`，只能由后续 Seed/Rule 的冻结模板和确定性规则构造并人工审计。最终分布以真实通过语义门的内容为准；审计用于发现缺口，不能迫使模型制造某类 Cue。

Current dimension 只使用 `person/location/object/activity/state/explicit_time`。旧版 `place/state_change/time` 不作为同义枚举继续保留，BGE 查询族也不能直接当作模型标签。operator 必须按 dimension 设合法组合，至少区分人物在场/说话/被提及、地点被提及/进入/处于、活动开始/持续/结束、状态成立/否定/变化，以及显式时间被陈述/计划/假设；不能只用通用 `eq/not_eq` 掩盖关系和语气。

Cue 是可判断的观察条件，不要求完整主谓宾。“手机出现”“厨房”“Jake 正在说话”“门已打开”可以成立；“他”“那里”“东西”“正在做”“发生变化”等没有可识别指向对象或状态承载者的表达不能成立。一个明确实体或地点通常用一条 clause；主体/对象与动作或状态通常用两条；只有第三个条件确实用于消歧时才使用三条。禁止把不相关事实拼进一个 Cue，也禁止把一个事实重复拆成多个 clause。

### 2. 千问 Flash 的工作

新版第 05 步只将 BGE selection 中的单个 Atom 发送给 `qwen3.7-flash`，不得拼接相邻 Atom。模型输出候选判断和 clause：

- `accepted/no_cue/ambiguous` 候选判断；
- `predicate.all_of`；
- 每个 clause 的完整词 `dimension/operator/value`；
- 每个 clause 的 `evidence.field/evidence.span`；
- ambiguous 的结构化安全原因码。

模型输出只是候选。正式 Cue 不保存 `confidence`、顶层类型、重复 Source 正文、可派生 split 或逐行模型/run/Schema 元数据。程序必须验证每个 clause 的 value 被自己的 span 直接支持，阻断错槽、字符串 `null`、跨字段/跨 Atom 拼接和释义。ambiguous 复核后只能进入 accepted、no-cue 或 excluded-ambiguous 终态。

### 3. 每条候选必须通过三层判断

第一层检查证据位置：`evidence.field` 只能是同一 Atom 的 `transcript` 或 `dense_caption`，`evidence.span` 必须是该字段中的连续原文。程序从 Source 重新读取字段验证，不能相信模型回显文本；禁止跨字段、跨 Atom、翻译、摘要、重排或拼接。

第二层检查 value：`value` 必须能由自己的 span 直接支持，最多只允许 Unicode 和空白规范化。它可以是 span 中较短但完整的实体，例如“我拿着手机”中的“手机”；不能删除否定词、改变数字/单位、改写词序或用常识补全。空串、`null/none/unknown/n/a` 和无法解析的纯代词/泛指词直接拒绝。

第三层检查完整语义：验证 `dimension + operator + value` 是否真的由 span 蕴含。必须检查人物是在场、说话还是仅被提到；活动的主体/对象；状态的承载者；否定、量词和范围；条件、假设、将来、疑问和不确定语气；显式时间是被陈述、计划还是已经到达。看到“冰箱”不能推断厨房，“Alice 被提到”不能推断 Alice 在场，“没拿手机”不能生成手机出现，“如果三点开会”不能生成三点已经到达。

前两层和部分第三层由 T2/T4 独立程序全量执行。程序不能可靠判断的人物角色、指代、范围和时间语气进入结构化人工审计，不得让另一模型的一句“同意”自动转为金标。稳定错误码至少区分 span 不连续、value 无支持、dimension 错置、operator 极性错误、人物角色错误、范围错误、时间语气错误、指向对象不可解析和跨字段借证。

### 4. 校准、验收和扩量顺序

1. 先复用 BGE proof 的 350 条 audit sample，人工标注 `no_cue`、dimension、operator、span、value、人物角色、否定/范围/时间语气和 Seed 可执行性，用于写 prompt、Schema、validator 和历史失败回归测试；
2. 最终协议另取 800–1,000 条验收 Atom，其中至少 120 条由三个账号重叠处理；先执行约 500 条子波次，若修改协议则整套验收重新开始；
3. 验收要求 span 与 value 两层硬门为 100%，accepted 分层语义精确率不低于 97%，事实角色/关系/否定/范围/时间语气失真为 0，Schema 有效率不低于 99.5%；
4. 正式生产先运行约 1,500 条 checkpoint，核对质量、dimension/operator 分布、worker 漂移、吞吐和每千条费用，再处理剩余候选；
5. 每个请求最多携带 5 个带稳定 `item_index` 的 Atom，各项独立验证。单项失败最多一次只含该 Atom 的简化修复，仍失败即排除，不循环重付；
6. 强模型只审计 ambiguous、分层样本和拟进入 Seed 的 trigger Cue。全部最终 Seed 由人工终审，Life Log 的事实观察不再调用模型生成。

约 3,000–5,000 条 accepted Cue 是规划范围而非配额。数量不足时检查 selection 和 prompt，不能通过放宽真实性门或强制 dimension 平衡凑数。

### 5. Cue Library 的输出

Cue v2 使用 `cues/v2/formal/part_N.jsonl`、`cues/v2/cue_library_manifest.json` 和一个 `cues/v2/CUE_LIBRARY_SUCCESS.json`。正式行只包含 `cue_id`、`atom_id` 和 clause-level predicate/evidence。模型、prompt、Schema、run、worker、预算和账本写入 manifest/provenance，不在每行重复。旧 `cues/formal/` 的 V9 分片永久只作审计。单文件导出若存在，只是可重建缓存。

---

## 八、第三阶段：决策优先生成 900–1,400 个候选 Reminder Seed

### 1. 为什么决策优先

不要先让模型写一周虚拟故事，再从故事里寻找提醒。那样很容易得到漂亮但不可判定的数据。正确顺序是：

> 真实 trigger atom → 可执行触发谓词 → 需要提醒的未来意图 → 相似 lure → 终止/沉默条件 → 再组装完整 Life Log。

这样每个最终决策点先天可解，而且能明确需要记住什么。

### 2. 每个候选 Seed 的硬条件

- 恰好一个核心提醒意图；
- 恰好一个 `trigger_cue_id`，解析到正式 Cue manifest 中的 `accepted_cue`；
- Cue 的 `atom_id` 和 predicate 必须分别与 `trigger_atom_id`、`trigger_predicate` 完全一致；分析用主 dimension 从 Cue clauses 确定性派生，不再保存顶层 `primary_cue_type`；
- 至少两个同 split、互不相同且不跨 Seed 复用的真实 lure/distractor；
- 至少一个 lure 与 trigger 同 `source_group_id`，至少一个来自不同 `source_group_id`；
- 每个 lure 保存未满足的 predicate 子句序号，不接受只写自然语言理由；
- lure 与 trigger 相似，但至少有一个关键谓词不满足；
- completed、cancelled、expired 或 already_reminded 中至少一种能形成困难 silent；
- trigger predicate 能被程序或有限规则判断，不是“看起来合适”；
- 当前 trigger 不能单独泄露此前是否有意图；
- 所有真实 atom 来自同一 split；
- 能构造成正反事实对。

### 3. 候选分布不是最终硬配额

候选总量允许在 900–1,400 之间扩展。不得按旧 cue 类型机械平分；应按 split、参与者、模态、来源组、主 clause dimension、生命周期终态和困难 silent 类型设置最低覆盖与单层上限：

| 主 clause dimension | 设计要求 | 预期 |
| --- | ---: | --- |
| person | 报告覆盖和集中度，不设强制比例 | 需要真实人物证据 |
| location | 报告进入/离开/处于覆盖 | 防止仅靠场景词触发 |
| activity | 报告 starts/ends/contains 覆盖 | 适合主动触发，但需排除泛化动作 |
| object | 报告 present/absent/状态覆盖 | 需要防止仅靠关键词判断 |
| explicit_time | 只使用 Source 显式时间证据 | 虚拟时间另在 Rule 构造 |
| state | 单独报告高淘汰率 | 宁缺毋滥，不接受推断状态 |

这些是覆盖维度，不是最终类别配额。一个 Seed 可以有多个合取 clause。只有各层覆盖门满足且至少 576 个候选通过机器门后，才可停止扩充；最终冻结数为 480。

### 4. 具体生成方式

1. 从 Cue manifest 中选择具有唯一 `cue_id` 的 trigger 候选，不遍历 package 审计文件；
2. 用 `BAAI/bge-m3` 固定修订 `5617a9f61b028005a4858fdac845db406aefb181` 对每个 split 的 Source corpus 建一次索引；
3. 使用 `bge_m3_hybrid_rrf_v1` 检索同 split atom：稠密/稀疏各取前 64，按 `1/(60+rank_dense)+1/(60+rank_sparse)` 合并，同分按 `atom_id` 升序；
4. 从排名中确定性选出至少一个同组 lure 和一个跨组 lure，并执行全候选快照的 Atom 去重；
5. 让该阶段另行冻结的单一生产模型根据冻结 trigger/Cue 提出提醒意图与生命周期规则，不允许改写 trigger predicate；
6. 程序验证 cue→atom/type/predicate 血缘、split、来源组别、失败子句和全局不复用；
7. 人工删除不自然、不可观察、无法状态机化或当前画面直接泄露答案的候选；
8. 每个 Seed 保存 accept/revise/reject 状态与理由。

`lexical_jaccard_v1` 只保留作历史 fixture/对照，不得出现在正式生产路径。Source→Cue 候选筛选先校验 `visible_text` 是 transcript/dense_caption 的派生字段，再只按独立 transcript、dense_caption 构造 passage；不得编码 visible_text，也不得加入人物、日期、组别、split 或视频时间戳元数据。查询族固定为 `Person / Location / Object / Activity / State / Explicit-Time`，六族全部进行 dense、sparse 和 RRF 召回、全部报告且不设配额。

全维 1024 维 BGE 向量用于检索与候选距离；粗粒度 diversity 使用固定投影至 256 维、65,536 条确定性分层样本和 1,024 簇 MiniBatchKMeans。核心 10,000 条至少有 3,500 条 diversity 主选、2,000 条不在 query union；随后按稀有簇与新颖度门补样，达到 12,000 或一整轮无新增时停止。具体精度、聚类、cluster ID、排序和缓存合同以 `wsl_BGE-M3_filter/` 为准。

BGE embedding 与索引是绑定 Source SHA、Cue manifest SHA、模型修订、序列化版本、依赖版本和参数哈希的可重建缓存，不是正式基准数据；正式检索结果保存稠密 rank、稀疏 rank 与 RRF 分数。若不复用或同组/跨组约束导致候选不足，应按固定排名扩大检索深度或更换 trigger，不能放宽规则；统计报告必须披露这类缺口。

### 5. Seed 示例逻辑

真实 trigger atom：人物进入厨房并开始准备食物。  
构造意图：下次开始做饭时提醒我把冷藏药品拿出来。  
trigger predicate：`location/at/kitchen` AND `activity/starts/cooking`。
lure 1：人物在厨房聊天，但没有开始做饭。  
lure 2：人物在餐桌吃饭，但地点和活动都不满足。  
negative history：这项任务此前已取消。  
正分支 gold：到 trigger 时 remind。  
负分支 gold：同一 trigger 时 silent。

这只是结构示例，正式 Seed 必须引用真实 atom_id，不能凭空写 scene。

---

## 九、第四阶段：Seed 审计与 Rule Bank 冻结

### 1. 两级审计

第一层由该阶段另行冻结的低成本审计模型检查；DeepSeek 仅少量用于争议第三意见：

- trigger 是否真的满足所有谓词；
- lure 是否只相似而不满足；
- lifecycle 是否有明确状态转移；
- matched counterfactual 是否可构造；
- 是否存在答案泄露；
- 是否出现模型臆造的来源事实。

第二层由人工逐个审计全部候选。任何模型只能提供意见，不能替代人工签字。

### 2. 审计结果

每个候选只能是：

- accept：无需语义修改，可冻结；
- revise：保留核心，但需要修改 predicate、lure 或 lifecycle；
- reject：不可观察、不可解、泄露、无合格 lure、规则含糊或跨 split。

目标是冻结 480 个。若少于 480 个，按预注册排序扩大 Cue/Seed 候选池；不得降低可观察性、lure、状态机、反事实或 split 标准，也不得强行保留不清晰 state。

### 3. 冻结后不得随意改

冻结 reminder_seeds_frozen.jsonl、rule_bank.jsonl 与 state_machine_policy.yaml 后，派生 6 条 Life Log。若修改某个 Seed 的核心 predicate 或 terminal policy，必须重新生成其整个 family 和所有 gold。

---

## 十、第五阶段：状态机与成对反事实

### 1. 最小状态集合

建议每个 intention 至少有：

- active_unreminded；
- active_reminded；
- completed；
- cancelled；
- expired。

状态转移由构造事件和规则驱动。例如：

- create_intention → active_unreminded；
- completion_event → completed；
- cancel_event → cancelled；
- virtual_time 超过 deadline → expired；
- trigger 且仍 active_unreminded → 输出 remind，然后进入 active_reminded。

### 2. Oracle 决策逻辑

~~~text
if trigger_predicate(current_atom) is false:
    silent
elif intention_state is not active_unreminded:
    silent
elif current_time is outside valid_window:
    silent
else:
    remind(intent_id)
~~~

金标必须由这个冻结逻辑产生。千问可以帮助写规则草案，但不能直接为每一行填 remind/silent。

### 3. 成对反事实要求

每个 positive 与 matched-negative 必须：

- 使用完全相同的当前 trigger atom；
- 使用相同的核心意图文本与 trigger predicate；
- 只改变一个足以翻转动作的历史条件；
- 负分支从 completed、cancelled、expired、already_reminded 中选择；核心统一数据不使用 never_created；
- 除位置相同的一条 constructed 生命周期控制事件外，Source Atom、事件数、trigger/lure 位置和背景序列全部相同，成对 token 差异不超过 5%；
- 由 validator 检查正分支为 remind、负分支为 silent。

不同 family 应轮换负例类型，不能全部只用 cancelled。

---

## 十一、第六阶段：同一任务生成短、中、长三种记忆难度

难度不是把同一视频机械拉长，也不是仅改变分钟数。它由“必须记住的信息与干扰之间的距离和负载”定义：

| 难度 | 建议事件数 | 背景意图 | 干扰密度 | 建议虚拟跨度 |
| --- | ---: | ---: | --- | --- |
| short | 12 | 0 | 低 | 60 分钟 |
| medium | 36 | 2 | 中 | 360 分钟 |
| long | 72 | 5 | 高 | 2,880 分钟，可跨日 |

这些是进入批次 B/C 和 token 校准的推荐单值，不得在不同样本中随意从旧区间取值。若校准表明某个值会导致 token 超限，只允许在正式生成前统一调整该难度的单值；生产开始后不能按样本改变事件数。

三种版本必须保持：

- 相同核心意图；
- 相同 trigger atom；
- 相同反事实条件；
- 相同正确动作；
- 相同 trigger predicate。

只改变：

- 意图到 trigger 的距离；
- 背景事件和相似 lure 数量；
- 并行意图数；
- 状态更新次数；
- token 负载；
- virtual span。

真实 source_time 与 virtual_time 必须分开保存。Source Atom 的内部顺序不能颠倒，但来自不同来源段的 atom 可在明确标记的虚拟时间轴中重新排列。不要声称这些排列是 EgoLife 中真实连续发生的一周。

---

## 十二、第七阶段：Life Log 组装

09_build_lifelog_families.py 读取冻结 Seed，先生成 family spec，再派生 6 条 log：

~~~text
Seed A
├─ positive-short
├─ positive-medium
├─ positive-long
├─ negative-short
├─ negative-medium
└─ negative-long
~~~

每条 Life Log 固定服务一个目标意图，并且固定包含：

- 一条目标意图创建事件；
- 一条 constructed 生命周期控制事件；
- 两条真实 lure 观察，其中一条同 source group、一条跨 source group；
- 一条真实 trigger 观察；
- 固定数量的背景 Source 观察与背景意图。

同一 family 的六条日志共享完全相同的 trigger、两条 lure 和背景 Source Atom 序列。positive/negative 成对日志只替换生命周期控制事件：positive 表示意图仍有效，negative 表示已完成、已取消、已过期或已经提醒；最终出现的是同一个 trigger，因此 gold 的变化只能来自记忆状态。核心 2,880 条不使用 `never_created`，因为统一骨架已经包含意图创建；该类型如需研究只能另作结构消融。

推荐在 token 校准后把 short/medium/long 固定为 12、36、72 个事件，背景意图分别为 0、2、5，虚拟跨度候选为 60、360、2,880 分钟。同一难度事件数完全相同，正负配对 token 差异不超过 5%。目标相关 Source 观察始终为三条，即一个 trigger 加两个 lure；难度只能通过背景量、时间跨度和干扰接近度变化。

主记录中的每个事件至少需要：

- event_id；
- family_id；
- lifelog_id；
- virtual_time；
- source_time 或 null；
- atom_id 或 null；
- event_kind；
- visible_text；
- source_srt_paths；
- source_video_path；
- rule_id；
- intention_state_before；
- intention_state_after；
- event_role；
- provenance。

event_role 可包括 intention_creation、background、lure、trigger、completion、cancellation、expiry、reminder_history。该字段属于构建审计信息，正式模型输入中必须移除，避免泄露答案。

模型可见事件进一步精简为 `event_id`、顺序、`virtual_time`、观察文本、provenance 和必要的 `atom_id`。真实观察只能使用 Source 原字段或包含完整证据的确定性连续窗口；超过文本上限时更换 Atom 或按固定窗口截取，不得由模型概括改写。Cue ID、predicate、event_role、状态前后值、反事实分支、gold、Evidence Set 和 oracle 理由全部留在隐藏标注。

组装约束：

- 优先保持同一 Life Log 的场景和人物组合合理；
- 跨 participant 组合必须避免暗示其为同一真实人物经历；
- 构造桥接事件只能表达意图和生命周期，不能伪造 EgoLife 视觉事实；
- 同 family 共用 trigger 和核心 lure；
- 正负分支共用同一 trigger、lure、背景 Source 序列和对应位置，只允许一条生命周期控制事件不同；
- 构造意图和生命周期文本优先使用受控模板；即使使用语言模型润色，也只能修改 constructed 文本并锁定实体占位符；
- constructed 文本中的现实人物、地点、物体和关系必须来自已验证 Cue/Source，不得自由添加；
- 每个正式 log 记录 referenced_source_seconds；
- 重复引用同一 atom 可以计入 manifest_referenced_hours，但不能重复计入 unique_source_hours。

---

## 十三、第八阶段：生成 Decision Instance 与 Evidence Set

10_run_oracle.py 逐事件推进状态机。在协议规定的每个决策点输出：

- 当前观察；
- 允许访问的预算记忆输入；
- gold action；
- active intention ledger；
- lifecycle state；
- minimal evidence set；
- counterfactual_pair_id；
- difficulty；
- split。

Evidence Set 至少区分：

- intention evidence：用户先前要求什么；
- trigger evidence：当前为什么满足条件；
- state evidence：任务是否仍有效；
- reminder-history evidence：是否已经提醒；
- distractor evidence：为什么相似事件不应触发。

Evidence Set 用于监督和分析，但不能把 event_role、gold 或规则答案直接拼进模型当前输入。

---

## 十四、第九阶段：全量验证，而不是 smoke

11_validate_all.py 对全部数据逐条执行。任何一条失败都进入 validation_errors.jsonl，修复后从受影响上游阶段重新生成。

### 1. Schema 与来源

- 所有 JSONL 可逐行解析；
- required 字段完整；
- 每个 source atom 的 SRT 路径存在；
- 时间范围合法；
- atom_id、event_id、lifelog_id 唯一；
- 构造事件具有 rule_id；
- 不存在伪造的 MP4 路径。

### 2. 决策与状态

- 每次状态迁移合法；
- completed/cancelled/expired 后不能再次提醒；
- already_reminded 满足冷却或一次提醒策略；
- 正分支在指定窗口 remind；
- 负分支在相同 trigger silent；
- 非 trigger 与 lure 不能误触发。

### 3. 反事实与难度

- pair 当前 trigger atom 完全相同；
- pair 只改变声明的历史变量；
- gold 必须翻转；
- 三种难度共享核心规则；
- short < medium < long 的事件数、距离和 token 负载总体成立；
- negative 不是通过删除当前 cue 作弊。

### 4. Split 与泄漏

- family 不跨 split；
- 共享 source atom 不跨 split；
- 近重复字幕和共享世界事件不跨 split；
- prompt 中不出现 gold、event_role、规则解释；
- train 中不存在 test Seed 的改写副本。

### 5. 人工复核

- 全部 Reminder Seed 人工复核；
- 全部 accept/revise/reject 有原因；
- 派生 Life Log 按 cue 类型、难度、split、负例类型分层抽取至少 10%；
- 所有发现的问题都记录 issue_type、修复方式和影响范围。

---

## 十五、时长与规模应该怎样统计

每个正式阶段的分布报告统一写入：

```text
egopm_bench_v1/audit/distributions/<stage>/<snapshot_id>/
```

目录必须包含机器可读的 `distribution_manifest.json`、按模型/split/参与者/模态/分片统计的文件、阶段特有维度、`semantic_gate_report.json`、人工阅读的 `distribution_report.md` 和 `DISTRIBUTION_SUCCESS.json`。即使只有一个模型也必须生成模型分布，以证明阶段内没有混用。对应生产 SUCCESS 必须绑定 `distribution_manifest_sha256`；只写 Markdown 摘要不能通过门禁。

至少同时报告三种时长：

1. manifest_referenced_hours：所有正式 Life Log 引用的 Source Atom 时长之和，反事实与难度重复引用会重复计算；
2. unique_source_hours：对 atom_id 去重后的真实 EgoLife 来源时长；
3. virtual_span_hours：每条虚拟时间轴首尾时间差之和。

“覆盖 100–120 小时”默认指第一项，论文中不能把它写成“新增了 100–120 小时互不重复的原视频”。最终统计表还应包括：

- Source Atom 数；
- Cue 数及类型分布；
- 900–1,400 个候选的接受、修改、拒绝数；
- 最终 Seed 数；
- Life Log 数；
- Decision Instance 数；
- 各场景、人物、天数、trigger 类型、负例类型和难度分布；
- 正负配对动作翻转成功率；
- SRT 对齐率、单模态率和来源失败率；
- 三种时长。

---

## 十六、完整项目推进表

| 阶段 | 主要输入 | 核心动作 | 必交付物 | 进入下一阶段的门 |
| --- | --- | --- | --- | --- |
| A. 原始清点 | 全部 SRT | 文件 inventory | srt_inventory.csv | 无漏扫、错误可追踪 |
| B. 原子建库 | SRT inventory | 解析、对齐、宽松保留 | source_video_atoms.jsonl | schema、来源、时间全通过 |
| C. 来源冻结 | atom 库 | 去重、分组、split | source_split_map.jsonl | 无跨 split 泄漏 |
| D. BGE 候选筛选 | atom 库 | WSL 单 GPU 的 dense+sparse+多样性筛选 | 10,000–12,000 个候选 Atom + proof + 综合报告 + manifest + SUCCESS | 固定 revision、Source/request SHA、WSL 数值审计、T4 离散 proof/分布/人工样本通过 |
| E. Cue v2 建库 | BGE selection | 三个百炼账号、同一 Flash 协议、程序语义门 | 约 3,000–5,000 条 Cue 分片 + manifest + SUCCESS | 每个 clause 有原字段证据，语义与分布门通过 |
| F. Seed 候选 | Cue v2 manifest | 固定单一模型决策优先生成 | 900–1,400 个 candidates | 每个有唯一 Cue 血缘、同组+跨组 lure、全局不复用与 terminal |
| G. Seed 冻结 | candidates | 低成本模型意见 + 人工终审 | 480 个 frozen Seeds | 全部可状态机化且血缘/组别/不复用检查通过 |
| H. Family 生成 | frozen Seeds | 2 反事实 × 3 难度 | 2,880 条 Life Logs | 核心规则一致 |
| I. Gold 编译 | Life Logs + rules | oracle 展开 | decision/evidence JSONL | 金标与状态全通过 |
| J. 全量验收 | 全部产物 | 验证、泄漏、人工抽检 | audit + statistics | 零阻断错误 |
| K. 基准发布 | 验收数据 | dataset card、评分器 | benchmark release | 可从配置完整重建 |

一个人执行时，每完成一行就提交对应产物和报告，不同时手工改多个下游 JSON。以后若增加协作者，可以按阶段分工，但 schema、rule bank、split 和 protocol 的冻结权应由同一负责人统一管理。

---

## 十七、现在立刻应该做的事情

历史 Source 阶段已经完成；当前从以下顺序继续，不要先生成 Seed 故事：

1. 按 CR-2026-018/019/020 实现 Cue Schema v2、selection contract、三账号账本/租约和 T4 语义门；
2. 将 `wsl_BGE-M3_filter/` 复制到 WSL，创建专用 `.venv-bge-m3`；
3. 执行已拆分并冻结的 BGE selection v3.1（根 request、模型配置、48 行查询集、选择策略、两个必要 Schema），导入并验证 10,000–12,000 个候选 Atom 及精简 proof；
4. 将候选静态分给三个阿里云账号，使用同一 `qwen3.7-flash` 协议写隔离 staging；
5. 协调器生成 Cue v2 正式分片、分布报告、manifest 和 SUCCESS；
6. 选择并冻结 Seed 生成模型，生成 900–1,400 个 candidates；
7. 完成机器门、低成本模型意见和全部人工终审，冻结 480 个 Seed；
8. 在生成 Life Log 前冻结其模型、布局和协议参数。

在第 4 步以前，不需要下载 EgoLife 原视频，也不需要拼接视频。MP4 映射可先保存为 pending；真正做视觉扩展时，只根据最终使用到的 atom manifest 按需下载相关视频，而不是下载整个 EgoLife 视频集合。

---

## 十八、Definition of Done

EgoPM-Bench v1 只有同时满足以下条件才算完成：

- 全部正式 atom 可追溯到 SRT；
- SRT 路径与 MP4 定位字段含义清楚；
- 480 个合格 Seed 来自 900–1,400 个候选的真实审计结果；
- 每个 Seed 有真实 trigger、至少两个真实 lure 和完整 silent 逻辑；
- 每个 Seed 派生 6 条匹配 Life Log；
- gold 全部由同一冻结 oracle 生成；
- 正反事实在相同当前 trigger 上稳定翻转动作；
- short/medium/long 真正改变记忆负载而不改变任务语义；
- family 与 source group 无跨 split 泄漏；
- 2,880 条 Life Log 通过全量机器验证和分层人工抽检；
- 三种时长与全部分布统计透明报告；
- 模型、prompt、schema、规则、随机种子和日志足以复现；
- 文本主轨道可以独立运行，未来视频轨道能通过相同 atom_id 接入。

达到这些条件后，得到的不是“把 EgoLife 片段随意拼成一周”，而是一个有真实生活场景依据、由明确规则生成、专门考察长期记忆状态与主动提醒决策的可复现 benchmark。
