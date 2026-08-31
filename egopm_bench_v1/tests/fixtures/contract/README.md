# 合同 fixture

这些是为冻结的 v1.0.0 合同特意手写的最小有效示例。它们不是 P0/P1/smoke 数据，除单元测试外绝不可作为模型输入，也不含任何 EgoLife 源内容。

`test_contract_freeze.py` 会用对应的 Schema 验证每个 fixture。只有出现新字段且 T0 批准 `CHANGE_REQUEST` 后，各工作流负责人才能新增仅用于测试的 fixture。
