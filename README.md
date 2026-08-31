# EgoPM-Bench v1

v1 是一个面向流式第一视角观察的、视频可追溯且文本优先的预算约束前瞻记忆基准。项目从冻结的数据合同开始；synthetic fixture 不属于数据集，v1 正式生产也不读取原始视频。

生产顺序见[完整生产指南](EgoPM_Bench_v1_完整生产流水线统筹指南.md)，唯一权威门禁状态见[协调状态板](egopm_bench_v1/coordination/STATUS.md)。

当前合同发布为 `v1.0.0`。单元测试命令为 `python -m pytest -q`。正式阶段由 `AGENTS.md`、SUCCESS 标记和哈希共同控制。

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