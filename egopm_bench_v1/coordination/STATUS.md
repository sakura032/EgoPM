# EgoPM-Bench v1 状态板

当前治理合同版本：**v1.5.0**（2026-09-15）。配置合同与已冻结 Source Atom Schema 为 `v1.1.0`；CR-2026-022 已冻结 Atom→Cue→Seed→Life Log 事实边界、Cue 三层语义门和统一 Life Log 骨架。优化版 WSL selection 快照已导入供检查，但尚未完成 T4 导入与人工精度复核；Cue v2 Schema、prompt、执行器和验证器仍未实施，当前不得启动正式 Cue API 或 Seed 生产。

`DONE` 表示 T0 已审阅产物并确认通过必需验证。状态只能是 `TODO`、`IN_PROGRESS`、`BLOCKED` 或 `DONE`。

| 门禁 | 负责人 | 状态 | 冻结产物/哈希 | 阻断项 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| 治理合同 v1.5.0 | T0 | IN_PROGRESS | CR-2026-021/022；工件节制门、事实边界、Cue 三层门、统一 Life Log 骨架 | Cue/Seed v2 Schema、配置、代码与测试尚未按新语义实施；既有旧执行测试基线仍需收敛 | 批次 B 先冻结 Cue v2 Schema/operator/错误码和 Life Log 参数，再做无 API 实现；代码与数据门仍为 BLOCKED |
| Source atoms | T1 | DONE | `SOURCE_ATOMS_SUCCESS.json`；`source_video_atoms.jsonl` SHA256 `be5f36b77970cb5147b88551c566f081589fe00fcf5ef912d8468a037e92960e`；370799 行 | 无 | Source 哈希已冻结，禁止重写；供 T4/T2 按 SUCCESS 门只读 |
| Source QA | T4 | DONE | 审计 `7ea18b8`；Source 阻断 0；答案/split 泄漏均为 0 | 无 | 作为 WSL BGE selection 与 Cue v2 的只读上游 |
| 旧 V9 Cue 审计快照 | T2/T4 | DONE | `realtime_v9_01`；75 个 task 分片；294839 条；manifest/SUCCESS SHA256 `a7ccd99e629d185911084bb654f79ca6891711b7874cd950c07b0bc7972fdf75` | 旧结构 QA 为 0 blocker，但存在系统性内容语义问题 | 永久只作审计；不覆盖、不混入、不作为 Seed 输入 |
| BGE candidate selection v3.1 | T2/WSL | BLOCKED | 优化版 10,000 条候选及五文件快照已导入供检查；候选唯一且可回查 Source | T4 proof 导入复核、人工精度抽样与正式路径/身份收敛尚未完成 | 只读完成 T4 离散复核和 350 条设计校准；不得把 WSL SUCCESS 直接视为 Cue 启动门 |
| Cue v2 library | T2 | BLOCKED | CR-2026-018/019/020/022 方向已冻结 | Cue Schema v2、1–3 clause、三层 validator、prompt、三账号执行器和协议验收尚未实现 | 先完成 350 条人工设计校准、800–1,000 条协议验收和无 API 测试，再另行取得 API 授权 |
| Seed candidates | T2 | BLOCKED | 目标 900–1,400；旧 CR-017 实现不得直接生产 | 依赖 Cue v2 SUCCESS、分布报告和 T4 Cue v2 QA；Seed Schema/布局/模型需更新 | Cue v2 完成后生成候选，至少 576 个通过机器门才可停止扩充 |
| Seed audit | T0/T4 | BLOCKED | — | candidate 标记 + 人工审计 | 审核候选 |
| Frozen seeds | T3 | BLOCKED | 目标 480 | 审计冻结 + T4 seed QA | 全部人工终审；不足 480 时扩大候选池，不降低标准 |
| Protocol parameters v1 | T0 | BLOCKED | — | 研究协议要求先有完整 source/seed 统计 | 冻结预算、冷却与重复提醒策略 |
| Families/oracle | T3 | BLOCKED | 预计 2,880 条 Life Log | `SEEDS_FROZEN_SUCCESS` 哈希 + seed QA + 协议参数 + Life Log 布局 CR | 编译六路 family 与 oracle gold |
| Final QA | T4 | BLOCKED | — | `DECISIONS_SUCCESS` 哈希 | 验证全部正式产物 |
| Release | T0 | BLOCKED | — | `FINAL_VALIDATION_SUCCESS` 哈希 | 审阅并发布 manifest |

## 2026-09-15 Cue/Seed v2 当前决议

- 八波实时 Cue 执行已经结束，370799 个 Source Atom 均有旧协议 disposition；其文件、费用和账本永久保留。由于内容审计发现 `cue_type` 塌缩、字符串 `null`、槽位错置和冗余字段空置，旧 V9 Cue 撤销 Seed 上游资格。不得删除、覆盖、修复、重发或混入 Cue v2。
- Cue v2 不再全量处理所有 Atom：当前冻结 selection 由 WSL2 单 GPU 的固定 BGE-M3 先产生 10,000 条核心候选，再按稀有簇和新颖度补样至 10,000–12,000 条；随后由 Flash 生成约 3,000–5,000 条高质量 accepted Cue。BGE 说明见 `wsl_BGE-M3_filter/`，总计划见 `coordination/CUE_SEED_V2_PLAN.md`。
- BGE 根请求不含自身 SHA；它直接绑定模型配置、48 行查询集、选择策略、Source 行 Schema 和统一 artifact Schema。六查询族不设配额；单 Atom 只编码一个冻结 passage；全维向量用于检索/距离，256 维投影与 65,536 条确定性样本用于 MiniBatchKMeans；近重复静态全序、CP-SAT 精确联合求解、弹性终止和全部 tie-break 已冻结。正式候选行只含 `atom_id`，Windows 接收含精简 proof 的五文件逻辑快照。
- `visible_text` 只做 Source 派生一致性校验，不进入 BGE passage 或候选。`event_timestamp` 只用于 Source 定位和事件顺序，未来 `temporal_condition` 仅在 Seed/Rule 阶段由模板构造并人工审计。
- Cue v2 正式行只保留 `cue_id`、`atom_id` 和 clause-level predicate/evidence，只允许 `all_of`；删除顶层 `cue_type`、`confidence` 和可派生冗余字段。ambiguous 必须闭环，正式分片只含 accepted Cue。
- 一个 Atom 最多一条 Cue；每条 Cue 只含一个 predicate 和 1–3 个 clause。Cue 可以是不完整句法的简短观察条件，但必须有可识别指向对象。每个 clause 依次通过字段内连续 span、value 直接支持和完整 `dimension/operator/value` 语义支持三层门。
- 三层门必须显式检查人物在场/说话/被提及、主客体、否定、范围、条件/假设和时间语气；物体不得反推地点，视频时间戳不得变成显式时间 Cue。规则无法判断的第三层问题进入人工审计，不以另一模型意见自动放行。
- 三个阿里云账号在同一 Cue 阶段必须使用相同 `qwen3.7-flash` 模型、prompt、Schema 和参数，并处理静态不重叠 partition。每个 worker 独立授权、预算、账本、租约和 staging；协调器只读聚合，任何共享追加或重复 request ID 均为 blocker。
- 大规模 Cue 调用前先做 800–1,000 个 Atom 的独立协议验收，其中至少 120 个重叠 Atom 由三个账号分别处理；验收集永不进入正式数据。
- BGE proof 的 350 条 audit sample 先用于人工设计校准，不能代替最终验收集；最终验收先跑约 500 条子波次，正式生产再以约 1,500 条为首个 checkpoint。单项最多一次简化修复，强模型仅处理歧义、抽样和拟进入 Seed 的 trigger Cue。
- Seed candidates 目标为 900–1,400，最终冻结 480 个 Seed，预计派生 2,880 条 Life Log。候选不足时扩大池，不降低 trigger/lure、同组/跨组、split、失败 clause、生命周期或反事实标准。
- 每条 Life Log 固定包含一个目标意图创建、一个 constructed 生命周期控制、同一个 trigger 和两条 lure；同一 family 的正负分支共享所有 Source 观察，只改变生命周期控制状态。目标相关 Source 观察数恒为 3，核心负分支限于 completed/cancelled/expired/already_reminded，`never_created` 不混入统一六路数据。
- 阶段内只允许一个固定生产模型，阶段间允许不同中国厂商模型。DeepSeek 只少量用于独立审计或争议第三意见；Seed 和 Life Log 的模型在各自执行前另行冻结。
- BGE selection、Cue v2、Seed candidates、Seed audit 和 Life Log 的分布报告统一写入 `audit/distributions/<stage>/<snapshot_id>/`，并由对应阶段 SUCCESS 绑定 `distribution_manifest_sha256`。

## T0 历史审阅记录

以下各条按发生时间保留，仅用于追溯当时状态；若与上方状态表或“2026-09-09 当前决议”冲突，以当前决议为准。

- Wave 0 合同冻结提交为 `487fa9a`。`raw/` 中有 808 个 SRT 文件并已被忽略；没有源媒体或源数据加入 Git。
- 本合同冻结数据形状、路径语义、文件所有权、SUCCESS 标记语义、来源 split 策略、模型登记表和评测协议结构。
- 数值型记忆预算与重复提醒参数刻意保持待定。这符合研究规范，并阻断所有正式 oracle 输出。
- 全部 Markdown 正文必须中文撰写；字段名、命令、路径和不可翻译专名除外。T0 将以此作为合并硬门禁。
- CR-2026-001 已将 Python 中文模块说明与关键中文注释提升为治理合同 v1.1.0 的合并硬门禁；数据 Schema 与配置合同未变，故不要求重生成数据。
- Wave 1 已按 `T1 → T4 → T2 → T3` 审阅并合并到 `main`：T1 为 `4d3b5b6`，T4 为 `174fa32`，T2 为 `7d99aaf`，T3 为 `abc0424`。所有改动均在各自文件所有权范围内；未合并 `.codex/`、原始语料、媒体或正式数据产物。
- Wave 1 合并后以仓库内已忽略的 pytest 临时目录执行 `python -m pytest -q --basetemp .pytest_cache/wave1`，结果为 `25 passed in 0.82s`；`git diff --check` 通过。测试仅使用 synthetic fixture，未运行正式 SRT 建库、未调用千问、未生成 Life Log。
- `CR-2026-002`、`CR-2026-003` 与 `CR-2026-004` 已由 T0 批准并落实为配置合同与 Source Atom Schema `v1.1.0`：对齐容差固定为 `2.0` 秒，v1 禁止合并窗口，草稿与最终原子使用独立工件/Schema，跨 session 去重比较同一人同一天的全部 session 对。`CR-2026-005` 仍阻断正式 trigger/lure 与 Seed candidates；`CR-2026-006` 仍阻断最终反事实与 Evidence Set 的完整可审计发布。
- 本次合同升级后以 synthetic fixture 执行 `python -m pytest -q --basetemp .pytest_cache/contract-v11`，结果为 `27 passed in 0.81s`；`git diff --check` 通过。未运行正式 01–04，未调用千问，未生成 Life Log。
- T1 已在主项目 `main` 正式运行 01–04，仅读取 808 个 EgoLife SRT（Transcript 402、Dense Caption 406），未读取、下载、复制、拼接或处理 MP4。正式 Source 产物提交为 `ada03ec`；近重复精确索引修复为 `f730cdf`。最终原子为 370799 行，冻结 SHA256 为 `be5f36b77970cb5147b88551c566f081589fe00fcf5ef912d8468a037e92960e`。
- T4 已以 `4c81eec` 将 Source QA 对齐 v1.1 的 Dense Caption 主时间窗口与全 session 精确近重复规则，并在 `7ea18b8` 写入新的只读审计。T0 已独立复算 SUCCESS 原子哈希与行数，结果一致；Source blocker 为 0，`answer_leakage_count` 与 `split_leakage_count` 均为 0。审计中的 5 个 blocker 都仅表示 Cue、candidate、frozen、lifelog、decisions 尚未生成，不归责 Source。
- 第 05 步最初的单 Atom v1 无 API 启动修复及其 `39 passed` 回归保留为成本对照历史；它不再是允许生产的请求协议。T4 的阶段化 Schema 版本校验为 `d2a1c67`；最初的 T2 显式执行守卫与恢复基础为 `310195f`、`9d44f46`、`a437c02`。全过程未调用千问、未读取密钥、未写 Cue library 或 SUCCESS。
- 当前唯一允许的 Cue 执行配置为 v2：每逻辑 shard `500` Atom，每 package 最多 `5` 条且 `max_tokens=128 × package Atom 数`，最多重试 `2` 次，目标为 `300 RPM` 与 `1000000 TPM`；逐请求只记录服务端 `response_usage` 与无正文账本，禁止保存原始模型响应。
- `CR-2026-007` 的 v2 无 API 实施已由 T0 审阅完成：T0 协议冻结为 `4f9b990`、`673ebf2`、`88efa16`；T2 执行器/账本/恢复与路径门为 `6628eb0`、`22862d3`；T4 阶段 Schema 与完整协议血缘 QA 为 `da38f78`、`d67aab7`。T2/T4 交接整理分别为 `2a4f4e9`、`b3e8716`。全仓无 API 测试由 T0 复跑为 `41 passed in 1.34s`，且 `git diff --check` 通过。
- T0 于 `2026-09-01` 对冻结的 370799 条 Source Atom 实际运行默认只读 v2 预检：74160 个 package、742 个逻辑 shard、最大请求 12202 UTF-8 字节、输入上界 311023165 UTF-8 字节、输出上界 47462272 token；未读密钥、未联网、未写正式 Cue/SUCCESS。按冻结价格的单次保守上界为 `¥100.1744506`，三次尝试全耗尽为 `¥300.5233518`；以 `1000000 TPM` 的保守预留口径，时长下界为约 5.98 小时（RPM 下界为 4.12 小时）。
- Cue 门仍为 `BLOCKED`，唯一阻断是用户尚未明确确认总预算、执行范围、运行时间窗和失败 package 重跑范围。确认前不得使用 `--execute`、调用千问、写 `cues/cue_library.jsonl` 或 `cues/CUE_LIBRARY_SUCCESS.json`，也不得启动 Seed 或 Life Log。
- `CR-2026-008` 已登记为 v2.1 Batch File 的无 API 设计与核算：仍固定同一模型、370799 条 Source 覆盖和最多五条 package；按北京 Batch File 半价规则，单次成功请求保守上界为 `¥50.0872253`。该方案引入远端输入/结果/错误文件保留边界，因此当前只更新文档，未冻结配置、未写代码、未创建 Batch task 或上传任何文件。
- `CR-2026-009` 已登记为 v2.2 紧凑推理协议与 96 token/Atom 的无 API 设计：短键/枚举码只存在于模型推理对象，程序仍回填既有最终 Cue Schema。按输入提示词/Schema 体积门与 96 token 输出门的保守设计代理，Batch File 上界为 `¥35.3738941`；这不是实测 token 或生产预算，当前未创建 Schema、代码、Batch 文件或远端任务。
- `CR-2026-009` 的无 API 实施现已由 T0 审阅完成：协议/短码 Schema 为 `21e01f6`，任务清单与账本终态冻结为 `738b7d9`、`b851583`；T2 生产者为 `c9cc106`、`a47b409`，合同对齐及流式预检修复为 `9378f6c` 与本次审阅提交；T4 独立 QA 为 `28461b7`、`0c47001`。全仓 synthetic 测试为 `46 passed in 2.06s`。冻结 Source 的流式只读预检为 74160 package、742 shard、75 task，最大行 `10943` UTF-8 字节，输入字节代理 `217655725`、输出上界 `35596704` token，按冻结 Batch 价格单次成功请求上界 `¥36.0042541`（输入 `¥21.7655725`、输出 `¥14.2386816`）。预检未读密钥、未联网、未写 Cue/SUCCESS；仅临时报告在 pytest 目录中生成。
- 教师已同意采用八波方案：`1 + 6×10 + 14 = 75` task。T0 已冻结授权文件版本、波次数量、每波最多一个提交中 task、轮询退避、每波 `0` 个本地验证隔离项上限及 T4 QA 后远端清理门；授权文件必须为本机未提交的 `cues/CUE_EXECUTION_AUTHORIZATION.json`，同时绑定 Source SHA、协议 SHA、预算、波次和数据保留/隔离同意。当前模板刻意为未批准状态，不读取密钥或联网。
- Batch File 适配器已具备上传临时输入、创建任务、读取状态、流式读取结果/错误 JSONL 与删除远端文件的最小 HTTP 操作，并以 fake HTTP 完成无网络测试；异常只保留 HTTP 状态与无正文摘要。当前 `--execute` 已接入授权波次提交入口，但结果接收与最终 Cue QA 仍未完成。
- 2026-09-05：用户在 `.venv` 中自行提交第 1 波 API，task `0` 共 `1000` 请求，返回 `batch_id` `batch_1d50a9e3-733f-4baf-b754-bc1344d00f73` 与输入文件 SHA256 `020ff3ead5741011b15a547b9067700d2273beab6d87227398910033853c0617`；本地仅保存无正文执行状态，远端清理状态为 `pending_t4_cue_qa`。尚未下载结果、生成 Cue 或写入 SUCCESS。
- 2026-09-05：用户查询该 Batch 的错误明细，20 条服务端校验错误均为 `model_not_found`，指出 `qwen3.7-flash-2026-07-15` 不受 Batch API 支持；`request_counts.total=0`，判定未发生推理调用且旧任务不得重试。T0 以 `CR-2026-010` 将 Batch 模型标识修正为基础别名 `qwen3.7-flash`，升级登记/执行协议版本；Source 覆盖、Batch 价格、八波计划和预算上限不变。新协议授权绑定与 Wave 1 重提须由用户明确确认。
- 2026-09-05：T2 已实现接收入口 `--receive`：它必须持有独立 `confirmation=RECEIVE_BATCH_RESULTS_API`、本机授权和运行时环境变量，接收前重建冻结 task 并校验 Source/协议/输入哈希及 `custom_id` 双向映射；远端 JSONL 仅流式读取，落盘仅为已验证 Cue 片段、无正文 ledger、结果行 SHA256 和收据。本地验证失败一律 quarantine，禁止自动重发。T4 已实现 receipt/ledger 的独立 QA；T0 在 `.venv` 复跑全仓无 API 测试为 `52 passed`。无 API 实现提交为 `8688bfa`，T4 QA 提交为 `5f18cb6`、`31b071c`。仍未读取密钥、联网、重提任务、写 Cue library 或 SUCCESS。
- 2026-09-05：用户确认取消 `batch_1cd32927-4c33-43f6-8d8e-f4bb0e17d01f`，决定不再使用 Batch File，改为实时 API。T0 已登记 `CR-2026-011`，旧 Batch 任何结果均不得读取或混入。T2 实时执行器提交为 `5c33980`、`7a070fe`；T4 实时 QA 与 T0 合同更新待本次审阅提交。正式 Source v3 预检得到 370799 Atom、74160 package、742 shard、输入代理 `55480053`、输出上界 `35596704`、单次上界 `¥39.5733738`，未读密钥、未联网、未写 Cue/SUCCESS。v3 协议 SHA 为 `42d3ab6a028a0c625c3642f0bca442f727a4087bd52b9632d1cfe41d41e11427`；现有 v2.2.1 授权不可复用，需用户重新授权预算与重试范围。
- 2026-09-05：用户首次实时运行在旧协议下收到 HTTP `400`；183 个 package 均为未计费的服务端提交失败，账本 `spent_cny=0.00`，另有一个 package 因 Windows `WinError 5` 留下未完成状态与 `.tmp`。这些旧运行工件仅保留作审计，不能重发、不能混入新 run。
- 2026-09-05：T0 将 `CR-2026-011` 的实时执行补齐为原八波计划的等价传输实现：固定 `1 + 6×10 + 14` task、每 task 10 个逻辑 shard，单波仅调度其冻结 task/shard 范围；波内最多 10 个在飞 package，RPM/TPM、每 package 最多 2 次重试、五条 Atom 上限和 96 token/Atom 上限不变。每 15 秒及每包终态原子写入无正文 `progress.json`；每波使用 `cues/realtime/wave_XX`，根目录累计账本确保 `¥80` 为跨八波累计预算。Wave N 在读取密钥前必须确认所有前序波同一 run/Source/协议且全部成功、零在飞、零隔离、零服务失败、零预算停止。T4 最终 QA 还要求八波全齐、task `0..74` 完整且不重叠、各波进度合法、根级累计账本与八波账本并集一致，才允许 `CUE_LIBRARY_SUCCESS.json`。
- 本次协议变化后的 SHA 为 `0d2e020d3e763c2934d69994e0ac78cc951a1d5cc22e0b698113d4f56003a8cc`，因此旧本机授权文件的协议绑定失效；用户须在再次 API 启动前以该值重新确认授权。T0 在 `.venv` 完整复跑无 API 测试：`48 passed in 5.73s`，`git diff --check` 通过；未读取密钥、未联网、未写正式 Cue 或 SUCCESS。
- 2026-09-05：新 Wave 1 `realtime_v4_01` 的首批十个并发实时请求均在服务端参数校验阶段以 HTTP `400` / `invalid_parameter_error` 拒绝；诊断指向 `response_format.json_schema.schema` 中不被该服务支持的 `uniqueItems`，累计 `spent_cny=0.00`，未生成 Cue。T0 删除该模型端关键字，并在本地展开逻辑恢复实体数组的等价去重检查；最终 Cue Schema 不变。无 API 全量测试为 `49 passed in 5.54s`。协议 SHA 更新为 `c1651d7cfa5e19c6cd70728b67005319f6427149ec348e802272fcf14771ae59`；旧 `realtime_v4_01` 与旧授权均只能审计，下一次尝试必须使用新 run ID 并重新绑定授权。
- 2026-09-05：为避免 Wave 1 启动时将全量 370799 Atom 驻留内存，实时执行器改为按冻结波次流式 materialize。Wave 1 只验证并保留 shard `0..9` 的 5000 Atom，越过边界立即停止读取；每完成一个 shard 写入并打印无正文 `preparing_source` 进度。T0 以冻结正式 Source 离线核验得到 5000 Atom、1000 package、shard `0..9`，授权与 SHA 一致；未读密钥、未联网、未写 Cue/SUCCESS。全仓无 API 测试为 `50 passed in 5.83s`；用户已确认本机 `¥80` 八波累计授权绑定当前协议 SHA。
- 2026-09-05：`realtime_v5_01` 与 `realtime_v6_01` 的无正文账本分别出现 `5/10`、`4/10` 个本地隔离项；安全分类均为 `PREDICATE_CUE_TYPE_MISMATCH`，累计实耗约 `¥0.0067032`。未读取或保存任何模型正文。T2 将安全分类码和 JSON 指针写入无正文账本；T0 确认根因是模型同时回传冗余的 `t` 与 `p`，两者存在可避免的不一致。
- 2026-09-05：实时协议升级为 `v3.3.0`：模型仅生成 `n,p,x,c,v,e,s,a,r`，禁止回传 `t`；程序从 `p[0][0]` 确定最终 `cue_type`，并继续进行严格 Schema、原文子串、血缘和最终 Cue Schema 校验。最终 Cue Schema、Source 覆盖和五 Atom package 上限均未改变。完整无 API 回归与授权绑定核验通过后，才允许使用新的 run ID `realtime_v7_01` 启动 Wave 1。
