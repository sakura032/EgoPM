# T1 Source 交接

- 分支 / 当前提交：`detached HEAD` / `1b869738c805aea75a282a3ab3f9a6e732e0007a`
- 供 T0 合并的完整提交链（必须按此顺序，后者以前者为直接父提交）：
  1. `debc422b29438c5fbee4628b1345fbfb6afd766e`：Source Atom Wave 1 代码与单元测试。
  2. `1b869738c805aea75a282a3ab3f9a6e732e0007a`：T1 Source 交接文件。
- 合同版本：本 worktree 中可核验的治理合同、冻结配置与 Schema 均为 `v1.0.0`；已补充中文 Python 模块说明和关键“为什么”注释，未自行合并 `main`。
- 完成内容：完成 Wave 1 的 fixture-only Source Atom 开发。`01` 递归清点双模态 SRT；`02` 解析字幕块并保留失败/过滤原因；`03` 以 Dense Caption 为主窗口按显式容差对齐并宽松保留单模态原子；`04` 按来源连通分量和近重复规则冻结 split、校验 Source Atom Schema、原子替换产物并最后写 SUCCESS 标记。
- 修改文件：
  - `egopm_bench_v1/scripts/01_inventory_srt.py`
  - `egopm_bench_v1/scripts/02_parse_srt.py`
  - `egopm_bench_v1/scripts/03_align_modal_text.py`
  - `egopm_bench_v1/scripts/04_make_source_splits.py`
  - `egopm_bench_v1/tests/test_source_pipeline.py`
- 只读输入及 SHA256：
  - `AGENTS.md`：`43f9f55d6de74939abfcf666799afd8cfe20b3fd7b3419dfe2854390fc9adb1f`
  - `EgoPM_Bench_v1_完整生产流水线统筹指南.md`：`b6a3beb8a9bc4d0bd8cc9eec4d2afcedc5505ddc82d12bd4e5da332b8760e743`
  - `egopm_bench_v1/config/paths.yaml`：`ea470eab7287aa8a82b997d15ab4c96713e7d05b1e1d3f6d4082e3dd9cb2aa86`
  - `egopm_bench_v1/config/split_policy.yaml`：`dd2b9bb361762f66bf500fbf0b0da2b48fae2d8d9965a59365d9d51ba098dbb0`
  - `egopm_bench_v1/schemas/source_video_atom.schema.json`：`a97d72984a0b41fccca87832f79d38f3b15d8c1e54c24e439f38005b2d0967e6`
- 输出及 SHA256：未产生任何正式 `source/**` 产物或 SUCCESS 标记，符合 Wave 1 禁止正式生产的授权边界。单元测试只在 pytest 临时目录创建 synthetic SRT 和输出，进程结束后不构成数据集产物。
- 复核命令：`$env:PYTHONDONTWRITEBYTECODE = '1'; python -m pytest -q`；`$env:PYTHONPYCACHEPREFIX = Join-Path $env:TEMP 'egopm_t1_pycompile_cache'; python -m py_compile egopm_bench_v1/scripts/01_inventory_srt.py egopm_bench_v1/scripts/02_parse_srt.py egopm_bench_v1/scripts/03_align_modal_text.py egopm_bench_v1/scripts/04_make_source_splits.py`；`git diff --check`。
- 复核结果：通过，`pytest` 为 `5 passed in 0.61s`；四个 T1 脚本的 `py_compile` 成功；`git diff --check` 无错误。编译缓存仅写入系统临时目录，不会产生正式 Source 产物或启动正式 SRT 建库。
- 未解决问题：正式运行前必须由 T0 决定下列 `CHANGE_REQUEST`；当前实现不调用千问，未生成 cue、Seed、Life Log 或任何 `remind`/`silent` gold。
- 无关工作树内容：保留未跟踪的 `.codex/`，未读取、修改或暂存。

## CHANGE_REQUEST（待 T0 登记）

### T1-CR-001：冻结 Source 文本对齐与原子合并参数

- 提出者 / handoff：T1 / `egopm_bench_v1/coordination/handoffs/T1_source.md`
- 当前合同版本：`v1.0.0`
- 受影响字段与产物：建议在 T0 管理的 Source 配置中新增 `alignment_tolerance_seconds`、相邻原子合并的最小/最大时长及连续性规则；影响 `03_align_modal_text.py`、`source_video_atoms.jsonl` 和 `atom_build_report.json`。
- 现有合同无法表达该需求的原因：生产指南要求对齐阈值写入配置，并允许按明确规则将连续短描述合并为 5–30 秒原子；现有 `paths.yaml` 与 `split_policy.yaml` 没有任何可冻结的容差、合并阈值或连续性定义。
- 建议的兼容修改或迁移方式：T0 在合同版本化配置中增加完整 Source 对齐块；T1 将 `03` 的临时 CLI 容差替换为冻结字段，并仅在 T0 批准后启用合并。
- 必须重新生成的上游/下游产物：所有正式 `source/**`、其 SUCCESS 标记，以及全部下游 cue、Seed、Life Log、Decision 和审计产物。
- 证明该问题的测试：`test_alignment_rejects_negative_tolerance` 证明容差当前必须显式传入；端到端 fixture 测试以 `0.5` 秒仅验证代码行为，不主张这是正式参数。

### T1-CR-002：区分未 split 草稿原子与最终 Source Atom

- 提出者 / handoff：T1 / `egopm_bench_v1/coordination/handoffs/T1_source.md`
- 当前合同版本：`v1.0.0`
- 受影响字段与产物：`source_video_atom.schema.json` 的必填 `split`、`paths.yaml` 的 `source_atoms` 产物语义，以及 `03` 到 `04` 的中间接口。
- 现有合同无法表达该需求的原因：第 03 步按指南生成原子、第 04 步才冻结 split，但冻结 Schema 要求每个 Source Atom 已有 `train`、`dev` 或 `test`。现有合同既没有 draft Schema，也没有单独的 draft artifact。为了让当前接口可测试，`03` 只能写入未冻结的 `split: "train"` 占位；无 SUCCESS 标记时下游不会读取它，但该占位不应成为正式语义。
- 建议的兼容修改或迁移方式：优先新增私有 `source_video_atoms_draft.jsonl` 与 draft Schema（允许 `split: null` 或 `unassigned`），由 `04` 独占生成符合现有最终 Schema 的 `source_video_atoms.jsonl`；若 T0 选择保持单一文件，则需明确允许中间占位的版本化语义与验证边界。
- 必须重新生成的上游/下游产物：所有正式 `source/**` 及全部下游产物。
- 证明该问题的测试：`test_source_pipeline_fixture_only_end_to_end` 在第 04 步后才对最终原子执行冻结 Schema 校验。

### T1-CR-003：定义“相邻 session”的可复现顺序

- 提出者 / handoff：T1 / `egopm_bench_v1/coordination/handoffs/T1_source.md`
- 当前合同版本：`v1.0.0`
- 受影响字段与产物：`split_policy.yaml` 的 `near_duplicate.comparison_scope` 与 `adjacency_grouping`，以及 `04_make_source_splits.py` 的跨 session 近重复比较。
- 现有合同无法表达该需求的原因：策略规定比较同一或相邻 session，却未提供不同 SRT session 的全局顺序或可比较的 session 起止时间；现有 `normalized_*` 仅是 session 内相对秒。当前 Wave 1 代码采用同 participant/day、按最早 session 相对时间和 session ID 的确定性后备排序，不能声称它就是数据合同指定的真实相邻关系。
- 建议的兼容修改或迁移方式：T0 冻结从文件名解析的 session 序号、录制开始时间或明确的 session 排序字段，并定义 `max_gap_seconds` 的跨 session 适用条件；否则将近重复比较范围改为可由现有字段严格表达的范围。
- 必须重新生成的上游/下游产物：所有正式 split map、Source SUCCESS 和全部下游产物。
- 证明该问题的测试：端到端 fixture 用相邻的 `session_one`/`session_two` 验证近重复连通；该 fixture 不涉及真实 session 顺序。

## 下一阶段

- Wave 1 的 T4 Source QA 验证器开发：可以启动，接口与 fixture-only 测试已具备。
- Wave 2 正式 SRT 生产：不可启动，需先由 T0 决定上述请求并冻结参数；正式产物生成后还须通过 T4 Source QA，T0 才能冻结 `SOURCE_ATOMS_SUCCESS` 哈希。
- T2 读取 Source 正式产物：不可启动。
