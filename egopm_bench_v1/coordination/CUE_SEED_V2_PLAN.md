# EgoPM-Bench v1 Cue/Seed v2 生产计划

> 决议日期：2026-09-09  
> 事实边界修订：2026-09-15，CR-2026-022
> 状态：T0 已冻结项目方向、Cue 三层语义门和统一 Life Log 骨架；批次 B 已完成 Cue v2 Schema、纯验证器、双 worker 验收计划与协议隔离的离线实现，暂不调用 API 或生成正式 Cue
> 适用范围：Cue v2、BGE-M3 候选筛选、Seed candidates、Seed 审计和 Life Log 规模  
> 上游：冻结 Source Atom 370,799 条，SHA256 `be5f36b77970cb5147b88551c566f081589fe00fcf5ef912d8468a037e92960e`

## 零、CR-2026-021 批次 A：主线切换与退役边界

批次 A 只整理治理边界，不修改 `config/**`、`schemas/**`、Python 生产代码或任何正式数据，也不运行 BGE/API。为遵守全仓工件节制规则，本迁移清单直接维护在本计划中，不另建清单 JSON、迁移目录或状态文件。

### 1. 处置矩阵

| 对象 | 当前处置 | 后继或用途 | 批次 A 边界 |
| --- | --- | --- | --- |
| `source/**` 与 `SOURCE_ATOMS_SUCCESS.json` | `KEEP_IMMUTABLE` | BGE selection v3.1 只读上游 | 禁止重写、搬移或仅为新布局重建 |
| `cues/formal/**`、旧 `cue_library_manifest.json`、旧 `CUE_LIBRARY_SUCCESS.json` | `ARCHIVE_IN_PLACE` | `realtime_v9_01` 结构、哈希与费用审计 | 原路径不可变；不得成为 06/07/11 的当前默认输入 |
| 旧 realtime/package/ledger/receipt/coverage/disposition | `ARCHIVE_IN_PLACE` | 执行、恢复和费用事故审计 | 不删除、不重发、不修复、不迁入 Cue v2 账本 |
| `cues/v2/**` | `CURRENT_TARGET` | selection、协议验收、两个 worker staging、formal、manifest、SUCCESS | 后续批次只在已冻结工件预算内创建，不预建空目录 |
| `config/paths.yaml`、`model_registry.yaml`、`benchmark_protocol.yaml` | `UPDATE_LATER` | 显式区分 `legacy_cue_v9_*` 与 `cue_v2_*` | 批次 B 经破坏性 CR 修改；当前批次不动 |
| `schemas/cue_candidate.schema.json` 与旧 inference Schema | `REPLACE_OR_LEGACY_LATER` | Cue v2 clause-level Schema 与新的模型输出 Schema | 批次 B 冻结；不同记录形状才允许独立 Schema |
| `scripts/05_extract_cues.py` | `REWRITE_LATER` | 只消费已通过门的 BGE selection 并生产 Cue v2 | 批次 C 移除旧生产默认入口；是否保留审计读取函数由引用盘点决定 |
| `scripts/06_retrieve_trigger_lures.py`、`07_generate_seed_candidates.py` | `UPDATE_LATER` | 只读取 Cue v2 manifest/SUCCESS | 批次 C 必须拒绝旧 V9 manifest，禁止兼容回退 |
| `scripts/11_validate_all.py`、`12_build_statistics.py` | `SPLIT_VALIDATION_LATER` | 当前 Cue v2 门与旧 V9 只读审计分离 | 批次 D；旧 QA 通过不得提升当前 Cue 门 |
| 旧 prompt、旧协议 fixture、旧生产适配代码 | `DELETE_CANDIDATE` | Git 历史或最小 legacy 审计替代 | 只有满足删除门后才可删除，不为它们新建归档目录 |
| README、状态板、完整指南、CR 与旧 handoff | `CONSOLIDATE_LATER` | 当前说明与历史证据分层 | 批次 E；优先压缩现有文件，不复制全文到新文档 |

### 1.1 已确认的旧默认入口

以下引用已在批次 A 盘点中确认，必须由后续批次显式处理；它们说明旧链路仍可执行，不代表本批次获准修改对应文件。

| 路径 | 仍存在的旧语义 | 后续处理 |
| --- | --- | --- |
| `config/paths.yaml` | `cue_library`、`cue_library_manifest` 和 Cue SUCCESS 仍指向 `cues/` 旧根路径 | 批次 B 改成无歧义的 legacy/current 键，生产消费者只接受 current |
| `config/model_registry.yaml` | Cue extraction 仍绑定旧最终 Schema 与紧凑 inference Schema | 批次 B 冻结 Cue v2 模型、prompt、Schema 和参数哈希 |
| `scripts/05_extract_cues.py` | 默认 prompt/Schema/formal/manifest 指向 V9 路径，并保留旧运行与 75 分片冻结入口 | 批次 C 重写当前入口；旧 API 生产能力不得随 legacy 审计保留 |
| `scripts/06_retrieve_trigger_lures.py` | 强制接受 75 个 task 的旧逻辑快照，默认读取旧 manifest | 批次 C 改为 Cue v2 manifest/SUCCESS 严格读门 |
| `scripts/07_generate_seed_candidates.py` | 默认读取旧 manifest，并把 75 分片形状作为合同 | 批次 C 改为 Cue v2 血缘并增加旧上游拒绝错误码 |
| `scripts/11_validate_all.py` | Cue 阶段默认验证旧路径、旧执行血缘和 75 分片 | 批次 D 分离 legacy 审计与 current 阶段门 |
| `prompts/cue_extractor_v1.md`、`cue_extractor_v2.md`、`cue_extractor_v3_compact.md` | 三代旧 prompt 同时位于当前 prompt 目录 | 批次 C/E 以实际代码引用决定删除；不复制到新 archive 目录 |
| `schemas/cue_candidate.schema.json`、`cue_inference_batch_v1.schema.json`、`cue_inference_batch_compact_v1.schema.json` | 名称无法区分旧 V9 最终记录与 Cue v2 新记录 | 批次 B 先冻结后继与 legacy 读取边界，再决定保留或删除 |
| `tests/test_qwen_contracts.py`、`test_validators.py`、`test_contract_freeze.py` | 仍覆盖旧执行器、短码和 75 分片合同 | 批次 C/D 用 current 测试替代；只保留最小旧快照完整性测试 |

### 2. 批次 B–E 边界

1. 批次 B：冻结 Cue v2 Schema、配置键、路径、SUCCESS 与工件预算；所有当前键必须显式带 `cue_v2` 语义，旧键不得作为 fallback。
2. 批次 C：实现 selection 导入、Cue v2 抽取/formalize 和 Seed 上游切换；生产入口收到旧 V9 manifest 时必须以稳定错误码拒绝。
3. 批次 D：把当前 Cue v2 验证与旧 V9 只读审计分开，并增加“旧 manifest 不能进入 Seed”的回归测试。
4. 批次 E：在引用归零后删除旧生产代码、prompt、fixture 和重复说明；正式旧数据、账本与其身份元数据永不进入删除候选。

### 3. 统一删除门

删除候选必须同时满足：已有明确后继；当前配置、代码、测试和文档入口均不再依赖；全仓引用扫描只剩登记的历史 allowlist；旧 V9 的分片、manifest、SUCCESS、账本和哈希仍能只读审计；新主线 synthetic 测试和 `git diff --check` 通过；删除对象不受正式 SUCCESS、manifest、费用或恢复血缘绑定；T0 已在对应 CR 中逐路径批准。任一条件不满足时只能保留或原地归档，不能先删后补。

### 4. 本迁移的工件预算

批次 A 新增正式机器文件为 **0**，新增目录为 **0**；只修改既有中文治理文档。后续每个 CR 或可独立审阅的落实单元默认最多新增 1 棵持久目录树和 5 种非分片机器工件，且每个 snapshot 实例只能产生预算列出的文件集合；分布报告固定为 4 个文件。正式数据分片、两个 worker 隔离和不同记录形状 Schema 如需豁免，必须在各自批次 CR 中逐项冻结，不能沿用本批次的概括性授权。

## 一、方向调整

旧 `realtime_v9_01` 及其 294,839 条 Cue 保持不可变，继续作为执行、费用、覆盖和故障审计材料；由于已确认存在系统性语义塌缩，它不再具有 Seed 正式上游资格，也不得与 Cue v2 混合。旧 Cue 的结构 QA“0 blocker”只证明当时合同下的 Schema、哈希、证据片段和覆盖关系成立，不代表 predicate 语义正确。

新主线不再要求对 370,799 个 Source Atom 各生成一个 Cue。生产改为：

1. 对全量 Source 做确定性预过滤和本地 BGE-M3 多路召回；
2. 当前 selection 先冻结 10,000 个核心候选，再按稀有语义簇和新颖度门确定性补样，最终为 10,000–12,000 个候选 Atom；
3. 两个阿里云账号使用同一个 `qwen3.7-flash` 生产协议并行抽取 Cue v2；
4. 目标得到约 3,000–5,000 条高质量 `accepted_cue`，按 Seed 可达性停止，而不是追求固定 Cue 总量；
5. 生成 900–1,400 个 Seed candidates；
6. 经程序门、低成本模型审计和全部人工终审，冻结 480 个独立 Seed；
7. 每个 Seed 派生 2 个反事实分支 × 3 个难度，共 2,880 条 Life Log。

480 个 Seed 至少占用 480 个唯一 trigger Cue、480 个唯一 trigger Atom 和 960 个唯一 lure Atom，共至少 1,440 个互不复用的 Source Atom。候选快照若包含 900–1,400 个 Seed，则至少需要 2,700–4,200 个互不复用 Atom，因此 Cue 和候选 Atom 池必须保留充分余量。

## 二、Cue v2 的科学边界

Cue 只表达单个 Source Atom 中已经观察到的事实，不表达未来提醒意图、虚拟时间、跨 Atom 关系或生命周期规则。Cue v2 只允许 `all_of` 合取；`any_of`、虚拟时间窗口、替代触发条件和 Reminder 状态机全部留在 Seed/Rule 阶段。

一个 Atom 最多产生一条正式 Cue；一条 Cue 只含一个 predicate，并包含 1–3 个 `all_of` clause。Clause 数量不是信息丰富度评分，而是表达一个可判断观察条件所需的最小充分集合：一个明确对象、地点或时间短语可以只用一条；主体/对象与动作或状态通常使用两至三条。不同主题的事实不得为了占满上限合在一条 Cue 中。

正式 Cue 行只保存科学内容：

```json
{
  "cue_id": "cue_...",
  "atom_id": "src_...",
  "predicate": {
    "all_of": [
      {
        "dimension": "person | location | object | activity | state | explicit_time",
        "operator": "由 dimension 限定的完整关系枚举",
        "value": "...",
        "evidence": {
          "field": "transcript | dense_caption",
          "span": "..."
        }
      }
    ]
  }
}
```

逐行删除 `confidence`、顶层 `cue_type`、`entities`、`scene_type`、`activity_type`、`source_text`、`split`、`model_id`、`prompt_version`、`schema_version`、`run_id`、`validation_status` 和 `ambiguity_reason`。其中 Source 可派生字段从 `atom_id` 回查；运行元数据进入 manifest/账本；正式分片天然只包含 accepted Cue，不重复写状态。

模型候选输出可以有 `accepted`、`no_cue`、`ambiguous` 三种判断，但它们不是三个正式 Cue 状态。`ambiguous` 必须经过复核闭环：

```text
ambiguous
├─ 证据充分   → accepted_cue
├─ 无有效线索 → excluded_no_cue
└─ 仍不确定   → excluded_ambiguous
```

只有 `accepted_cue` 进入正式 Cue 分片。其余终态只进入无正文 disposition ledger；不得把未解析的 `ambiguous` 写进阶段 SUCCESS。

Cue 不要求自然语言上的完整主谓宾。`object/present/手机`、`location/at/厨房`、`person/speaking/Jake`、`state/state_is/门已打开` 都可以形成简短而可判断的条件；但每条条件必须具有可识别的指向对象或状态承载者。无法在同一 span 和 Atom 元数据中解析的“他”“那里”“这个”“东西”“正在做”“发生变化”等泛指表达不得 accepted。第一人称“我”只有在 Atom participant 能唯一确定 wearer 时才可使用，且不得把它改写成 span 中没有出现的人名。

`operator` 必须表达关系和语气，而不是让通用 `eq/not_eq` 掩盖语义差异。批次 B 的 Schema 至少要能区分：人物实际在场、作为说话人、仅被提及；地点被明确说出、进入地点、处于地点；物体出现、缺失或处于某状态；活动开始、持续或结束；状态成立或发生变化；显式时间被陈述、计划或假设。否定、条件、将来、不确定和引用话语不得被丢弃或改成肯定的已发生事实。具体枚举由批次 B 冻结，但实现不得退回旧版“任意 dimension 配任意 operator”的宽松组合。

Current dimension 统一使用 `person/location/object/activity/state/explicit_time`；旧 V9 的 `place/state_change/time` 只保留在 legacy 数据中，不得作为同义 current 枚举并存。BGE query family 只用于召回，不能直接复制为 Cue dimension。批次 B 应按下表冻结 dimension 与 operator 的合法组合：

| dimension | 最小可识别指向 | 可接受的语义关系 | 必须拒绝的偷换 |
| --- | --- | --- | --- |
| `person` | 原文人名、明确说话人标签，或由 participant 唯一解析的“我” | 在场、说话、被提及、离开/靠近等由原文明确支持的角色 | 名字被提到即推断在场；说话人即推断可见；跨 Atom 消解“他/她” |
| `location` | 明确地点名称或无歧义场所短语 | 位于、进入、离开、地点被提及，关系必须由 span 支持 | 由冰箱/床/锅推断厨房或卧室；地点词出现即推断人在该地 |
| `object` | 具体可识别物体或明确类别 | 出现、缺失、持有/放置等与 activity clause 一致的观察 | “东西/这个/它”无同 span 先行对象；由用途补造物体 |
| `activity` | 可识别动作，并有主体、对象或明确活动名称 | 开始、持续、结束、未发生，极性和阶段由 span 支持 | 只有“正在做/弄一下”；把计划、建议或条件句写成已发生动作 |
| `state` | 可识别人物/物体/环境作为状态承载者 | 状态成立、状态不成立、变化到某状态 | 只有“变了/好了”；把普通出现改成状态变化；遗漏否定或比较范围 |
| `explicit_time` | 原文明示日期、时刻、频率、期限或先后短语 | 被陈述、计划、假设、否定等与原文语气一致的时间语义 | 视频时间戳充当内容；“等一下/时间戳/秒表”当作具体时刻；假设时间写成已经到达 |

一个 clause 只能采用该 dimension 允许的 operator；不合法组合在 Schema 或本地语义表中直接拒绝。某个 span 同时支持多个维度时，只有构成同一最小充分条件的维度才进入同一 predicate，其余事实舍弃，不另外生成第二条 Cue。

## 三、模型政策

### 1. 阶段内单模型

同一个正式生产阶段只能使用一个固定模型 ID、一个 prompt hash、一个推理 Schema hash 和一套采样参数。多个账号只扩展吞吐，不得改变模型语义。Cue v2 沿用 `qwen3.7-flash`；新 campaign 启动时必须冻结实际请求模型 ID、地域、端点、参数和协议 SHA。运行过程中若服务端模型映射发生不可证明的一致性变化，必须停止并新建 campaign，不能继续混写。

当前协议的两个阿里云账号分别绑定 `worker_00`、`worker_01`。每个账号只处理预先分配且互不重叠的 partition。账号、worker、partition 不进入正式 Cue 行，但必须在私有执行账本和 shard provenance 中可追溯；旧三 worker 交接仅作只读历史。
Cue v2 运行器只读取 `cue_v2_inference.schema.json`、`cue_v2_artifacts.schema.json`、`cue_extractor_v2.md` 与 `cues/v2/**`；legacy V3.6 继续只读紧凑 Schema、旧 prompt、`cues/formal/**` 和 `cues/realtime/**`。两套协议不得共享 request builder、staging、ledger 或正式输出入口，Cue v2 禁止 legacy fallback。

### 2. 阶段间允许不同模型

- Cue v2 批量抽取：`qwen3.7-flash`，非思考或平台最低稳定推理设置；
- Seed candidate 生成：先以 `qwen3.7-plus-2026-05-26` 为候选，不在本 CR 中最终冻结；
- Cue/Seed 模型审计：优先抽样使用 Plus；DeepSeek 只作为少量独立审计或争议第三意见，不做全量审计；
- Life Log 组装：默认使用确定性编排和受控 constructed 模板；如为语言自然度使用模型，必须在 Seed 冻结前专项比较并锁定实体占位符，模型不得改写 Source 观察或决定状态/gold；
- oracle、状态迁移、gold、split、血缘和 SUCCESS：始终由确定性程序产生。

模型审计只提供意见，不能替代程序门或人工签字。为控制费用，Cue 阶段不对全部 10,000–12,000 条再次调用昂贵审计模型；必须审计全部最终 trigger Cue、全部争议 Cue，并按模型、split、参与者、模态和分片分层抽检其他终态。

### 3. 大规模调用前的协议验收集

正式扩量前，从 BGE selection 中按 `split × participant × modality × source_group_id × 召回通道` 分层冻结 800–1,000 个 Atom，形成独立的协议验收集。它只用于验证 prompt、Schema、解析器、语义门和账号同质性，永不进入 Cue、Seed 或 benchmark，也不计入正式分布。

BGE proof 已提供的 350 条分层 audit sample 先作为设计校准集，用于人工形成高质量正例、`no_cue` 例、歧义例和旧故障反例；它们帮助编写 prompt、Schema 和 validator，但不能代替 800–1,000 条最终协议验收。最终验收集在协议固定后另行冻结，其中首个约 500 条作为受控子波次；只有该子波次不触发协议修改时，结果才可与余下 300–500 条合并。若根据首波修改 prompt、Schema、operator 或语义门，整个验收身份作废并使用新集合重新开始。
当前 `_02` proof 的 350 条 `audit_sample` 按七个固定 `sample_stratum` 各自使用 `sample_index=1..50`。校准身份固定为 `(sample_stratum, sample_index, atom_id)`，计划按 `Activity`、`Explicit-Time`、`Location`、`Object`、`Person`、`State`、`diversity_only` 的顺序派生 `calibration_index=1..350`；该编号只存在于内存验收计划，不回写或改编号原始 proof。未知层名、重复局部编号、重复 Atom 或缺层仍是硬阻断。

采用 `adopted_external_v1` 时，BGE 预检返回 `data_gate=passed`、`provenance_gate=warning`、`provenance_status=origin_schema_unavailable` 和 `ORIGIN_ARTIFACT_SCHEMA_UNAVAILABLE`。该 warning 不属于下游阻断条件，允许候选进入 Cue v2 生成；若采用本地 Schema 做结构校验，只记录为 `effective_validation_schema`，不得声称它就是原始产生 Schema。它限制的是 BGE 原始可复现性声明，而不是 Source→Cue 三层事实门。

其中至少 120 个重叠 Atom 必须由两个阿里云账号分别处理一次，用于检测账号、地域、端点或服务端映射差异。验收只保存结构化输出、无正文 disposition、安全错误码、人工标签和聚合统计，仍然禁止保存原始模型响应。

扩量门至少要求：第一层字段内连续 span 合法率 100%；第二层 value 直接支持率 100%；哨兵字符串、跨字段/跨 Atom 借证、无法解析指向对象为 0；Schema 有效率不低于 99.5%；accepted Cue 的分层三层语义精确率不低于 97%；人物角色、地点关系、否定、范围和时间语气的事实失真为 0；`no_cue` 与各 clause dimension 单独报告精确率/召回率；两个账号重叠样本的结构和语义差异均经人工解释，不存在系统性漂移。任一门失败时必须修改协议并产生新的验收集 ID，旧验收结果不得与新协议合并，也不得直接扩大正式调用。

## 四、BGE-M3 候选筛选

BGE-M3 在 WSL2 中本地单 GPU、单编码进程运行。当前正式 selection 为 `bge_m3_source_select_v3_1_20260914_02`。Windows 仓库中的 `wsl_BGE-M3_filter/` 是可搬运执行包；WSL 输出返回 Windows 后进入：

```text
egopm_bench_v1/cues/v2/source_selection/<selection_id>/
```

当前快照的 manifest 绑定根请求 SHA256 为 `4e4c79d33e9ce8bd4a0636b92448fc8c500532f885db47519a135c837d8e359d`、Source 行 Schema SHA256 为 `0d576ed34f4a4d19fa38294392bb277306bba145f0492015fe909709c8be92e4`、Source SHA256 为 `be5f36b77970cb5147b88551c566f081589fe00fcf5ef912d8468a037e92960e`，外部 artifact Schema SHA256 为 `fb6f619cf0bfb81074f95fb1f471dcbec66af5023dd5085c8b543a2589d8a261`。该原始 artifact Schema 在 Windows 权威目录不可用，因此按 `adopted_external_v1` 兼容导入并保留 provenance warning；不得伪造或删除 manifest 原始 SHA。不另建 schema manifest、Source SUCCESS Schema 或规范化向量文件；相关 proof 类型统一为 artifact Schema 内的 `$defs`。组件任一字节变化都必须新建 selection ID。

BGE 执行包的机器合同固定为 7 个小文件：根请求、旁路 SHA、模型配置、查询 JSONL、选择策略和两个 Schema；用户另复制既有 Source/Source SUCCESS，不为它们生成包装 JSON。正式回传恰好 5 个文件。query hit、候选 provenance、cluster/shard 汇总和人工样本使用一个异构 `selection_proof.jsonl`，全部统计使用一个 `selection_report.json`，不按查询族、cluster、shard 或 proof 类型拆文件。

### 0. BGE v3.1 工件预算与豁免

CR-2026-019 对默认五种工件预算只批准以下必要豁免；除此之外不得增加 JSON/JSONL、旁路清单或目录树：

| 工件集合 | 路径/类型 | 属性与直接消费者 | 不能合并的理由 | 关闭后处置 |
| --- | --- | --- | --- | --- |
| 便携输入合同 | `selection_request.json`、`selection_request.sha256`、`model_config.json`、`query_set.jsonl`、`selection_policy.json` | T0 权威输入；WSL 执行器/validator | 根请求避免自引用；查询集必须独立哈希；模型与选择策略生命周期不同 | 随 selection 身份永久保留 |
| 两个 Schema | `source_video_atom.schema.json`、`bge_selection_artifacts.schema.json` | T0 权威接口；WSL/T4 validator | 前者必须与既有 Source Schema 逐字节同 SHA；后者合并所有新增回传记录形状 | 随 selection 身份永久保留 |
| 五文件正式快照 | `candidate_atoms.jsonl`、`selection_proof.jsonl`、`selection_report.json`、`selection_manifest.json`、`BGE_FILTER_SUCCESS.json` | WSL 正式输出；Cue v2/T4 | 主数据、离散证明、聚合报告、哈希闭合和成功原子门职责不同 | 回传 Windows 后作为不可变快照 |
| WSL 本地机器记录 | `cache/cache_manifest.jsonl`、`work/run_ledger.jsonl`、`work/run_report.json` | 仅 WSL 恢复和完整数值审计 | cache inventory、append-only 事件与当前汇总具有不同写入语义 | 至少保留到 Windows 导入 QA；之后按用户决定清理 |
| 大型缓存分片族 | 模型 snapshot、dense/sparse shard、索引、centroid/assignment 数组 | 仅 WSL 编码、检索、恢复 | 体量、第三方布局和流式恢复要求，无法合并为 JSON | 不回传；导入 QA 后可重建清理 |

本豁免不允许按 shard 写 SUCCESS JSON、按错误写 blocker JSON、按 query/cluster 写报告，或为 checkpoint 再建一组状态文件。所有安全错误、shard 关闭、恢复、solver 状态与 validator 事件统一追加到 `work/run_ledger.jsonl`，当前汇总原子写入 `work/run_report.json`；二进制缓存只由 `cache/cache_manifest.jsonl` 编目。

### 1. Source 字段和时间边界

冻结 Source 中的 `visible_text` 保留不变，但 BGE passage 只编码非空的 `transcript` 与 `dense_caption`。一个 Atom 固定生成一个字符串：先写 `transcript: ` 行，再写 `dense_caption: ` 行，以一个 `\n` 连接，不 trim、不做 NFKC/casefold，也不添加末尾换行；只编码一次。`visible_text` 仅用于核验 Source 派生关系，不重复编码，也不进入候选或 proof。资格/审计规范化固定为 Unicode 15.0.0 下的 NFKC、casefold、删 `Cf`、统一/折叠空白与首尾去空格，六个边界测试向量直接内嵌策略。

`event_timestamp` 是事件在 Source 视频/session 的位置，只用于 Source 定位、时间排序、Life Log 时间轴和状态机事件顺序。`temporal_condition` 是未来提醒的日期、频率、期限或关系条件，只能在 Seed/Rule 阶段由冻结模板和确定性规则构造，并经人工审计。BGE 不把 `00:10:05` 等视频时间戳当 trigger；“秒表”“看手机”等内容按证据属于 Object 或 Activity，不自动归入 Explicit-Time。

### 2. 六查询族与无配额政策

查询族统一为 `Person`、`Location`、`Object`、`Activity`、`State`、`Explicit-Time`。`Object / Person / Activity` 是 EgoLife 预计高产的第一梯队，`Location / State` 为第二梯队，`Explicit-Time` 为第三梯队；层级只用于方法解释和查询顺序。六族全部执行 dense/sparse 召回并报告原始召回、跨通道去重、最终贡献和人工抽样精度，但完全不设最低值或最高值，不得为补量放宽语义门。query family 只属于召回和统计层，Cue 最终 clause 语义仍由原字段证据决定。

### 3. 低内存 diversity 与确定性 cluster

全量 1024 维 BGE FP32 向量继续用于检索和候选间精确 cosine distance；聚类单独使用固定稀疏随机投影至 256 维，并在按 `split × participant × modality` 确定性抽取的 65,536 条样本上训练 1,024 簇 MiniBatchKMeans。冻结参数为 batch 8,192、`n_init=3`、`max_iter=20`、无重分配、单训练线程和固定 seed，再为全量 Atom 分块指派。这降低 11 GiB 内存下的风险，同时避免把粗聚类向量用于最终检索判断。

cluster ID 由 centroid 的 C 连续 little-endian FP32 规范字节生成：统一负零、拒绝 NaN/Inf，按 SHA256 和完整字节排序；重复 centroid 直接阻断。ID 只在当前 snapshot 内稳定，不能被解释为跨运行语义标签。

全部资格 Atom 必须恰好获得一次 cluster 指派，空 cluster 和重复 centroid 必须为 0；综合报告记录训练 inertia、cluster size 的 minimum/median/p95/p99/maximum 与占用熵。发现聚类塌缩时必须以新策略和新 selection ID 重跑，不能事后重标或删除大簇。

同簇全维 cosine distance `<=0.04` 视为近重复；每簇最多 20 条。近重复先按来源组稀有度、`split × participant × modality` 稀有度、query union 外优先、RRF/rank、centroid 距离和 `atom_id` 的静态全序生成 survivor，不能依赖尚未形成的 reservoir。随后每簇从 survivor 中确定性构造最多 64 条 diversity reservoir：首项靠近 centroid，后续最大化与已入集合的最小全维距离。核心 10,000 条至少包含 3,500 条 reservoir 成员，且至少 2,000 条同时位于 query top-k 并集之外，从而抑制“拿杯子”“打开门”等高频片段挤占。

### 4. 弹性数量与冲突规则

先在全部联合硬约束下生成恰好 10,000 条核心候选；随后按稀有簇轮转，只接受同簇最小全维 cosine distance 严格大于 `0.08`、该簇尚未达到扩展软上限 12 且不破坏其他门的样本。达到 12,000，或完整一轮无新增时停止。最终少于 10,000 才是 blocker；不得为了达到 12,000 降低质量门。

split 以 0.50/0.17/0.33 对最终行数使用最大余数法；参与者按 split 内资格份额分配；模态采用比例边界；来源组和 cluster 采用冻结上限。核心联合约束由固定单 worker OR-Tools CP-SAT 在全部 survivor 上求解，依次优化 query-union 覆盖、全局检索 rank、reservoir 新颖度和 `atom_id` 序号；每阶段必须证明 `OPTIMAL`，固定全部目标后还须从新 solver 重复两次并得到相同的选中 Atom SHA。`FEASIBLE`、`UNKNOWN`、超时或贪心失败均不能被解释为成功或不可行。所有召回、余数分配、cluster 规范化、缺口选择和扩展轮转都必须以 `atom_id` 或合同指定键终结平局。联合约束不可行时阻断，不自动放宽。

### 5. 五文件回传和 T4 验证边界

BGE 只决定“哪些 Atom 值得交给生成模型”。正式 `candidate_atoms.jsonl` 每行只含 `atom_id`。Windows 正式回传为候选、`selection_proof.jsonl`、一个综合报告、一个 manifest 和一个 SUCCESS。proof 约 6 万行，保存 top-k rank/FP32 分数、候选 provenance、cluster 汇总、shard 证明与确定性人工样本，但不保存 Source 正文、embedding 或索引。

T4 不重跑 BGE，可以从 proof 与 Source 独立重算 rank 连续性、RRF、primary attribution、候选成员、离散配额和分布报告。T4 无法从小文件证明全库 BGE top-k 数值完备性、embedding 正确性或全量 cluster 指派；这些由 WSL 本地完整审计验证，并由 manifest 绑定审计 Merkle 根、固定源码、模型 revision 和依赖锁。该边界必须在数据集卡和论文方法中明示。

## 五、两个 API 终端并行合同

### 1. 静态分配

协调器在任何 API 调用前生成唯一 `campaign_manifest.json`，其中冻结全部 partition、每个 partition 的 Atom 范围、所属 worker、模型、协议 SHA 和预算上限。两个终端不得自行领取任务或修改 partition。

### 2. 请求 ID

每次请求使用确定性且全局唯一的身份：

```text
<campaign_id>/<worker_id>/<partition_id>/<package_index>/<atom_set_sha>/<attempt>
```

同一逻辑请求的网络重试保持同一个 idempotency key；模型修复请求必须增加 attempt 并使用不同 request ID。request ID 的生成输入、规范化方式和哈希算法在执行前冻结。

### 3. 账本与预算

过去发生过重复 request ID、Wave/累计账本不一致和共享预算身份冲突，新版禁止多个 worker 追加任何共享账本：

- 每个 worker 有独立授权文件、独立预算上限、独立 request ledger 和独立费用快照；
- 总预算在运行前拆成两个不可重叠的硬额度，worker 不得借用其他额度；
- worker 只原子更新自己的状态文件；
- 协调器只读两个已关闭账本，按 request ID 集合构造累计账本；
- 聚合若发现任何重复 request ID、费用事件缺失、终态冲突或身份不一致，立即阻断，不自动重发；
- 恢复只扫描本 worker、本 partition 的未终态请求；已计费、已成功或已有终态的 Atom 永不自动重发；
- 迁移只能由确定性工具生成新账本并保留全部历史费用事件，不得手改 JSONL 或删除冲突行。

正式实现还必须增加“租约文件”：一个 partition 同时只能被一个 worker 持有；租约记录 campaign、worker、partition、启动时间和协议 SHA。失效租约只能由协调器在确认无进程、无在飞请求后释放。

### 4. staging 与 formal

worker 只写：

```text
cues/v2/staging/<campaign_id>/<worker_id>/<partition_id>/
```

每个 package 使用 `*.tmp` 后原子落盘。worker 完成后，协调器流式读取成功结构化结果，闭合 ambiguous，运行逐项与分片语义门，按固定顺序写 `cues/v2/formal/part_N.jsonl.tmp`，复算行数/字节数/SHA 后原子改名。这个过程不再次调用模型，复杂度为线性扫描；对数千条 Cue 而言工作量很小。

旧 `cues/formal/` 不得覆盖。Cue v2 使用版本目录和一个顶层 manifest/SUCCESS；不要求生成物理巨型 JSONL。

## 六、语义质量门

### 1. 逐项三层硬门

每个候选先校验 `cue_id`、`atom_id`、一个 predicate、1–3 个 clause、`all_of` 唯一性和血缘，再按 clause 独立执行以下三层。三层是递进关系，不得以第三层模型意见跳过前两层，也不得以 span 存在替代完整语义判断。

#### 第一层：字段内连续原文

- `evidence.field` 只能指向该 Atom 的一个原始 `transcript` 或 `dense_caption` 字段；`visible_text` 是派生展示字段，不作为新增 Cue 的权威 clause 证据字段；
- `evidence.span` 必须是该字段中的非空连续原文，禁止跨字段、跨 Atom、句段重排、翻译、摘要和拼接；
- 程序必须从 Source 重新取字段验证，不得相信模型回显的 Source 文本；
- 若采用字符偏移，偏移只负责从权威字段确定性切出 span，并必须同时检查边界和回切一致性；若模型只回传 span，则程序必须执行字段内连续查找并记录多处命中，但多处命中本身不能改变文本。

#### 第二层：value 直接支持

- `value` 必须能在自己的 span 中直接找到；比较最多允许 Unicode 规范化、Unicode 空白统一/折叠和首尾空白处理，不得删除实词、数字、单位、否定词、标点承载的语气或调整词序；
- 允许 `value` 是 span 中较短但完整的实体或状态短语，例如 span 为“我拿着手机”，value 为“手机”；不允许把“手机”规范化成“厨房”，也不允许把“下午三点左右”改成精确的“15:00”；
- `null`、`none`、`unknown`、`n/a`、空串及无法解析的纯代词/泛指词不得作为 value；
- 同一事实需要两个字段才能成立时，不得拼成一个 clause。确需组合时只能写成两个分别有独立证据的 clause，并在第三层检查二者是否仍属于同一 Atom 中同一个一致观察条件。

#### 第三层：完整断言语义支持

- 审核对象是 `dimension + operator + value` 组成的完整断言，而不是孤立关键词；span 必须蕴含该 dimension、关系、极性和作用范围；
- 人物必须区分“画面/描述中实际出现”“字幕说话人”“对话中仅被提及”。`Jake:` 可以支持 Jake 正在说话，不能自动支持 Jake 出现在画面；“我问过 Alice”不能自动支持 Alice 当前在场；
- 活动和状态不要求完整主谓宾，但必须有可识别的主体、对象或状态承载者。“拿着手机”“门已打开”可接受；单独“正在做”“发生变化”不可接受；
- 地点必须由明确地点词和相应关系支持。出现“冰箱”“锅”“床”等物体不能反推出厨房或卧室；仅提到地点不能改写成已经进入或当前位于该地；
- 否定词、量词、范围、比较、条件、假设、将来、计划、疑问、传闻和不确定语气必须保留。“没拿手机”不能生成手机出现；“如果三点开会”不能生成三点已经到达；“可能在厨房”不能生成确定在厨房；
- 显式时间只接受 Source 文本明确表达的日期、时刻、频率、期限或先后关系，并使用能保留其陈述/计划/假设语气的 operator。视频/session 的 `event_timestamp` 只用于定位和排序，永远不是 clause 证据或未来提醒条件；
- 多 clause 必须共同描述同一可判断条件，不得把 Atom 中彼此无关的事实堆在一个 predicate 中。删除任一 clause 若不改变触发含义，则该 clause 视为冗余并拒绝或删去后重新验证。

T2 生产验证和 T4 独立验证必须使用一致的规范化测试向量，但第三层不得仅靠字符串规则宣称完成。确定性规则能明确拒绝的直接拒绝；规则无法判断的人物角色、指代、范围和时间语气进入结构化人工审计。实现至少稳定输出 `SPAN_NOT_CONTIGUOUS`、`VALUE_NOT_SUPPORTED`、`SEMANTIC_DIMENSION_MISMATCH`、`OPERATOR_POLARITY_MISMATCH`、`PERSON_ROLE_MISMATCH`、`SCOPE_MISMATCH`、`TEMPORAL_MODALITY_MISMATCH`、`UNRESOLVED_REFERENT`、`CROSS_FIELD_EVIDENCE` 和 `CLAUSE_COUNT_OUT_OF_RANGE` 等原因码，账本不得保存模型原文解释。

### 2. 分片硬门

- JSON/Schema 成功率、修复率和各安全错误码；
- accepted/no-cue/ambiguous/排除比例；
- clause dimension、operator 和 evidence field 分布；
- 每个 split、参与者、模态和 `source_group_id` 覆盖；
- 哨兵值、槽位错置和证据错误必须为 0；
- 单一维度异常占优、字段覆盖归零或与前序分片显著漂移时暂停后续 partition；
- 每个分片完成分层人工抽检后才可被协调器纳入 formal。

分布阈值用于发现塌缩，不用于强迫模型制造预定比例。真实数据可以不均衡，但任何极端集中都必须得到人工解释和签字。

### 3. 全局硬门

- 候选 selection、全部分片和 disposition 全覆盖且互不重叠；
- Cue/Atom 唯一性和 Source SHA 全局一致；
- 模型、prompt、Schema 和参数在阶段内完全同质；
- 480 个 Seed 的 trigger/lure 可达性压力检查通过；
- 分布报告 manifest 已冻结且被 Cue SUCCESS 绑定；
- T4 语义 QA 零 blocker。

### 4. 真实性优先与最小 Cue 设计

本阶段采用以下全局内容约束：从 Atom、Cue、Seed 到 Life Log，任何人物、地点、物体、活动、状态和显式时间的事实性表述，都必须由同一 Source Atom 中明确的原文字段支持；构造内容只能表达提醒意图、生命周期或虚拟时间，必须标明 `constructed`，不得伪装为真实观察，也不得补造现实人物、地点、物体或已发生事件。无法从原文明确判断时，输出 `no_cue` 或排除，而不是合理猜测。

`span` 是证据锚点，不是质量保证。它只能证明一段字符存在于 Source，不能自动证明维度正确、主客体关系正确、否定词和范围词没有被截掉、说话人被提及等同于其在场，或视频时间被误当成未来时间。第 1 节规定的三层门必须逐层留下机器判定和人工审计结果；任何 accepted Cue 都不能只有“Schema 通过”和“span 找到”两项证据。

Cue 是可组合的观察条件，不是完整自然语言句子，故不要求每条 Cue 具有语法上的主谓宾。每个 Cue 最多一个 predicate，predicate 含一至三个 `all_of` clause；每个 clause 采用完整的 `dimension`、`operator`、`value` 和 `evidence`，不使用单字母压缩码。地点、物体、人物或显式时间可以是单一、无歧义的条件短语；活动和状态必须有可识别的动作主体、作用对象或状态承载者，否则不得接受。对于“说话人”“被提及的人”“画面中出现的人”必须使用不同 operator，禁止把名称出现偷换为人物在场。

Clause 数量由最小充分证据决定，而非配额：一条用于清楚的单一条件；两条通常用于“主体/对象 + 活动或状态”的可执行触发；三条只用于需要再加入地点、人物或状态才能消歧，且三条都能独立取证的复合条件。Clause 越多，跨短语拼接、关系错置和过拟合风险越高，因此模型必须选择最少且足够的 clause；程序将数量限制为 1–3，但不强迫各数量比例，也不把 clause 多视为质量高。进入 Seed 的 trigger Cue 另需满足可执行性要求，而不是要求所有 Cue 都写成完整句子。

`split` 是防止 train/dev/test 泄漏的操作元数据，不是 Cue 语义的一部分。正式 Cue 行不重复保存它，由下游根据 `atom_id` 从 Source 索引确定性回查；模型不生成 split，predicate 中也不出现它。执行期缓存可以携带 split 加速检索，但不得成为第二份正式事实源。

### 5. Life Log 的衔接边界

Cue library 只提供可追溯的条件与证据，不向 Life Log 嵌入 Cue JSON。每条日志固定关联一个目标意图、一个最终 trigger 观察和两个 lure；具体的固定事件布局、模型输入字段和隐藏标注边界由本计划第九节定义。背景 Atom 即使在 Cue 库中另有 Cue，也不计入该日志的目标相关观察数。

### 6. 校准、扩量与归档

优先复用 BGE selection 已提供的 350 条分层审计样本，人工标记 `no_cue`、Cue 维度、operator、证据 span、value、人物角色、否定/范围/时间语气、歧义和 Seed 可执行性；据此修改 prompt 与本地语义门。该设计校准集不能替代第 3 节的 800–1,000 条最终协议验收集。最终验收先运行约 500 条受控子波次，不改协议且通过后再完成余下 300–500 条；正式生产随后以约 1,500 条为首个检查点，通过后才扩展剩余候选。

全部候选执行第一、二层确定性检查和可自动化的第三层规则；较强模型只处理 ambiguous、人工抽样及拟进入 Seed 的 trigger Cue，不对 10,000–12,000 条做昂贵全量复审。每个请求建议最多携带 5 个具有稳定 `item_index` 的 Atom，各项独立验证和落盘；单项失败不得导致已通过项重付。失败项最多一次只含该 Atom 的简化修复，仍失败即关闭为 `excluded_after_repair` 或 `excluded_ambiguous`，不能为了接受率循环调用。一个 Atom 最多一条 accepted Cue。

生产按 checkpoint 检查 accepted/no-cue/ambiguous 比例、clause 数量、dimension/operator/evidence field、三层错误码、每千条成本、吞吐和 worker 漂移。约 3,000–5,000 条只是规划区间：达到 Seed 可达性与质量门即可停止，数量不足时回查 selection/prompt，禁止降低事实门凑数。旧版 370,799 Atom 全量调用约缩减为当前 10,000–12,000 候选，费用控制主要依靠前置筛选、短结构化输出、最多一次修复和按风险审计，而不是压缩成会引起语义混淆的单字母协议。

旧 `cues/formal/` 与旧 Cue library 保持只读审计归档：不得移动、覆盖、混入 v2 或作为下游数据。旧版的 `null` 哨兵、time 塌缩、槽位错置、高置信错误和空字段模式应整理为新 prompt/validator 的回归反例；可复用旧执行器中的分包、费用统计、独立账本、流式写入、Atom 回查和原子写入框架，但不得复用旧 compact 输出协议或旧 Cue 语义转换逻辑。

## 七、分布报告位置与结构

所有正式阶段统一写入：

```text
egopm_bench_v1/audit/distributions/<stage>/<snapshot_id>/
├── distribution_manifest.json
├── distribution_report.json
├── distribution_report.md
└── DISTRIBUTION_SUCCESS.json
```

`distribution_report.json` 是唯一机器权威报告，在一个严格 Schema 下合并 `summary/by_model/by_worker/by_split/by_participant/by_modality/by_shard/by_dimension/by_source_group/by_semantic_cluster/by_retrieval_channel/semantic_gates`。每个键必须有代码消费者；不适用的维度写带原因码的 `not_applicable` 对象，不生成空壳文件。即使一个阶段只有一个模型，`by_model` 也必须存在，用于证明阶段同质。多账号阶段的 `by_worker` 使用内部 worker 名而非账号标识，分别报告成功率、终态、费用和语义分布，并与重叠 Atom 对照检查账号漂移。

`distribution_report.md` 只从 JSON 确定性渲染，不另存一套数字。`distribution_manifest.json` 绑定机器报告、Markdown、生成参数和上游 manifest SHA；阶段 SUCCESS 必须记录 `distribution_manifest_sha256`。这把原先十余个相似小文件压缩为四文件快照，同时保留全部审计维度。

Cue v2 示例路径为：

```text
egopm_bench_v1/audit/distributions/cue_v2/<campaign_id>/
```

Seed candidate、Seed audit 和 Life Log 分别使用 `seed_candidates`、`seed_audit` 和 `lifelogs` 作为 `<stage>`。JSON/JSONL 是机器权威报告，Markdown 只负责人工阅读，不能替代其哈希绑定。

## 八、Seed candidates 与 480 Seed

Seed candidate 目标范围为 900–1,400，不提前锁死一个精确候选数。生产采用预注册停止规则：只有当每个 split、参与者、主要 clause dimension、生命周期终态和困难 silent 类型都达到覆盖下限，并且至少有 576 个候选通过机器门后，才可以停止扩充候选池。576 是最终 480 的 20% 替换余量，不代表允许事后挑选最好看的结果。

每个正式 Seed 必须：

- 引用唯一 `trigger_cue_id` 和对应 `trigger_atom_id`；
- `trigger_predicate` 与 Cue v2 predicate 完全一致；
- 至少有一个同 split、同 `source_group_id` lure；
- 至少有一个同 split、不同 `source_group_id` lure；
- 每个 lure 指出至少一个未满足的 predicate clause；
- trigger 和全部 lure 在候选快照内不跨 Seed 复用；
- 包含可执行的形成、完成、取消、过期和已提醒规则；
- 若包含未来时间语义，使用独立 `temporal_condition`，只能由冻结任务模板和确定性规则构造，必须与 `event_timestamp` 分字段保存并经人工审计；
- 能构成 matched positive/negative counterfactual；
- 当前 trigger 画面不能单独泄漏历史意图状态。

建议暂按 train 240、dev 80、test 160 规划 480 个 Seed；最终分配必须先证明冻结 Source split 的参与者和 `source_group_id` 足以支撑该结构。所有 480 个 Seed 都是统计 family 单位；2,880 条 Life Log 不能被当作 2,880 个独立任务。

## 九、Seed 审计与 Life Log 前置设计

Seed 审计分三层：确定性硬门、低成本模型意见、全部人工终审。DeepSeek 不做全量调用，只对跨模型争议、抽检和第三意见使用。人工审计必须先独立填写，再查看模型意见，防止锚定。

Life Log 只有在 480 个 Seed、rule bank 和协议参数冻结后生成。不同阶段允许选择不同中国厂商模型，但一个 Life Log 生产 campaign 内必须只有一个固定模型。Life Log 固定 2 个反事实分支 × 3 个难度，gold 只由 oracle 产生，生成模型不得决定 `remind/silent`。

### 1. 每条日志的固定骨架

每条 Life Log 只服务一个目标意图，并固定拥有以下五个结构角色：一条目标意图创建事件、一条生命周期控制事件、两条 lure 观察和一条最终 trigger 观察。两条 lure 中一条来自与 trigger 相同的 `source_group_id`，一条来自不同 `source_group_id`；positive 与 negative 分支必须使用同一个最终 trigger Atom/Cue，不能用不满足 predicate 的另一个观察替换它。于是每条日志恰有三条与目标 predicate 相关的真实 Source 观察，即同一个 trigger 加同两条 lure。这个“3”是目标相关观察数，不是把三个 Cue JSON 塞入 Life Log，也不限制背景 Atom 自身在 Cue library 中是否另有 Cue。

同一 `family_id` 的六条日志复用相同的 trigger、两条 lure 及全部背景 Source 观察；positive/negative 成对日志只允许替换一条位置相同的 constructed 生命周期控制事件。positive 使用明确的“意图仍有效/继续提醒”状态，negative 使用 `completed/cancelled/expired/already_reminded` 之一，使相同 trigger 上的 gold 从 `remind` 翻转为 `silent`。两支的事件数、Source Atom 序列、trigger 位置、lure 位置和难度负载保持一致。构造生命周期文本只表达规则状态，不声称视频中发生了新的现实事件。

核心数据不使用 `never_created`：统一骨架要求每条日志都有目标意图创建事件，若同时标记 never-created 会自相矛盾。`never_created` 如需保留，只能在后续作为单独的结构消融设计，不能混入这 2,880 条统一六路 Life Log，也不能与上述配对统计合并。

### 2. 长度、难度与一致性

实现前先以校准集确认 token 负载，随后将每个难度冻结为单一事件数而不是范围。当前推荐 short/medium/long 分别使用 12、36、72 个事件，背景意图数分别固定为 0、2、5，虚拟跨度候选值分别为 60、360、2,880 分钟；批次 B/C 必须根据真实 token 统计一次性确认或调整这些值。同一难度的每条日志必须事件数相同，positive/negative 成对日志也必须相同。五个固定结构角色占据确定位置，其余位置只填充背景 Source 观察或固定数量的背景意图。难度只由背景数量、背景意图数量、虚拟时间跨度和干扰接近度构成，绝不能通过减少 lure、删除 trigger 或让某些日志拥有大量额外 target Cue 实现。

每个难度还必须冻结统一的单事件文本上限和整条日志 token 区间；同一难度的日志 token 数应落在预注册区间内，成对 positive/negative 的 token 差异不得超过 5%。超过上限的 Atom只能使用仍包含完整证据的确定性连续原文窗口或更换背景 Atom，不得由模型概括改写。截取算法必须以权威字段、固定上下文窗口和稳定边界规则实现，并保留 `atom_id` 供回查；不得为了控制长度删除否定词、人物角色、范围词或时间语气。

### 3. 模型可见内容与隐藏标注

模型可见的 Life Log 事件只保留 `event_id`、顺序、虚拟时间、原文观察文本、provenance 和必要的 `atom_id` 引用。真实观察文本直接来自 Atom 原字段或其确定性连续窗口；其主语沿用原文、说话人标签或 Atom participant 所确定的 wearer。构造意图和生命周期控制优先使用受控模板，不默认调用语言模型；即使后续为语言自然度使用模型，也只能改写 constructed 文本并受占位符约束，其他现实人物、地点、物体和事件只能复制自已验证 Cue，不能自由添加、替换或改写 Source 事实。

Cue ID、predicate、trigger/lure 角色、生命周期前后状态、counterfactual branch、gold remind/silent、证据分组、置信度和 oracle 理由均是隐藏标注，不得进入模型输入。这样模型必须从生活记录本身决定提醒或沉默，而不是从标注字段读取答案。

正式 Life Log 主记录与模型输入视图必须明确分层：主记录可以为审计保存 `family_id/seed_id/split/difficulty` 和 Source 引用；模型输入视图只序列化时间与文本，不暴露 `counterfactual_branch`、`event_role` 或任何 gold 字段。Decision/Evidence 由主记录和隐藏标注确定性派生，不得把隐藏标注反向写回观察文本。

## 十、历史故障的强制规避

| 历史问题 | Cue/Seed v2 强制措施 |
| --- | --- |
| 模型端不支持 `uniqueItems` 导致 HTTP 400 | 每个生产模型先验证服务端支持的 Schema 子集；不支持的约束移到本地硬门 |
| 冗余 `cue_type` 与 predicate 冲突 | 删除顶层 `cue_type`，仅保留 clause dimension |
| 单字母 `T` 同时代表 transcript/time | 禁止全部单字母短码，使用完整枚举 |
| JSON `null` 变成字符串 `"null"` | 输入缺失字段省略；哨兵字符串零容忍 |
| optional 字段长期为空 | 删除无信息字段，不由解析器自动补空 |
| 错误结果仍有高 confidence | 删除模型自报 `confidence` |
| 只验 span、不验 predicate 语义 | clause-level value/evidence/dimension 三元硬门 |
| 全部 Wave 跑完才发现维度塌缩 | 每个 partition 写分布报告并设置漂移暂停门 |
| 修复只覆盖显式失败，不覆盖伪成功 | 对 accepted 也执行语义门和分层人工抽检 |
| 重复 request ID | 五级确定性 ID、worker 命名空间和聚合唯一性门 |
| 累计账本与终态冲突 | worker 独立账本；协调器只读集合聚合，不并发追加 |
| 共享预算身份冲突 | 两个独立授权和硬预算切片；总预算由 campaign manifest 绑定 |
| 恢复时误重发 | 仅恢复本 worker 未终态 request；任何冲突先阻断、后迁移 |
| 完整验证占用约 5.5 GB 内存 | 分片流式验证；近重复索引独立执行并使用磁盘/分桶算法 |
| BGE 依赖在下游启动时仍缺失 | WSL 环境、模型 revision、自检和 selection SUCCESS 先于 Cue API |

## 十一、实施顺序

批次 B 至 B07 已完成 Cue v2 Schema、配置、纯验证器、BGE 兼容导入预检、协议验收计划和协议隔离测试；仍不运行 API、不生成正式 Cue。后续顺序必须是：

### 0. 先清点并隔离 legacy 接口

当前仓库仍可见的 `cue_candidate.schema.json`、`cue_inference_batch_v1.schema.json`、`cue_inference_batch_compact_v1.schema.json`、`reminder_seed.schema.json`、legacy `model_registry.yaml` 分支以及 `prompts/seed_generator_v1.md` 中的 `time/place/state_change`、短码和 `primary_cue_type`，均属于只读 legacy 执行接口。它们不能被解释为 Cue v2 合同，也不能被 v2 或 Seed 入口读取；v2 只使用独立 Schema、prompt、配置键和 `cues/v2/**` 路径。

- 将正式 Cue Schema、推理 Schema、配置编码表和 Seed Schema 的 current dimension 统一为 `person/location/object/activity/state/explicit_time`，并删除顶层 `cue_type`、`primary_cue_type` 等旧血缘字段；
- 将推理字段改为单一原字段连续 `span`，在解析器中实现一 Atom 一 Cue、一个 predicate、1–3 个 `all_of` clause 及三层质量门；
- 更新 Seed prompt、validator、fixture 和测试，使 trigger predicate 只能精确引用 Cue v2，正负分支只能替换 constructed 生命周期控制事件；
- 对迁移前的旧 Schema/fixture/执行器保留只读审计身份，增加稳定的 legacy 拒绝错误码；任何旧 manifest、旧短码或旧 dimension 进入正式入口都必须在读取前阻断。

1. T0 以 CR-018/019/020/021/022 冻结 Cue v2 Schema 方向、模型政策、事实性三层门、统一 Life Log 骨架、SUCCESS 字段和工件预算；批次 B 再把 operator、错误码和推荐数值落实到 Schema/配置；
2. T2 只做无 API 实现：BGE 导入器、Cue v2 prompt/解析器、两个 worker 的独立预算/账本/lease/恢复机制，以及唯一 formalizer；
3. T4 只做无生产数据实现：语义门、账本一致性门、分布报告和阶段 SUCCESS validator；
4. 在 WSL 建立专用环境，完成 BGE-M3 自检并生成带输入 SHA 的 selection request；
5. WSL 单进程生成 Source selection，回传 Windows 指定目录，由 T4 验证 SHA、覆盖、互斥和分布；
6. 先完成人工标注的 350 条设计校准，再冻结 800–1,000 个协议验收 Atom，其中至少 120 个由两个账号重叠处理；验收先跑约 500 条不改协议的受控子波次；
7. 验收通过后冻结 Cue 协议 SHA、静态 partition、两个账号的独立授权和预算切片；
8. 用户在两个终端分别执行单行 PowerShell API 命令；生产先关闭约 1,500 条 checkpoint，质量、费用和 worker 漂移通过后才能继续；生产者只能写各自 staging 与私有账本；
9. 唯一协调器关闭所有 worker 后，完成 ambiguous 终态、formal 分片、全局分布、T4 QA、manifest 和 Cue SUCCESS；
10. T0 冻结 Seed Schema、单文件布局、900–1,400 候选停止规则、阶段模型和审计抽样合同；
11. T2 生成 Seed candidates，T4 验 trigger/lure 唯一性、同组/跨组构成、血缘、失败子句和分布；
12. 模型先给独立审计意见，人工随后全量终审；T3 只从通过门的候选冻结 480 个 Seed；
13. 480 Seed SUCCESS 后，再冻结 Life Log 模型、布局、Decision/Evidence 布局和实验协议参数；
14. 生成 2,880 条 Life Log，由确定性 oracle 产生 gold，最后完成分布报告和全链路 QA。

任何下游阶段都不得在上游 manifest、分布报告、T4 QA 与阶段 SUCCESS 全部成立前提前读取“看起来已完成”的局部文件。
CR-2026-022 第四步接纳 `_02` 为外部优化结果兼容导入；原 Schema 不可用仅记录 provenance warning，anytime solver 不得作全局最优表述，三层事实门不放宽。
