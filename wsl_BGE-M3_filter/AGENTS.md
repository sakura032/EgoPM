# WSL BGE-M3 独立任务约束

本目录可独立复制到 WSL2。不要假定 Windows 父仓库或历史对话可见。开始前依次完整阅读 `README.md`、`SELECTION_PROTOCOL.md`、`RUNBOOK.md`、`TRANSFER_CONTRACT.md`、`input/README.md` 和 `input/request/` 全部冻结文件。

规则优先级：Windows 根仓库 `AGENTS.md` 的全项目治理与工件节制规则最高，且本目录不得放宽；在不冲突的 WSL 任务细节中以本文件为准。算法以 `SELECTION_PROTOCOL.md` 为准；字段和回传以 `TRANSFER_CONTRACT.md` 为准；具体参数以根请求绑定的机器配置为准。缺信息即停止，不得猜测。

## 工件节制继承

- 本目录属于根合同的全项目约束范围。不得按查询族、cluster、shard、处理状态或脚本阶段增加 JSON 文件或子目录，也不得预建空目录和占位工件。
- 当前 selection v3.1 已批准的正式回传只有 `output/<selection_id>/` 一棵目录模板和恰好五个文件；缓存、checkpoint、日志与本地完整审计不得进入正式回传。任何新增正式文件、目录模板或机器报告键拆分都必须先由 Windows T0 通过 CR 修改工件预算。
- WSL 本地 JSON/JSONL 只允许 `cache/cache_manifest.jsonl`、`work/run_ledger.jsonl` 和 `work/run_report.json`；禁止 per-query、per-cluster、per-shard、per-error 或 per-checkpoint JSON。大型向量、索引与模型按已批准缓存分片族保留，不回传。
- 实现测试和正式闭合检查必须断言输出目录文件集合恰好等于冻结五文件集合；多文件、少文件、残留 `*.tmp` 或未声明子目录均为 blocker。

## 不可变身份

- 只生产 Cue v2 的 Source 候选 selection，不生产 Cue、Seed、Life Log 或 gold。
- Source 只读：370,799 行，SHA256 `be5f36b77970cb5147b88551c566f081589fe00fcf5ef912d8468a037e92960e`。
- 模型固定为 `BAAI/bge-m3` revision `5617a9f61b028005a4858fdac845db406aefb181`。
- selection ID 固定为 `bge_m3_source_select_v3_1_20260910_01`；根请求 SHA256 固定为 `921024d8b4621fb8f8a8d600e191f4ba3d7406325bc4b5a17954863b7f435baa`。
- 候选数由冻结停止规则决定，必须在 10,000–12,000 之间。
- 禁止用 `lexical_jaccard_v1`、BM25 或其他词面算法替代 BGE-M3 dense+sparse。

## 执行边界

- 必须使用本目录专用 `.venv-bge-m3`；全部 Python、pip 和任务命令在该环境执行。
- 单 GPU 只运行一个 BGE-M3 模型进程。CPU 验证可并行，但写入分区必须互斥。
- 生成文件先写 `*.tmp`，内部验证后原子替换；禁止手改 JSONL、manifest、哈希和 SUCCESS。
- 不读取或保存 API Key，不调用生成式 API，不处理 MP4。
- `visible_text` 只做 Source 派生一致性校验，不编码、不输出。
- `selection_request.json` 直接绑定 `source_video_atom.schema.json` 与统一的 `bge_selection_artifacts.schema.json`；不得从数据样本猜字段。Source SUCCESS 按冻结原始字节 SHA 验证，不再复制冗余 Schema。
- passage 固定为 transcript/dense caption 组成的单一字符串并只编码一次；Unicode 规范化只用于资格和审计，不改变模型输入。
- 核心联合约束必须由固定单 worker OR-Tools CP-SAT 求得并证明四阶段 `OPTIMAL`；不得以贪心失败冒充不可行。
- `candidate_atoms.jsonl` 每行只含 `atom_id`；T4 所需离散证据写入 `selection_proof.jsonl`。
- 正式 `output/<selection_id>/` 恰有候选、proof、report、manifest、SUCCESS 五个文件。
- embedding、索引、模型、checkpoint、全量审计、Source 正文和日志只留 WSL 本地。

## 硬停止条件

出现任一情况必须阻断：输入或请求哈希不符；未知/缺失/占位字段；模型 revision 或 GPU 不可证明；NaN/Inf；运行中修改代码、参数或依赖；联合约束不可行；核心不足 10,000；候选超过 12,000；候选重复或无法回查；proof/report 无法闭合；正式目录多文件；仍有写进程、`.tmp` 或 blocker。

不得自动降级、放宽阈值、复用 Atom 或凑数。只有唯一协调器在全部门通过后才可最后写 `BGE_FILTER_SUCCESS.json`。
