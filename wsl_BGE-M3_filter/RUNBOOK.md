# BGE-M3 WSL 执行手册 v3.1

本手册只规定执行顺序。算法以 `SELECTION_PROTOCOL.md`、参数以 `input/request/`、传输字段以 `TRANSFER_CONTRACT.md` 为准。

## 一、接收与环境

把执行包放在 WSL Linux 文件系统，例如 `~/EgoPM_BGE-M3_filter/`。用户只需把两个冻结 Source 文件复制到 `input/source/`。

```bash
cd ~/EgoPM_BGE-M3_filter
mkdir -p input/source src model cache work output
python3 -m venv .venv-bge-m3
source .venv-bge-m3/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

从 PyTorch 官方选择与当前 Linux/驱动兼容的稳定 CUDA wheel，再安装 `FlagEmbedding`、`huggingface_hub`、`safetensors`、`numpy`、`scipy`、`scikit-learn`、`jsonschema`、`ortools`。执行 `python -m pip check`，并把完整冻结结果原子写为 `requirements-bge-m3.lock`。不得直接复制 Windows `.venv`。

## 二、身份和 GPU 预检

全量编码前依次验证：

1. `selection_request.sha256` 与根请求原始字节一致；
2. 根请求绑定的 Source、Source SUCCESS、两个 Schema、模型配置、查询集、选择策略 SHA/行数一致；
3. 请求为 v3.1 且无自引用 SHA、未知字段、占位符、非法 null 或哨兵字符串；
4. Source 为 370,799 行、Atom ID 唯一、原始字节 SHA 正确；
5. 每行先通过随包 Source Schema，再通过 modality/`visible_text` 语义门；passage 按冻结伪代码形成一个字符串并只编码一次；
6. Unicode runtime 为 15.0.0，策略内嵌的规范化测试向量全部通过；48 个查询 ID 唯一、六族各 8 条，策略所有叶字段均有代码消费者；
7. `nvidia-smi`、PyTorch CUDA、GPU 矩阵运算和 BGE dense+sparse 小批编码全部成功；
8. 模型从固定 revision 本地快照加载，embedding 维度、类型、归一化和稀疏输出符合配置。

失败事件只追加到 `work/run_ledger.jsonl`，当前聚合状态原子写入 `work/run_report.json`；字段限安全错误码、文件、JSON 路径、行号/Atom ID 和计数，不复制 Source 正文。不得按错误或阶段另建 JSON，也不得自动改 batch、精度、长度或模型。

## 三、实现与冻结

WSL Codex 在 `src/` 分离实现：严格配置解析、Source 流式校验与 passage、分片编码、dense/sparse 召回、精确 RRF、投影与聚类、cluster 规范化、近重复、联合可行性、核心/扩展选择、proof/report/manifest/SUCCESS 以及独立只读 validator。

Python 文件必须有中文模块说明，并为哈希门、恢复、排序、状态转换和异常处理写中文关键注释。正式运行前生成源码 manifest；运行中源码、请求、依赖锁或模型快照变化立即阻断。

## 四、单 GPU 分片编码

只启动一个模型进程，按 Source 顺序每 4,096 条形成一个 shard：

1. 校验 Atom 与 passage 资格；
2. batch 4 生成 dense+sparse；
3. dense 转 FP32 并 L2 归一化，sparse 用固定 CSR 格式；
4. 检查顺序、shape、NaN/Inf、字节数和 SHA；
5. 原子提交 shard，再把包含路径、SHA、行数和身份的关闭事件追加到统一 `work/run_ledger.jsonl`；不得为每个 shard 写完成 JSON。

中断后只复用身份与全部 SHA 完整匹配的已关闭 shard；未完成 shard 从头重跑。旧 selection 缓存必须隔离，禁止混入。

## 五、检索与 diversity

严格执行以下阶段：

1. 编码 48 条查询并做每查询 dense/sparse top-500；
2. 生成精确 rank/RRF 与 primary attribution；
3. 从资格集合分层确定性抽取 65,536 条训练样本；
4. 固定稀疏随机投影至 256 维，运行冻结 MiniBatchKMeans；
5. 按 centroid 规范字节生成 snapshot-local cluster ID，并为全量 Atom 分块指派；
6. 按冻结全局顺序，用全维 BGE 向量执行同簇近重复 survivor 选择；
7. 构造每簇最多 64 条 diversity reservoir；
8. 用固定单 worker OR-Tools CP-SAT 对全部 survivor 执行四阶段词典序求解，四次均为 `OPTIMAL` 才接受核心 10,000 条；
9. 对每个拟议总数重算 split/participant 增量层，按稀有簇、新颖度 `>0.08` 和软上限 12 补样；
10. 达到 12,000，或当前必需增量层无候选/完整一轮无新增时确定性停止。

六个 query family 不设数量配额。任何不足、冲突或漂移写 blocker，不在运行中改策略。

## 六、本地审计与缓存

本地完整审计至少保存 top-k 全列表、全量 cluster assignment、centroid、近重复关系、选择/跳过原因、联合可行性证明、各轮扩展记录和独立 validator 结果。大数组使用已批准的二进制缓存分片；事件统一进入 `work/run_ledger.jsonl`，当前汇总统一进入 `work/run_report.json`。`cache/cache_manifest.jsonl` 记录 model/cache/work 中有效材料的相对路径、类别、SHA、字节数、上游身份和完成状态。

这些材料不进入正式 output。缓存至少保留到 Windows 确认导入成功；后续清理须由用户单独决定。

## 七、五文件输出

在 `output/bge_m3_source_select_v3_1_20260910_01/` 依次原子写：

1. `candidate_atoms.jsonl`；
2. `selection_proof.jsonl`；
3. `selection_report.json`；
4. `selection_manifest.json`；
5. `BGE_FILTER_SUCCESS.json`。

proof 中六族各冻结 50 条、diversity-only 冻结 50 条人工审计样本。写 SUCCESS 前重新启动独立只读 validator：用 Source Schema 验证全部 Source 行，用统一 artifact Schema 验证候选、五类 proof 行、report、manifest 和 SUCCESS；Source SUCCESS 则复核完整文件 SHA。validator 还须从 Source、请求、本地完整审计和前四个输出重算机器门，并确认无 `.tmp`、无写进程、目录没有第六个文件。

## 八、交付

成功时只把五文件正式 output 目录交给用户。另回传 `src/`、`requirements-bge-m3.lock` 和中文 `WSL_HANDOFF.md` 到 Windows 执行包。失败时不创建 SUCCESS，只提供不含正文的 blocker 摘要与可恢复 cache 身份。
