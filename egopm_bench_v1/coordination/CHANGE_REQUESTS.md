# CHANGE_REQUEST 登记册

初始化合同版本：`v1.0.0`。

| 编号 | 日期 | 提出者 | 受影响合同 | 摘要 | 兼容性 | 决定 | 目标版本 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CR-2026-001 | 2026-08-31 | T0 | 治理合同与生产指南 | 新增 Python 中文模块说明和关键中文注释的合并硬门禁 | 仅治理规则变更；数据 Schema/配置仍为 `v1.0.0`，无需重生成数据 | 批准 | 治理合同 `v1.1.0` | DONE |
| CR-2026-002 | 2026-08-31 | T1 | Source 配置与 Source Atom 产物 | 冻结文本对齐容差、原子合并时长和连续性规则 | 新增或变更冻结参数后，必须重建全部 `source/**` 及下游产物 | 批准：容差 `2.0` 秒，Dense Caption 主窗口，禁用相邻窗口合并 | 配置合同 `v1.1.0` | DONE |
| CR-2026-003 | 2026-08-31 | T1 | Source Atom Schema 与第 03/04 步接口 | 区分未 split 的草稿原子与最终 Source Atom | 若增加草稿工件或改变中间 `split` 语义，必须重建全部正式 Source 及下游产物 | 批准：草稿使用独立路径与 Schema，`atom_stage=draft`、`split=null`；最终原子为 `atom_stage=final` | 配置合同与 Source Schema `v1.1.0` | DONE |
| CR-2026-004 | 2026-08-31 | T1 | `split_policy.yaml` 与 session 邻接比较 | 定义跨 session 的可复现时间顺序与 `max_gap_seconds` 适用边界 | 规则变更会影响 split map、Source SUCCESS 及全部下游产物 | 批准：同一人同一天的全部不同 session 对均比较；禁止以 session 相对秒排序或使用 `max_gap_seconds` | 配置合同 `v1.1.0` | DONE |
| CR-2026-005 | 2026-08-31 | T2 | 检索配置、路径与 Schema | 以固定修订的 `BAAI/bge-m3` 稠密+稀疏混合检索替换 `lexical_jaccard_v1` | 需重建检索集合、Seed candidates 及所有后续产物；不影响已冻结 Source/Cue | 方案批准；无 API 实现已完成，待本地固定权重和正式检索验证 | Seed 数据合同 `v1.1.0` | IN_PROGRESS |
| CR-2026-006 | 2026-08-31 | T4 | 反事实配对与 Evidence Set Schema/成功标记 | 为 `counterfactual_pairs.jsonl` 和 `evidence_sets.jsonl` 增加可审计的 Schema 与哈希边界 | 若字段或语义改变，必须重建相应 Life Log、Decision、QA、统计和数据集卡 | 待决定 | 数据合同后续版本 | 待决定 |
| CR-2026-007 | 约 2026-09-01 | T2 | 第 05 步执行协议 | v2 无 API 实施：实时执行器、无正文账本、恢复与路径门 | 无 API；未运行正式 Cue 时不要求重生成数据 | 批准 | 执行协议 v2 | DONE |
| CR-2026-008 | 约 2026-09-02 | T0 | 第 05 步执行协议 | v2.1 Batch File 无 API 设计与核算（北京半价） | 仅更新文档，未冻结配置、未写代码 | 已登记 | 执行协议 v2.1 | 已登记 |
| CR-2026-009 | 约 2026-09-02 | T2 | 第 05 步执行协议 | v2.2 紧凑推理协议与 96 token/Atom 无 API 设计 | 短码只存在于模型推理对象，程序回填最终 Cue Schema | 批准 | 执行协议 v2.2 | DONE |
| CR-2026-010 | 2026-09-05 | T0 | 模型登记表 | Batch 模型标识修正为基础别名 `qwen3.7-flash`（修复 `model_not_found`） | Source 覆盖、Batch 价格、八波计划与预算上限不变 | 批准 | 登记/执行协议版本升级 | DONE |
| CR-2026-011 | 2026-09-05 | T0 | 第 05 步执行协议 | 取消 Batch File 改用实时 API，旧 Batch 结果不得读取或混入 | 授权须重新绑定新协议 SHA | 批准 | 实时执行协议 v3 | DONE |
| CR-2026-012 | — | — | — | 编号保留；尚无权威材料可赋予合同语义 | 不适用 | 待核对 | — | 待核对 |
| CR-2026-013 | 2026-09-06 | T0/T2 | 第 05 步模型证据协议 | 升级到 v3.6；模型返回 `n,f,x,p,c,v,e,s,a,r`，`x` 仅能在 `f` 指定的单一原字段中按冻结归一化规则连续匹配，并从原字段确定性切出最终 span | 不改变 Source；旧 v4–v8 run 只可审计，不得混入或重跑 | 批准；协议 SHA256 `c7d809927f9cca4ff7d4501a0121c419768cd95c1d3c05d13b156000c50fbbb5` | 实时执行协议 v3.6 | DONE |
| CR-2026-014 | 约 2026-09-05 | T0/T4 | 第 05 步覆盖闭合 | 将「每包都成功」改为「每个 Atom 均有可审计终态」（`coverage_disposition.jsonl`） | 覆盖账本以逐 Atom 终态为准 | 批准 | — | 已冻结 |
| CR-2026-015 | 2026-09-06 | T0 | 第 05 步实时执行 | 内容安全过滤器对口语字幕返回 400 `data_inspection_failed` 时不应停整波；新增 `content_filtered` 终态与 `excluded_content_filtered` 覆盖处置 | 无 API；需要已落盘的旧 `service_transport_exhausted` 包在续跑时被新代码重分类为 `content_filtered` | 批准 | 执行语义扩展（不改变冻结 Source/协议哈希） | DONE |
| CR-2026-016 | 2026-09-09 | T0 | 正式产物存储与 SUCCESS 合同 | 将阶段完成定义为一个逻辑快照；Source/Cue 允许 manifest+分片，Seed/Frozen/Life Log 保持单文件，Decision/Evidence 延后按规模冻结 | 已冻结 Source 不重建；Cue 已将 75 个 task 物化并由顶层 manifest/SUCCESS 统一绑定，T4 Cue 专项零阻断 | 批准；实现与 T4 Cue QA 已完成 | 治理合同 `v1.2.0` | DONE |
| CR-2026-017 | 2026-09-09 | T0 | Seed Schema、检索结果与审计规则 | 新增必填 `trigger_cue_id`；冻结 cue→atom/type/predicate 血缘、同组+跨组 lure 构成、失败子句和跨 Seed 禁止复用；后续模型统一 Plus | Schema/配置/06–08/T4 已升级；正式 BGE 权重缺失，Seed 仍不得启动 | 批准；无 API 实现已完成，待 BGE 检索与 T4 验证 | Seed 数据合同 `v1.1.0` | IN_PROGRESS |
| CR-2026-018 | 2026-09-09 | T0 | Cue v1 语义资格与 Cue v2 Schema | V9 虽通过旧结构 QA，但出现 `time` 塌缩、字符串 `null`、人物进入时间槽、冗余字段全空和自报 confidence 失真；旧 Cue 撤销 Seed 上游资格，Cue v2 改为 clause-level predicate/evidence、仅 `all_of`、删除冗余逐行字段 | 破坏性 Cue Schema 变更；V9 保留不可变审计，不覆盖、不混入；Seed 及全部下游必须从 Cue v2 重建 | 方向批准；待 Schema、prompt、执行器和 T4 语义门实施 | Cue Schema `v2.0.0`、治理合同 `v1.3.0` | IN_PROGRESS |
| CR-2026-019 | 2026-09-10 | T0 | Cue v2 候选选择与 WSL BGE-M3 | 不再全量生成 370799 条 Cue；固定 BGE-M3 形成 10,000–12,000 条；六查询族无配额；v3.1 补齐两个必要 Schema、单 passage、Unicode 规则、近重复全序和 CP-SAT 精确求解 | 旧 v3 草案身份作废且尚无正式输出；v3.1 使用新 selection ID 与组件 SHA，不影响冻结 Source 或旧 V9 审计 | 方向与 v3.1 机器请求已冻结；待 WSL 实现、正式运行和 T4 proof/人工精度复核 | BGE selection protocol v3.1 | IN_PROGRESS |
| CR-2026-020 | 2026-09-10 | T0 | Seed 规模、模型、三账号并行、账本和分布报告 | Seed candidates 调整为 900–1,400，Frozen Seed 固定 480；Cue 抽取沿用同一 `qwen3.7-flash` 协议并允许三个阿里云账号处理静态分区；各 worker 独立授权/预算/账本；阶段分布精简为机器报告、中文摘要、manifest、SUCCESS 四文件 | 替代 CR-017 中后续统一 Plus、35–40 Seed 和小规模单文件假设；Seed/Life Log 布局需按新规模重新冻结；旧账本不迁入 | 方向批准；待配置、Schema、执行器、恢复工具和 QA 实施 | 治理合同 `v1.4.0` | IN_PROGRESS |
| CR-2026-021 | 2026-09-10 | T0 | Cue v2 主线切换批次 A 与全项目工件节制 | 建立旧 V9 只读审计边界和迁移矩阵；整个仓库每个落实单元默认最多新增 1 棵持久目录树和 5 种非分片机器工件，报告合并，正式目录测试必须断言文件集合恰好相等 | 适用于根目录、主流水线、WSL 包和 T0–T4 全部阶段；子合同只能收紧；不重排不可变历史产物 | 方向批准；批次 A 进行中 | 治理合同 `v1.4.2` | IN_PROGRESS |
| CR-2026-022 | 2026-09-15 | T0 | 全流程事实边界、Cue 三层语义门与统一 Life Log 骨架 | Cue 固定为一个 predicate、1–3 个 `all_of` clause；依次验证字段内连续 span、value 直接支持和完整断言语义；简短 Cue 必须有可识别指向；统一每条 Life Log 的意图创建、生命周期控制、同一 trigger 与两条 lure | 破坏性收紧 Cue/Seed/Life Log 语义；不修改 Source/BGE 数据；Cue v2 尚未生产，无需重生成正式 v2；旧 V9 继续只读审计 | 设计批准；待批次 B/C 实现 Schema、prompt、代码、测试与协议验收 | 治理合同 `v1.5.0`、Cue Schema `v2.0.0` | IN_PROGRESS |

> 注：`CR-2026-012` 继续保留为空号，未获得权威材料前不得补写语义；`CR-2026-013` 已按冻结的 v3.6 协议与 SHA 补录。

## 提交模板

```text
### CR-YYYY-NNN
- 提出者 / handoff：
- 当前合同版本：
- 受影响字段与产物：
- 现有合同无法表达该需求的原因：
- 建议的兼容修改或迁移方式：
- 必须重新生成的上游/下游产物：
- 证明该问题的测试：
```

仅 T0 可以登记、决定和关闭请求。工作对话仅可在自身 handoff 文件中提出请求，且解释性正文必须使用中文。

## T0 决议说明

### CR-2026-002

`paths.yaml` 已冻结 `transcript_dense_caption_tolerance_seconds: 2.0`。Dense Caption 是主窗口；未命中的单模态窗口保留。v1 不合并相邻字幕窗口，也不按窗口时长淘汰记录；超过 30 秒的窗口只写入报告，供后续审计。

### CR-2026-003

第 03 步只能写 `source/source_video_atoms_draft.jsonl`，并以 `source_video_atom_draft.schema.json` 验证。草稿记录的 `atom_stage` 必为 `draft`，`split` 必为 `null`。第 04 步必须先验证草稿，再写唯一正式路径 `source/source_video_atoms.jsonl`；最终记录的 `atom_stage` 必为 `final`，`split` 必为 `train`、`dev` 或 `test`。没有 `SOURCE_ATOMS_SUCCESS.json` 的草稿永远不可被下游读取。

### CR-2026-004

`normalized_start_sec` 与 `normalized_end_sec` 只表达单个 session 内的相对秒，绝不可推断不同 SRT session 的真实先后。为避免不可复现的邻接猜测，近重复检查固定为同一 `participant_source_id`、同一 `source_day` 的全部不同 session 对；不使用 `max_gap_seconds`。

### CR-2026-005

生产检索固定为 `bge_m3_hybrid_rrf_v1`。模型为 `BAAI/bge-m3`，修订固定为 `5617a9f61b028005a4858fdac845db406aefb181`；采用官方稠密 CLS 表示与稀疏词项权重，最大输入长度 `512`，稠密向量归一化并以 FP32 内积排序。每个通道保留前 `64` 个候选，按确定性 RRF 合并：`1 / (60 + rank_dense) + 1 / (60 + rank_sparse)`；同分依次以 `atom_id` 升序打破。v1 不引入 reranker，避免新增未冻结模型和不可比评分。

每个 split 的 Source corpus 只编码一次。规范化固定为 Unicode NFKC、将连续 Unicode 空白折叠为一个 ASCII 空格并去除首尾空白，保留大小写和标点。query 按固定字段顺序序列化为 `cue_type`、去重后按 Unicode 码点排序的 `entities`、`scene_type`、`activity_type`、按键排序且无多余空白的 `normalized_predicate` JSON、`supporting_text_span`；null 统一写为空字符串。passage 只序列化 `transcript` 与 `dense_caption` 两行，不加入 participant/day/group/split 等可能形成捷径的元数据；空字段保留空值。query/passage 均由模型 tokenizer 截断到 `512` token，不跨 Atom 拼接。

编码固定 `use_fp16=false`，稠密向量转 FP32 后 L2 归一化；稠密侧使用 CPU `IndexFlatIP` 等价的精确内积，不使用近似 ANN。检索索引与 embedding 是绑定 Source SHA、Cue manifest SHA、模型修订、序列化版本、依赖版本和参数哈希的派生缓存，不是正式基准产物。正式输出只保存候选 Atom、两通道 rank、RRF 分数和必要血缘。T4 必须验证 `lexical_jaccard_v1` 已完全退出生产路径，并从固定抽样 query 独立复算排名；若跨设备出现数值差异，以冻结检索产物哈希为本次发布依据，不得把不同环境结果混成一个候选快照。

### CR-2026-016

正式阶段的科学完整性由“一个有序逻辑快照”保证，而不是由单文件大小保证。Cue 以 task `000`–`074` 的 75 个不相交 JSONL 分片为正式数据面；`cues/cue_library_manifest.json` 是唯一入口，按 task 顺序列出每个分片的相对路径、SHA256、行数、字节数、Atom 覆盖范围、Source SHA、协议 SHA 和 `realtime_run_id`。`CUE_LIBRARY_SUCCESS.json` 绑定 manifest SHA、75 个分片、Cue 总数及四类 disposition 总数。package 文件和 Wave ledger 继续作为审计证据，但不得被 Seed 直接读取。

单文件 `cue_library.jsonl` 若生成，只是可删除、可重建的便利缓存。已冻结 Source 单文件不为布局升级重跑。Seed candidates、Frozen seeds 与 Life Log 继续单文件；Decision/Evidence 在正式生成前根据预计字节数、行数和并发需求另开 CR 决定。

### CR-2026-017

Seed 必填 `trigger_cue_id`，并满足 `Cue.atom_id == trigger_atom_id`、`Cue.cue_type == primary_cue_type`、`Cue.normalized_predicate == trigger_predicate`。每个 lure 审计项必须保存 `atom_id`、`source_group_id`、与 trigger 的组别关系、未满足的 predicate 子句序号，以及 BGE 两通道 rank/RRF 分数。每个 Seed 至少一个同组 lure 和一个跨组 lure；全部 lure 与 trigger 同 split。

同一正式候选快照内，trigger Cue、trigger Atom 和 lure Atom 均全局唯一，不得跨 Seed 复用。被拒 Seed 的 Atom 只能在生成一个全新候选快照时释放并重新分配。模型生成使用 `qwen3.7-plus-2026-05-26` + `reasoning_effort=medium`；模型审计使用同一 Plus 快照 + `reasoning_effort=high`；人工对全部候选独立签字，模型不得替代人工终审。

若稀有 cue 类型因全局不复用或同组/跨组构成而不足，不得降低规则或复用 Atom；按固定排名继续扩大候选深度，仍不足则将该候选记为不可构造并扩大 trigger 候选池。最终报告必须给出每类缺口和被去重占用的数量，避免静默改变样本分布。

### CR-2026-018

旧 `realtime_v9_01` 的执行账本、费用、coverage/disposition、75 个正式分片、manifest 和 SUCCESS 全部保持不可变。其 T4“0 blocker”解释限定为旧合同下的结构、哈希、Source 血缘与证据片段检查通过；不得扩张解释为 predicate 语义正确。Seed 和后续正式阶段不得再读取旧 Cue manifest。

Cue v2 正式行只包含稳定 `cue_id`、`atom_id` 和 `predicate.all_of`。每个 clause 必须含完整词形式的 `dimension`、`operator`、`value` 和单字段 `evidence.field/evidence.span`。删除顶层 `cue_type`、`confidence`、`entities`、`scene_type`、`activity_type`、重复 Source 正文和逐行运行元数据。`split`、Source 文本和参与者信息由 `atom_id` 回查；模型、prompt、Schema、run 和参数写入 campaign/shard manifest。

模型候选判断允许 `accepted/no_cue/ambiguous`；`ambiguous` 复核后必须转为 `accepted_cue`、`excluded_no_cue` 或 `excluded_ambiguous`。正式 Cue 分片只含第一类，其他终态只进入无正文 disposition。Cue 只表达一个 Source Atom 中可直接观察的事实，并只允许 `all_of`；`any_of`、虚拟时间、跨 Atom 条件和生命周期规则属于 Seed/Rule。

T4 新增 clause-level 语义门：证据必须来自指定原字段，value 必须被其直接支持，dimension 不得错槽，time 必须有明确时间语义，所有 `null/none/unknown/n/a` 变体为零，禁止跨字段/跨 Atom 拼接和释义。Schema 正确但语义不正确必须计 blocker。

### CR-2026-019

WSL2 使用专用 `.venv-bge-m3`、单 GPU 单编码进程和固定 `BAAI/bge-m3@5617a9f61b028005a4858fdac845db406aefb181`。候选 selection 由确定性资格过滤、dense 查询召回、sparse 查询召回、RRF 和 dense 多样性补足的并集组成；按 split、参与者、模态和 `source_group_id` 分层去重。BGE 只决定候选 Atom，不生成 predicate 或 accepted 判断。

WSL 执行包位于 `wsl_BGE-M3_filter/`。当前冻结 selection 为 `bge_m3_source_select_v3_1_20260910_01`，根请求 SHA256 为 `921024d8b4621fb8f8a8d600e191f4ba3d7406325bc4b5a17954863b7f435baa`。根请求不含自身 SHA；它直接绑定模型配置、48 行查询集、选择策略，以及两个必要 Schema。Source 行 Schema SHA256 为 `0d576ed34f4a4d19fa38294392bb277306bba145f0492015fe909709c8be92e4`，统一 artifact Schema SHA256 为 `283c6de2a0bf7ab3a222b76ab65ba6c1fa6010fe569b6b9dc1f9b08de4b0e3da`，选择策略 SHA256 为 `02f812f01a72fd50cda220c7fc31f49e0483be36980dd1bd208685a525508065`。不另建 schema manifest、Source SUCCESS Schema 或规范化测试文件。

筛选先形成 10,000 条核心候选，再以稀有 cluster 轮转、新颖度严格大于 `0.08` 和每簇扩展软上限 12 补样，达到 12,000 或完整一轮无新增时停止。六查询族 `Person / Location / Object / Activity / State / Explicit-Time` 全部召回并报告，不设任何类别配额。核心至少 3,500 条 diversity 主选，其中至少 2,000 条不在 query union；同簇近重复阈值仍为 cosine distance `<=0.04`，每簇全局上限 20。

全维 1024 维 BGE FP32 向量用于检索和最终距离；聚类使用固定稀疏随机投影至 256 维，并在 65,536 条确定性分层样本上训练 1,024 簇 MiniBatchKMeans。cluster ID 从规范 centroid 字节生成且只在 snapshot 内稳定。`visible_text` 不编码也不输出；视频/session 的 `event_timestamp` 不得变成未来 `temporal_condition`。

Windows 回传恰有候选、`selection_proof.jsonl`、综合报告、manifest、SUCCESS 五个文件。T4 不重跑 BGE，从 proof 和 Source 复核 rank、RRF、归因、候选成员、离散约束与分布；全库 embedding/top-k/cluster 数值正确性和 CP-SAT 最优性由 WSL 本地完整审计承担并由 manifest 绑定审计根。

每个 Atom 的 passage 固定按 transcript、dense caption 顺序组成一个字符串并只编码一次；资格规范化固定 Unicode 15.0.0，六个测试向量直接内嵌策略。近重复 survivor 使用不依赖 reservoir 的静态全序，随后才构造 reservoir。核心 10,000 条由固定单 worker OR-Tools CP-SAT 四阶段词典序求解，每阶段必须为 `OPTIMAL`，固定目标后重复两次的选中 Atom SHA 必须一致；否则阻断，不得用贪心失败宣称不可行。

正式返回 Windows 的 selection 进入 `cues/v2/source_selection/<selection_id>/`。逐 Atom 全量 cluster assignment/原因、embedding、稀疏权重、索引、模型、checkpoint 和日志均留在 WSL 本地；精简 query/rank/score 与候选/cluster/shard/audit_sample 证明统一写入 `selection_proof.jsonl`。导入门必须复算 Source SHA、模型 revision、request/组件哈希、候选唯一性和综合分布报告。

### CR-2026-020

Cue v2 目标约 3,000–5,000 条 accepted Cue，但不以数量单独判成功；当 Seed 覆盖门满足且至少 576 个候选通过机器门后可停止扩充。Seed candidate 目标 900–1,400，最终 Frozen Seed 固定 480，建议暂按 train 240、dev 80、test 160 规划，最终须根据冻结 Source split 的参与者和来源组可达性确认。每个 Seed 派生 6 条 Life Log，预计 2,880 条。

三个阿里云账号使用同一个 `qwen3.7-flash` Cue 协议，分别绑定三个静态 worker/partition 集。每个 worker 独立授权、预算、ledger、费用快照、租约和 staging；协调器只读聚合，不允许共享追加累计账本。request ID 必须绑定 campaign、worker、partition、package、Atom 集合 SHA 和 attempt；重复 ID、费用缺失、终态冲突或共享身份错误一律阻断且不自动重发。恢复只处理所属 worker/partition 的未终态请求。

阶段内只有一个固定生产模型，阶段间允许选择不同中国厂商模型。DeepSeek 只少量用于独立审计或争议第三意见，不做全量审计。Seed 生成、Seed 审计和 Life Log 生成的最终模型在各自生产前另行冻结。

所有阶段分布报告统一写入 `audit/distributions/<stage>/<snapshot_id>/`，并严格收敛为 `distribution_report.json`、由其确定性渲染的中文摘要、manifest 和 `DISTRIBUTION_SUCCESS.json` 四文件。`by_model`、多账号阶段的 `by_worker`、`by_split`、`by_participant`、`by_modality`、`by_shard` 和阶段特有维度都作为报告内对象，不再各建 JSON。对应生产 SUCCESS 必须绑定 `distribution_manifest_sha256`。
CR-2026-022 第四步：批准 `_02` 兼容导入，保留原始 Schema SHA 并记录 `origin_schema_unavailable`；BGE 为非事实召回层，Cue 事实门保持硬门。

### CR-2026-022-B06

| 字段 | 内容 |
| --- | --- |
| 变更 | 将当前 Cue v2 协议验收固定为两个 worker，并以 BGE proof 的 350 条 `audit_sample` 排除集和最大余数分层抽样确定 900/120 验收计划 |
| 当前身份 | `worker_00`、`worker_01`；模型、Prompt、推理 Schema、参数和预算规则不变 |
| 受影响文件 | `egopm_bench_v1/scripts/05_extract_cues.py`、`egopm_bench_v1/tests/test_qwen_contracts.py`、当前配置与协议文档 |
| 合同原因 | 原三 worker 计划不能表达当前双账号预算、分区、重叠验收和恢复身份；简单排序取样不能证明 strata 配额闭合 |
| 兼容性 | 历史交接和 legacy V3.6 账本只读保留；当前运行器不得读取历史第三 worker 身份 |
| 验收门 | candidate proof 每个 Atom 恰一条、Source 元数据全覆盖、校准恰 350 条、验收恰 900 条、overlap 恰 120 条、主分区 390/390 且互斥完整 |
| 状态 | IMPLEMENTED；本步只完成离线确定性计划和回归测试，不调用 API、不生成正式 Cue |

### CR-2026-022-B07

| 字段 | 内容 |
| --- | --- |
| 变更 | API 前一致性修正与 Cue v2/legacy V3.6 协议隔离；当前身份统一为 `bge_m3_source_select_v3_1_20260914_02`、`worker_00`、`worker_01` |
| 受影响文件 | `AGENTS.md`、`egopm_bench_v1/coordination/CUE_SEED_V2_PLAN.md`、`egopm_bench_v1/coordination/STATUS.md`、`egopm_bench_v1/coordination/CHANGE_REQUESTS.md`、`egopm_bench_v1/config/model_registry.yaml`、`pyproject.toml`、`egopm_bench_v1/scripts/05_extract_cues.py`、当前合同与 Qwen 测试 |
| 合同原因 | 第六步遗留的旧 selection/三 worker 表述可能使运行器误读历史身份；验收计划必须保持候选 Source 流式边界、整数最大余数法、全局 selection 序列和 350 条校准闭合 |
| 隔离规则 | Cue v2 只读取 v2 prompt、推理/正式 Schema、`cues/v2/**` 和双 worker 资源；legacy V3.6 只读取紧凑 Schema、旧 prompt、`cues/formal/**`/`cues/realtime/**`。两套协议不共享 request builder、配置入口、staging、ledger 或正式输出 |
| 兼容性 | 历史 CR、handoff 和 legacy 账本保留只读事实；`worker_02` 不得进入当前配置或运行器。BGE `_02` 按外部优化结果兼容导入，原始 artifact Schema 缺失仅保留 provenance warning |
| 验收门 | 双 worker 分区 5000/5000；协议验收 900/120/780/390/390；校准恰 350 且与验收不相交；candidate proof、Source 元数据和 selection_sequence 全覆盖；标记测试与全量回归无新增 legacy 失败。当前 `_02` proof 的 `sample_index` 在七个固定 `sample_stratum` 内各为 `1..50`，校准身份为三元组，`calibration_index=1..350` 仅由计划派生，不改写原始 proof |
| 状态 | IMPLEMENTED；本步不调用 API、不读取密钥、不生成正式 Cue 或任何正式验收工件 |

### CR-2026-022-B08

| 字段 | 内容 |
| --- | --- |
| 变更 | 校准样本身份修正：接纳现有 proof 在七个 `sample_stratum` 内分别编号 `sample_index=1..50`，并在验收计划中派生全局 `calibration_index=1..350` |
| 受影响文件 | `egopm_bench_v1/scripts/05_extract_cues.py`、`egopm_bench_v1/tests/test_qwen_contracts.py`、`egopm_bench_v1/coordination/CUE_SEED_V2_PLAN.md`、`egopm_bench_v1/coordination/STATUS.md`、本文件 |
| 不可变边界 | 不修改、重写、重编号或移动 BGE 五文件；原始校准身份始终是 `(sample_stratum, sample_index, atom_id)`，派生编号不回写 proof |
| 验收门 | 七层名称与固定顺序、每层恰 50 条、局部编号唯一且覆盖 `1..50`、Atom 可回查 candidate/Source；校准排除、overlap、主分区和计划摘要均按 Atom 或完整复合身份处理 |
| 状态 | IMPLEMENTED；仅离线修正与测试，不调用 API、不读取密钥、不创建验收工件 |

### CR-2026-022-B09

| 字段 | 内容 |
| --- | --- |
| 变更 | 收口 `origin_schema_unavailable`：adopted 外部兼容导入保留 provenance 状态，但将 Schema 缺失 warning 与 strict 身份硬错误分离 |
| 受影响文件 | `egopm_bench_v1/scripts/05_extract_cues.py`、`egopm_bench_v1/tests/test_qwen_contracts.py`、`egopm_bench_v1/coordination/STATUS.md`、`egopm_bench_v1/coordination/CUE_SEED_V2_PLAN.md`、本文件 |
| 兼容规则 | `strict` 仍以 `ARTIFACT_SCHEMA_SHA_MISMATCH` 阻断；`adopted_external_v1` 返回 `provenance_status=origin_schema_unavailable`、`data_gate=passed`、`provenance_gate=warning` 和 `ORIGIN_ARTIFACT_SCHEMA_UNAVAILABLE`，warnings 不作为失败 |
| 身份边界 | 本地结构校验 Schema 仅记录为 `effective_validation_schema`，不宣称为原始产生 Schema；原始 artifact Schema SHA 不伪造、不删除、不覆盖 |
| 状态 | IMPLEMENTED；不修改 BGE 五文件、不调用 API、不读取密钥；warning 限制原始可复现性声明但不阻断 Cue v2 下游 |
