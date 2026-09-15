# EgoPM-Bench v1

v1 是一个面向流式第一视角观察的、视频可追溯且文本优先的预算约束前瞻记忆基准。项目从冻结的数据合同开始；synthetic fixture 不属于数据集，v1 正式生产也不读取原始视频。

生产顺序见[完整生产指南](EgoPM_Bench_v1_完整生产流水线统筹指南.md)，唯一权威门禁状态见[协调状态板](egopm_bench_v1/coordination/STATUS.md)。

当前治理合同版本为 `v1.5.0`；配置合同与已冻结 Source Atom Schema 仍为 `v1.1.0`。CR-2026-021 已启动 Cue v2 主线切换批次 A并冻结全仓工件节制，CR-2026-022 进一步冻结全流程事实/构造边界、Cue 三层语义门和统一 Life Log 骨架。Cue/Seed v2 的 Schema、配置和执行代码尚未实施。

Cue/Seed v2 的唯一详细计划见 [Cue/Seed v2 生产计划](egopm_bench_v1/coordination/CUE_SEED_V2_PLAN.md)。WSL 本地 BGE-M3 部署与传输说明见 [WSL BGE-M3 执行包](wsl_BGE-M3_filter/README.md)。

## 正式产物布局

- Source 与 Cue 是大规模数据，权威形态允许采用“有序 manifest + 不相交分片 + 一个阶段级 SUCCESS”，不再要求物理合并为一个巨型 JSONL。
- 已冻结的 Source 单文件不因存储合同升级而重建。旧 V9 Cue 的 75 个 task 分片只保留为不可变审计材料，不再是 Seed 上游。
- 当前 Cue v2 从 WSL BGE-M3 selection v3.1 的 10,000 条核心候选开始，再按稀有语义簇与新颖度确定性补样，最终为 10,000–12,000 条；计划形成约 3,000–5,000 条高质量 accepted Cue。正式 Cue 形态为 `cues/v2/formal/` 分片、一个 manifest 和一个 SUCCESS，不要求物理合并。
- 一个 Atom 最多产生一条 Cue；一条 Cue 只含一个 predicate 和 1–3 个 `all_of` clause。每个 clause 必须依次通过同字段连续原文 span、value 直接支持以及 `dimension + operator + value` 完整语义支持三层门；Cue 可以是简短条件，但必须有可识别的指向对象。
- BGE 查询族固定为 `Person / Location / Object / Activity / State / Explicit-Time`，只用于召回和报告且不设类别配额；`visible_text` 不重复编码。Windows 回传包含精简 `selection_proof.jsonl`，使 T4 无需重跑 BGE 即可复核 rank、RRF、归因和离散选择门。
- Source 的视频时间位置与未来提醒条件严格分离：`event_timestamp` 只用于定位和顺序，`temporal_condition` 只在 Seed/Rule 阶段由冻结模板构造并人工审计。
- WSL 包只携带两个必要 Schema：一个与 Windows 同 SHA 的 Source v1.1.0 行 Schema，以及一个统一覆盖候选、proof、report、manifest、SUCCESS 的 artifact Schema；单 Atom 只形成一个 transcript+dense caption passage，联合约束由单 worker CP-SAT 求解且只接受经重复性检查的 `OPTIMAL` 结果。
- Seed candidates 目标为 900–1,400，最终冻结 480 个独立 Seed，并派生 2,880 条 Life Log。其正式布局在实现前按实际字节数冻结。
- 每条 Life Log 的目标结构固定为一个意图创建、一个 constructed 生命周期控制、同一个 trigger 与两条 lure；同一 family 的正负分支共享全部 Source 观察，只改变生命周期控制状态，目标相关 Source 观察数恒为 3。模型输入不暴露 trigger/lure、状态或 gold。
- 三个阿里云账号可使用同一个 `qwen3.7-flash` 协议并行写入三个静态分区；每个 worker 必须拥有独立授权、预算、账本和 staging，只有协调器可以生成累计账本、manifest 和 SUCCESS。
- Cue、Seed 和 Life Log 的机器分布报告统一写入 `egopm_bench_v1/audit/distributions/<stage>/<snapshot_id>/`，并由对应阶段 SUCCESS 绑定报告 manifest SHA。

旧 Cue 快照 `realtime_v9_01` 包含 75 个 task 分片和 294,839 条当时合同下的 accepted Cue；其结构/血缘 QA 曾为 0 blocker，但后续语义审计发现 `cue_type` 塌缩、字符串 `"null"`、槽位错置和冗余字段空置。该快照不得删除或覆盖，也不得继续作为正式 Seed 输入。当前 Seed 生产保持 `BLOCKED`，直到 Cue v2、WSL BGE-M3 selection、语义门和新 SUCCESS 全部完成。

项目目录

D:\scientific\EgoPM\
├─ Egolife\raw\                 原始 EgoLife SRT，只读，不修改
├─ egopm_bench_v1\
│  ├─ config\                   全项目统一规则
│  ├─ schemas\                  每类 JSON 必须有哪些字段
│  ├─ prompts\                  千问的固定提示词
│  ├─ scripts\                  12 个按顺序运行的脚本
│  ├─ source\                   SRT 解析后的真实视频原子
│  ├─ cues\                     从原子中抽取的触发线索
│  ├─ seeds\                    900–1,400 个候选提醒任务、审计结果、480 个冻结任务
│  ├─ rules\                    状态机与提醒规则
│  ├─ lifelogs\                 生成的虚拟生活记录
│  ├─ benchmark\                最终模型评测输入、gold、证据集
│  ├─ audit\                    验证错误、人工审核、统计报告
│  ├─ logs\model_runs\          千问调用日志，不放 API Key
│  ├─ tests\                    自动测试
│  └─ coordination\             多对话交接、状态板、变更申请
├─ AGENTS.md                    所有对话都要遵守的协作规则
├─ wsl_BGE-M3_filter\           可复制到 WSL 的 BGE-M3 部署、运行与传输说明
├─ pyproject.toml               Python 依赖与测试命令
└─ .gitignore                   不把密钥、大模型日志和大原始数据提交进 Git
