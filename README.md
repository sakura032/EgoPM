# EgoPM-Bench v1

v1 是面向流式第一视角观察、视频可追溯且文本优先的前瞻记忆基准。正式数据只使用可回查的 Source 文本；synthetic fixture 仅用于测试，v1 不读取或复制原始视频。

当前开发主线是 Cue v2。第 05 步的默认入口只读取 Source 与 `candidate_atoms.jsonl`，其唯一默认配置在 `egopm_bench_v1/config/model_registry.yaml` 的 `cue_v2_extraction` 中，CLI 可显式覆盖。开发态不把 proof、manifest、SUCCESS 或哈希作为读门；真实 API 小样本、checkpoint/finalize 和下游 Seed 联调在相应阶段逐步加入。

本次路径切换和后续清理顺序见[代码整理与去治理优化执行方案](代码整理与去治理优化执行方案.md)。WSL 本地 BGE-M3 部署与传输说明见 [WSL BGE-M3 执行包](wsl_BGE-M3_filter/README.md)。

## 正式产物布局

- Cue v2 仅表达单个 Source Atom 可直接支持的观察。每个 predicate 为 1–3 个 `all_of` clause；每个 clause 必须保留连续 evidence span、直接支持的 value，以及能说明状态承载者、持有者或指向对象的 `anchor`。
- 当前日常输入是 BGE selection `bge_m3_source_select_v3_1_20260914_02` 中的 `candidate_atoms.jsonl`。proof、report 等只保留为可选 provenance；`sample_index` 在各 `sample_stratum` 内编号不是错误。
- `event_timestamp` 只定位或排序 Source 事件，不能直接变成未来提醒条件。constructed 内容仅从 Seed/Life Log 阶段出现并显式标记。
- Seed 的 trigger 与 lures 必须同 split，至少包含一个同 `source_group_id` 和一个跨 `source_group_id` 的 lure；每个 lure 都要记录未满足的 predicate clause。Life Log 的 paired 分支只改变一条 constructed 生命周期控制事件，gold 由确定性状态机生成。
- 旧 V9 realtime、75 分片、旧 manifest 与账本只作为隔离历史，当前 05/06/07 默认路径不会读取它们；在新 Cue 与 Seed 接口稳定并取得用户确认前，不归档也不删除。

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
