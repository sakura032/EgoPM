# BGE-M3 输入、回传与证明合同 v3.1

本文件只规定 Windows 与 WSL 之间传什么、各字段由谁消费以及什么不能回传。算法参数以 `SELECTION_PROTOCOL.md` 和 `input/request/selection_policy.json` 为准，执行步骤以 `RUNBOOK.md` 为准。

## 一、输入目录

```text
input/
├── source/
│   ├── source_video_atoms.jsonl
│   └── SOURCE_ATOMS_SUCCESS.json
├── request/
    ├── model_config.json
    ├── query_set.jsonl
    ├── selection_policy.json
    ├── selection_request.json
│   └── selection_request.sha256
└── schema/
    ├── source_video_atom.schema.json
    └── bge_selection_artifacts.schema.json
```

所有相对路径均以执行包根目录为基准。Source 全程只读。`selection_request.json` 不含自身哈希，外部 sidecar 绑定其原始字节；根请求直接绑定两个必要 Schema。正式运行必须核验 Source 行数/SHA、Source SUCCESS、三个配置组件、两个 Schema 和根请求 SHA，并以 Draft 2020-12 format checker 验证 Source 行与全部回传类型。Source Schema 必须与 Windows 权威文件逐字节同 SHA。Source SUCCESS 只接受请求绑定的完整文件 SHA，任何增删字段都会改变身份，故不再复制独立 Schema。

## 二、正式回传目录

当前 selection ID 为 `bge_m3_source_select_v3_1_20260910_01`。正式成功目录恰有以下五个文件，不得增加调试附件：

```text
output/bge_m3_source_select_v3_1_20260910_01/
├── candidate_atoms.jsonl
├── selection_proof.jsonl
├── selection_report.json
├── selection_manifest.json
└── BGE_FILTER_SUCCESS.json
```

### 1. `candidate_atoms.jsonl`

每行严格只有：

```json
{"atom_id":"src_..."}
```

行数必须在 10,000–12,000 之间，`atom_id` 唯一、可回查冻结 Source，并按 `atom_id` 升序。不得包含 `visible_text`、query、score、rank、cluster、split、参与者、模态或重复的运行元数据。

### 2. `selection_proof.jsonl`

这是 T4 的精简复核接口，不是下游 Cue 的数据接口。每行必须通过 `bge_selection_artifacts.schema.json#/$defs/selection_proof_record`。浮点分数和距离以 little-endian IEEE-754 FP32 的 8 位小写十六进制表达。所有行先按 `query_hit/candidate/cluster/shard/audit_sample` 顺序，再按各类型冻结键排序；禁止 `null` 和未知字段。

证明流必须足以让 T4 在不重跑 BGE 的情况下重算离散 rank、RRF、归因、候选成员关系、已选集合约束与报告统计。它不承诺让 T4 复算全库 BGE 数值、聚类指派、近重复 survivor 集或 CP-SAT 最优性；这一限制必须写入 report。

### 3. `selection_report.json`

整个文档必须通过 `bge_selection_artifacts.schema.json#/$defs/selection_report`。其固定顶层内容包括：

- 运行和上游身份；
- 输入、资格、编码、恢复、近重复和最终行数；
- 六查询族各自的召回量、去重量、最终贡献、审计样本规模；
- split、participant、modality、source group、semantic cluster、retrieval channel 分布；
- 核心 10,000 与弹性扩展的停止原因；
- 配置叶字段消费覆盖；
- WSL 数值验证与 T4 离散复核的责任边界；
- solver 四阶段 `OPTIMAL` 状态、目标值、核心解哈希和扩展停止原因；
- blocker 列表，成功时必须为空。

不把逐 Atom rank/score、Source 正文或完整 cluster assignment 嵌入 report。

### 4. `selection_manifest.json`

manifest 是正式文件与环境身份的权威绑定，至少绑定：

- Source 数据及 SUCCESS 的路径、SHA、行数；
- 根请求 SHA；根请求再传递绑定三个配置组件与 Source/artifact Schema；
- BGE repository、固定 revision、下载快照 SHA；
- Python、Unicode、CUDA、PyTorch、FlagEmbedding、NumPy、SciPy、scikit-learn、OR-Tools 的冻结版本；
- 源码 manifest SHA、runtime lock SHA；
- `candidate_atoms.jsonl`、`selection_proof.jsonl`、`selection_report.json` 的路径、SHA、行数/字节数；
- WSL 本地完整审计 Merkle 根和 cache manifest SHA；
- cluster centroid 摘要根、最终候选数及弹性停止原因。

manifest 必须通过 `bge_selection_artifacts.schema.json#/$defs/selection_manifest`，不包含自身 SHA，也不提前绑定 SUCCESS。

### 5. `BGE_FILTER_SUCCESS.json`

协调器在前三个数据/证明文件均已关闭并校验、manifest 已原子替换、无活动写进程和 blocker 后最后写入。SUCCESS 必须通过 `bge_selection_artifacts.schema.json#/$defs/bge_filter_success`，并绑定 manifest、selection、Source、根请求、两个 Schema、候选数和时间。失败运行不得留下 SUCCESS。

## 三、禁止回传

以下内容只在 WSL `work/` 或 `cache/` 中保留：

- dense/sparse embedding 和量化副本；
- ANN/检索索引；
- 规范化 passage 与文本缓存；
- 模型权重、tokenizer、Hugging Face cache；
- checkpoint、partial shard、恢复状态和失败临时文件；
- 全量 cluster assignment、centroid 数组、近重复邻接；
- 逐 Atom Source 正文；
- 调试日志、性能 profile、显存/内存 dump；
- Python wheel cache、包下载缓存、编译缓存。

`cache/cache_manifest.jsonl` 只记录可重建缓存的路径、类别、SHA、字节数、上游身份和是否完整，不复制正文到回传目录。安全错误、恢复、shard 关闭、solver 和 validator 事件统一进入 `work/run_ledger.jsonl`，当前汇总统一为 `work/run_report.json`；不得再拆小 JSON。成功后可按用户存储策略清理缓存，但清理不是筛选算法的一部分。

## 四、工程材料回到项目的位置

实现完成后，下列小型可复现工程材料同步回 Windows 的 `wsl_BGE-M3_filter/`，但不放入 selection 正式数据目录：

```text
src/
requirements-bge-m3.lock
WSL_HANDOFF.md
```

`src/` 中 Python 文件必须符合主项目的中文模块说明与关键中文注释规则。`WSL_HANDOFF.md` 记录环境、命令、运行耗时、峰值资源、输出 SHA、数值验证结果、未解决项和回传清单。

## 五、Windows 导入与 T4

用户把五个正式文件复制到：

```text
egopm_bench_v1/cues/v2/source_selection/<selection_id>/
```

T4 执行独立导入复核：

1. 验证目录恰有五文件及 manifest/SUCCESS 哈希链；
2. 回查所有候选 `atom_id` 的 Source 血缘与唯一性；
3. 用同一 artifact Schema 验证五文件，从 proof 重算 rank 连续性、RRF、归因、已选集合硬约束和 report 聚合；
4. 从 Source 重算 split、participant、modality、source group 分布；
5. 对六查询族各 50 条和 diversity-only 50 条样本完成人工精度审计；
6. 写入 `audit/distributions/bge_selection/<selection_id>/` 的机器报告、中文摘要、manifest 和 `DISTRIBUTION_SUCCESS.json`。

T4 不重新运行 BGE，也不声称复验全库向量、survivor 集或 CP-SAT 最优性。对应 T4 导入代码尚未实现时，WSL 可以完成工程实现和本地输出，但 BGE QA 必须保持 `BLOCKED`，不得启动 Cue v2 协议验收。
