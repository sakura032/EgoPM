# EgoPM-Bench v1

v1 是一个面向流式第一视角观察的、视频可追溯且文本优先的预算约束前瞻记忆基准。项目从冻结的数据合同开始；synthetic fixture 不属于数据集，v1 正式生产也不读取原始视频。

生产顺序见[完整生产指南](EgoPM_Bench_v1_完整生产流水线统筹指南.md)，唯一权威门禁状态见[协调状态板](egopm_bench_v1/coordination/STATUS.md)。

当前合同发布为 `v1.0.0`。单元测试命令为 `python -m pytest -q`。正式阶段由 `AGENTS.md`、SUCCESS 标记和哈希共同控制。
