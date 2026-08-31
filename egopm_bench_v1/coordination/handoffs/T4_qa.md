# T4 Wave 1 独立 QA 交接

## 第 05 步无 API 启动修复：阶段冻结 Schema 版本

- 适用提交：本段随本次 T4 提交写入；未运行正式 Cue、Seed 或完整生产 QA，未调用千问。
- 修复范围：`scripts/11_validate_all.py` 将 SUCCESS 校验从“所有 Schema 版本必须等于全局 `CONTRACT_VERSION`”改为显式 `STAGE_ARTIFACT_VERSIONS`。它分别冻结 Source 的 `source_video_atom` 与 `source_video_atom_draft` 为 `v1.1.0`，Cue 的 `cue_candidate` 为 `v1.0.0`，candidate/frozen 的 `reminder_seed` 为 `v1.0.0`，lifelog 的 `lifelog` 为 `v1.0.0`，decisions 的 `decision_instance` 为 `v1.0.0`；伴随正式产物的 `state_machine_policy`、`reminder_seed`、`lifelog` 声明也逐项保留校验。
- SUCCESS 版本边界：每个阶段同时固定自己的 `contract_version` 和 `config_version`。因此未来执行配置升级不会追溯否定已冻结的 Source `v1.1.0` 标记；每个下游新阶段须由 T0 在其正式启动前确认并更新对应冻结表，不能以全局版本猜测。
- 合成测试：新增 Source `v1.1.0` 标记可通过、携带已验证 Source 哈希的 Cue `cue_candidate: v1.0.0` 标记可通过、错误 Cue `v1.1.0` 声明被 `success_marker_schema_versions` 阻断的无 API 测试。测试只在临时目录写 synthetic 文件，不会触碰任何正式 JSONL 或 SUCCESS。

## 交接元数据

- 分支 / Wave 1 实现提交：`HEAD (no branch)` / `08e5d0e6decdc435f198d4c334ffa3025c331649`。
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

## 正式 Source QA 时间边界修复（待重跑审计）

- 适用提交：本段随 T4 修复提交写入；正式 QA 结果与审计哈希将在该提交之后的独立重跑中补充。
- 已确认的 T1 正式 Source 输入：`source_video_atoms.jsonl` SHA256 为 `be5f36b77970cb5147b88551c566f081589fe00fcf5ef912d8468a037e92960e`，行数为 `370799`；`SOURCE_ATOMS_SUCCESS.json` 的声明已由前一轮 T4 逐项复算通过。
- 修复原因：v1.1.0 的第 03 步以非空 `dense_caption` 对应的 Dense Caption SRT 作为 `local_start_sec` / `local_end_sec` 的主时间窗口。Transcript 可作为同一 session 的较早对齐证据而提前结束；把相同 atom 窗口强制限制在两份 SRT 的较短者内，会产生 `source_time_out_of_srt` 假阳性。
- 修复范围：`scripts/11_validate_all.py` 仍对每条非空 `source_srt_paths.transcript` 和 `source_srt_paths.dense_caption` 检查文件存在与可解析时间戳；仅对主时间窗口模态检查 `local_start_sec` 和 `local_end_sec` 不超过其末时间戳。`dense_caption` 非空时主模态为 Dense Caption，否则为 Transcript。
- 合成测试：`tests/test_validators.py` 新增“Transcript 仅至 10 秒、Dense 至 20 秒而 atom 窗口为 12–18 秒”不产生 `source_time_out_of_srt`，并验证 Transcript-only 的 8–12 秒窗口仍被 10 秒 SRT 阻断。`python -m pytest -q egopm_bench_v1/tests/test_validators.py` 结果为 `8 passed`；`python -m pytest -q` 结果为 `30 passed`；`git diff --check` 通过。
- 中文代码验收：`scripts/11_validate_all.py` 的首个有效内容仍为完整中文模块说明；新增主时间窗口选择、双路径可解析性检查及其防止误报的原因性中文注释。`tests/test_validators.py` 的首个有效内容仍为完整中文模块说明，新增测试文档说明为中文。
- 审计边界：此修复提交不接受先前含 `392` 条 `source_time_out_of_srt` 的审计输出；提交后必须以同一代码重跑 `11_validate_all.py`，再据新 `validation_errors.jsonl` 和 `leakage_report.json` 判断 Source stage 是否零 blocker。Cue、candidate、frozen、lifelog、decisions 尚未准备的门禁将仅作为预期下游阻断，不得归责 Source。

## 正式 Source QA 重跑结果

- 验证器代码提交：`4c81eec2427acecd122bf4057b663fa9e1bee129`。
- 已在主项目 `D:\scientific\EgoPM` 的 `main` 分支唯一实例执行：

```powershell
python egopm_bench_v1/scripts/11_validate_all.py --config egopm_bench_v1/config/benchmark_protocol.yaml
```

- 本次只读读取已冻结的 Source SUCCESS 边界与其正式 Source JSONL；未读取、下载、复制或处理 MP4，未调用千问，未生成 Cue、Seed、Life Log 或 Decision。
- `SOURCE_ATOMS_SUCCESS.json` 的 SHA256、行数、版本、Schema 声明、上游哈希及正式 Source 产物哈希均通过；`source_video_atoms.jsonl` 哈希仍为 `be5f36b77970cb5147b88551c566f081589fe00fcf5ef912d8468a037e92960e`，行数为 `370799`。
- Source stage 阻断数：`0`。修复前的 `392` 条 `source_time_out_of_srt` 已全部消失；没有 Source Schema、来源路径、时间戳、主时间窗口、split、近重复、视频伪造或 SUCCESS/哈希阻断。
- 新审计输出：`audit/validation_errors.jsonl` 共 `5` 行，SHA256 为 `4910f18f983d24d086fe68357dd8cc7897549f29f9201dcca7a82d09d112407d`；`audit/leakage_report.json` 报告总阻断数 `5`、答案泄漏 `0`、split 泄漏 `0`。五条均是预期下游未准备：Cue 缺少 SUCCESS 一条，candidate、frozen、lifelog、decisions 各一条上游未就绪。它们不属于 Source 阶段。
- 运行耗时：精确跨 session 近重复复核在正式规模下耗时约 33 分钟，但持续运行并以原子替换写入审计结果；未出现中断、半成品或并发写入。
- T0 下一门结论：可以将 `Source QA` 提升为 `DONE` 并冻结 `SOURCE_ATOMS_SUCCESS.json` 哈希；随后 T2 可以在该冻结哈希和 T4 Source QA DONE 的边界下启动 Cue 阶段。
