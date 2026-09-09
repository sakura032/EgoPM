# EgoPM-Bench v1 Cue/Seed v2 生产计划

> 决议日期：2026-09-09  
> 状态：T0 已冻结项目方向；Schema、配置和执行代码尚未实施  
> 适用范围：Cue v2、BGE-M3 候选筛选、Seed candidates、Seed 审计和 Life Log 规模  
> 上游：冻结 Source Atom 370,799 条，SHA256 `be5f36b77970cb5147b88551c566f081589fe00fcf5ef912d8468a037e92960e`

## 一、方向调整

旧 `realtime_v9_01` 及其 294,839 条 Cue 保持不可变，继续作为执行、费用、覆盖和故障审计材料；由于已确认存在系统性语义塌缩，它不再具有 Seed 正式上游资格，也不得与 Cue v2 混合。旧 Cue 的结构 QA“0 blocker”只证明当时合同下的 Schema、哈希、证据片段和覆盖关系成立，不代表 predicate 语义正确。

新主线不再要求对 370,799 个 Source Atom 各生成一个 Cue。生产改为：

1. 对全量 Source 做确定性预过滤和本地 BGE-M3 多路召回；
2. 冻结 8,000–12,000 个具有覆盖性和多样性的候选 Atom；
3. 三个阿里云账号使用同一个 `qwen3.7-flash` 生产协议并行抽取 Cue v2；
4. 目标得到约 3,000–5,000 条高质量 `accepted_cue`，按 Seed 可达性停止，而不是追求固定 Cue 总量；
5. 生成 900–1,400 个 Seed candidates；
6. 经程序门、低成本模型审计和全部人工终审，冻结 480 个独立 Seed；
7. 每个 Seed 派生 2 个反事实分支 × 3 个难度，共 2,880 条 Life Log。

480 个 Seed 至少占用 480 个唯一 trigger Cue、480 个唯一 trigger Atom 和 960 个唯一 lure Atom，共至少 1,440 个互不复用的 Source Atom。候选快照若包含 900–1,400 个 Seed，则至少需要 2,700–4,200 个互不复用 Atom，因此 Cue 和候选 Atom 池必须保留充分余量。

## 二、Cue v2 的科学边界

Cue 只表达单个 Source Atom 中已经观察到的事实，不表达未来提醒意图、虚拟时间、跨 Atom 关系或生命周期规则。Cue v2 只允许 `all_of` 合取；`any_of`、虚拟时间窗口、替代触发条件和 Reminder 状态机全部留在 Seed/Rule 阶段。

正式 Cue 行只保存科学内容：

```json
{
  "cue_id": "cue_...",
  "atom_id": "src_...",
  "predicate": {
    "all_of": [
      {
        "dimension": "person | place | object | activity | state_change | time",
        "operator": "eq | not_eq | present | absent | starts | ends | contains",
        "value": "...",
        "evidence": {
          "field": "transcript | dense_caption | visible_text",
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

## 三、模型政策

### 1. 阶段内单模型

同一个正式生产阶段只能使用一个固定模型 ID、一个 prompt hash、一个推理 Schema hash 和一套采样参数。多个账号只扩展吞吐，不得改变模型语义。Cue v2 沿用 `qwen3.7-flash`；新 campaign 启动时必须冻结实际请求模型 ID、地域、端点、参数和协议 SHA。运行过程中若服务端模型映射发生不可证明的一致性变化，必须停止并新建 campaign，不能继续混写。

三个阿里云账号分别绑定 `worker_00`、`worker_01`、`worker_02`。每个账号只处理预先分配且互不重叠的 partition。账号、worker、partition 不进入正式 Cue 行，但必须在私有执行账本和 shard provenance 中可追溯。

### 2. 阶段间允许不同模型

- Cue v2 批量抽取：`qwen3.7-flash`，非思考或平台最低稳定推理设置；
- Seed candidate 生成：先以 `qwen3.7-plus-2026-05-26` 为候选，不在本 CR 中最终冻结；
- Cue/Seed 模型审计：优先抽样使用 Plus；DeepSeek 只作为少量独立审计或争议第三意见，不做全量审计；
- Life Log 语言生成：在 Seed 冻结前另做阶段专项比较，可与 Cue/Seed 使用不同中国厂商模型；
- oracle、状态迁移、gold、split、血缘和 SUCCESS：始终由确定性程序产生。

模型审计只提供意见，不能替代程序门或人工签字。为控制费用，Cue 阶段不对全部 8,000–12,000 条再次调用昂贵审计模型；必须审计全部最终 trigger Cue、全部争议 Cue，并按模型、split、参与者、模态和分片分层抽检其他终态。

### 3. 大规模调用前的协议验收集

正式扩量前，从 BGE selection 中按 `split × participant × modality × source_group_id × 召回通道` 分层冻结 800–1,000 个 Atom，形成独立的协议验收集。它只用于验证 prompt、Schema、解析器、语义门和账号同质性，永不进入 Cue、Seed 或 benchmark，也不计入正式分布。

其中至少 120 个重叠 Atom 必须由三个阿里云账号分别处理一次，用于检测账号、地域、端点或服务端映射差异。验收只保存结构化输出、无正文 disposition、安全错误码、人工标签和聚合统计，仍然禁止保存原始模型响应。

扩量门至少要求：证据 span 合法率 100%；哨兵字符串与跨字段/跨槽位错配为 0；Schema 有效率不低于 99.5%；predicate 语义精确率达到预注册阈值；`no_cue` 与各 clause dimension 有单独的精确率/召回率；三个账号不存在无法解释的分布漂移。任一门失败时必须修改协议并产生新的验收集 ID，旧验收结果不得与新协议合并，也不得直接扩大正式调用。

## 四、BGE-M3 候选筛选

BGE-M3 在 WSL2 中本地单 GPU、单编码进程运行。Windows 仓库中的 `wsl_BGE-M3_filter/` 是可搬运的执行说明包；WSL 输出返回 Windows 后进入：

```text
egopm_bench_v1/cues/v2/source_selection/<selection_id>/
```

筛选包含四路并集：

1. 确定性资格过滤：排除空文本、纯噪声、极短无信息文本和已知不可用格式，但不得依据 split 或目标答案改变文本；
2. BGE-M3 dense 召回：覆盖人物交互、地点进入/离开、物体出现/操作、活动开始/结束、可观察状态变化和明确时间表达的冻结查询族；
3. BGE-M3 sparse 召回：补回显式词项、名字、地点、物体和动作；
4. dense embedding 多样性保留：从查询未覆盖的语义簇中保留样本，避免查询族把候选池限制成预设模板。

候选并集按 `split × participant × modality × source_group_id` 分层，先做 Atom 去重，再限制单一 `source_group_id` 的最大占比。最终 selection manifest 绑定查询族、BGE revision、序列化规则、全部参数、依赖版本、Source SHA、候选行数和分布报告 SHA。

BGE 结果只能决定“哪些 Atom 值得交给生成模型”，不能决定 Cue predicate、是否 accepted 或最终 Seed。BGE embedding、稀疏权重和索引是可重建缓存；正式传输只需要候选 Atom ID、召回通道、rank/score、分层字段和 manifest/SUCCESS。

## 五、三个 API 终端并行合同

### 1. 静态分配

协调器在任何 API 调用前生成唯一 `campaign_manifest.json`，其中冻结全部 partition、每个 partition 的 Atom 范围、所属 worker、模型、协议 SHA 和预算上限。三个终端不得自行领取任务或修改 partition。

### 2. 请求 ID

每次请求使用确定性且全局唯一的身份：

```text
<campaign_id>/<worker_id>/<partition_id>/<package_index>/<atom_set_sha>/<attempt>
```

同一逻辑请求的网络重试保持同一个 idempotency key；模型修复请求必须增加 attempt 并使用不同 request ID。request ID 的生成输入、规范化方式和哈希算法在执行前冻结。

### 3. 账本与预算

过去发生过重复 request ID、Wave/累计账本不一致和共享预算身份冲突，新版禁止多个 worker 追加任何共享账本：

- 每个 worker 有独立授权文件、独立预算上限、独立 request ledger 和独立费用快照；
- 总预算在运行前拆成三个不可重叠的硬额度，worker 不得借用其他额度；
- worker 只原子更新自己的状态文件；
- 协调器只读三个已关闭账本，按 request ID 集合构造累计账本；
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

### 1. 逐项硬门

- `cue_id`、`atom_id` 唯一且血缘可解析；
- 每个 clause 只引用同一 Atom 的一个原字段；
- span 按冻结的 Unicode 归一化匹配后从原字段确定性切出；
- `value` 必须受该 clause 的 span 直接支持；
- person/place/object/activity/state_change/time 不得发生槽位错置；
- time 仅接受显式时间、频率、期限或时间关系证据；
- 禁止 `null`、`none`、`unknown`、`n/a` 及其大小写/空白变体；
- 禁止跨字段拼接、跨 Atom 拼接和释义替代证据；
- Cue 只允许 `all_of`，不得出现 `any_of`；
- 未闭合 ambiguous 不得进入正式数据。

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

## 七、分布报告位置与结构

所有正式阶段统一写入：

```text
egopm_bench_v1/audit/distributions/<stage>/<snapshot_id>/
├── distribution_manifest.json
├── distribution_summary.json
├── by_model.json
├── by_worker.json
├── by_split.json
├── by_participant.json
├── by_modality.json
├── by_shard.jsonl
├── by_dimension.json
├── semantic_gate_report.json
├── distribution_report.md
└── DISTRIBUTION_SUCCESS.json
```

即使一个阶段只有一个模型，`by_model.json` 也必须存在，用于证明阶段同质。多账号阶段还必须有 `by_worker.json`，使用内部 worker 名而非账号标识，分别报告成功率、各终态、费用和语义分布；它与协议验收集的重叠 Atom 对照共同检查账号漂移。`distribution_manifest.json` 逐文件绑定 SHA256、行数或对象数、生成参数和上游 manifest SHA；生产阶段 SUCCESS 必须记录 `distribution_manifest_sha256`，没有该字段不得进入下一阶段。

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
- 能构成 matched positive/negative counterfactual；
- 当前 trigger 画面不能单独泄漏历史意图状态。

建议暂按 train 240、dev 80、test 160 规划 480 个 Seed；最终分配必须先证明冻结 Source split 的参与者和 `source_group_id` 足以支撑该结构。所有 480 个 Seed 都是统计 family 单位；2,880 条 Life Log 不能被当作 2,880 个独立任务。

## 九、Seed 审计与 Life Log 前置设计

Seed 审计分三层：确定性硬门、低成本模型意见、全部人工终审。DeepSeek 不做全量调用，只对跨模型争议、抽检和第三意见使用。人工审计必须先独立填写，再查看模型意见，防止锚定。

Life Log 只有在 480 个 Seed、rule bank 和协议参数冻结后生成。不同阶段允许选择不同中国厂商模型，但一个 Life Log 生产 campaign 内必须只有一个固定模型。Life Log 仍固定 2 个反事实分支 × 3 个难度，gold 只由 oracle 产生，生成模型不得决定 `remind/silent`。

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
| 共享预算身份冲突 | 三个独立授权和硬预算切片；总预算由 campaign manifest 绑定 |
| 恢复时误重发 | 仅恢复本 worker 未终态 request；任何冲突先阻断、后迁移 |
| 完整验证占用约 5.5 GB 内存 | 分片流式验证；近重复索引独立执行并使用磁盘/分桶算法 |
| BGE 依赖在下游启动时仍缺失 | WSL 环境、模型 revision、自检和 selection SUCCESS 先于 Cue API |

## 十一、实施顺序

当前只冻结计划，不修改 Python、Schema 或配置，也不运行 API。后续顺序必须是：

1. T0 以 CR-018/019/020 冻结 Cue v2 Schema、模型政策、SUCCESS 字段和大规模分片合同；
2. T2 只做无 API 实现：BGE 导入器、Cue v2 prompt/解析器、三个 worker 的独立预算/账本/lease/恢复机制，以及唯一 formalizer；
3. T4 只做无生产数据实现：语义门、账本一致性门、分布报告和阶段 SUCCESS validator；
4. 在 WSL 建立专用环境，完成 BGE-M3 自检并生成带输入 SHA 的 selection request；
5. WSL 单进程生成 Source selection，回传 Windows 指定目录，由 T4 验证 SHA、覆盖、互斥和分布；
6. 冻结 800–1,000 个协议验收 Atom，其中至少 120 个由三个账号重叠处理；
7. 验收通过后冻结 Cue 协议 SHA、静态 partition、三个账号的独立授权和预算切片；
8. 用户在三个终端分别执行单行 PowerShell API 命令；生产者只能写各自 staging 与私有账本；
9. 唯一协调器关闭所有 worker 后，完成 ambiguous 终态、formal 分片、全局分布、T4 QA、manifest 和 Cue SUCCESS；
10. T0 冻结 Seed Schema、单文件布局、900–1,400 候选停止规则、阶段模型和审计抽样合同；
11. T2 生成 Seed candidates，T4 验 trigger/lure 唯一性、同组/跨组构成、血缘、失败子句和分布；
12. 模型先给独立审计意见，人工随后全量终审；T3 只从通过门的候选冻结 480 个 Seed；
13. 480 Seed SUCCESS 后，再冻结 Life Log 模型、布局、Decision/Evidence 布局和实验协议参数；
14. 生成 2,880 条 Life Log，由确定性 oracle 产生 gold，最后完成分布报告和全链路 QA。

任何下游阶段都不得在上游 manifest、分布报告、T4 QA 与阶段 SUCCESS 全部成立前提前读取“看起来已完成”的局部文件。
