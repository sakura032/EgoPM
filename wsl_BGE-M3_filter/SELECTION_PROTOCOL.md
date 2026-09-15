# BGE-M3 候选筛选协议 v3.1

本文件是筛选算法的唯一权威说明。目标是从冻结 Source 中确定性选出 `10,000–12,000` 个唯一 Atom，兼顾 Cue 潜力、语义多样性以及后续 480 个 Frozen Seed 的覆盖。BGE 分数只用于召回，不是 Cue 正确性、语义标签或置信度。

## 一、输入身份与职责分离

```text
source_video_atoms.jsonl ─┐
SOURCE_ATOMS_SUCCESS.json ├─> selection_request.json ─> 正式执行
两个必要 Schema ─────────┤
model_config.json ────────┤
query_set.jsonl ──────────┤
selection_policy.json ────┘
```

`selection_request.json` 只保存运行身份及其他输入的相对路径、SHA256 和必要行数，不保存自身哈希。自身原始字节 SHA256 仅写入 `selection_request.sha256`，避免自引用。其余职责如下：

| 文件 | 唯一职责 |
| --- | --- |
| `model_config.json` | 固定 BGE-M3 revision、模型参数、passage 和缓存格式 |
| `query_set.jsonl` | 固定 48 条有序查询及六个查询族 |
| `selection_policy.json` | 固定资格、召回、聚类、去重、分层、弹性补样、冲突和排序 |
| `input/schema/source_video_atom.schema.json` | 与 Windows 权威文件同 SHA，严格定义 Source 每行 |
| `input/schema/bge_selection_artifacts.schema.json` | 在一个文件的 `$defs` 中严格定义候选、五类 proof、report、manifest 与 SUCCESS |

根请求直接绑定三个配置组件和两个 Schema。根请求及配置组件由原始字节 SHA 和实现中的严格键集合共同约束；两个数据接口使用 Draft 2020-12 Schema、format checker 和 `additionalProperties=false`。Source SUCCESS 作为已冻结上游证明，只接受根请求绑定的完整文件 SHA；未知字段会改变该 SHA，因此不额外复制一个只服务单份冻结文件的 Schema。禁止占位文本以及非 Source Schema 明确允许位置的 JSON `null`；禁止哨兵字符串。执行器维护“已消费配置叶字段”集合；任何声明但未使用、代码读取但合同未声明的字段均为 blocker。组件任一字节改变都必须更新绑定并使用新的 `selection_id`。

## 二、Source 字段与两个时间概念

### 1. passage 与 `visible_text`

冻结 Source 每行先使用随包提供且 SHA 与 Windows 权威文件一致的 `source_video_atom.schema.json` 验证，再做语义一致性门。`transcript_only` 必须是非空 transcript 加 null dense caption，`dense_caption_only` 反之，`both` 必须两个字段均为非空字符串。`visible_text` 只做输入一致性检查，不独立编码，也不进入正式候选或证明流：

- `dense_caption_only`：`visible_text == dense_caption`；
- `transcript_only`：`visible_text == transcript`；
- `both`：`visible_text == "Dense caption: " + dense_caption + "\nTranscript: " + transcript`。

一个 Atom 只形成一个模型输入字符串，只调用一次 passage 编码。执行器按以下等价伪代码逐 Unicode code point 构造，不 trim、不 casefold、不做 NFKC：

```python
lines = []
if isinstance(transcript, str) and len(transcript) > 0:
    lines.append("transcript: " + transcript)
if isinstance(dense_caption, str) and len(dense_caption) > 0:
    lines.append("dense_caption: " + dense_caption)
passage = "\n".join(lines)
```

不得分别编码两个字段后再取最大、求和或平均；不得再拼接 `visible_text`；不得加入 split、参与者、`source_group_id`、路径、日期、session 或视频时间戳。查询同样按 `query_set.jsonl.text` 的原始字符串单次编码，不执行文本变换。

`nfkc_casefold_whitespace_cf_v1` 只用于资格与审计，不作为模型输入：固定 Unicode 15.0.0，依次执行 NFKC、默认 casefold、删除 general category `Cf`、把 Python `str.isspace()` 为真的字符映射成 ASCII space、折叠连续 ASCII space、删除首尾 ASCII space。字母/数字判定严格为 `unicodedata.category(ch)` 首字母属于 `L` 或 `N`。规范结果不含任何字母/数字时排除；原 Source 字符串永不覆盖。宽字符、NBSP、`Cf`、混合空白、纯空白和纯标点六个测试向量直接内嵌在对应策略对象中，避免另建零散文件；正式执行前必须逐项验证。

等价实现必须逐步调用 `unicodedata.normalize("NFKC", text)`、Python `str.casefold()`、`unicodedata.category()` 与 `str.isspace()`；不得用正则 `\s`、ASCII-only lower 或 tokenizer normalization 替代。运行时 `unicodedata.unidata_version` 不等于 `15.0.0` 时直接阻断。

### 2. `event_timestamp` 与 `temporal_condition`

`event_timestamp` 指 Source 视频或 session 中的事件位置。现有 Source 时间字段继续用于定位、排序、Life Log 时间轴和状态机事件顺序，但不构成 prospective-memory trigger。

`temporal_condition` 指“明天见到 Alice”“每周五”“下周之前”等未来提醒条件。它只能在 Seed/Rule 阶段由冻结模板和确定性规则构造，并经人工审计；禁止从视频时间戳推导。

因此，`00:10:05` 不得自动成为提醒条件；“秒表”“看手机”等内容通常属于 `Object` 或 `Activity`。`Explicit-Time` 查询只召回原始文本明确出现的日期、时刻、期限、频率或先后关系，最终 Cue 仍须提供原字段可直接引用的 clause-level 证据。

## 三、六类查询与召回

查询族固定为 `Person`、`Location`、`Object`、`Activity`、`State`、`Explicit-Time`。它们用于查询组织、召回归因和报告，不是 Cue 的最终语义标签，也没有任何最低值或最高值。

论文解释中的优先层级是：`Object / Person / Activity` 为第一梯队，`Location / State` 为第二梯队，`Explicit-Time` 为第三梯队。优先层级只影响查询顺序和结果解释，不形成数量配额，不得为补足任一类而放宽语义门。

每族固定 4 条中文与 4 条英文查询。每条查询分别执行 dense top-500 和 sparse top-500，列表按 `(-float32_score, atom_id)` 排序，rank 从 1 开始。RRF 固定为 `Σ 1 / (60 + rank)`，排序时从整数 rank 重算精确有理值，不使用展示小数。

primary attribution 依次按 RRF 降序、最佳 rank 升序、冻结 family 顺序、`query_id` 升序决定。它只是单一统计归因，不改变 Atom 真实语义，也不限制 diversity 通道选出的内容。

## 四、聚类、规范化 cluster ID 与近重复

### 1. 计算路径

- BGE-M3 全量 dense embedding 为 L2 归一化 FP32、1024 维，用于检索以及候选间精确 cosine distance。
- 所有精确 cosine distance 在 CPU 单线程计算：C 连续 FP32 输入逐维提升为 FP64 相乘，以冻结 NumPy 版本的 `sum(..., axis=-1, dtype=float64)` 归约，dot 截断到 `[-1,1]`，再把 `1-dot` 转为 FP32；所有 `0.04/0.08` 比较和 proof 十六进制均使用这一最终 FP32。不得把投影距离、GPU FP16 dot 或多线程归约用于这些门。runtime lock 与重复解 SHA 门共同限定该数值实现的可复现边界。
- 聚类专用向量通过固定 `SparseRandomProjection` 从 1024 维投影至 256 维，再 L2 归一化；投影只用于粗粒度 diversity cluster，不能替代 BGE 检索分数。
- 按 `split × participant_source_id × modality` 从资格集合确定性抽取 65,536 条训练样本。先对每个非空层分配 `min(可用量, 32)`；总和不超过样本数时，余量按剩余可用份额和最大余数分配。若这些最低分配总和超过样本数，先给每个非空层 1 条，再按剩余可用份额分配；非空层本身多于 65,536 时阻断。层内按 `SHA256(seed + NUL + atom_id)` 升序取样。
- 在样本上运行固定版本 scikit-learn `MiniBatchKMeans`：`n_clusters=1024`、`batch_size=8192`、`init_size=8192`、`n_init=3`、`max_iter=20`、`max_no_improvement=30`、`tol=0`、`reassignment_ratio=0`、单训练线程、固定 seed。随后分块为全部资格 Atom 指派 cluster。

这比在全部 `370,799 × 1024` 向量上做 10 次、200 轮初始化明显节省内存与 CPU，同时保留全量 BGE 向量作最终距离门。MiniBatchKMeans 使用投影后单位向量的欧氏目标；文档不得把未归一化 centroid 的距离误称为严格 cosine。

### 2. cluster ID

原始 label 不得进入正式记录。每个 centroid 必须：转为 C 连续 little-endian FP32；把 `-0.0` 归一为 `+0.0`；拒绝 NaN/Inf；对规范字节计算 SHA256；按 `(centroid_sha256, centroid_bytes)` 升序映射为 `cluster_0000` 起的零基编号。若 centroid 规范字节完全相同则阻断，禁止用库原始 label 兜底。

cluster ID 只在当前 selection snapshot 内稳定，不宣称跨硬件或跨库版本具有语义恒等性。manifest 必须绑定运行时 lock、源码 manifest、请求 SHA 和 centroid 摘要。

聚类质量门要求全部资格 Atom 恰好获得一次指派、空 cluster 为 0、重复 centroid 为 0。报告必须给出训练 inertia、cluster size 的 minimum/median/p95/p99/maximum 和占用熵；这些统计用于识别聚类塌缩，不能通过事后改 cluster 标签或删除大簇修饰结果。

### 3. 高频动作抑制

- 同一 cluster 内，若当前 Atom 与任一更早 survivor 的全维 cosine distance `<=0.04`，当前 Atom 被抑制；
- 每个非空 cluster 在可行时至少贡献 1 条，最终最多 20 条；
- 每个 cluster 先按“离 centroid 最近的首项，再最大化与已选集合的最小全维距离”生成最多 64 条 diversity reservoir；核心 10,000 条至少选择其中 3,500 条，其中至少 2,000 条不在任何 query top-k 并集；
- 稀有 cluster 按资格规模升序、cluster ID 升序轮转；首个代表按投影空间离 centroid 最近选取，后续代表最大化其与本 cluster 已选集合的最小全维 cosine distance；
- 近重复处理顺序固定为：来源组资格数升序、`split × participant × modality` 层资格数升序、query union 外优先、RRF 降序、最佳 dense rank、最佳 sparse rank、投影空间 centroid 距离、`atom_id`；缺失 rank 视为正无穷。该顺序在计算任何 survivor 前一次性冻结，不依赖尚未生成的 reservoir，也不含动态“缺口数”。
- reservoir 只能在 survivor 集合形成后构造：每簇首项取投影空间离 centroid 最近者，后续逐次最大化与已入 reservoir 集合的最小全维 cosine distance；平局依次优先 query union 外、RRF 较高和 `atom_id` 较小。每簇最多 64 条，`reservoir_selection_sequence` 从 0 开始；求解器中的新颖度效用为“该簇 reservoir 大小减去序号”，非成员为 0。

这些规则共同防止“拿杯子”“打开门”等大簇挤占池子，同时保证 query 未覆盖的稀有语义获得通道预算。

## 五、`10,000–12,000` 弹性终止

先在全部硬门下生成恰好 10,000 条核心候选。split 按 `train/dev/test = 0.50/0.17/0.33` 对实际最终总数采用最大余数法计算，平局顺序为 train、dev、test；参与者在 split 内按资格份额使用最大余数法分配。模态按最终总数把 minimum 向上取整、maximum 向下取整：

| modality | 最低占比 | 最高占比 |
| --- | ---: | ---: |
| `both` | 0.50 | 0.70 |
| `dense_caption_only` | 0.20 | 0.35 |
| `transcript_only` | 0.08 | 0.15 |

每个非空 `source_group_id` 在可行时至少 1 条、最多 250 条。六个查询族全部运行并报告，但不参与数量约束。

核心完成后按稀有 cluster 轮转补样。对每个拟议总数 `N=10001..12000`，先按最大余数法重算该 N 的 split 及 split 内 participant 精确计数；相对 N-1 增加 1 的唯一层就是本步必须来源的层。扩展 Atom 还必须不触发近重复、所在 cluster 未超过软上限 12/全局上限 20、与本 cluster 已选集合的最小全维 cosine distance 严格大于 `0.08`，并保持模态边界及下一步最低值可达。该必需层无候选时停在 N-1。达到 12,000，或完整一轮合格 cluster 无新增时停止；不得跳过某个 N 再尝试 N+1。

## 六、联合约束与统一 tie-break

近重复 survivor 集合形成后，核心 10,000 条必须由固定 OR-Tools CP-SAT 精确求解，不使用贪心可行性判断。每个 survivor 对应一个布尔变量；约束包含核心总数、split 精确计数、split 内 participant 精确计数、模态边界、来源组上下限、cluster 上下限和两个 diversity reservoir 最低值。

求解器按四次词典序目标运行：最大化 query-union 选中数；最小化全局检索 rank 之和；最大化 diversity reservoir 新颖度 rank utility；最小化 `atom_id` 序号之和。全局检索 rank 和 reservoir rank 完全按策略中的静态排序键生成；`atom_id` 序号是在全部 survivor 按 Unicode code point 升序后的 1-based rank。每次必须得到 `OPTIMAL`，把最优目标值加为等式后再求下一目标。变量按 `atom_id` 排序，固定 `FIXED_SEARCH`、单 worker、seed 和 decision strategy；每目标最多 21,600 秒。固定全部目标值后，从全新 solver 再求两次，两次选中 Atom SHA 必须相同。`FEASIBLE`、`UNKNOWN`、超时或重复性失败都阻断，不能将“尚未证明最优”写成成功。正式候选最终按 `atom_id` 升序输出。

上述精确求解只对已冻结的近重复 survivor 集合判断可行性。最低覆盖不足、上下限冲突或 CP-SAT 证明不可行时立即阻断；禁止自动放宽阈值、复用 Atom、改变 split、扩大查询、退回词面算法或静默改参数。

## 七、精简证明流与验证边界

Windows 回传目录固定只有五个文件：

1. `candidate_atoms.jsonl`：每行仅 `{"atom_id":"src_..."}`；
2. `selection_proof.jsonl`：T4 可消费的精简离散证明；
3. `selection_report.json`：综合统计与验证摘要；
4. `selection_manifest.json`：输入、源码、环境、五文件前四项和本地审计根哈希；
5. `BGE_FILTER_SUCCESS.json`：最后原子写入的成功标记。

`selection_proof.jsonl` 使用有 `record_type` 的严格行类型：

- `query_hit`：`query_id/family/channel/rank/atom_id/score_f32_hex_le`；
- `candidate`：`atom_id/selection_sequence/selection_phase/cluster_id/selection_memberships`，以及适用时的 primary query 和最小距离；可选字段必须省略而非写 null；
- `cluster`：资格数、近重复 survivor 数、选中数、reservoir 数、centroid SHA 和抑制数；
- `shard`：输入覆盖范围、行数、缓存摘要和完成状态；
- `audit_sample`：六族各 50 条及 diversity-only 50 条的确定性人工抽样身份。

T4 不重跑 BGE 时，必须能从 proof 与 Source 独立重算：top-k rank 连续性、RRF、primary attribution、候选/proof 一致性、候选唯一性、split/参与者/模态/来源组分布、cluster 选中上限、弹性停止记录及 report 聚合值。

小型证明无法证明 BGE 对全库的数值 top-k 完备性、embedding 数值正确性、每个全库 cluster 指派或 CP-SAT 全体 survivor 上的最优性。该边界由 WSL 使用本地完整向量、survivor 集与求解记录验证；manifest 绑定本地审计 Merkle 根、固定源码、模型 revision 和 runtime lock。Windows T4 只独立验证 proof 中可见的离散事实和已选集合硬约束，不能声称从精简文件复算了 BGE 或求解器最优性。

逐 Atom Source 正文、dense/sparse embedding、ANN 索引、规范化 passage、模型权重、checkpoint、全量 cluster assignment、调试/性能日志、失败临时文件和 Hugging Face 缓存一律不回传，只留 `work/` 或 `cache/`。机器记录限统一的 `work/run_ledger.jsonl`、`work/run_report.json` 和 `cache/cache_manifest.jsonl`；不得按 query、cluster、shard、错误或 checkpoint 另建 JSON。

## 八、报告与人工精度

综合报告至少按六个查询族、split、participant、modality、source group、semantic cluster、检索通道统计。每个查询族报告原始召回量、跨通道去重后数量、最终贡献和确定性人工样本规模；T4 导入后完成盲审并填写人工抽样精度。每族目标 50 条、diversity-only 目标 50 条；某层不足时抽取全部可用项、报告短缺但不因抽样数阻断。`Explicit-Time` 真实召回不足时如实报告，不作补量。

WSL SUCCESS 只证明机器筛选和证明流闭合；Windows 项目标准的 `audit/distributions/bge_selection/<selection_id>/` 由 T4 从 Source、proof 和 report 独立生成，人工精度未完成前不得提升 BGE 的 T4 QA 门。

只有输入、源码和环境身份匹配，全量资格 Atom 恰好编码一次，候选数位于 10,000–12,000，全部机器硬门成立，proof/report 可复核，正式目录恰有五文件且无 blocker 时，协调器才可最后写入 SUCCESS。
