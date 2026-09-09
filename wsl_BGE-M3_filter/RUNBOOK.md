# BGE-M3 WSL 部署与筛选运行手册

本手册把任务拆成可检查、可停止、可恢复的阶段。WSL Codex 每完成一阶段都应先核对退出条件，再进入下一阶段。正式运行所用参数只来自 `input/selection_request.json`，本手册中的数值建议不能覆盖冻结请求。

## 一、建立本地目录

将本执行包放在 WSL Linux 文件系统后，在包根目录工作：

```bash
cd ~/EgoPM_BGE-M3_filter
mkdir -p input model src cache/normalized_source cache/dense cache/sparse cache/retrieval
mkdir -p work/checkpoints work/reports work/logs output
```

完整布局应为：

```text
EgoPM_BGE-M3_filter/
├── AGENTS.md
├── README.md
├── PROJECT_CONTEXT.md
├── SELECTION_PROTOCOL.md
├── RUNBOOK.md
├── TRANSFER_CONTRACT.md
├── .venv-bge-m3/
├── input/
│   ├── source_video_atoms.jsonl
│   ├── SOURCE_ATOMS_SUCCESS.json
│   └── selection_request.json
├── model/
│   └── BAAI_bge-m3_5617a9f/
├── src/
├── cache/
│   ├── normalized_source/
│   ├── dense/
│   ├── sparse/
│   └── retrieval/
├── work/
│   ├── checkpoints/
│   ├── reports/
│   └── logs/
└── output/
    └── <selection_id>/
```

`.venv-bge-m3/`、`input/`、`model/`、`cache/`、`work/` 和 `output/` 均属于本地运行材料，不应提交 Git。若 WSL Codex 为本目录初始化 Git，应在第一次提交前建立覆盖这些路径的忽略规则。

阶段退出条件：六份说明文件均已阅读，目录创建完成，当前工作目录确认无误。

## 二、创建专用虚拟环境

```bash
python3 -m venv .venv-bge-m3
source .venv-bge-m3/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

若 `venv` 模块缺失，只安装发行版提供的 `python3-venv`。不得使用 `sudo pip`，不得复用 Windows Python 环境。

PyTorch 使用官方稳定 Linux/Pip/CUDA wheel。当前 NVIDIA 驱动报告支持 CUDA 13.1，通常能够运行 PyTorch 提供的 CUDA 12.x runtime；最终以实际 GPU 自检为准。不要从源码编译 PyTorch，也不要仅为本任务更换驱动或系统 CUDA Toolkit。

安装 PyTorch 后，在同一虚拟环境安装：

```bash
python -m pip install FlagEmbedding huggingface_hub safetensors numpy scipy scikit-learn jsonschema
python -m pip check
python -m pip freeze --all > work/reports/requirements-lock.txt.tmp
mv work/reports/requirements-lock.txt.tmp work/reports/requirements-lock.txt
```

必须记录实际 PyTorch 安装命令、wheel 索引、Python 版本、`torch.__version__`、`torch.version.cuda`、cuDNN 版本和完整依赖锁。不能只写“最新版”。正式复算时应使用已记录版本；若无法复现，报告环境漂移。

阶段退出条件：专用环境可激活，`pip check` 无错误，依赖锁已生成。

## 三、GPU 与运行时自检

先保存以下无敏感信息的输出：

```bash
nvidia-smi
nvcc --version
python -c "import torch; print(torch.__version__); print(torch.version.cuda); print(torch.backends.cudnn.version()); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO_CUDA')"
```

再执行一次实际 GPU 张量创建、矩阵乘法和结果回传 CPU 的测试。通过条件：

- `torch.cuda.is_available()` 为 `True`；
- 设备名与 RTX 5060 Laptop/系列一致；
- 实际矩阵运算成功；
- 自检结束后没有 CUDA 初始化、驱动或动态库错误。

CUDA Toolkit 12.2 与驱动支持 CUDA 13.1 本身不是冲突。PyTorch 无法加载、GPU 不可见或实际算子失败才是 blocker。不得自动降级到 CPU 完成正式全量编码；CPU 只能用于输入检查、统计和恢复诊断。

阶段退出条件：GPU 实际算子通过，环境报告草稿已写入 `work/reports/`。

## 四、下载并冻结模型

唯一允许的模型身份：

```text
repository: BAAI/bge-m3
revision: 5617a9f61b028005a4858fdac845db406aefb181
local_dir: model/BAAI_bge-m3_5617a9f
```

可以使用 `huggingface_hub.snapshot_download` 按上述 revision 下载到本地目录。禁止下载滚动 `main`，禁止把缓存中身份不明的模型用于正式运行。

下载后必须：

1. 验证请求和下载记录均绑定完整 revision；
2. 遍历模型目录，为每个普通文件记录相对路径、字节数和 SHA256；
3. 将清单写到 `work/reports/model_files_manifest.json`；
4. 对规范化 manifest 计算总 SHA256；
5. 使用本地目录加载模型，避免正式运行时静默拉取其他 revision。

`BGEM3FlagModel` 应同时返回 dense 与 sparse 表示，并关闭不需要的 ColBERT 多向量。官方资料：[FlagEmbedding BGE-M3](https://github.com/FlagOpen/FlagEmbedding/blob/master/research/BGE_M3/README.md)、[BGE-M3 模型卡](https://huggingface.co/BAAI/bge-m3)。

阶段退出条件：模型固定 revision 可证明，模型文件 manifest 完整，本地加载不触发替代下载。

## 五、接收并验证三项输入

本任务只认本目录 `input/` 中的文件：

- `input/source_video_atoms.jsonl`；
- `input/SOURCE_ATOMS_SUCCESS.json`；
- `input/selection_request.json`。

任何文件缺失都不能启动正式全量运行。验证顺序：

1. 流式计算 Source SHA256，必须严格等于 `be5f36b77970cb5147b88551c566f081589fe00fcf5ef912d8468a037e92960e`；
2. 流式计数，必须严格等于 370,799 行；
3. 验证 Source SUCCESS 声明的 SHA、行数与实际文件一致；
4. 验证每行是合法 JSON，必需字段和枚举符合 `PROJECT_CONTEXT.md`；
5. 验证 `atom_id` 全局唯一；
6. 验证时间区间合法，但不改写时间值；
7. 验证请求文件 `frozen` 为 `true`，无占位文本，身份与 Source、模型一致；
8. 按请求规定的规范化方法复算请求 SHA256；
9. 验证查询 ID 唯一、参数类型与范围、目标候选数和选择策略完整。

输入验证程序只能读取 Source，不得覆盖、格式化或重新保存它。失败时在 `work/reports/input_blocker.json` 写安全错误码、文件、JSON 路径和数量摘要；不要复制大段 Source 正文。

阶段退出条件：三项输入均通过，验证报告绑定文件 SHA256。

## 六、实现执行程序与源码冻结

若本目录尚无执行程序，WSL Codex 可在 `src/` 中实现，但必须把职责拆开，至少覆盖：

- 输入与请求验证；
- passage 流式构造；
- 模型和 GPU 小批自检；
- 分片 dense+sparse 编码；
- shard 校验与 checkpoint；
- 查询编码和多通道召回；
- RRF、多样性与分层选择；
- 输出、分布报告、manifest 和 SUCCESS 验证。

每个 Python 文件的首个有效内容应为中文模块说明，说明职责、输入、输出和所处阶段；关键哈希、恢复、排序、分片与异常分支应有解释“为什么”的中文注释。

在正式 campaign 前生成 `src_manifest.json`：记录每个执行文件的相对路径、字节数和 SHA256。正式运行中不得修改源代码；若修改，旧 checkpoint 不再属于同一身份，必须停止并创建新 selection。

阶段退出条件：程序完成静态检查和小型 fixture 验证，源码 manifest 冻结。

## 七、passage 构造与确定性资格过滤

每个 Atom 的 passage 严格为：

```text
transcript: <原字段或空>
dense_caption: <原字段或空>
visible_text: <原字段>
```

不得加入 participant、day、session、split、source_group、时间、路径或未来标签。文本规范化仅用于模型输入、空值判断和诊断；正式候选仍只引用原 `atom_id`。

资格过滤遵守 `SELECTION_PROTOCOL.md`，每个排除必须记录确定性原因码。需要保存规范化 passage 缓存时，只能保存在 `cache/normalized_source/`，不得进入正式输出。

阶段退出条件：资格集合行数、排除原因计数、Atom ID 顺序和输入哈希均已冻结。

## 八、小批编码自检与参数冻结

在正式全量编码前，只允许使用固定的小型样本完成环境自检，目的包括：

- 验证本地模型能返回 dense 和 sparse；
- 测量不同 batch size 的峰值显存；
- 确认 `max_length` 与请求一致；
- 比较候选精度模式的排序稳定性；
- 检查输出 shape、NaN、Inf 和确定性。

建议从 FP32 小 batch 开始。若 8 GiB 显存不稳定，可评估 FP16；但精度选择必须在正式运行前冻结，并写回一份由用户认可且哈希固定的最终 `selection_request.json`。正式 campaign 中不得因 OOM 自动改变精度、`max_length` 或 batch size。

自检样本与结果属于 `work/`，不能混入正式候选，也不能被描述为正式覆盖结果。

阶段退出条件：所有身份参数最终冻结，请求 SHA256 重算通过，尚未启动任何正式 shard。

## 九、全量分片编码

只启动一个 GPU 模型进程。按请求中的 `shard_size` 和输入顺序编码：

1. 创建 shard 临时文件；
2. 写 dense、sparse 与 Atom ID 顺序；
3. 检查行数、shape、NaN、Inf、范围和输入哈希；
4. 生成 shard manifest；
5. 将临时文件原子改名；
6. 最后写 shard 完成标记；
7. 更新只追加或原子替换的 checkpoint 状态。

Dense 落盘前转换为 FP32 并 L2 归一化。370,799 × 1,024 个 FP32 约 1.52 GB，可使用 `numpy.memmap`。Sparse 采用分片 CSR 或等价压缩结构，禁止同时把全量 Source 和全量 sparse Python 对象放入内存。

OOM 或进程中断时：

- `.tmp` 视为未完成并从当前 shard 开头重跑；
- 已完成且 SHA 匹配的 shard 不重算；
- 不改变 shard 边界、顺序或参数；
- 身份不符的旧 cache 必须隔离，不能自动合并。

阶段退出条件：全部资格 Atom 恰好覆盖一次，每个 shard 完成标记和 SHA 均匹配。

## 十、查询、融合与多样性筛选

严格读取请求中冻结的查询顺序和算法参数：

1. 编码冻结查询；
2. 对每个查询执行 dense top-k；
3. 对每个查询执行 sparse top-k；
4. 按请求定义执行 RRF；
5. 建立语义多样性 reservoir；
6. 合并通道并按 `atom_id` 去重；
7. 执行冻结的分层覆盖与上限策略；
8. 按确定性规则产生最终候选和顺序。

任何库的默认排序、默认随机种子或默认聚类参数都不能隐式成为合同。若结果不足目标下限或覆盖门冲突，生成 blocker 报告，不得重复 Atom、临时修改配额或退回词面检索凑数。

阶段退出条件：候选数在冻结范围内，Atom 唯一、全部可回查，各通道和分层决策可解释。

## 十一、生成正式输出与报告

按 `TRANSFER_CONTRACT.md` 在 `output/<selection_id>/` 写正式文件。所有文件先写 `*.tmp`，逐项校验后原子改名。

报告至少包括：

- 输入 Source、资格集合和候选的各维度分布；
- 每查询、查询族、检索通道、融合和 diversity 的贡献；
- 每个 encoding shard 的耗时、峰值显存、行数和 SHA；
- 重复、回查失败、NaN、Inf、缺失来源组和排除原因计数；
- 环境、模型、请求、源码、cache 和输出身份；
- 所有恢复事件与未解决问题。

分布 JSON 是机器可读真值，`execution_report.md` 是中文摘要；二者不一致时阻断。

阶段退出条件：输出目录无 `.tmp`，manifest 与实际文件完全一致，重新计算分布无差异。

## 十二、写 SUCCESS 与交付

`BGE_FILTER_SUCCESS.json` 必须最后写入，并绑定：

- `selection_id`；
- Source SHA256 与行数；
- 模型仓库、revision 与模型 manifest SHA256；
- 请求 SHA256；
- 源码 manifest SHA256；
- candidate manifest SHA256；
- distribution manifest SHA256；
- 候选行数；
- 时间戳；
- 未解决 blocker 数，必须为 0。

写入前确认不存在第二个 GPU 进程、在飞 shard 或未关闭 writer。写入后执行一次只读全量交付验证。最后只把完整 `output/<selection_id>/` 交给用户；用户负责把它导入不可见的主项目。

若任何门禁未通过，交付 blocker 报告和安全的诊断摘要，但不得写 SUCCESS。
