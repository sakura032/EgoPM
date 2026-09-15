# WSL BGE-M3 筛选交接：成功快照

## 状态与范围

WSL 侧 Source Atom 筛选已在 2026-09-15 成功关闭。它只完成“从冻结 Source 中选出值得进入 Cue v2 抽取的 Atom”，**没有**生成 Cue、Seed 或 Life Log。下一责任方是 Windows T4 的导入、离散复核和人工抽样；在这些工作结束前，不得把 WSL SUCCESS 当作 Cue v2 验收。

| 项目 | 值 |
| --- | --- |
| selection ID | `bge_m3_source_select_v3_1_20260914_02` |
| 根请求 SHA256 | `4e4c79d33e9ce8bd4a0636b92448fc8c500532f885db47519a135c837d8e359d` |
| Source SHA256 / 行数 | `be5f36b77970cb5147b88551c566f081589fe00fcf5ef912d8468a037e92960e` / 370,799 |
| 模型 | `BAAI/bge-m3` @ `5617a9f61b028005a4858fdac845db406aefb181` |
| 源码 manifest SHA256 | `3e06e60ac4d505fd36a4968ff57980500348bc0a0cdec1993c914f7f64d04f57` |
| 正式 manifest SHA256 | `30a34f949c56e3389c14669eab6ad1b3792e932c6481d07431f95c1e416b12e5` |
| 本地 audit Merkle root | `af367d7da0655f92b75f59d599b90ea7125975622495f3e7b4d15350249225aa` |
| SUCCESS 文件 SHA256 | `9c949d3407797ff5d2c6dd17290ba08861b1507c60e7bf877b4e45d83a482240` |

## 正式输出

只复制以下目录及其中恰好五个文件；不要把 `work/`、`cache/`、模型、日志或失败证据带入正式 selection 目录。

```text
output/bge_m3_source_select_v3_1_20260914_02/
├── candidate_atoms.jsonl       10,000 rows, SHA256 1ca0da04eddbbc34308b91e772448e25bcd5172310667f515c5f7b0a541faefe
├── selection_proof.jsonl       59,465 rows, SHA256 42977c2311c1c5eb7c8329c49bb3498a690efac20b001ed31bd352e9fbb2c9f4
├── selection_report.json                 SHA256 eeb55e8bf4ec71dabf4b0bcbeea7b00148688c36a494fa38e9e2250db92511d4
├── selection_manifest.json               SHA256 30a34f949c56e3389c14669eab6ad1b3792e932c6481d07431f95c1e416b12e5
└── BGE_FILTER_SUCCESS.json               SHA256 9c949d3407797ff5d2c6dd17290ba08861b1507c60e7bf877b4e45d83a482240
```

## 已闭合的机器门

- H/I：370,799 条 Source 全部合格并恰好编码一次；48 条查询完成 dense+sparse 检索。
- J：1,024 clusters，无空簇、无重复 centroid；exact CPU FP64 去重为 290,200 survivors 与 80,599 suppressed，二者唯一、互斥并完整覆盖 370,799 条。共比较 99,209,776 对，接受 survivor 的最小精确距离为 `0.040001340210437775`，严格大于 `0.04`。GPU 与 exact survivor 数同为 290,200。
- K：coverage 为 `OPTIMAL=8000`；quality 在固定 1,800 秒结束时为 `FEASIBLE=150046500`；核心解 SHA256 为 `b5c036fab7cbfc5a3c4dc2d2d488a530b5c8a4aa67f20bd406de9fb3b677b583`；固定核心数为 10,000。
- L/M：候选、proof、report 与 manifest 通过本地验证，report blockers 为空，配置叶字段消费为 13/13。
- N：按修正后的零基 dense 行号独立扫描最终同簇候选 77,339 对，最小 selected distance 为 `0.040023233741521835 > 0.04`；目录无 `.tmp`、无写进程后最后写 SUCCESS。

## 运行环境与资源记录

任务使用 `.venv-bge-m3`，通过 `env LD_LIBRARY_PATH=/usr/lib/wsl/lib PYTHONDONTWRITEBYTECODE=1` 启动 Python，以使用 WSL CUDA 桥接库。正式 manifest 记录的运行时为 Python 3.12.3、PyTorch 2.13.0+cu130（CUDA runtime 13.0）、FlagEmbedding 1.4.2、NumPy 2.3.5、SciPy 1.16.3、scikit-learn 1.7.2、OR-Tools 9.15.6755、Unicode 15.0.0。

- J 总耗时 344.43 秒；其中 exact near-duplicate 196.93 秒、reservoir 107.46 秒；J 记录的 GPU peak allocated 为 465.25 MiB。
- K 总耗时 2,805.21 秒；coverage 后的 quality 使用 2 个 CP-SAT workers、1,800 秒固定预算；CP-SAT 内存上限为 4,096 MiB。
- L 与 M 已正常关闭；N 最终扫描后正常关闭。各阶段的事件和精确 wall time 保留在本地 `work/run_ledger.jsonl`。

## 失败证据与修复边界

一个旧 N attempt 曾因 1-based SQLite `source_row` 被直接用于 0-based dense mmap 而产生错误结论；其失败证据已保留在 WSL 本地 `work/failed_n_near_duplicate_evidence.tar`，SHA256 为 `cef627691f810acae6634beece8c45f89e525b4f37b750709cb4192b43b9d8fe`，不属于正式回传。修复后，J 的 survivor 顺序按 query-union 外优先，权威去重为 CPU FP64 exact；新 J snapshot 使 K 从头求解，N 以零基索引独立闭合。

## Windows T4 交接清单

1. 将五个正式文件复制到 `egopm_bench_v1/cues/v2/source_selection/bge_m3_source_select_v3_1_20260914_02/`，保持文件名与字节完全不变。
2. 先验证目录恰有五文件，再验证 SUCCESS 与 manifest 的 SHA 链、输入身份和 artifact Schema。
3. 从 Source 与 proof 重算离散 rank、RRF、归因、候选唯一性、split/participant/modality/source-group/cluster 硬约束及 report 聚合；不重跑 BGE，不声称复验全库向量、survivor 集或 CP-SAT 最优性。
4. 对六个 query family 各 50 条和 diversity-only 50 条进行人工精度审计。
5. T4 导入通过前，Cue v2、Seed 与 Life Log 仍不得启动。

当前没有已知 WSL blocker。保留 WSL 的 cache、audit 和失败证据，直至 Windows 确认导入成功；其后的清理由用户另行授权。
