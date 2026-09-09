# WSL BGE-M3 独立任务约束

本目录是一个**完全自包含的 WSL 执行包**。在 WSL 中工作的 Codex 只能看见本目录，因此不得假定任何父目录、Windows 仓库、历史对话或外部项目文档可见。除模型下载与依赖安装外，任务所需的规则、输入和交付要求都必须从本目录取得。

开始工作前必须依次完整阅读：

1. `AGENTS.md`：不可变边界与停止条件；
2. `README.md`：入口、目录结构与任务概览；
3. `PROJECT_CONTEXT.md`：项目背景、术语和本阶段在全流程中的位置；
4. `SELECTION_PROTOCOL.md`：候选筛选的算法合同与验收门；
5. `RUNBOOK.md`：环境、模型、编码、恢复和执行步骤；
6. `TRANSFER_CONTRACT.md`：本目录输入、输出和交付合同。

若上述文件互相冲突，以本文件为最高优先级；若任务所需输入、字段说明或已冻结参数在本目录内缺失，必须停止并向用户报告缺口，禁止到不可见目录猜测、引用或自行补造。

## 不可变边界

- 本任务只生产 Cue v2 的候选 Source Atom selection，不生成 Cue、Seed、Life Log、Decision、Evidence 或 gold。
- Source Atom 只读；不得改写、重新切分、重新分配 split、修订正文或创建替代 Source。
- 固定 Source 行数为 370,799，文件 SHA256 为 `be5f36b77970cb5147b88551c566f081589fe00fcf5ef912d8468a037e92960e`。
- 模型固定为 `BAAI/bge-m3`，revision 固定为 `5617a9f61b028005a4858fdac845db406aefb181`。实际 revision 不匹配必须停止。
- 禁止以 `lexical_jaccard_v1`、BM25 或纯词面相似度替代正式 BGE-M3 dense+sparse 检索；词面规则只能承担确定性格式过滤或诊断。
- 正式运行参数只能来自本目录 `input/selection_request.json`。该文件缺失、未标记冻结或哈希不符时，只能完成环境与小型自检，不能开始全量编码或写正式结果。
- WSL 必须使用本目录独立虚拟环境 `.venv-bge-m3`。所有 Python、pip 和任务命令都必须先激活该环境，或显式调用其中的 Python。
- 单 GPU 只允许一个 BGE-M3 模型进程。不得从多个终端重复加载模型或并行启动正式筛选。
- 所有生成文件先写 `*.tmp`，通过本地校验后原子改名；不得手改生成的 JSONL、manifest、哈希或 SUCCESS。
- 不读取、不请求、不保存任何 API Key；本阶段不调用生成式 API。
- 不下载、复制或处理原始 MP4；不把 Source 正文、模型权重、embedding 或缓存提交到 Git。
- 只有在全部合同门通过且不存在未解决 blocker 时，协调器才可写 `BGE_FILTER_SUCCESS.json`。

## 允许的并行

- GPU 编码：单进程、单线控制，可在进程内部使用批处理和安全的数据加载 worker。
- 编码前的确定性输入检查与清洗：可按预先静态分片使用 CPU worker，但只能写互不重叠的临时文件。
- embedding 完成后的只读统计、哈希和分片检索：可使用 CPU 并行，但不得同时创建第二个 GPU 模型进程。
- manifest 与 SUCCESS：只能由一个协调器写。

## 强制停止条件

出现以下任一情况必须停止，不得自动降级或带病继续：

- Source 行数、SHA256、SUCCESS 身份或 `atom_id` 唯一性不符；
- `selection_request.json` 缺失、参数未冻结、Schema 不合格或其声明的 Source/模型身份不符；
- 模型 revision 无法证明、GPU 实际算子失败、embedding 出现 NaN/Inf；
- 正式 campaign 中途改变模型、精度、`max_length`、序列化规则、查询集、配额或随机种子；
- checkpoint 身份不一致、正式分片重叠、候选重复或回查 Source 失败；
- 目标候选数、覆盖门或分布报告未达到 `SELECTION_PROTOCOL.md` 与 `selection_request.json` 的共同要求。

## 交付最低报告

交付前必须在本目录 `output/<selection_id>/` 内报告：环境版本、GPU 自检、模型 revision、模型文件清单、Source SHA、参数哈希、查询集哈希、候选数、各检索通道贡献、每个 split/参与者/模态/来源组分布、缓存清单、正式输出 SHA、恢复记录和未解决问题。
