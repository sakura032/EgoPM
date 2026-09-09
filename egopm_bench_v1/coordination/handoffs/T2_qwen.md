# T2 交接：CR-2026-011 的 Cue v3 实时 API 无 API 生产者

## 2026-09-05：实时 API 切换的离线执行准备

本次仅实现和测试实时执行的离线部件；未读取 `DASHSCOPE_API_KEY`、未联网、未调用 API，
未读取已取消 Batch 的结果，也未写 `cue_library.jsonl`、`CUE_LIBRARY_SUCCESS.json` 或 Seed。

- 读取 T0 冻结的 v3 实时协议：`qwen3.7-flash`、`enable_thinking:false`、`temperature:0`、
  最多五条 Atom/package、每 Atom `96` 输出 token、最多两次临时服务重试、实时价格
  `¥0.2/M` 输入和 `¥0.8/M` 输出。
- `RealtimeTransport` 只在未来显式生产入口中可使用；它不含 Batch 上传、轮询、下载接口，
  也不保存原始响应。默认命令执行实时预检，`--execute`/`--receive` 对已取消 Batch 一律拒绝。
- `TokenBucket` 对 RPM 与 TPM 分别节流；每次调用前状态仅记录 package 身份、协议/Source
  哈希、尝试次数和无正文标识。服务端临时失败最多重试两次；本地验证失败写
  `local_validation_quarantine`，永不自动重试；实际 usage 缺失或费用越过剩余授权预算则熔断。
- 实时根只能是 `cues/realtime`。全局 `realtime_shards_manifest.jsonl` 所需对象由
  `realtime_shards_manifest()` 生成，含 `run_id`、`transport`、Source/协议哈希、package 数、
  package ID 哈希、`package_id_to_request_sha256` 和 `completion_sha256`；不含请求/响应正文。
- 每包状态为 `packages/<package_id>/realtime_state.json`，字段含 `run_id`、`transport`、
  `realtime_shard_index`、`package_id`、Source/协议/请求哈希、`attempt`、`retry_count`、`status`。
  完成标记含上述身份、`status:validated_success`、结果/账本/状态 SHA256；账本严格包含 T0
  `realtime_ledger_policy.required_fields`，并包含传输、Source/协议身份与 usage，但不含原始响应。
- 无 API 测试覆盖配置冻结、令牌桶、临时 `429` 重试、完成包恢复跳过、本地验证隔离、预算熔断、
  Batch 目录/字段混用拒绝。

`--realtime-execute` 已具备受控编排：先重建冻结 Source、写无正文全局 manifest/run state、
验证 `authorization_version:v2.0.0` 与 Source/协议哈希、核对输出上界预算，最后才读取环境
变量 `DASHSCOPE_API_KEY` 并调用实时传输。其默认入口仍只做预检；不得在 T4 独立 QA 和 T0
明确启动许可前使用执行开关。正式 Cue library 与 SUCCESS 仍不由本命令生成。

## 2026-09-05：Batch 结果接收闭环补充

本次仅实现和测试第 05 阶段的结果接收路径；未读取或设置 `DASHSCOPE_API_KEY`，未联网、未
提交 Batch、未读取任何远端结果，未写 `cue_library.jsonl` 或 `CUE_LIBRARY_SUCCESS.json`。
当前模型为 `qwen3.7-flash`，执行协议为 `v2.2.1`，协议 SHA256 为
`c2a5db76c6e74cd09942aea020caa6c09ffcfcb9ce57f8a4e87dec8ec6421198`。
实现提交为 `824dd1f541e63578d296fd044468f18a496390a1`。

- `scripts/05_extract_cues.py` 新增 `--receive` 入口。它要求独立的
  `confirmation=RECEIVE_BATCH_RESULTS_API`、本机授权文件和运行时环境变量；默认预检仍完全
  离线。接收器按冻结退避策略轮询 Batch 状态，在内存中流式读取 output/error JSONL，绝不把
  原始请求、响应或错误正文落盘。
- 接收前从冻结 Source 重建同一 task，严格验证 Source SHA、协议 SHA、Batch 输入 SHA 与
  `custom_id` 双向一对一映射。哈希或 ID 漂移会在写任何 Cue 片段前终止。
- 已验证项按全局 `cues/batch/packages/` 的固定 package 路径原子写入清单、Cue 片段、无正文
  ledger 与完成哈希；远端行级失败写可重组失败标记；服务端成功但本地 Schema/血缘校验失败写
  quarantine 标记，`retry_eligible=false`，禁止自动重发。
- 每个完成 task 在 `cues/batch/batch_tasks_manifest.jsonl` 原子登记无正文
  `custom_id_to_package_id` 映射及 `wave_index`；收据固定写在
  `cues/batch/wave_XX/task_XXX.batch_receipt.json`。ledger 额外记录远端 ID、结果行 SHA256、
  `retry_eligible` 与 `failure_origin`，不含正文。
- 接收器不合并 `cue_library.jsonl`，不写 Cue SUCCESS，也不删除远端文件；T4 Cue QA 仍是
  远端清理和最终合并的前置门。

本次验证：

```powershell
python -m pytest -q egopm_bench_v1/tests/test_qwen_contracts.py egopm_bench_v1/tests/test_validators.py --basetemp .pytest_cache/t2-cross
# 34 passed

python -m pytest -q --basetemp .pytest_cache/t2-batch-full
# 52 passed

git diff --check
# 通过
```

## 当前结论

本交接对应 T2 已提交的实现。第 05 阶段已改为紧凑协议的本地 Batch File 计划器：默认仅
验证冻结 Source、构造内存中的五条 Atom package、十个逻辑 shard 一个任务的无正文任务
元数据，并输出费用预检。没有读取 `DASHSCOPE_API_KEY`，没有网络客户端、上传、远端任务、
下载或模型调用；`--execute` 与失败重跑参数都会在读取密钥之前报合同阻断。

## 交接元数据

| 项目 | 值 |
| --- | --- |
| 分支 | `main` |
| T2 代码提交 | `c9cc106920de178c2079c44ec7088f6c957e1ada` |
| T2 交接提交 | `a47b409` |
| 治理合同版本 | `v1.1.0` |
| 配置合同版本 | `v1.1.0` |
| 最终 Cue Schema | `v1.0.0` |
| 紧凑推理 Schema | `cue_inference_batch_compact_v1.schema.json` / `v1.0.0` |
| 生产调用状态 | 未授权、未执行 |
| 冻结只读输入 | `source_video_atoms.jsonl` SHA256 `be5f36b77970cb5147b88551c566f081589fe00fcf5ef912d8468a037e92960e`；370799 行 |
| 本次正式输出 | 无；未写 `cue_library.jsonl`、`CUE_LIBRARY_SUCCESS.json`、Batch 请求文件或远端工件 |

## 修改内容

- `prompts/cue_extractor_v3_compact.md`
  - 全中文提示词为 UTF-8 `445` 字节，不超过冻结的 `450` 字节。
  - 规定数组完整性、`n,t,p,x,c,v,e,s,a,r` 短字段、短码表、同项连续原文子串、主槽位匹配和
    受控字段禁止回显。
- `scripts/05_extract_cues.py`
  - 从冻结配置读取 `v2.2.0` Batch、紧凑码、账本终态、价格与恢复规则，并把完整 `execution`
    连同提示词/Schema SHA256 纳入协议哈希。
  - 按 `atom_id` 排序，按每逻辑 shard `500` 条、每 package 最多 `5` 条和实际请求 `24000`
    UTF-8 字节限制构造 package；Batch 请求顶层 `enable_thinking:false`，输出上限为每 Atom
    `96` token。
  - 每十个逻辑 shard 形成一个内存 Batch task，检查单行 `1MB`、单文件 `50000` 行与 `500MB`
    限制。任务元数据含固定的血缘/哈希/范围/远端句柄字段；合成写入函数只写
    `batch_tasks_manifest.jsonl` 允许的无正文元数据及 `{custom_id: package_id}` 映射。
  - 严格展开 `n,t,p,x,c,v,e,s,a,r`：短码未知、遗漏/重复索引、私加字段、跨 Atom 子串、主槽位
    不匹配均拒绝；程序回填最终 Cue 的 ID、split、原文和运行字段，默认回填空实体与 null。
  - 模拟结果行只在内存解析。服务端行级失败的终态为
    `service_line_failure_requeueable`；服务端成功但本地校验失败为
    `local_validation_quarantine`，绝不自动重传；通过为 `validated_success`。账本不保存请求、
    响应、错误正文或原文，包含冻结的 Batch 六字段和 `outcome`。
  - 同一 `batch_custom_id` 只能有一个终态；隔离项永远不在可重排队集合中。
  - 面向冻结 Source 的默认预检采用逐行读取和逐 task 哈希：内存中只暂存当前十个 shard 的
    请求行，完成哈希后立即释放；不会把全量 Atom、package 与请求正文同时常驻内存。
- `tests/test_qwen_contracts.py`
  - 保留第 06/07 的回归测试；新增紧凑提示词字节数、五条 package、Batch 分组/`custom_id`、
    三个解析终态、隔离不重排队、无正文任务清单和默认只读/执行阻断测试。

## 只读输入与产物边界

| 输入 | 约束 |
| --- | --- |
| `source/source_video_atoms.jsonl` | 仅由预检读取，必须与 `SOURCE_ATOMS_SUCCESS.json` 的 SHA256 和行数一致 |
| `config/model_registry.yaml` | T0 冻结的 v2.2 配置，仅读取 |
| 紧凑提示词与两个 Cue Schema | 仅读取，SHA256 进入协议哈希 |

没有正式输出哈希：本次没有写 `cues/cue_library.jsonl`、`CUE_LIBRARY_SUCCESS.json`、Seed、
请求文件、原始响应、错误响应或远端文件。测试中的 JSONL 均位于 pytest 临时目录。

## 中文说明与注释验收

- `scripts/05_extract_cues.py` 的首个有效内容为中文模块说明，写明第 05 阶段职责、输入、输出
  和无 API 边界。
- 分包上限、custom_id 哈希、防跨 Atom 证据、隔离不重传、账本终态和执行开关阻断均有中文注释，
  说明血缘、成本和重复计费风险。
- 提示词、测试说明和本交接均为中文；代码字段、路径、模型 ID 和配置键按合同保留原文。

## 验证结果

```powershell
python -m py_compile egopm_bench_v1/scripts/05_extract_cues.py egopm_bench_v1/tests/test_qwen_contracts.py
# 通过

python -m pytest -q egopm_bench_v1/tests/test_qwen_contracts.py --basetemp .pytest_cache/t2-v22-targeted
# 10 passed

python -m pytest -q --basetemp .pytest_cache/t2-v22-full
# 46 passed

git diff --check
# 通过
```

T0 复跑的冻结 Source 只读预检结果为：`74160` 个 package、`742` 个逻辑 shard、`75` 个
Batch task；最大 Batch 请求行 `10943` UTF-8 字节，输入字节代理上界 `217655725`，输出上界
`35596704` token。该预检未读密钥、未联网、未写正式工件。

## 未解决问题与下一门

- `CR-2026-009` 的无 API T2 实现待 T0/T4 审阅。任何真正 Batch 上传、轮询、下载、远端清理、
  正式 Cue 合并和 SUCCESS 写入均不在本提交中，须另获用户的预算与执行授权。
- T4 应针对完整协议哈希、任务总清单、账本终态和最终 SUCCESS 的 Batch 血缘字段实施独立 QA。

## 实时 v3.1 故障恢复交接（2026-09-05）

本节覆盖用户首次实时启动暴露的 HTTP `400` 与 Windows `PermissionError`；它不改动
任何用户真实运行目录、Source、Cue library 或 SUCCESS。

### 本次修改

- `scripts/05_extract_cues.py`
  - 状态和 JSONL 写入使用唯一临时文件并对 Windows 共享锁有限重试；重试耗尽会保留旧
    状态和临时文件后中止，绝不删除真实 `realtime_state.json`。
  - HTTP 错误只在内存中提取受限的状态码、服务 `code` 和净化限长 `message`。完整错误体、
    请求体、字幕和模型原始响应均不保存。HTTP `400` 写无正文
    `service_transport_exhausted` 终态且不重试，调度器不再提交新包。
  - RPM/TPM 桶与费用账本均加锁；`ThreadPoolExecutor` 最多 `10` 个在飞 package，worker
    仅写自身 package 文件，主线程单独追加全局账本。
  - 每 15 秒及每个完成事件原子写波次目录内 `progress.json` 并打印同一无正文快照：波次、
    task 范围、总数、完成/成功/隔离/服务失败/预算停止、在飞数、预算、累计费用、耗时与 ETA。
  - 实时路径读取 `realtime_execution_policy` 冻结的八波范围
    `[1,10,10,10,10,10,10,14]` 和每 task 十个逻辑 shard。`--wave-index` 只调度该波；每波
    使用独立根目录 `cues/realtime/wave_XX`，不能与其它波或旧协议恢复状态混合。
- `tests/test_qwen_contracts.py`
  - 新增 HTTP `400` 安全诊断/终态、Windows 原子替换重试、十并发上限和按波
    `progress.json` 无正文测试。

### 真实运行恢复边界

旧 `cues/realtime` 目录的 `183` 个无计费 HTTP `400` 失败状态及一个 `requesting` 状态
绝不覆盖、绝不自动重发。T0/T4 完成新协议 SHA 和授权复核后，用户必须采用新的 run id；
新执行会从独立 `cues/realtime/wave_01` 开始，仅处理 task 0。每波通过门禁后才可授权下一波。

### 全八波累计预算补充

`¥80` 是同一 `run_id`、Source 哈希和协议哈希下八个波次的共同上限，不会在
`wave_XX` 子目录中重置。共享根 `cues/realtime` 新增无正文
`realtime_cumulative_ledger.jsonl` 和 `realtime_cumulative_progress.json`：每次波内事件先
写波账本、再写累计账本和累计费用快照；恢复时按 `realtime_request_id` 去重扫描所有波账本
和累计账本，重建已经发生的真实 usage 费用。若共享身份或授权预算不匹配，执行在读取密钥
或联网前拒绝。新增测试验证 Wave 2 会从 Wave 1 已花费用量继续核算。

### 波次顺序启动门补充

启动 `Wave N`（`N>1`）时，执行器会在读取 `DASHSCOPE_API_KEY` 前逐一读取共享根下
`wave_01` 到 `wave_{N-1}` 的 `progress.json`。每个前序波必须具有一致的 run id、Source
哈希和协议哈希，且 `status=completed`、完成数等于总数、在飞数为零、成功数等于总数、
隔离/服务失败/预算停止均为零；任何缺失、身份不一致或失败都会阻断下一波。进度快照已
绑定上述身份字段；测试覆盖 Wave 2 的通过与失败阻断场景。

## 实时 v5 无正文隔离诊断交接（2026-09-05）

### 只读事实与边界

- 仅读取 `realtime_v5_01` 的 package 状态、波次状态和进度，未读取结果 JSONL、模型原始响应、
  Source 文本或 API Key，也未联网。
- 现有无正文状态只能确认：首批 10 个 package 中 5 个 `validated_success`、5 个
  `local_validation_quarantine`，累计账面费用 `¥0.0033416`。旧版本没有记录失败类别；在
  不保存原始响应的合同下，不能从旧账本可靠倒推字段级原因，故不得猜测或自动重发。

### 本次修改

- `scripts/05_extract_cues.py` 新增 `LocalValidationError` 与只含固定大写错误码、JSON 字段/下标
  路径的诊断。错误码覆盖 JSON 解析、响应结构/根、推理 Schema 关键字、项目索引或数量、实体重复、
  短码、支撑文本子串、predicate 主槽位和最终 Cue Schema。
- 实时隔离事件、`*.failed.json` 与 `realtime_state.json` 新增
  `local_validation_failure={code,path}`；其中不含字段值、Atom 文本、请求体或模型响应。未知内部
  合同异常只记为 `LOCAL_VALIDATION_UNCLASSIFIED`，不会回显异常消息。
- `tests/test_qwen_contracts.py` 增加 JSON 解析、原文子串和 predicate 对齐三种模拟失败的无正文
  落盘测试，并验证账本字段合法。

### 验证结果

```powershell
python -m pytest -q egopm_bench_v1/tests/test_qwen_contracts.py
# 15 passed

python -m pytest -q
# 53 passed

git diff --check
# 通过
```

### 下一门

- 该改动改变执行协议哈希；T0 必须更新冻结协议/授权绑定，T4 应复核诊断字段和无正文保证。
- 旧 `realtime_v5_01` 仅保留审计，不自动重跑。以新协议和新 run id 发起的、小范围诊断运行才会
  产生可归类的失败记录；是否调用 API 仍须由用户单独确认。

## CR-016/017 正式 Cue 与 Seed 链升级交接（2026-09-09）

### 本次交付

- 在 `main` 分支完成正式 Cue 收官器：只读取 `realtime_v9_01`，将 accepted Cue 原子地写成 `task_000.jsonl` 至 `task_074.jsonl`，并生成 manifest/SUCCESS；package 与 Wave ledger 仅作审计输入。
- 完成 Cue manifest 读取接口、`trigger_cue_id` 必填字段、Cue→Atom/type/predicate 精确血缘、同组/跨组 lure、失败 predicate 子句和候选快照全局不复用门。
- 第 06 步固定 `bge_m3_hybrid_rrf_v1`、`BAAI/bge-m3` revision `5617a9f61b028005a4858fdac845db406aefb181`、双通道前 64、RRF `k=60`、CPU FP32 精确内积；缺依赖时阻断，不退回 lexical。
- Seed 生成与审计登记统一为 `qwen3.7-plus-2026-05-26`，分别使用 `medium`/`high`；本次未调用 API，也未保存模型原始响应。

### 交接边界

- 分支：`main`；当前工作区未提交，保护既有未提交修改。
- Cue manifest SHA256：`a7ccd99e629d185911084bb654f79ca6891711b7874cd950c07b0bc7972fdf75`；Cue 总数 `294839`；分片数 `75`。
- Source SHA256：`be5f36b77970cb5147b88551c566f081589fe00fcf5ef912d8468a037e92960e`；协议 SHA256：`c7d809927f9cca4ff7d4501a0121c419768cd95c1d3c05d13b156000c50fbbb5`。
- BGE-M3 正式检索尚未运行：项目 `.venv` 当前缺少 `FlagEmbedding`、`huggingface_hub` 及固定 revision 权重。因此 Seed 仍阻断；不得静默使用 lexical 检索。

### Python 门禁

本次修改的 Python 文件均保留中文模块说明；正式冻结、manifest/SUCCESS 原子写入、BGE 缺失阻断、Cue 血缘和 Seed 不复用判断均有中文关键注释。交接前须用项目 `.venv` 执行定向测试、全量测试和 `git diff --check`。
