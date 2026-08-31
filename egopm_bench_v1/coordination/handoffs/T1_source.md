# T1 Source 正式建库交接

- 分支：`main`。
- Source 近重复精确索引修复提交：`f730cdf0bbac2995fd9c7d4d07f83d9af4ee41ef`。
- 正式 Source 产物提交：`ada03ec12ef6a485e71e171f6121cf4bbfa907ab`。
- 治理合同版本：`v1.1.0`；配置合同版本：`v1.1.0`；Source Atom 与草稿 Schema 版本：`v1.1.0`。

## 授权边界与执行内容

已在主项目 `D:\scientific\EgoPM` 的 `main` 分支按顺序执行：

```powershell
python egopm_bench_v1/scripts/01_inventory_srt.py --config egopm_bench_v1/config/paths.yaml
python egopm_bench_v1/scripts/02_parse_srt.py --config egopm_bench_v1/config/paths.yaml
python egopm_bench_v1/scripts/03_align_modal_text.py --config egopm_bench_v1/config/paths.yaml
python egopm_bench_v1/scripts/04_make_source_splits.py --config egopm_bench_v1/config/paths.yaml
```

仅递归读取 `raw/EgoLifeCap/Transcript` 的 `402` 个 SRT 与 `raw/EgoLifeCap/DenseCaption` 的 `406` 个 SRT。未读取、下载、复制、拼接或处理 MP4，也未调用千问、生成 Cue、Seed 或 Life Log。

首次正式第 04 步在写入任何最终产物前发现最终 split 校验对每个成员扫描全表、会在正式规模退化为二次复杂度，已安全中止；当时没有 `source_video_atoms.jsonl`、`source_split_map.jsonl`、SUCCESS 或临时文件。修复以精确前缀倒排索引筛选不可能的候选对，并仍以完整 `char_3gram_jaccard`、阈值 `0.92` 复核；比较范围仍是同一 participant 与 `source_day` 的全部不同 session，不使用时间排序、近似检索或降采样。

## 修改文件与中文代码验收

- `egopm_bench_v1/scripts/04_make_source_splits.py`：正式近重复比较改为精确索引，保留同一连通性语义；首个有效内容为中文模块说明，新增的复杂度与精确性理由均为中文注释。
- `egopm_bench_v1/tests/test_source_pipeline.py`：新增索引边集合与朴素全对参考完全一致的 synthetic 测试；首个有效内容为中文模块说明。
- `egopm_bench_v1/source/**`：由脚本通过 `*.tmp`、`os.replace` 和最后的 SUCCESS 写入生成，未手改 JSONL 或 JSON。
- `egopm_bench_v1/coordination/handoffs/T1_source.md`：本交接。

已复核 `01_inventory_srt.py`、`02_parse_srt.py`、`03_align_modal_text.py`、`04_make_source_splits.py`：每个文件均以明确输入、输出与流水线阶段的中文模块说明开头；时间对齐、过滤、跨 session 约束、原子替换、哈希/SUCCESS 门和异常处理均有中文的原因性注释。

## 输入与输出哈希

只读配置及 Schema 输入：

- `egopm_bench_v1/config/paths.yaml`：冻结版本 `v1.1.0`。
- `egopm_bench_v1/config/split_policy.yaml`：冻结版本 `v1.1.0`。
- `egopm_bench_v1/schemas/source_video_atom.schema.json` 与 `source_video_atom_draft.schema.json`：冻结版本 `v1.1.0`。

可追溯上游哈希：

- `srt_inventory.csv`：`90a87fbe2cf2ef5dcc799264fb218d2bb0b9fb0cd79dc3eff8b4ab705da87d70`，共 `808` 条已发现 SRT。
- `raw_srt_segments.jsonl`：`1767315c2e852b4d74a058c4da32560d19053206ec9a82f43826059c71e97778`。
- `source_video_atoms_draft.jsonl`：`e931c1b42b0abb9dceef7a92a1e564c5a14df46192b38cc134d6c587096aebca`，共 `370799` 条草稿原子。

正式输出与核验哈希：

- `source_video_atoms.jsonl`：`be5f36b77970cb5147b88551c566f081589fe00fcf5ef912d8468a037e92960e`，共 `370799` 条最终原子。
- `source_split_map.jsonl`：`59ef3e8efd0a4b496b4a894779de2e923da126f5ab5a741e321be9efff3f2278`。
- `atom_build_report.json`：`9296482af9e792d8ffc61eaf78d346bc43ef9c8d885ccede972292c7cbb7138e`。
- `SOURCE_ATOMS_SUCCESS.json`：已存在；`sha256`、`row_count`、合同与配置版本、Schema 版本、三个上游哈希与全部正式产物哈希均已逐项复算一致。生成时间为 `2026-08-31T20:14:58.330464+08:00`。

## 测试与下一门

```powershell
python -m pytest -q egopm_bench_v1/tests/test_source_pipeline.py
python -m pytest -q
git diff --check
```

结果：Source pipeline 测试 `3 passed`；全量测试 `28 passed`；`git diff --check` 通过。精确索引测试逐边比较索引结果与朴素跨 session 全对 `char_3gram_jaccard` 参考，结果完全一致。

未解决问题：无待处理 `CHANGE_REQUEST`；`CR-2026-002`、`CR-2026-003`、`CR-2026-004` 已由 v1.1.0 决议冻结。

下一门：`SOURCE_ATOMS_SUCCESS.json` 已具备，T4 可以执行 Source QA。T2 仍须等待 T4 Source QA 通过且 T0 冻结该 SUCCESS 哈希后才能启动。
