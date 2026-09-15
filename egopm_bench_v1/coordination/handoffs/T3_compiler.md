# T3 确定性基准编译器交接

> **历史交接说明（2026-09-09，v1.3）**：最终规模后来改为 480 个 Frozen Seed 和 2,880 条六路 Life Log；本文件其余治理/数据版本和 Wave 1 参数均是当时记录，不能覆盖当前 `AGENTS.md` v1.5.0 与 CR-2026-022。Life Log 正式布局、生成模型和协议参数必须在生产前另开 CR；T3 在 Cue v2、Seed candidates、人工审计、T4 Seed QA 和 `SEEDS_FROZEN_SUCCESS` 完成前只能使用 synthetic fixture，不得读取旧 V9 Cue 启动正式编译。

## 合同与提交状态

- 交接时治理合同版本：`v1.1.0`（当前治理合同为 `v1.5.0`；本文件只记录历史 fixture 实现）。
- 数据合同版本：`v1.0.0`。
- 分支：`codex/t3-wave1-compiler`。
- Wave 1 实现提交：`ba3eb30504a9005d140fadb9e83ba68ec368b7c7`（本交接的提交补充在该提交之后）。
- 工作范围：`scripts/08_freeze_seed_audit.py`、`scripts/09_build_lifelog_families.py`、`scripts/10_run_oracle.py`、`rules/**`、`tests/test_state_machine.py` 与本文件。未修改 `config/**`、`schemas/**`、source、cues 或候选 Seed。

## Wave 1 已完成内容

- `08_freeze_seed_audit.py`：历史 Wave 1 实现曾要求审计覆盖 35–40 个接受 Seed；该数量已被 CR-2026-020/022 的 900–1,400 候选、480 个 Frozen Seed 目标取代。通过后原子写入冻结 Seed、规则银行、状态机策略，最后才写入 `SEEDS_FROZEN_SUCCESS.json`。
- `09_build_lifelog_families.py`：在重新验证冻结 Seed 与 source atom SUCCESS 标记及哈希、且协议数值参数已经冻结后，确定性派生每个 Seed 的 `positive/negative × short/medium/long` 六条 Life Log、family spec 与反事实配对清单。正负分支共用同一当前 trigger atom。
- `10_run_oracle.py`：逐事件调用状态机编译 decision 和 evidence。gold 只由冻结 atom、有效窗口、生命周期和提醒历史决定，绝不调用模型或从自由文本判断触发；同时强制同 pair 的 `remind`/`silent` 翻转。
- `rules/state_machine.py`：实现唯一的生命周期转移、虚拟时间、有效窗口、trigger 匹配与 gold 决策。`never_created`、`completed`、`cancelled`、`expired`、`already_reminded` 均确定性产生 `silent`。
- `rules/compiler_io.py`：集中实现配置/JSONL 读取、Schema 验证、SUCCESS 哈希核验、原子写入与协议参数冻结门，避免不同阶段采用不一致的可信边界。
- `rules/__init__.py`：声明 T3 规则包，不包含数据或副作用。
- `tests/test_state_machine.py`：仅使用内存中的手写合成 fixture；覆盖人工审计过滤、每 Seed 六路日志、全部负例历史、gold 翻转与状态机拒绝伪造状态。fixture 不写入正式目录，不计入基准。

## 中文说明与关键注释验收

- 已逐一检查所有上述 Python 文件均有中文模块说明，说明职责、输入、输出与在流水线中的位置。
- `08_freeze_seed_audit.py` 的中文注释覆盖审计唯一性/完整性、接受条件、窗口/泄漏阻断、内部验证后原子发布和 SUCCESS 最后写入的原因。
- `09_build_lifelog_families.py` 的中文注释覆盖固定选择难度下界以消除随机性、正负分支共享 trigger、来源时间对齐、上游哈希门与写入顺序的原因。
- `10_run_oracle.py` 的中文注释覆盖只让状态机决定 gold、逐事件状态对照、反事实配对翻转和失败时不发布产物的原因。
- `rules/state_machine.py` 的中文注释覆盖固定虚拟时间基准、拒绝自由文本 trigger 推断、窗口计算、状态迁移和异常阻断的原因。
- `rules/compiler_io.py` 的中文注释覆盖重新计算 SUCCESS 哈希、逻辑行数复核、原子替换和协议参数未冻结即阻断的原因。
- `rules/__init__.py` 与 `tests/test_state_machine.py` 的中文模块说明分别说明无副作用包边界和 fixture-only 测试边界；测试中的关键注释说明为何动态加载编号脚本、为何 fixture 不可进入正式数据集。

## 只读输入与正式输出哈希

- 正式只读输入哈希：无。`SOURCE_ATOMS_SUCCESS.json` 与 `SEEDS_FROZEN_SUCCESS.json` 均不存在，且 `PROTOCOL_PARAMETERS_V1` 尚未冻结，故没有获授权读取正式上游数据。
- 正式输出哈希：无。没有生成 `rules/*.jsonl`、`lifelogs/*.jsonl`、`benchmark/*.jsonl`、decision、evidence 或任何 SUCCESS 标记。
- 测试 fixture 哈希：不适用。fixture 仅为测试过程中的内存对象，不能作为数据集产物。

## 验证

```powershell
python -m pytest -q
```

结果：`11 passed`。

```powershell
python -m py_compile egopm_bench_v1/scripts/08_freeze_seed_audit.py egopm_bench_v1/scripts/09_build_lifelog_families.py egopm_bench_v1/scripts/10_run_oracle.py egopm_bench_v1/rules/__init__.py egopm_bench_v1/rules/compiler_io.py egopm_bench_v1/rules/state_machine.py egopm_bench_v1/tests/test_state_machine.py
```

结果：通过。

```powershell
git diff --check
```

结果：通过，无空白错误。

## 未解决问题与变更请求

- `CHANGE_REQUEST`：无。现有合同可表达本阶段所需语义，未提出 schema 或配置变更。
- 阻断项：缺少可核验的 `SOURCE_ATOMS_SUCCESS.json`、`SEEDS_FROZEN_SUCCESS.json`，T4 尚未完成所需 source/seed QA，且 `PROTOCOL_PARAMETERS_V1` 参数尚未冻结。

## 下一门判断

- 当前不可启动正式 Families/oracle 门，且本次提交保持 fixture-only。
- 仅当 T0 已冻结并可核验 `SEEDS_FROZEN_SUCCESS.json`、对应 source 哈希和 `SOURCE_ATOMS_SUCCESS.json`，T4 已完成相应 QA，且 `PROTOCOL_PARAMETERS_V1` 已冻结，才可依序运行 `09_build_lifelog_families.py`、`10_run_oracle.py`。正式产物之后交由 T4 验证。
