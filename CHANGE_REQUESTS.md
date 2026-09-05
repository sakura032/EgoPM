# EgoPM-Bench v1 变更请求与实施指导

本文件由 T0 维护，用于记录跨角色、跨门禁或需要冻结执行语义的变更。本文件不授权绕过
任何 `SUCCESS`、哈希、质量验证或用户预算确认门。

## CR-2026-011：Cue v3 实时 API 可恢复执行路径

### 状态与决策边界

- 状态：**v3 实时无 API 配置、执行器与独立 QA 已完成；等待用户以新协议 SHA 重新绑定本机授权后才能启动 Wave 1。**
- 终止边界：已提交的 `batch_1cd32927-4c33-43f6-8d8e-f4bb0e17d01f` 不得下载、接收、重试或与新产物混用。
  Batch 在取消完成前可能已有成功行并由服务商计费；本项目不将其任何内容写入 Cue 工件。
- 目标：保持完整 370799 条 Source 覆盖、`qwen3.7-flash`、非思考、温度 `0`、最多五条 Atom package、
  96 token/Atom 和最终 Cue Schema `v1.0.0` 不变；仅将异步 Batch File 传输改为可限流、可熔断、
  可恢复的实时 `/chat/completions` 调用。
- 新协议：模型登记 `v1.5.0`，Cue 执行协议 `v3.0.0`。实时目录固定为 `cues/realtime/`；任何
  `cues/batch/` 状态、远端文件、收据、package、使用量或结果都不是 v3 输入。
- 成本：按北京实时公开价输入 `¥0.2/M`、输出 `¥0.8/M`，v3 正式 Source 流式预检得到输入代理
  `55480053`、输出上界 `35596704 token`，单次保守上界为 `¥39.5733738`。用户的 `¥80` 是跨八波
  的累计硬上限，而不是每波独立额度；重试、服务失败等已计费 usage 也进入累计账本。达到剩余额度
  前即停止，绝不以三次尝试的理论极端上界自动透支。
- 兼容性修复：2026-09-05 的首个实时 Wave 1 在服务端参数校验阶段以 `invalid_parameter_error`
  拒绝，诊断指向 `response_format.json_schema.schema` 的 `uniqueItems`；十个初始并发包均未计费，
  其运行目录仅作审计。推理 Schema 移除该服务端不兼容关键字，并在本地展开前恢复实体数组去重
  校验，因此最终 Cue Schema 与质量约束不变。此变更使协议 SHA 更新为
  `c1651d7cfa5e19c6cd70728b67005319f6427149ec348e802272fcf14771ae59`，必须使用新 run ID 与重新
  绑定的本机授权；不得复用 `realtime_v4_01`。

### 冻结执行规则

1. 每包最多 `5` Atom、每 shard `500` Atom；包顺序由 `atom_id` 字典序及 shard/package 编号唯一决定。
2. 实时执行软上限为 `300 RPM`、`1000000 TPM`、最多 `10` 个并发请求；请求前以序列化请求字节加
   `max_tokens` 预留 token，避免并发下穿透 TPM 限制。
3. 每包最多尝试 `3` 次（初始加两次重试）；仅 `408`、`429`、`500`、`502`、`503`、`504` 允许自动重试，
   使用 `2` 至 `60` 秒指数退避；单次 HTTP 请求超时固定为 `60` 秒。任何本地 Schema、索引、原文子串、血缘或受控字段失败一律 quarantine。
4. 每次请求仅保留 request SHA、尝试次数、无正文失败摘要、服务端 `usage`、等待时间和终态；严禁保存
   原始请求、原始响应、错误正文或 API Key。
5. 每次发起前，已记账成本加本次上界预留不得超过授权总额；否则写 `budget_stopped` 终态并停止。
6. 仅来源 SHA、协议 SHA、输入清单 SHA、结果片段 SHA、账本 SHA 和完成标记全部匹配的 package 可恢复跳过。
   `local_validation_quarantine` 和 `budget_stopped` 永不自动重排；任何显式失败重跑都须新授权。
7. 实时传输必须保持原八波范围 `1 + 6×10 + 14` task；一个 task 固定十个逻辑 shard。每波仅调度
   自身 task/shard，波内才允许最多十个在飞 package。Wave N 在读取密钥前须验证 Wave 1 至 N-1
   同一 run、来源和协议并且全部成功、零在飞、零隔离、零服务失败、零预算停止。
8. 每 15 秒和每个 package 终态均原子写无正文 `progress.json`。最终 QA 必须聚合 `wave_01` 至
   `wave_08`，确认 task `0..74` 完整无重叠，且根级累计账本与各波账本并集一致；否则禁止写
   `CUE_LIBRARY_SUCCESS.json`。
9. 波次启动不得为便捷性把全量 Source Atom 常驻内存。执行器必须流式验证、仅保留当前波的
   target shard；Wave 1 在越过 shard `9` 后立即停止读取，并在每完成一个 shard 时发布无正文
   `preparing_source` 进度。该启动快照不含请求、响应或字幕正文。

### 实施与启动门

| 步骤 | 负责人 | 允许工作 | 禁止事项 |
| --- | --- | --- | --- |
| 1 | T0 | 冻结 v3 配置、成本/限流边界、变更记录 | API、正式 Cue |
| 2 | T2 | 实时执行器、恢复账本、fake transport 测试 | 读取密钥、联网、正式产物 |
| 3 | T4 | 实时独立 QA、无正文/混用/熔断验证 | 修改 T2 输出 |
| 4 | T0 | 所有权审阅、全仓无 API 回归、重算 v3 SHA | 实时调用 |
| 5 | 用户 | 填写新的本机授权并明确确认预算后执行实时首波 | 与旧 Batch 并行 |

正式启动前必须通过全仓无 API 测试、T4 QA、v3 Source 预检和预算授权核验。该 CR 不授权实时调用。

## CR-2026-010：Batch API 模型标识兼容性修正

### 状态与决策边界

- 状态：**T0 已批准并落实；旧 Wave 1 输入作废，必须重新绑定授权后才可重提。**
- 发现：2026-09-05 第 1 波任务 `batch_1d50a9e3-733f-4baf-b754-bc1344d00f73` 在服务端文件校验阶段失败，错误为
  `model_not_found`，明确指出 `qwen3.7-flash-2026-07-15` 不受 Batch API 支持；`request_counts.total=0`，因此未发生推理调用。
- 根因：模型登记沿用了实时接口可用的日期快照 ID，而 Batch API 要求模型族基础别名。
- 修正：Cue 执行模型从 `qwen3.7-flash-2026-07-15` 改为 Batch 支持的基础别名 `qwen3.7-flash`。这不是更换模型家族，
  仍为同一 Qwen Flash 能力；仅修正传输接口的合法模型标识。参考 [Batch 推理文档](https://help.aliyun.com/zh/model-studio/batch-inference)。
- 影响：模型登记版本升为 `v1.4.0`，Cue 执行协议升为 `v2.2.1`，协议 SHA、Batch 输入 SHA 和运行授权绑定值均改变；Source、Cue 最终 Schema、
  package 上限、费用单价、波次计划和 370799 条覆盖范围不变。旧 Batch 输入不得重用，也不得与新协议结果合并。
- 失败批次保留无正文状态和远端文件 ID 供审计；不得对旧 `batch_id` 重试。重新提交前应由用户在本机授权文件中写入新的协议 SHA，
  并重新执行无 API 预检；T0 不代替用户调用 API。

### 验收门

1. `model_registry.yaml`、请求构造和最终 Cue 回填的模型 ID 全部为 `qwen3.7-flash`，不存在旧快照漂移。
2. 全仓无 API 测试及 `git diff --check` 通过；根据新配置重新计算协议 SHA。
3. 本机 `CUE_EXECUTION_AUTHORIZATION.json` 的 `source_atoms_sha256` 不变，`cue_execution_protocol_sha256` 必须更新为新值；预算仍不得超过已批准的 `¥40`。
4. 仅在用户重新下达 Wave 1 执行命令后，才允许上传新的输入文件；旧远端文件按既定清理门处理。

## CR-2026-009：Cue v2.2 紧凑推理协议——短码、默认回填与 96 token 输出上限

### 状态与决策边界

- 状态：**v2.2 配置、紧凑推理 Schema、无 API 计划器、独立 QA、冻结 Source 实测预检及八波授权核验已完成；未调用 API、未创建远端 Batch、未生成正式 Cue。**
- 目标：在 CR-2026-008 的同模型 Batch File 之上，压缩模型可见的提示词、推理 Schema 和推理输出；
  最终 `cue_candidate.schema.json`、370799 条 Source Atom 覆盖、split、五条 package 上限、来源检查和
  程序回填语义均不得变化。
- 新的候选输出上限为 **96 token/Atom**，即每个五条 package 的 `max_tokens=480`。这只是待验收值，
  不是执行授权；若出现 JSON 截断、漏项或 QA 退化，必须拒绝该版本，不能在生产中临时扩大上限。
- 该变更将产生新的提示词、推理 Schema、编码表、输出上限、Batch 请求体、协议哈希和运行版本；任何
  v2/v2.1 package、结果、账本或远端 Batch 文件都不能与 v2.2 混用。

### 紧凑对象：模型返回什么，程序回填什么

模型仍只接收 `items` 内的局部索引与 `text`，不接收 Atom ID、split、Cue ID、路径、视频、Source 原文副本
或任何 oracle 字段。模型的推理对象改为短键；程序在严格验证后确定性展开为现有最终 Cue 字段。

| 紧凑键 | 模型含义 | 程序展开/默认值 |
| --- | --- | --- |
| `n` | package 内 `item_index` | 直接展开为 `item_index` |
| `t` | Cue 类型码：`T/P/L/O/A/S` | `time/person/place/object/activity/state_change` |
| `p` | 1--3 个 `[slot码, 操作码, value]` | 展开为 `normalized_predicate.all_of` |
| `x` | 最短连续原文支撑片段 | `supporting_text_span` |
| `c` | 0--100 整数置信度 | 除以 100 得到 `confidence` |
| `v` | 状态码：`A/R/N` | `accepted/rejected/needs_review` |
| `e` | 可选实体数组 | 缺省为 `[]` |
| `s` | 可选场景类型 | 缺省为 `null` |
| `a` | 可选活动类型 | 缺省为 `null` |
| `r` | 可选歧义原因 | 缺省为 `null` |

操作码固定为：`=`=`eq`、`!`=`not_eq`、`+`=`present`、`-`=`absent`、`^`=`starts`、`$`=`ends`、
`~`=`contains`。`p` 中至少一个 slot 码必须等于 `t`；未知码、重复/越界 `n`、非法整数置信度、缺失
`p`/`x`/`v`、跨 Atom 原文片段或最终 Cue Schema 不通过均为阻断错误。

例如模型只返回：

```json
{"n":0,"t":"A","p":[["A","^","cooking"]],"x":"starts cooking","c":80,"v":"A"}
```

程序才构造仍符合原最终 Schema 的 `cue_type="activity"`、完整 predicate、`confidence=0.80`、
`entities=[]`、其余缺省 `null`，再回填 `cue_id`、`atom_id`、`split`、`source_text`、模型、提示词、
Schema 与 run ID。模型永远不能自行返回或覆盖这些受控字段。

### 提示词与推理 Schema 的体积目标

当前 v2 文件的 UTF-8 体积为系统提示词 894 字节、推理 Schema 2378 字节；实际嵌入请求的紧凑化
推理 Schema 为 1900 字节。v2.2 的设计门不是“尽量短”，而是同时满足严格 JSON 验证和如下上限：

| 工件 | 当前 v2 | v2.2 设计上限 | 原因 |
| --- | ---: | ---: | --- |
| 系统提示词 | 894 字节 | 450 UTF-8 字节 | 只保留数组覆盖、短码表、原文子串和禁受控字段规则 |
| 序列化推理 Schema | 1900 字节 | 1000 UTF-8 字节 | 用短键、默认字段和枚举码替代长字段路径 |
| 输出上限 | 128 token/Atom | 96 token/Atom | 长键、`null` 和重复 predicate 包装不再由模型生成 |

最终 Cue Schema 不是压缩对象，也不能用短键替换。短码只存在于请求与内存解析阶段；其映射表必须进入
v2.2 协议哈希和 T4 独立 QA。

### 保守费用情景

冻结 Source 的 v2.2 实测预检仍得到 74160 个最多五条 Atom 的 package。完整序列化 Batch 请求的
输入字节代理上界为 `217655725`，最大请求行仅 `10943` UTF-8 字节；这不是服务端最终账单 Token，
正式计费仍以服务端 `response_usage` 为准。

| 路径 | 输入代理上界 | 输出上界 | 保守费用上界 |
| --- | ---: | ---: | ---: |
| 原始 v1：逐 Atom 实时请求 | 1779240532 | 189849088 | ¥507.7273768 |
| **拟采用 v2.2：Batch File、短码协议、96 token/Atom** | **217655725** | **35596704** | **¥36.0042541** |

实测预检代理相对原始 v1 约降 `92.9%`。费用使用北京 Batch File
输入 `¥0.1/M`、输出 `¥0.4/M` 的当前公开价格快照；Batch 仍只对成功请求计费。正式预算应向上
取整为 **¥36.01**，并在提交任何远端任务前以最新价格与实际 token usage 重新确认。

### 无 API 验收门与失败策略

在任何付费调用前，T2/T4 必须完成以下仅本地工作：

1. 新建独立的紧凑推理 Schema 与中文提示词；其短码表、最大长度、默认值和展开函数必须具备
   双向 synthetic 测试，且禁止额外字段。
2. 对当前 370799 条冻结 Source Atom 生成**只读** Batch 请求预检，核对 5 条/24000 字节门、75 个
   task 分组、`custom_id` 映射、文件 500 MB/50000 行限制、输入/输出上界与协议 SHA256。
3. 用 synthetic 的合法、未知码、少项、重复索引、长文本、跨 Atom 支撑、截断 JSON 和 96 token 边界
   响应验证：任何失败都不写 Cue，且不会转入自动付费重试。
4. T4 独立复算短码映射、默认回填、最终 Cue Schema、Source/split 血缘、Batch metadata 和无正文账本。
5. 全部无 API 测试通过后，用户才能选择是否批准一个有硬性费用上限的独立 smoke 验证；该 smoke
   不能计入正式 370799 条基准，也不能用来跳过完整覆盖。

### 执行授权与八波门

教师已同意按照 `1 + 6×10 + 14` 个 task 分八波运行。每波只在前一波本地接收校验、账本审阅和
预算复核通过后才允许提交。为避免聊天文本被误当成可审计授权，实际执行还必须在本机未提交的
`cues/CUE_EXECUTION_AUTHORIZATION.json` 填写并校验：批准人和时间、明确总预算、允许波次、冻结
Source/协议 SHA、远端文本保留至 T4 Cue QA 的同意，以及隔离项仅人工处置的同意。模板位于
`config/CUE_EXECUTION_AUTHORIZATION.example.json`，不含密钥且默认 `approved=false`。

冻结的执行核验仅计算波次 task 范围和费用代理，明确报告 `network_called=false`、
`credentials_read=false`、`formal_outputs_written=false`。真实上传、创建、轮询、结果接收和远端删除
已由标准库 HTTP 适配器及 fake HTTP 覆盖；适配器不将远端 `response`/`error` 写盘。当前适配器尚未
接入仍被阻断的 `--execute` 编排入口；接入前必须有用户再次明确下达的开始 API 指令、有效本机授权文件
及 `DASHSCOPE_API_KEY`。

生产时若 v2.2 成功请求在本地解析、短码映射或最终 QA 中失败，必须隔离该 package；禁止自动改回
128 token、禁止静默回退到 v2.1、禁止自动重发。任何此类处置均须新的用户授权和新的协议/预算决定。

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

### Batch File 传输成本推导

当前 v2 实时执行器只作为 Batch 方案的 package、验证、血缘和恢复实现基础，不再作为成本选项。
在当前 74160 个五条 package、128 token/Atom 的协议下，Batch File 的单次成功请求输入/输出上界分别为
311023165 字节代理和 47462272 token；按北京 Batch File 单价计算为 ¥50.0872253。这是 CR-2026-009
继续压缩短码协议与输出上限时的内部推导基准，不是保留的用户决策路径。

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

### 实时实现基础

v2 将相同覆盖和模型的请求数从 370799 降至 74160；它消除重复提示词、完整 Schema、受控字段和
原文回显造成的冗余，但仅作为 Batch 和紧凑协议的本地实现基础，不再作为可授权的生产路径。

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

### 历史实时执行注记

实时 v2 的 74160 package、742 shard、最大请求 12202 UTF-8 字节和 deterministic package 清单是
CR-2026-008/009 的实现输入。这些数值只证明五条分包的可重现性；实时价格、限流时长、自动重试和
生产授权均已由 Batch File 与 v2.2 紧凑协议设计接替，不得再作为当前预算或运行指令。

### 历史 v2 实现角色记录

| 步骤 | 负责人 | 工作 | 允许的产物 | 禁止事项 |
| --- | --- | --- | --- | --- |
| 0 | T0 | 审阅本 CR、冻结 v2 配置字段、提示词/推理 Schema 哈希和验收阈值 | 配置、合同测试、状态板 | API 调用、Cue 产物 |
| 1 | T2 | 实现 package 构建、受控字段回填、严格响应解析、恢复和确定性合并 | 脚本、提示词、无 API 测试、handoff | `--execute`、密钥读取、正式 JSONL |
| 2 | T4 | 为 v2 运行标记和最终 Cue 血缘补充独立 QA 测试；确认 Cue Schema 仍为 `v1.0.0` | 验证器、无 API 测试、handoff | 修改 T2 生产者输出 |
| 3 | T0 | 检查文件所有权、中文说明门禁、哈希边界、全量无 API 测试和预检成本 | 合并提交、状态更新 | 未获授权的生产运行 |
| 4--6 | 已由 CR-2026-008/009 接替 | Batch File、短码协议与新的无 API QA 门 | — | 不得按此历史表启动生产 |

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

当前唯一的实施指导是 CR-2026-009：T0 先冻结 v2.2，随后 T2/T4 只完成 Batch File 与紧凑推理协议
的无 API 实现、独立 QA 和冻结 Source 预检。完成前不得调用千问、上传 Batch 文件、创建远端任务或
写 Cue、SUCCESS、Seed 或 Life Log。
