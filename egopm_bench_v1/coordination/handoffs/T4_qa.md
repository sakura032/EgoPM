# T4 Wave 1 独立 QA 交接

## 交接元数据

- 分支 / 提交：`HEAD (no branch)` / `待本次 T4 Wave 1 提交后回填`。
- 治理合同版本：`v1.1.0`；数据合同版本：`v1.0.0`。
- 治理合同遵守：本 worktree 未自行合并 T0 的治理合同变更；所有 T4 Python 文件均补有中文模块说明（职责、输入、输出、流水线位置），并为 SUCCESS/哈希门、时间对齐、过滤、状态转移、反事实、答案泄露和异常处理写明“为什么”的中文注释。
- 本次修改：`scripts/11_validate_all.py`、`scripts/12_build_statistics.py`、`tests/test_validators.py`、`audit/validation_errors.jsonl`、`audit/leakage_report.json` 和本文件。
- 只读上游输入哈希：无。所有正式上游 `SUCCESS` 标记均不存在，T4 未读取任何生产 JSONL。
- QA 输出：`audit/validation_errors.jsonl`，6 行，SHA256 为 `ad732cfaf84b98d2f61a7630a3b1c58b63d7807ec2c474ff98feb2a53f92b72a`；未生成 `FINAL_VALIDATION_SUCCESS.json`。

## Python 文件中文说明与关键注释验收

| 文件 | 中文模块说明验收 | 关键中文注释验收 | 结论 |
| --- | --- | --- | --- |
| `scripts/11_validate_all.py` | 已说明职责、输入、输出和第 11 步流水线位置 | 已覆盖原子写入、SUCCESS/哈希和上游谱系门、JSONL 空行、SRT 时间边界、近重复过滤、状态承接、来源顺序、oracle 重算、答案泄露、反事实翻转、过期最终标记与阶段读取边界 | 通过 |
| `scripts/12_build_statistics.py` | 已说明职责、输入、输出和第 12 步流水线位置 | 已覆盖虚拟时长语义、完整配对分母、唯一来源时长、阻断时不写半成品统计及异常处理原因 | 通过 |
| `tests/test_validators.py` | 已说明职责、临时输入、pytest 输出和 Wave 1 流水线位置 | 测试名称与故意破坏数据说明均为中文，说明其不形成正式产物 | 通过 |

## 已完成工作

- 实现了 SUCCESS 标记、合同/配置版本、schema 版本、时间戳、上游哈希字段、产物 SHA256 和行数的前置门；未通过前不会读取对应正式 JSONL。
- 实现了 schema、SRT 路径与时间、来源可追溯、状态迁移、oracle、反事实动作翻转、难度、split、近重复、答案泄露、三种时长和统计检查。
- 统计器仅在全量 QA 零阻断时写入 `audit/final_statistics.json` 与 `benchmark/dataset_card.md`，并使用原子替换。
- 增加了篡改哈希与上游哈希、schema、来源时间 / split 近重复、状态迁移 / 时长、反事实动作翻转、答案泄露、缺少 SUCCESS 标记等合成单元测试。

## 当前阻断与退回

运行 `python egopm_bench_v1/scripts/11_validate_all.py --config egopm_bench_v1/config/benchmark_protocol.yaml` 得到 6 个阻断错误。

| 严重度 | 失败 ID | 预期 | 实际 | 建议修复阶段 |
| --- | --- | --- | --- | --- |
| `BLOCKER` | `source` | 存在 `SOURCE_ATOMS_SUCCESS.json` | 标记不存在 | T1 source |
| `BLOCKER` | `cue` | source SUCCESS/哈希已通过 | 上游未就绪 | T2 cue（等待 T1/T4 source QA） |
| `BLOCKER` | `candidate` | source、cue 均已就绪 | 上游未就绪 | T2 seed |
| `BLOCKER` | `frozen` | source、candidate 均已就绪 | 上游未就绪 | T3 compiler |
| `BLOCKER` | `lifelog` | source、frozen 均已就绪 | 上游未就绪 | T3 compiler |
| `BLOCKER` | `decisions` | source、frozen、lifelog 均已就绪 | 上游未就绪 | T3 compiler |

这些问题也已逐条写入 `audit/validation_errors.jsonl`，每条均包含严重度、复现命令、失败 ID、预期、实际和唯一建议修复阶段。

## CHANGE_REQUEST 建议

状态：待 T0 登记和决定；T4 未自行修改 `config/**`、`schemas/**` 或任何生产 JSONL。

### CR-T4-20260831-001

- 提出者 / handoff：T4 / `coordination/handoffs/T4_qa.md`。
- 当前治理合同版本：`v1.1.0`；当前数据合同版本：`v1.0.0`。
- 受影响字段与产物：`lifelogs/counterfactual_pairs.jsonl`、`benchmark/evidence_sets.jsonl`、它们的 JSON Schema、SUCCESS 标记和 SUCCESS 标记中可验证的产物哈希范围。
- 现有合同无法表达该需求的原因：两个路径虽已列入配置，却没有对应 JSON Schema，也没有独立 SUCCESS/哈希边界。T4 因而不能在“不读取未冻结产物”的规则下安全读取它们，更无法机械验证反事实 pair 的两侧 log、声明的唯一历史差异，以及 Evidence Set 与 decision 的一一对应关系。
- 兼容性影响：目前 `decision_instances.jsonl` 内可验证同一当前 atom、正分支 `remind`、负分支 `silent`；但“每对仅改变声明的一个历史条件”和独立 Evidence Set 完整性不可审计。若保持现状，最终验收会缺少该两项可追溯证据。
- 建议的兼容修改或迁移方式：由 T0 定义可哈希 manifest，或分别增加 schema 与 SUCCESS 标记。反事实记录至少应有 `counterfactual_pair_id`、`positive_lifelog_id`、`negative_lifelog_id`、唯一历史差异声明；Evidence Set 至少应有 `decision_id` 与规范化证据组。SUCCESS 需将相应正式文件哈希纳入其声明范围。
- 必须重新生成的上游/下游产物：受影响的 `counterfactual_pairs.jsonl`、`evidence_sets.jsonl`；若字段或语义变更，重生全部对应 Life Log、Decision Instance、audit、统计与数据集卡。
- 证明该问题的测试：在完整上游 SUCCESS 可用后运行 `python egopm_bench_v1/scripts/11_validate_all.py --config egopm_bench_v1/config/benchmark_protocol.yaml`；验证器会对不可表达的唯一历史差异记录 `contract_counterfactual_delta_unverifiable` 警告，待 T0 决定后升级为可验证规则。
- 当前处理：保留已有动作翻转检查；不自行新增字段、不读取这两个未哈希产物。

## 测试结果

```powershell
python -m pytest -q
# 结果：9 passed in 0.38s

python egopm_bench_v1/scripts/11_validate_all.py --config egopm_bench_v1/config/benchmark_protocol.yaml
# 结果：6 个预期门禁阻断；未生成最终成功标记

python egopm_bench_v1/scripts/12_build_statistics.py --config egopm_bench_v1/config/benchmark_protocol.yaml
# 结果：blocked；未生成统计或数据集卡
```

## 下一门

不能启动正式 Cue 生产。T1 先生成并冻结 `SOURCE_ATOMS_SUCCESS.json`，随后 T4 应运行 source QA；只有零阻断且 T0 将 Source QA 提升为 `DONE` 后，T2 才可正式启动 Cue 阶段。
