# EgoPM-Bench v1

v1 是一个面向流式第一视角观察的、视频可追溯且文本优先的预算约束前瞻记忆基准。项目从冻结的数据合同开始；synthetic fixture 不属于数据集，v1 正式生产也不读取原始视频。

生产顺序见[完整生产指南](EgoPM_Bench_v1_完整生产流水线统筹指南.md)，唯一权威门禁状态见[协调状态板](egopm_bench_v1/coordination/STATUS.md)。

当前治理合同发布为 `v1.2.0`；配置合同与已冻结 Source Atom Schema 仍为 `v1.1.0`。正式阶段由 `AGENTS.md`、顶层 manifest、SUCCESS 标记和逐分片哈希共同控制。

## 正式产物布局

- Source 与 Cue 是大规模数据，权威形态允许采用“有序 manifest + 不相交分片 + 一个阶段级 SUCCESS”，不再要求物理合并为一个巨型 JSONL。
- 已冻结的 Source 单文件不因存储合同升级而重建。Cue 的 75 个 task 级分片将作为正式读取边界；实时 package 文件只保留为执行审计材料。
- Seed candidates、Frozen seeds 与 Life Log 规模较小，继续使用单一正式 JSONL。Decision/Evidence 在生成前根据实际规模另行冻结是否分片。
- 多终端只能写入预先分配且互不重叠的临时分区；只有协调器可以生成 manifest 和 SUCCESS。

Cue 正式快照已由 `realtime_v9_01` 冻结为 75 个 task 分片、294839 条 accepted Cue；权威入口是 `cues/cue_library_manifest.json` 与 `cues/CUE_LIBRARY_SUCCESS.json`，不是 `cue_library.jsonl` 缓存。Seed 正式生产仍被阻断，直到 T4 Cue QA 完成、固定 revision 的 `BGE-M3` 检索可用，并完成 `trigger_cue_id` 血缘与 lure 审计。

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
│  ├─ seeds\                    60 个候选提醒任务、审计结果、冻结任务
│  ├─ rules\                    状态机与提醒规则
│  ├─ lifelogs\                 生成的虚拟生活记录
│  ├─ benchmark\                最终模型评测输入、gold、证据集
│  ├─ audit\                    验证错误、人工审核、统计报告
│  ├─ logs\model_runs\          千问调用日志，不放 API Key
│  ├─ tests\                    自动测试
│  └─ coordination\             多对话交接、状态板、变更申请
├─ AGENTS.md                    所有对话都要遵守的协作规则
├─ pyproject.toml               Python 依赖与测试命令
└─ .gitignore                   不把密钥、大模型日志和大原始数据提交进 Git
