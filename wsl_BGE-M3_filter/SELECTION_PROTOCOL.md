# BGE-M3 候选筛选协议

## 一、协议目标与非目标

目标是在 370,799 条冻结 Source Atom 中确定性选出 8,000–12,000 个唯一候选 `atom_id`，提高后续 Cue v2 抽取的有效密度、可观察事实覆盖和来源多样性。

本协议不输出 Cue 类型、predicate、置信度或接受状态。相似度仅用于候选召回与排序，不构成语义真值。

## 二、正式运行身份

一次正式 selection 的身份至少由下列内容共同确定：

- `selection_id`；
- Source 文件 SHA256 与行数；
- 模型仓库、固定 revision 与模型文件 manifest SHA256；
- passage 序列化版本；
- `max_length`、精度、batch size 与编码选项；
- 查询集及其顺序；
- dense/sparse 每路 top-k；
- RRF 常数和融合规则；
- 多样性算法、距离度量、簇数与随机种子；
- 分层目标、上限、下限与最终选择顺序；
- 执行程序版本或源码 manifest SHA256。

除 batch size 可在**正式运行前**通过小型自检冻结外，上述任一值改变都必须使用新的 `selection_id`。正式 campaign 开始后不得原地改变身份参数。

## 三、正式请求文件

`input/selection_request.json` 是本阶段唯一参数来源。正式文件必须是有效 JSON，至少包含以下逻辑结构；示例值仅展示字段，不代表已批准参数：

```json
{
  "schema_version": "bge_selection_request_v1",
  "frozen": true,
  "selection_id": "由用户冻结的唯一ID",
  "source": {
    "relative_path": "input/source_video_atoms.jsonl",
    "sha256": "be5f36b77970cb5147b88551c566f081589fe00fcf5ef912d8468a037e92960e",
    "row_count": 370799
  },
  "model": {
    "repository": "BAAI/bge-m3",
    "revision": "5617a9f61b028005a4858fdac845db406aefb181"
  },
  "encoding": {
    "passage_serialization_version": "source_text_fields_v1",
    "max_length": 512,
    "precision": "fp32或fp16的冻结值",
    "batch_size": "小型自检后冻结的正整数",
    "return_dense": true,
    "return_sparse": true,
    "return_colbert_vecs": false,
    "shard_size": "冻结的正整数"
  },
  "retrieval": {
    "dense_top_k_per_query": "冻结的正整数",
    "sparse_top_k_per_query": "冻结的正整数",
    "rrf_k": "冻结的正数",
    "queries": [
      {
        "query_id": "唯一且稳定的查询ID",
        "family": "person_interaction",
        "language": "zh",
        "text": "描述可直接观察事实的冻结查询文本"
      }
    ]
  },
  "diversity": {
    "algorithm": "冻结的算法名与版本",
    "distance_metric": "cosine",
    "cluster_count": "冻结的正整数",
    "random_seed": "冻结的整数",
    "per_cluster_cap": "冻结的正整数"
  },
  "stratification": {
    "target_candidate_count": "8000至12000之间的冻结整数",
    "dimensions": [
      "split",
      "participant_source_id",
      "modality_coverage",
      "source_group_id"
    ],
    "minimums": {},
    "maximums": {},
    "selection_policy": "冻结的确定性策略名与版本"
  },
  "expected_request_sha256": "对不含本字段或按约定规范化后内容计算的冻结SHA256"
}
```

正式请求不能保留“由用户冻结”“冻结的正整数”等占位文本。若请求未定义候选总数、排序策略、配额冲突处理或请求哈希计算方法，WSL Codex 必须先提交参数缺口报告，不能自行选择后开始正式运行。

## 四、查询族设计门

冻结查询集应覆盖下列六类直接可观察事实：

1. `person_interaction`：人物出现、相遇、交谈、递交、共同活动；
2. `place_transition`：进入、离开、到达或处于可辨识地点；
3. `object_interaction`：物体出现、持有、拿取、放置、开启、关闭；
4. `activity_boundary`：活动开始、进行、完成或停止；
5. `state_change`：物体、设备、食物、门窗或环境的可观察变化；
6. `explicit_time`：原文明确表达时间、频率、期限或先后关系。

查询可以有中文与英文版本，但每个版本必须具有独立 `query_id`，全文和顺序必须冻结。不得在看到全量命中结果后临时增删查询来追求理想分布；确需修改时创建新 `selection_id`。

查询文本不得：

- 包含某个最终 Seed 的答案或人工选定 trigger；
- 包含参与者 ID、split、文件路径或来源组 ID；
- 把虚拟提醒时间写成 Source 观察事实；
- 要求模型推断跨 Atom 关系、意图、心理状态或不可见事实。

每个查询族的查询数、语言构成、dense/sparse 命中贡献和最终保留数都必须报告。某个查询族完全无命中或几乎支配全部候选时，属于需要解释的分布异常，不得静默忽略。

## 五、passage 构造

每个 Atom 严格按固定字段顺序构造：

```text
transcript: <原字段字符串；空值则留空>
dense_caption: <原字段字符串；空值则留空>
visible_text: <原字段字符串>
```

仅对模型输入执行冻结的 Unicode 和换行规范化；正式 Source 不得重写。不得加入 `participant_source_id`、`source_day`、`session_id`、`source_group_id`、时间戳、路径、`split`、`modality_coverage` 或未来标签。

资格过滤只能排除：

- 三个模型输入字段规范化后都没有有效文字；
- 规范化后只含空白、标点或格式字符；
- 冻结请求明确列出的纯格式解析失败或噪声。

不得因某个 Atom 看起来“不像提醒”、属于某一 split 或来自高频参与者而在 embedding 前删除。覆盖控制应在召回后通过透明的分层策略完成。

## 六、分片编码与缓存

- Source 必须流式读取；禁止把完整 JSONL 与全部 sparse 表示同时载入 11 GiB 内存。
- 以冻结 `shard_size` 按输入行顺序静态分片，范围必须连续、互不重叠并覆盖全部资格集合。
- 每个 shard 同时保存 Atom ID 顺序、输入范围哈希、dense shape、sparse shape、NaN/Inf 检查和文件 SHA256。
- dense 落盘前转为 FP32 并 L2 归一化；可使用 `numpy.memmap`。
- sparse 使用逐 shard CSR 或等价压缩结构；不得生成不可恢复的 Python pickle 作为唯一缓存。
- `.tmp` 不可用于恢复；只信任完成标记和 SHA256 均匹配的 shard。
- OOM 时停止当前 shard，从该 shard 开头重跑。若需要改变冻结 batch size 或精度，终止当前 campaign 并创建新 selection。

## 七、多通道召回

对每条冻结查询分别执行：

1. dense top-k；
2. sparse top-k；
3. 在各自名次上执行冻结 RRF；
4. 记录 `query_id`、通道、原始名次与融合分数。

若 RRF 定义为 `score = Σ 1 / (k + rank)`，必须固定 rank 从 1 开始还是从 0 开始，并在环境报告中写清；不得依赖库默认值。所有同分项最终以 `atom_id` 升序打破平局。

正式输出不要求保存全部 370,799 条的原始得分，但必须保留足以复核每个候选为何入选的命中摘要。缺失的通道字段应省略，不要写虚假的 0 或字符串哨兵。

## 八、多样性与分层选择

多样性步骤只能在冻结算法上执行，并使用固定随机种子。它的目的有两个：

- 从 dense 语义空间补足未被查询 top-k 覆盖的可观察事件模式；
- 避免少数重复场景、参与者或来源组消耗大部分候选预算。

最终候选至少由以下集合并集形成：

- 各查询族 dense 命中；
- 各查询族 sparse 命中；
- RRF 高排名命中；
- 语义簇 diversity reservoir；
- 按冻结最小覆盖门补足的参与者、模态、split 和来源组样本。

执行顺序必须由 `selection_policy` 精确定义，至少说明：通道如何轮转、查询族如何分配、最低覆盖与最高上限冲突时如何处理、何时停止、候选不足时是否允许从何种 reservoir 补足。不能用重复 Atom 或重复同一场景凑数。

所有候选按 `atom_id` 去重。分层元数据只用于选择与报告，不得进入 BGE passage。若覆盖门在目标上限内无法同时满足，应报告 blocker，不得临时降低门禁或增加目标上限。

## 九、正式候选行

`candidate_atoms.jsonl` 每行至少包含：

```json
{
  "atom_id": "src_...",
  "selection_channels": ["dense_query", "sparse_query", "rrf", "diversity"],
  "query_hits": [
    {
      "query_id": "query_...",
      "dense_rank": 1,
      "rrf_score": 0.016393
    }
  ],
  "selection_reason_codes": ["query_family_hit", "coverage_retained"],
  "diversity_cluster_id": "cluster_..."
}
```

若字段对某个候选不适用，应省略该可选字段。`selection_channels` 与 `query_hits` 内部顺序必须确定。正式候选不得重复保存 Source 正文、参与者、split、模态或路径；这些信息通过 `atom_id` 在本地 Source 回查。

## 十、报告与漂移检查

必须报告：

- Source 总体与资格集合的 split、参与者、模态、来源组分布；
- 每种资格排除原因的数量；
- 每个查询、查询族和检索通道的召回数、去重后贡献和最终保留数；
- 候选的 split、参与者、模态、来源组和 diversity cluster 分布；
- 每个 encoding shard 的行数、耗时、峰值显存和 SHA256；
- 候选重复、回查失败、缺失来源组、NaN 和 Inf 数量；
- 候选相对 Source 的分布偏移与覆盖缺口；
- 环境、模型、请求、源码、cache 与输出 manifest 哈希。

至少对每个 split、参与者、模态和 shard 比较候选率。异常塌缩的判断阈值必须在请求中冻结；没有冻结阈值时可以生成诊断，但不能声称已通过正式分布门。

本阶段不报告 Cue `dimension`，因为 Cue 尚未生成。

## 十一、SUCCESS 门

只有以下条件全部满足才可写 `BGE_FILTER_SUCCESS.json`：

- Source、模型、请求和源码身份全部匹配；
- 所有资格 Atom 均完成编码，所有 shard 互不重叠且 SHA 一致；
- 候选总数在冻结目标内，`atom_id` 唯一且全部可回查；
- 查询、融合、多样性和分层策略均按请求执行；
- 分布报告与实际候选重算一致；
- `candidate_manifest.json` 绑定所有正式输出；
- 没有未解决 blocker 或仍在飞的进程；
- SUCCESS 最后写入，并绑定 candidate manifest、Source、模型、请求、源码和分布报告哈希。

若未通过，应保留无正文错误报告与可验证缓存，但不得创建伪 SUCCESS。
