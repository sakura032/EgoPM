# EgoPM-Bench v1 变更请求与实施指导

本文件由 T0 维护，用于记录跨角色、跨门禁或需要冻结执行语义的变更。本文件不授权绕过
任何 `SUCCESS`、哈希、质量验证或用户预算确认门。

## CR-2026-008：Cue v2.1 Batch File——同模型异步批量传输设计

### 状态、范围与结论

- 状态：**仅完成无 API 设计与核算；未冻结配置、未实现、未获任何生产授权**。
- 决策建议：以 `Batch File` 替换 v2 的实时传输，但保持 `qwen3.7-flash-2026-07-15`、北京地域、
  `enable_thinking=false`、温度、五条自适应 package、370799 条 Source Atom 覆盖、最终 Cue Schema
  和程序回填语义不变。
- 这是一项新的执行传输与数据保留边界，不能把现有 v2 实时 `SUCCESS`、package 或账本与将来的
  Batch run 混用。实现时必须冻结新的 `cue_execution_policy_version`、传输类型、Batch 价格、任务
  分组、`custom_id` 规则和远端文件清理策略，并使协议哈希变化。
- Batch File 不是上下文缓存。官方说明其按成功请求的输入/输出 Token 以实时价格 50% 计费，
  且不支持上下文缓存；因此本 CR 只采用 Batch File，不叠加缓存假设。

官方依据：[千问 3.7 Flash 模型与北京价格](https://help.aliyun.com/zh/model-studio/qwen3-7-flash)、
[批量推理规范、文件限制与恢复字段](https://help.aliyun.com/zh/model-studio/batch-inference)。正式提交任务前
必须再次核验控制台中的模型可用性、地域与价格；此处的数值只是 `2026-09-01` 的设计快照。

### 只保留的两条成本路径

| 路径 | 模型与覆盖 | 传输 | 单次保守费用上界 | 时间语义 | 结论 |
| --- | --- | --- | ---: | --- | --- |
| 原始 v1 | 同一模型，370799 Atom | 每 Atom 实时请求 | ¥507.73 | 限流下界 32.82 小时 | 不采用 |
| **拟采用 v2.1** | **同一模型，同一 370799 Atom，最多 5 条/package** | **Batch File** | **¥50.09** | **异步任务；请求 24 小时完成窗口，不承诺实时下界** | **待无 API 实现和用户授权后唯一生产方案** |

当前 v2 实时执行器只作为 v2.1 的 package、验证、血缘和恢复实现基础，不再作为成本方案列入比较。
v2.1 对原始 v1 的保守费用上界降低约 `90.1%`，对已预检的 v2 实时上界再降低 `50%`。

### 当前冻结 Source 的无 API 成本核算

下列输入/输出数是 v2 当前只读预检的保守上界：输入为完整序列化请求的 UTF-8 字节代理，不是
服务端最终账单 Token；输出为 `128 × Atom 数` 的固定上限。最终费用只能以 Batch 任务结束后的服务端
用量为准。

| 项目 | 数值 | 计算 |
| --- | ---: | --- |
| Source Atom | 370799 | 已冻结 Source SHA256 不变 |
| package | 74160 | 每包最多 5 条，最大请求 12202 UTF-8 字节 |
| 逻辑 shard | 742 | 每 shard 最多 500 条 Atom |
| 输入上界 | 311023165 | UTF-8 字节代理 |
| 输出上界 | 47462272 | `370799 × 128` token |
| Batch 输入单价 | ¥0.1 / 百万 token | 北京 `<=32K`，实时 ¥0.2 的 50% |
| Batch 输出单价 | ¥0.4 / 百万 token | 北京 `<=32K`，实时 ¥0.8 的 50% |
| 输入费用上界 | ¥31.1023165 | `311023165 / 1e6 × 0.1` |
| 输出费用上界 | ¥18.9849088 | `47462272 / 1e6 × 0.4` |
| **单次计划总上界** | **¥50.0872253** | **输入加输出，预算时向上取整为 ¥50.09** |

Batch 仅对成功请求计费；文件解析失败、任务失败和行级错误不收费。已由服务端成功生成、但被本地
Schema/血缘门拒绝的响应已经产生费用，因此 v2.1 **禁止**对这类记录自动二次提交，必须隔离并由
用户决定。若人为批准把全部成功 package 完整重跑两次，绝对三轮上界才是 `¥150.2616759`；它不是
计划预算，也不是自动重试策略。

`128 token/Atom` 继续保持为 v2 已测协议值。本 CR 不擅自降至 96 或 80；此类输出上限调整必须
单列变更请求、进行结构性截断测试、重算费用，并取得新的用户预算确认。

### Batch 文件与任务分组

官方限制为单个 JSONL 文件最多 50000 个请求、500 MB，每行最多 1 MB，且同一文件必须使用同一模型
与思考模式。v2.1 固定采用“10 个逻辑 shard 为一个 Batch task”的分组：共 75 个任务，前 74 个最多
1000 个 package，最后一个 2 个逻辑 shard。即使每行都达到当前 12202 字节请求上界，加上封装字段后
每个输入文件仍远低于 500 MB；小分组把单个远端任务的恢复域限制在至多 10 个逻辑 shard。

每一行固定为：

```json
{
  "custom_id": "v21_s00000_p000_6d3e2a1f",
  "method": "POST",
  "url": "/v1/chat/completions",
  "body": {"model": "qwen3.7-flash-2026-07-15", "enable_thinking": false}
}
```

实际 `body` 完整复用 v2 的五条 package 请求：固定系统提示词、推理 JSON Schema、`items` 中的
`item_index` 与 `text`，以及固定输出上限。`custom_id` 只编码 run/shard/package 与短哈希，长度小于
官方 256 字符限制；Atom ID、split、来源路径、视频路径、Cue ID 和其他受控字段都不进入模型输入。
Batch JSONL 的每行必须将 `enable_thinking=false` 放在 `body` 顶层，不能放在 `extra_body`。

任务 metadata 至少包含：`run_id`、批次组编号、Source SHA256、v2.1 协议 SHA256、输入文件 SHA256、
请求行数、最小/最大逻辑 shard 和创建时间。每个 `custom_id` 只能映射一个本地 package 清单；任何重复、
未知、漏项或协议不一致都会阻断该 task 的结果接收。

### 数据保留、结果接收与可恢复性

Batch File 必然向服务端上传含 `visible_text` 的请求 JSONL，且服务端结果文件包含原始 `response`、
错误文件包含原始 `error`。这比实时 v2 增加了远端临时文件边界，必须在用户的正式生产授权中明确接受。
本地策略固定如下：

1. 仅在明确执行时，从已验证 Source Atom 和 package 清单确定性生成一个 `*.tmp` Batch 输入文件；它
   不进入 Git、不作为正式工件，上传确认后只保留 SHA256、行数、file ID 与 metadata，随后删除本地明文。
2. 结果与错误文件只能流式读取到内存，按 `custom_id` 验证并立即转换为无正文 package 结果片段或无正文
   ledger 事件；不得把原始 `response`、`error`、请求正文或 API Key 落盘。
3. 本地 package 仍保存清单、已验证 Cue 片段、无正文账本、完成/失败标记和 SHA256。重跑时从冻结 Source
   确定性重建请求，不依赖已删除的本地 Batch 输入文件。
4. Batch 任务完成、结果完成接收且 T4 Cue QA 通过后，运行者必须删除服务端输入、结果和错误文件，并在
   账本记录删除确认；官方说明未下载的任务结果会在 30 天后自动删除，但这不是本项目的保留策略。

Batch job 设定 `completion_window=24h`。官方允许设置 1--14 天且处理时长受系统负载影响，因此 v2.1
不能承诺实时 v2 的 5.98 小时下界；费用监控数据也会在任务完成后才出现，并可能有 1--2 小时延迟。

恢复流程不以整批任务为单位盲重跑：下载输出后，逐个 `custom_id` 写入完成或失败状态。只有未返回、服务端
行级失败、清单/哈希不符或未完成的 package 组成新的小 Batch 输入；已通过本地验证的 package 永不重发。
服务端成功但本地验证失败的 package 则进入隔离清单，禁止自动重试，避免为同一错误重复付费。

### 将来的无 API 实施与 QA 门

本 CR 现在**只定义设计**，不授予 T2 写入生产 Cue、调用千问或读取密钥的权限。后续必须按以下顺序：

1. T0 冻结 v2.1 配置与协议哈希字段，包括 `transport=batch_file`、Batch 价格、24 小时窗口、10-shard
   task 分组、远端文件清理、禁止自动重试本地验证失败记录和新的账本字段。
2. T2 只用 synthetic fixture 实现 Batch JSONL 生成、`custom_id` 映射、流式结果解析、远端句柄账本和
   失败 package 再组批；无 API 测试只可在临时目录生成合成 Batch 文件，不得生成生产输入或访问服务端。
3. T4 增加独立验证：输入清单/metadata/`custom_id` 双向唯一、Source 与协议哈希、Batch 价格版本、
   无原始响应落盘、删除确认、成功/行级失败/本地验证失败的计费与恢复分支。
4. T0 复跑完整无 API 测试和冻结 Source 的 Batch 文件规模/费用预检，并更新状态板。
5. 用户单独确认：不超过 ¥50.09 的成功请求预算、是否允许一项有上限的付费 smoke 验证、24 小时任务窗口、
   远端临时文件保留与删除、以及隔离失败 package 的人工处理范围。

在第 5 步前，禁止上传 Batch 输入文件、创建远端 file/batch、下载结果、调用千问或写任何 Cue/SUCCESS。

## CR-2026-007：Cue 提取协议 v2——五条自适应包与受控字段回填

### 状态与结论

- 状态：**v2 实时执行基础已完成；生产方案由 CR-2026-008 的 v2.1 Batch File 设计接替**。
- 决策：采用“每个请求最多 5 条 Atom”的自适应打包方案。
- 目的：在不更换模型、不缩减 370799 条冻结 Source Atom 覆盖、也不改变最终
  `cue_candidate` 数据 Schema 的前提下，降低第 05 步的重复输入、输出和请求数。
- 本变更只改变第 05 步的请求协议、临时 shard/package 组织、提示词版本和运行配置。
  现有 `SOURCE_ATOMS_SUCCESS`、Source Atom 哈希、split 和最终 Cue Schema 均不改变。
- 正式执行仍须由用户另行确认预算、执行范围和分批方案。确认前，默认路径必须保持只读，
  禁止读取 `DASHSCOPE_API_KEY`、调用千问、写 `cue_library.jsonl` 或写
  `CUE_LIBRARY_SUCCESS.json`。

### 正式实施摘要

本 CR 只保留两条可比较的路径：

| 路径 | 请求组织 | 保守费用上界 | 目标限流下时长下界 | 结论 |
| --- | --- | ---: | ---: | --- |
| 现有 v1 基线 | 每个 Atom 单独请求 | ¥507.73 | 32.82 小时 | 不采用 |
| v2 实时实现基础 | 最多 5 条 Atom 一个自适应 package | ¥100.17 | 5.98 小时 | 仅作 v2.1 的本地实现基础，不再请求生产授权 |

v2 在相同覆盖和模型下，将请求数从 370799 降至 74160；按实际只读预检的保守上界，费用降低约 80.3%，
时长下界降低约 81.8%。这不是删减样本或降低最终 Cue 数据要求，而是消除重复提示词、完整
Schema、受控字段和原文回显造成的冗余。

### 已冻结的上游边界与设计输入

| 项目 | 冻结值或约束 |
| --- | --- |
| Source Atom 数 | 370799 |
| Source Atom SHA256 | `be5f36b77970cb5147b88551c566f081589fe00fcf5ef912d8468a037e92960e` |
| 模型 | `qwen3.7-flash-2026-07-15` |
| 地域 | `cn-beijing` |
| 推理模式 | `enable_thinking=false`、`temperature=0` |
| 最终 Cue Schema | `cue_candidate.schema.json`，版本 `v1.0.0`，不修改 |
| 默认包上限 | 5 条 Atom |
| 单请求输入保护线 | 序列化 UTF-8 请求字节不超过 24000；该字节上界用于保守地留在 `<=32K` 价格档 |
| 输出上限 | 每条 Atom 128 token；包上限为 `128 × 本包 Atom 数` |
| 传输重试 | 每个 package 最多额外重试 2 次 |
| 正式计量 | 仅以服务端 `usage.prompt_tokens`、`completion_tokens`、`total_tokens` 为准 |
| 原始响应 | 禁止落盘；只可在内存中解析，随后仅持久化验证后的最终 Cue 和无正文账本 |

`128 token/Atom` 是待生产前质量试运行确认的初值，不得在正式运行中临时改大或改小。若
试运行显示截断或质量下降，必须先更新本变更的冻结值、重跑无 API 预检，再请求用户确认。

### 目标与非目标

本变更必须实现以下目标：

- 每条冻结 Atom 恰好进入一个确定性 package，并保持覆盖、split 和最终输出顺序。
- 每个 package 只发送一次固定提示词和一次推理 JSON Schema。
- `visible_text` 在模型输入中只出现一次；模型不回显完整原文或程序可控字段。
- 无论 package 内有多少 Atom，程序都独立验证并构造每条最终 Cue。
- 中断、超时、哈希不符或未完成时，只重跑相应小 package，绝不重跑已完成 package。
- 下游读取的仍是原有 Cue JSONL 和原有 `CUE_LIBRARY_SUCCESS.json` 语义。

本变更不做以下事情：

- 不删减 Atom、不改变 split、不抽样替代正式覆盖。
- 不读取、下载、复制、拼接或上传 MP4；生产输入仍只读 EgoLife SRT 衍生的冻结 Atom。
- 不改最终 Cue、Seed、Life Log 或 Decision Schema。
- 不保存 API Key、`.env`、原始模型响应、原始响应日志或手工编辑的 JSONL。
- v2 实时基础本身不采用上下文缓存；Batch File 的生产边界、价格、远端文件和恢复规则完全由
  `CR-2026-008` 管理，不能混用两套协议。

### v2 请求与回填协议

#### 输入给模型的最小信息

每个请求只含一个固定系统提示词、一个严格推理 Schema 和一个 `items` 数组。数组元素只带
局部索引和该条可见文本：

```json
{
  "items": [
    {"item_index": 0, "text": "我拿着手机"},
    {"item_index": 1, "text": "……"}
  ]
}
```

不得向模型传递 `atom_id`、`split`、`cue_id`、`source_text`、`model_id`、
`prompt_version`、`schema_version`、`run_id`、来源路径、视频路径、隐藏字段或任何
oracle/提醒标签。`item_index` 是唯一保留的非语义关联键；其取值为本包内的 `0` 至 `n-1`。

#### 模型返回的推理对象

响应顶层是 `items` 数组。每个元素必须带 `item_index` 和以下由模型推理的字段：

- `entities`
- `scene_type`
- `activity_type`
- `cue_type`
- `normalized_predicate`
- `supporting_text_span`
- `confidence`
- `ambiguity_reason`
- `validation_status`

推理 Schema 必须禁止额外字段，并实施紧凑上限：最多 5 个实体、有限的谓词子句、简短的
歧义原因和最短充分的原文支撑片段。它是 API 响应约束，不是新的正式数据 Schema；构造后的
最终记录必须仍通过 `cue_candidate.schema.json`。

#### 程序唯一可写的受控字段

程序按输入 package 清单和冻结运行配置填入下列字段，且完全忽略模型可能私自返回的同名字段：

| 最终字段 | 唯一来源 |
| --- | --- |
| `cue_id` | 由 `atom_id` 确定性派生 |
| `atom_id` | package 清单 |
| `split` | 冻结 Source Atom |
| `source_text` | 冻结 Source Atom 的 `visible_text` |
| `model_id` | 冻结模型登记 |
| `prompt_version` | 冻结值 `cue_extractor_v2`；精确提示词字节由运行 manifest 的提示词 SHA256 约束 |
| `schema_version` | 现有 Cue Schema 的 `v1.0.0` |
| `run_id` | 本次冻结运行标识 |

`validation_errors` 由本地验证器生成或省略，绝不让模型编造。模型若标记 `rejected`，仍必须
返回该 Atom 的推理对象以实现完整覆盖；只有满足既有生产语义的接受记录才进入最终 Cue
JSONL，保持 v1 的现有输出语义。

### 自适应打包算法

1. 验证 `SOURCE_ATOMS_SUCCESS.json` 的项目内路径、版本、行数、SHA256 和 Source Schema。
2. 按 `atom_id` 字典序建立唯一、稳定的 Atom 序列；任何空 ID 或重复 ID 都阻断运行。
3. 以当前 package 的候选请求体序列化 UTF-8 字节数做预估。加入下一条 Atom 后，只有同时满足
   “条数不超过 5”和“请求字节不超过 24000”时才纳入当前包。
4. 否则封存当前包，并以该 Atom 开启下一包。单条 Atom 超过保护线时必须阻断并人工处理，不能
   悄然进入更高价格档。
5. `max_tokens` 固定计算为 `128 × 本包 Atom 数`。不得按模型临时建议或失败后静默扩大。
6. 每 500 个 Atom 保留一个逻辑 shard；每个 shard 内 package 编号从零递增。合并顺序固定为
   `shard_index → package_index → item_index`。

对当前冻结来源的 `2026-09-01` 只读预检中，5 条上限产生 74160 个请求 package：741 个完整
shard 各有 100 个 package，最后一个 299 Atom shard 有 60 个 package，其中最后一个 package 有 4 条。
最大的实际序列化请求为 12202 UTF-8 字节，因此当前来源会在 24000 字节保护线内运行；该结论必须在
每次提示词、推理 Schema 或模型参数变动后重新预检，不能手工沿用。

### package 工件、原子写入与恢复

每个 package 的输入清单只保存 `atom_id`、Atom 行 SHA256、package/shard 编号、来源 SHA256 和
协议哈希；它不重复持久化可见文本。运行时从已验证的冻结 Source Atom 重建请求。

每个 package 必须在同一运行根目录下原子写入以下工件：

| 工件 | 必含内容 |
| --- | --- |
| 输入清单 | package 原子顺序、各 Atom 哈希、上游 Source 哈希、协议哈希 |
| 结果片段 | 仅已解析、受控字段已回填且通过最终 Cue Schema 的 JSONL；不含原始响应 |
| 无正文账本 | 请求时间、尝试数、服务端 usage、预留 token、限流等待、状态、失败类别和截断后的摘要 |
| 完成标记 | 输入清单、结果片段、账本 SHA256；来源哈希；协议哈希；完成时间；接受行数 |
| 失败标记 | 可复现的失败类别和账本哈希；不含模型正文 |

所有正式或中间 JSON/JSONL 都必须先写入同名 `*.tmp`，完成内部验证和 `fsync` 后原子替换。
完成标记必须最后写入。

恢复时，只有同时匹配来源 SHA256、协议哈希、输入清单 SHA256、结果片段 SHA256 和账本 SHA256 的
完成 package 才会跳过。缺失、失败、未完成或任一哈希不符的 package 才可进入重跑队列。传输失败
可在该 package 内按冻结上限重试；结构、数量、索引、语义或血缘失败应写入失败标记并停止该
package，等待显式 `--rerun-failed-packages`，避免确定性坏输出被无限重复计费。

### 逐包验证门

在任何结果片段落盘前，T2 必须验证：

1. 模型数组长度等于输入 Atom 数，`item_index` 恰好是 `0..n-1` 的无重复排列。
2. 每个推理对象通过严格的 v2 推理 Schema，且没有受控字段。
3. 每个 `supporting_text_span` 是其映射 Atom 的 `visible_text` 的连续子串；不能跨 Atom 借用文字。
4. `cue_type` 与 `normalized_predicate.all_of` 至少一个 `slot` 一致。
5. 程序回填后，每条记录通过既有 `cue_candidate.schema.json`，并与 Source Atom 的
   `atom_id`、`split`、`source_text` 一致。
6. 结果片段内 `cue_id` 唯一，且其 Atom 行哈希与 package 清单一致。

全部 package 通过后，才允许生成唯一的 `cue_library.jsonl.tmp`。合并程序必须再次验证全局
顺序、唯一性、来源血缘和最终 Cue Schema；哈希、行数、版本、上游 Source 哈希、提示词/推理
Schema/协议哈希和用量汇总齐全后，才能原子写入 `CUE_LIBRARY_SUCCESS.json`。随后仍由 T4 进行
独立 Cue QA；T0 未将 T4 Cue QA 提升为 `DONE` 前，禁止启动 Seed。

### 限流、用量与预算

实时执行采用无突发调度。每一次 HTTP 尝试（包括重试）按“完整序列化请求 UTF-8 字节数 +
本请求 `max_tokens`”预留 token，取 RPM 和 TPM 两个最严格的间隔。当前保守目标保持
`300 RPM` 与 `1000000 TPM`；真实账务只累计服务端 `usage`，不可将预检字节数伪装为实际 token。

当前模型在北京 `<=32K` 档的实时价格为输入每百万 token `¥0.2`、输出每百万 token `¥0.8`；
官方额度为 `30000 RPM` 与 `5000000 TPM`。价格和额度在正式执行前必须重新核验并冻结到运行
manifest，禁止按旧截图或记忆覆盖。官方依据见
[模型信息与价格](https://help.aliyun.com/zh/model-studio/qwen3-7-flash) 和
[限流说明](https://help.aliyun.com/zh/model-studio/rate-limit)。

下表是当前冻结 Source Atom 与本协议的只读保守模拟。输入“token”是 UTF-8 字节上界代理，
不是账单实测 token；费用为单次成功尝试的上界，实际账单可能更低。

| 方案 | 请求数 | 输入上界 | 输出上界 | 费用上界 | 目标限流下时长下界 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 现有逐 Atom v1 基线 | 370799 | 1779240532 | 189849088 | ¥507.73 | 32.82 小时 |
| **已采用 v2：最多 5 条/包** | **74160** | **311023165** | **47462272** | **¥100.17** | **5.98 小时** |

本次预检的 TPM 约束为 `(311023165 + 47462272) / 1000000 = 358.485437` 分钟，即约 `5.98` 小时；
RPM 约束为 `74160 / 300 = 247.2` 分钟，因此实际调度应以 TPM 为主、RPM 为副。若每个 package
都耗尽两次额外重试，5 条包的极保守上界约为 `¥300.53`。该数字不是批准预算；
用户必须在正式执行前确认可接受的总预算、失败重跑上限和是否允许夜间连续运行。调用方式固定为
本 CR 的实时五条 package 方案，禁止临时切换其他通道。

### 角色分工与实施顺序

| 步骤 | 负责人 | 工作 | 允许的产物 | 禁止事项 |
| --- | --- | --- | --- | --- |
| 0 | T0 | 审阅本 CR、冻结 v2 配置字段、提示词/推理 Schema 哈希和验收阈值 | 配置、合同测试、状态板 | API 调用、Cue 产物 |
| 1 | T2 | 实现 package 构建、受控字段回填、严格响应解析、恢复和确定性合并 | 脚本、提示词、无 API 测试、handoff | `--execute`、密钥读取、正式 JSONL |
| 2 | T4 | 为 v2 运行标记和最终 Cue 血缘补充独立 QA 测试；确认 Cue Schema 仍为 `v1.0.0` | 验证器、无 API 测试、handoff | 修改 T2 生产者输出 |
| 3 | T0 | 检查文件所有权、中文说明门禁、哈希边界、全量无 API 测试和预检成本 | 合并提交、状态更新 | 未获授权的生产运行 |
| 4 | 用户 | 确认总预算、实时五条 package 运行时间窗和失败重跑范围 | 明确生产授权 | 含糊地默认授权 |
| 5 | T2 | 仅在明确授权后执行正式第 05 步 | package、Cue library、SUCCESS | Seed、Life Log、MP4 操作 |
| 6 | T4 → T0 | 独立 Cue QA，再由 T0 决定是否提升 Cue QA 门 | audit、状态更新 | 在 QA 前启动 Seed |

### 无 API 测试与生产前验收

实现完成后必须至少验证：

- 同一冻结 Source SHA 下 package 清单、顺序、协议哈希和预检成本完全可复现。
- 单条、五条、超长文本和末尾不足五条的 package 均符合字节保护线和输出上限。
- 少一项、重复一项、错 `item_index`、跨 Atom 原文片段、模型私传受控字段、错误 split、错误
  Atom 哈希和错误协议哈希都会被阻断。
- 缺失/篡改 package 账本、片段或完成标记时，只该 package 回到待处理队列。
- 已完成 package 不重发；失败 package 需要显式重跑开关；合并前存在任一待处理 package 必须失败。
- 默认命令不读取环境密钥、不联网、不生成 Cue/SUCCESS；测试只使用合成 fixture 或临时目录。
- 全仓 `python -m pytest -q`、`git diff --check` 通过，且 T4 的阶段 Schema 校验继续接受
  `cue_candidate: v1.0.0`。

任何真实小规模质量试运行都必须与正式数据隔离，拥有独立 run ID、单独预算和用户授权；它不能
充当正式 Cue 产物，也不能以“已经跑过样本”为由跳过完整 370799 Atom 覆盖。

### 回滚与运行中变更

当前没有正式 Cue，所以在 API 生产前切换到 v2 不需要重建下游产物。一旦任意 v2 package 开始
正式执行，模型 ID、提示词、推理 Schema、包上限、字节保护线、输出上限、限流、价格快照和
受控字段规则都必须保持不变。任何修改都使该 run 的未完成 package 不可与已完成 package 混合，
必须创建新的 run ID，并由 T0 决定是否完整重跑。

### 当前下一步

本文件已经完成 v2 配置、执行器、独立 QA、无 API 合成测试和冻结 Source 的只读预检。正式模型
调用仍等待用户明确确认总预算、执行范围、运行时间窗与失败 package 重跑范围；确认前不得传入
`--execute`，不得调用千问，也不得写 Cue、SUCCESS、Seed 或 Life Log。
