# EgoPM-Bench v1 统筹合同

治理合同版本：**v1.5.0**（2026-09-15）。本文件仅由 T0 维护。配置合同与已冻结 Source Atom Schema 保持 `v1.1.0`；CR-2026-021 启动 Cue v2 主线切换批次 A 并增加全仓工件与目录节制硬门禁，CR-2026-022 进一步冻结 Atom→Cue→Seed→Life Log 全流程事实边界、Cue 三层语义门和统一 Life Log 骨架。Cue v2 Schema、配置、纯验证器和离线验收计划已完成实现，但正式 API 生产与 Seed 生成仍未启动，必须通过对应 CHANGE_REQUEST 和验证后才能开始正式生产。

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

### 事实性与构造内容边界（硬门禁）

- 本规则适用于 Atom→Cue→Seed→Life Log→Decision/Evidence 的全流程。任何人物、地点、物体、活动、状态和显式时间的事实性陈述，必须能回查到同一 Source Atom 的明确原文字段与连续证据 span；仅有 JSON/Schema 正确或 span 字符串存在，不足以证明维度、关系、角色、否定、范围和时间语义正确。
- Cue 的一个 predicate 只允许 `all_of`，包含 **1–3** 个 clause；一个 Atom 最多产生一条正式 Cue。Clause 数量遵循“最少且充分”，不得为丰富度堆叠无关事实，也不得把同一事实拆成重复 clause。两个或三个 clause 只允许用于同一 Atom 内确有必要的主体、对象、活动、地点或状态消歧，且每个 clause 必须独立通过全部事实门。
- 每个 clause 必须由完整词形式的 `dimension`、`operator`、`value` 与自己的 `evidence.field/evidence.span` 构成，并依次通过三层质量判断：第一层，span 是同一 `transcript` 或 `dense_caption` 字段中的连续原文；第二层，`value` 能由该 span 直接支持，最多只允许确定性的 Unicode 与空白规范化；第三层，`dimension + operator + value` 整体被 span 的语义支持，并正确处理人物角色、主客体、否定、量词与范围、条件/假设、时态和时间语气。任一层失败均不得进入正式 Cue。
- Cue 是可判断的观察条件，不要求完整主谓宾，可以是“手机出现”“厨房”“Jake 正在说话”“门已打开”等简短条件；但必须有可识别的指向对象或状态承载者。单独的“他”“那里”“这个”“东西”“正在做”“发生变化”等无法在同一证据 span 与 Atom 元数据中唯一解析的表达必须 `no_cue` 或人工审计。
- 人物被提及、作为说话人和实际在场必须区分；第一人称“我”只在 Atom participant 能确定 wearer 时可解析，其他代词不得跨 Atom 消解。物体不得反推地点；地点词出现不得自动证明进入或在场；将来、假设、否定或不确定话语不得改写成已发生事实；视频/session 时间戳不得被写作显式事件时间或未来提醒条件。
- 构造内容只允许表达提醒意图、虚拟时间、生命周期状态或 oracle 所需的规则化观察，并必须标为 `constructed`。构造内容不得伪装为视频中发生的观察，也不得添加未经已验证 Cue 或 Source 支持的现实人物、地点、物体、事件或关系。无法明确支持时必须 `no_cue`、排除或进入人工审计，禁止合理猜测。
- 所有生产者和验证器必须区分 Source-grounded 与 constructed 的 provenance；下游不得把 constructed 文本重新当作 Source 事实。真实观察进入 Life Log 时只能逐字使用或确定性截取 Source 原字段，不得生成式补写主语、人物、地点、物体、活动或状态。最终 Seed、Life Log 与决策数据发现虚构实体、错误关系或事实/构造混淆时，均为阻断错误。

### 数据与执行规则

- v1 是“视频可追溯、文本优先”轨道。源 SRT 只读；v1 生产不复制、下载或拼接 MP4。
- 严禁提交 API Key、`.env` 文件、原始语料/媒体或模型原始响应日志。`DASHSCOPE_API_KEY` 只能从环境变量读取。
- 不得手改任何生成的 JSONL。生产者必须写入 `*.tmp`，完成内部验证后原子替换正式文件，最后写入 SUCCESS 标记。标记必须包含 SHA256、行数、合同/配置/Schema 版本、时间戳及上游哈希。
- 下游正式运行仅可读取同时满足以下条件的产物：SUCCESS 标记存在、哈希匹配且 T4 已通过必需的验证门。手写 synthetic fixture 只可用于单元测试，永不计入基准数据。
- 缺字段或不兼容修改一律视作 `CHANGE_REQUEST`；工作对话不得改动 `config/**` 或 `schemas/**`。

### 全项目工件与目录节制规则（硬门禁）

- 本节适用于整个仓库和全部阶段：仓库根目录、`egopm_bench_v1/**`、`wsl_BGE-M3_filter/**`，以及 T0–T4 的文档、代码、配置、Schema、prompt、测试、fixture、正式数据、审计、报告、缓存、staging 和恢复工件。子目录中的 `AGENTS.md` 只能收紧本节，不得放宽、改写计数口径或自行增加例外。
- “一个落实单元”指一个 CHANGE_REQUEST，或一个可独立审阅的功能、修复、实验设计或阶段改动；不能通过拆成多个提交、脚本、snapshot 或子目录规避预算。同一落实单元必须先复用现有权威文档、配置和目录，不得为了展示规划而预建空目录、占位 JSON、逐维度报告文件或没有生产者与消费者的“以后可能用到”工件。
- 一个落实单元默认最多新增 **1 棵持久目录树**和 **5 种非分片机器可读工件**。同一相对路径模板在不同 snapshot、worker 或 partition 下产生的实例按一种工件计数；`part_<n>.jsonl` 等正式分片族按一种工件计数，但仍须单独取得分片豁免。五种预算包含主数据或 proof、综合报告、manifest、SUCCESS、ledger、receipt、Schema 等全部新增 JSON/JSONL 类型，而不是每类各有五个名额。
- 持久目录树默认应复用现有阶段根；确实需要新根时只能新增一个。该新根下默认最多增加两层固定语义目录；`<snapshot_id>`、`<worker_id>`、`<partition_id>` 等动态实例层只有在不可变快照或并行隔离合同已批准时才允许。禁止按查询族、统计维度、状态、脚本、单个文件或“输入/输出/中间结果”机械建立成组子目录。
- 每个正式逻辑快照实例也不得超过其落实单元批准的工件集合。分布报告沿用本合同已冻结的四文件快照，不得再拆成 `by_model.json`、`by_split.json` 等一批小文件。
- 同一种记录应优先写入一个 JSONL；同一份报告的多个统计维度应优先写入一个具有稳定顶层键的 JSON。禁止按查询族、统计维度、状态、单个 request、单个 Atom 或单次 attempt 各建一个 JSON 文件。不同 worker/partition 因并行写入隔离而必须独立的 ledger 或 staging 属于例外，但不得成为下游正式接口，阶段闭合后由协调器只读聚合。
- 新建子目录必须形成真实的生命周期边界、不可变快照边界、权限/并行写入边界或不同保留策略；仅为了给一个文件分类、镜像概念层级或容纳同名 JSON 不得新建目录。每增加一层目录都必须能说明其生产者、消费者、关闭条件和保留期限。
- 对应 CHANGE_REQUEST 或现有生产计划必须给出“工件预算”，逐项列明路径、权威/缓存/临时属性、生产者、直接消费者、不能合并的原因和关闭后的处置。未列入预算的新增 JSON/JSONL、manifest、SUCCESS、ledger、receipt、report、Schema 或子目录不得合并。
- 只有以下情况可以超过默认预算：单文件规模或流式内存门要求分片；静态并行分区要求隔离写入；记录形状不同而必须使用独立 Schema；法规、安全或不可变审计要求独立保留。豁免必须在实施前由 T0 通过 CR 冻结文件数/分片规则、合并替代为何不可行以及清理策略，不能在运行中临时扩张。
- 新增或修改任何阶段的生产者、formalizer 或报告器时，对应测试必须断言正式目录中的文件集合与冻结预算**恰好相等**，出现未声明文件也要失败，不能只检查必需文件存在。既有阶段不要求一次性重写，但首次修改时必须提交该阶段的工件盘点，删除无消费者的可重建工件，或为确需保留的超额布局补 CR；不可变历史产物不因本规则重排或重写。
- 缓存、临时文件和便利导出不得伪装成正式产物，也不得被下游或 SUCCESS 单独绑定；任务结束后能确定性重建且没有审计保留义务的中间文件应删除或加入忽略规则。T0/T4 发现无消费者文件、重复事实源、无理由目录层或超预算未获批时，必须阻断合并与阶段 SUCCESS。

### 逻辑快照、分片与并行写入规则

- “阶段合并”指形成一个不可变的逻辑快照，不等同于必须生成一个物理巨型 JSONL。大规模正式产物可以由一个有序 manifest、若干互不重叠的正式分片和一个阶段级 SUCCESS 组成。
- manifest 必须逐分片绑定相对路径、SHA256、行数、字节数、顺序键、覆盖范围及全部必要上游哈希；SUCCESS 必须绑定 manifest SHA256、分片数、总行数、合同版本和上游哈希。任一分片缺失、重复、越界或哈希不符时，整个阶段均不可读。
- Source 与 Cue 采用上述大规模布局；已冻结的 Source 单文件作为兼容特例，不得仅为改变布局而重建。旧 V9 Cue 的 75 个 task 分片只保留不可变审计身份，不再作为 Seed 上游。Cue v2 使用 `cues/v2/formal/` 下的正式分片、一个 manifest 和一个阶段 SUCCESS，具体分片数在候选规模冻结后确定；package 级结果只属于执行审计。
- Seed candidates 规模调整为 900–1,400，是否继续采用单文件必须在实现 CR 时按实际字节数冻结；480 个 Frozen seeds 可保持单文件。Life Log 预计 2,880 条，必须在正式生成前通过 CHANGE_REQUEST 冻结单文件或 manifest+分片布局。Decision/Evidence 同样按规模提前冻结，不得运行中临时决定。
- 多终端并行生产只允许写入预先静态分配、互不重叠的 `*.tmp` 分区。每个分区完成内部验证后原子替换自己的正式分片；只有一个协调器可以执行全局唯一性、覆盖和哈希检查并写 manifest 与 SUCCESS。
- 单文件便利导出可以从 manifest 确定性重建，但只属于缓存，不是权威输入，不得被 SUCCESS 单独绑定。

### 多账号执行、账本与恢复规则

- 同一生产阶段只能有一个固定模型、一个 prompt hash、一个 Schema hash 和一套采样参数；多个账号只扩展吞吐，禁止按账号改变模型或协议。
- Cue v2 当前协议只允许两个阿里云账号并行，分别固定绑定 `worker_00`、`worker_01` 和互不重叠的静态 partition。每个 worker 使用独立授权、独立预算上限、独立 ledger、独立费用快照和独立 staging 目录；历史三 worker 交接仅作只读记录。
- 禁止多个 worker 追加同一个累计账本、状态文件、manifest 或 SUCCESS。协调器只读聚合已关闭的 worker 账本；发现重复 request ID、终态冲突、费用缺失或身份不一致必须立即阻断，禁止自动重发。
- request ID 必须确定性绑定 campaign、worker、partition、package、Atom 集合 SHA 和 attempt。网络层幂等重试复用 idempotency key；模型修复必须增加 attempt 并产生新 request ID。
- 恢复只能处理本 worker、本 partition 的未终态请求。任何已计费、已成功、已排除或已有终态的 Atom 均不得自动重发。账本迁移只能由确定性工具原子完成并保留全部费用事件，严禁手改或删除 JSONL 行。
- 每个 partition 必须有独占租约；协调器只有在确认无进程、无在飞请求后才能释放失效租约。

### BGE selection v3.1 与精简证明规则

- 冻结 Source 中的 `visible_text` 不删除也不修改；BGE passage 只编码 `transcript` 与 `dense_caption`。`visible_text` 仅用于派生一致性校验，不得独立编码或进入候选输出。
- 查询族固定为 `Person`、`Location`、`Object`、`Activity`、`State`、`Explicit-Time`。六族全部召回并报告，但不设任何最低值或最高值；查询族是召回统计层，不是 Cue 最终语义标签。
- BGE 候选先形成 10,000 条核心，再按稀有 cluster 与确定性新颖度门补样；达到 12,000 或完整一轮无新增时停止。不得为凑上限放宽质量门。
- `event_timestamp` 只表示 Source/session 中的事件位置，用于定位、排序和状态机顺序；`temporal_condition` 是 Seed/Rule 阶段构造并人工审计的未来提醒条件。禁止把视频时间戳直接变成 prospective-memory trigger。
- WSL 正式回传恰有 `candidate_atoms.jsonl`、`selection_proof.jsonl`、`selection_report.json`、`selection_manifest.json`、`BGE_FILTER_SUCCESS.json` 五个文件。T4 从 proof 与 Source 复核离散选择逻辑，但不重跑 BGE；全库 embedding 数值、top-k 完备性和 cluster 指派由 WSL 完整审计负责，manifest 必须绑定其本地审计根。
- WSL 包只携带两个必要 Schema：与 Windows 权威文件同 SHA 的 Source v1.1.0 行 Schema，以及统一定义候选行、五类 proof 行、report、manifest 和 SUCCESS 的 Draft 2020-12 artifact Schema。二者由根请求直接绑定；Source SUCCESS 按冻结原始字节 SHA 验证，不复制冗余 Schema。不得从数据样本猜字段。
- 每个 Atom 的检索表示固定为 transcript 行与 dense caption 行组成的单一原始字符串，只编码一次；不得分别编码后聚合。`nfkc_casefold_whitespace_cf_v1` 固定 Unicode 15.0.0 和操作顺序，只用于资格/审计，不变换模型输入。
- 同簇近重复按冻结静态全序贪心产生 survivor；核心联合约束使用固定单 worker OR-Tools CP-SAT 四阶段词典序求解。只有全部目标为 `OPTIMAL` 且重复求解候选 SHA 一致才可成功，贪心失败、`FEASIBLE` 或超时均不得宣称不可行或成功。

### Cue v2、Seed 血缘、lure 与模型政策

- Cue v2 只表达单个 Source Atom 中可直接观察的事实，只允许 `all_of` 合取；`any_of`、虚拟时间、跨 Atom 关系和生命周期规则必须在 Seed/Rule 阶段表达。
- Cue v2 每条正式记录只允许一个含 1–3 个 clause 的 predicate；每个 clause 都必须通过“字段内连续 span → value 直接支持 → 完整断言语义支持”三层门。Cue 不要求完整句法，但必须具有可识别指向对象；无法解析的代词、泛指词、空值和无承载者的活动/状态不得接受。
- Cue v2 clause 的 `dimension` 统一为 `person/location/object/activity/state/explicit_time`；旧 `place/state_change/time` 只属于 legacy，不得作为 current 同义枚举并存。BGE 的查询族只表示召回来源，不自动决定 Cue dimension。
- Cue v2 批量抽取沿用 `qwen3.7-flash`。两个阿里云账号必须使用相同地域、端点、模型 ID、prompt、Schema 和参数；模型在阶段中途发生不可证明的一致性变化时必须停批并创建新 campaign。
- Cue v2 扩量前必须从 BGE selection 分层冻结 800–1,000 个协议验收 Atom，其中至少 120 个重叠 Atom 由两个账号分别处理。该集合只验证协议与账号同质性，永不进入正式数据；任一验收门失败必须产生新协议 SHA 和新验收集 ID，禁止沿用旧结果扩量。
- 不同生产阶段可以使用不同的固定模型。Seed 生成、Seed 审计和 Life Log 生成的具体模型在各阶段执行前分别通过 CHANGE_REQUEST 冻结；DeepSeek 只可少量用于独立审计或争议第三意见，不做全量高成本审计。任何模型意见均不得替代人工终审。
- Cue v2 正式行删除顶层 `cue_type`、`confidence` 及可由 Source/manifest 派生的冗余字段；每个 predicate clause 自带 `dimension/operator/value/evidence`。正式行只包含 accepted Cue；`no_cue`、闭环后仍不确定的 `excluded_ambiguous` 和其他排除终态只写无正文 disposition ledger。
- 每个正式 Seed 必须保存 `trigger_cue_id`。该 ID 必须解析到 Cue v2 manifest 中的 `accepted_cue`，并与 `trigger_atom_id` 和 `trigger_predicate` 建立可由程序验证的唯一血缘；顶层 `primary_cue_type` 不再是正式血缘字段，需要分析维度时从 predicate clauses 确定性派生。
- `trigger_predicate` 必须与所引用 Cue 的规范化 predicate 完全一致；若人工修改 predicate，必须改为引用一个能精确支持该 predicate 的 Cue，禁止仅靠模型解释补足血缘。
- 每个 Seed 至少有两个互不相同且不同于 trigger 的同 split lure：至少一个与 trigger 同 `source_group_id`，用于同上下文困难干扰；至少一个来自不同 `source_group_id`，用于跨上下文语义干扰。每个 lure 必须明确记录至少一个未满足的 predicate 子句。
- 一个正式候选快照内，`trigger_cue_id`、`trigger_atom_id` 和所有 `lure_atom_id` 均不得跨 Seed 复用；被拒 Seed 释放的 Atom 只有在下一次有新 SUCCESS 的候选快照中才能重新分配。任何复用、组别构成或失败子句不合格都必须阻断 Seed SUCCESS。
- Seed candidates 目标为 900–1,400；只有覆盖门满足且至少 576 个候选通过机器门后才可停止扩充。最终 Frozen Seed 固定为 480，每个 Seed 派生 6 条 Life Log，预计共 2,880 条。不得降低质量门凑数。
- 同一 Seed 的六条 Life Log 必须共享同一 trigger Atom/Cue 和同两条 lure。positive/negative 成对日志在相同最终 trigger 观察上只改变一条构造生命周期控制事件，使 gold 在 `remind/silent` 间翻转；不得替换 trigger、增删目标 Cue 或用不同事实输入制造答案差异。每条日志固定含一条意图创建、一条生命周期控制、两条 lure 和一条最终 trigger 观察，目标相关 Source 观察数恒为 3；同一难度采用固定事件数和受控 token 区间。
- Life Log 的模型可见输入只含事件顺序、虚拟时间、原文观察或明确 constructed 文本及必要来源引用；`trigger/lure` 角色、predicate、状态前后值、反事实分支、gold、Evidence Set 和 oracle 理由必须留在隐藏标注。核心负分支只使用意图创建后的 `completed/cancelled/expired/already_reminded`，`never_created` 如需保留必须另设不与统一骨架混算的专项设计。

### 分布报告硬门

- Cue v2、Seed candidates、Seed audit 和 Life Log 必须分别在 `audit/distributions/<stage>/<snapshot_id>/` 生成 `distribution_report.json`、由其确定性渲染的中文摘要、manifest 和 `DISTRIBUTION_SUCCESS.json` 四文件快照。
- 机器报告至少包含按模型、split、参与者、模态、分片和阶段特有维度的对象。即使阶段只有一个模型，也必须有 `by_model` 键证明阶段同质；多账号阶段还必须有去账号标识化的 `by_worker` 键检查成功率、终态、费用和语义分布漂移。不适用维度写结构化原因，不生成一批空壳文件。
- 阶段 SUCCESS 必须绑定 `distribution_manifest_sha256`。没有报告、报告哈希不符、单一维度异常塌缩、字段覆盖归零或未解释的跨分片漂移时，阶段不得成功。

## 文件所有权与允许写入范围

| 负责人 | 允许写入 | 允许读取 | 正式启动门 |
| --- | --- | --- | --- |
| T0 | `AGENTS.md`、`.gitignore`、`README.md`、`pyproject.toml`、`egopm_bench_v1/config/**`、`egopm_bench_v1/schemas/**`、`egopm_bench_v1/coordination/STATUS.md`、`egopm_bench_v1/coordination/CUE_SEED_V2_PLAN.md`、`egopm_bench_v1/coordination/CHANGE_REQUESTS.md`、`CHANGE_REQUESTS.md`、`wsl_BGE-M3_filter/**`、`tests/fixtures/**`、`tests/test_contract_freeze.py` | 全部 | Contract v1 DONE |
| T1 | `scripts/01_inventory_srt.py`–`04_make_source_splits.py`、`source/**`、`tests/test_source_pipeline.py`、`coordination/handoffs/T1_source.md` | config/schema/源 SRT | Contract v1 DONE；正式 source 输出还须通过 T4 source QA |
| T2 | `prompts/*`、`scripts/05_extract_cues.py`–`07_generate_seed_candidates.py`、`cues/**`、`seeds/reminder_seed_candidates.jsonl`、`tests/test_qwen_contracts.py`、`coordination/handoffs/T2_qwen.md` | 已冻结的 source/cues/config/schema | `SOURCE_ATOMS_SUCCESS` 哈希冻结且 T4 source QA DONE |
| T3 | `scripts/08_freeze_seed_audit.py`–`10_run_oracle.py`、`rules/**`、`lifelogs/**`、`benchmark/decision_instances.jsonl`、`benchmark/evidence_sets.jsonl`、`tests/test_state_machine.py`、`coordination/handoffs/T3_compiler.md` | 已冻结 seeds/config/schema | `SEEDS_FROZEN_SUCCESS` 哈希冻结且 T4 seed QA DONE |
| T4 | `scripts/11_validate_all.py`、`12_build_statistics.py`、`tests/test_validators.py`、`audit/**`、`benchmark/dataset_card.md`、`coordination/handoffs/T4_qa.md` | 所有已完成产物 | 对应生产者 SUCCESS 哈希存在；T4 永不修改生产者输出 |

只有 T0 可以将门禁提升为 `DONE`、合并工作、冻结哈希或变更本合同。治理合同 v1.5.0 DONE 后，T0 可以允许 T1–T4 以 synthetic fixture 独立开发代码；这不构成运行正式生产或读取未完成上游产物的授权。

## 必需输入、输出与门禁

| 门禁 | 必需输入 SUCCESS 标记 | 必需正式输出 | 负责人 | 验收条件 |
| --- | --- | --- | --- | --- |
| Source atoms | 治理合同 v1.1.0 | `source/SOURCE_ATOMS_SUCCESS.json`，以及 inventory、segments、atoms、split map、report | T1 | T4 通过 Schema、来源时间、路径与 split 检查 |
| BGE candidate selection | source 标记、冻结哈希、T4 source QA | `cues/v2/source_selection/<selection_id>/` 下五文件快照 | T2/WSL | selection v3.1；10,000–12,000 个候选；两个直接绑定的必要 Schema、固定 revision、请求/组件 SHA、CP-SAT 最优门、proof 离散复核、WSL 数值审计与 Source 血缘通过 |
| Cue v2 protocol acceptance | BGE selection 标记、冻结协议与验收集 manifest | 协议验收报告与 `PROTOCOL_ACCEPTANCE_SUCCESS.json` | T2/T4 | 800–1,000 个分层 Atom；至少 120 个两账号重叠 Atom；证据、Schema、语义精度和账号漂移门全部通过；验收数据不进入正式 Cue |
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

CR-2026-022 第四步：BGE 属于非事实候选召回层；外部 anytime 优化结果可在原 Schema 不可用时兼容导入，但不得宣称全局最优。Source→Cue 三层事实门继续为硬门。
当前有效 BGE selection 为 `bge_m3_source_select_v3_1_20260914_02`；Cue v2 只允许 `worker_00`、`worker_01` 两个账号/预算/ledger/staging。历史三 worker 交接只读保留，不得被当前运行器读取。
