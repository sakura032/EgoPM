# T2 交接：Cue v2 无 API 执行器收尾

## 当前结论

T2 已完成 `CR-2026-007` 的无 API 代码与合成测试收尾。第 05 步现在使用固定的
最多五条 Atom 自适应 package 协议，默认只做只读预检；没有调用千问、没有读取真实
密钥、没有生成正式 Cue、Seed、`CUE_LIBRARY_SUCCESS.json` 或 `SEED_CANDIDATES_SUCCESS.json`。

本交接对应代码提交为 `6628eb02d7fa0a6ad12c566654c408ec9d9d61b6` 与
`22862d3d21ac19ca8b8f43d2627641aa9ce1f906`。后者修复最终 SUCCESS 的受管相对路径，
避免 T4 因绝对路径拒绝正式产物。它们建立在 `9b2490e`（v2 初始实现）、`b552b74`
（package 完整性补丁）、`88efa16`（协议载荷版本）和 `d67aab7`（T4 完整协议 QA）之上。

## 交接元数据

| 项目 | 值 |
| --- | --- |
| 分支 | `main` |
| T2 代码提交 | `6628eb02d7fa0a6ad12c566654c408ec9d9d61b6`、`22862d3d21ac19ca8b8f43d2627641aa9ce1f906` |
| 治理合同版本 | `v1.1.0` |
| 配置合同版本 | `v1.1.0` |
| 最终 Cue Schema | `v1.0.0` |
| 推理批次 Schema | `cue_inference_batch_v1.schema.json` / `v1.0.0` |
| 生产调用状态 | 未授权、未执行 |

## 本次修改

- `scripts/05_extract_cues.py`
  - 默认路径只验证 Source SUCCESS、Schema、排序、分包和费用上界；不读取环境变量、不联网、
    不创建运行目录。
  - 以 `atom_id` 固定排序；每逻辑 shard 最多 `500` 条 Atom，再以最多 `5` 条和实际
    序列化请求不超过 `24000` UTF-8 字节双门限组成 package。
  - 模型输入仅含 `item_index` 和 `text`；程序只在推理 Schema、索引覆盖、同 Atom 原文
    子串和谓词槽位检查均通过后，回填 `cue_id`、`atom_id`、`split`、`source_text`、模型、
    提示词、Schema 与 `run_id`。
  - 使用和 T4 完全一致的 canonical 协议载荷哈希：`payload_version`、模型字段、服务字段、
    完整 `execution`、提示词 SHA256 与推理 Schema SHA256。该哈希变更会使旧 package
    不可恢复。
  - package 清单绑定 `run_id`、Source 哈希、协议哈希及每条 Atom 的 canonical SHA256。
    `complete` 只有在当前清单完全相等、包 ID/Source/协议匹配、清单/结果/账本 SHA256
    全匹配时才可复用。
  - 每个 HTTP 尝试都以 fsync 追加无正文账本：run/package/Atom、请求时间、模型与服务
    参数、重试次数、本次限流等待、三个 `usage` 字段、解析状态、失败类别摘要和血缘哈希。
    不保存请求正文、模型正文、原始 HTTP 响应或 API Key。
  - 失败 package 只有显式传入 `--rerun-failed-packages` 才会重跑；重跑增加账本周期，
    不删除历史失败尝试。最终合并按数字 shard/package 顺序进行，任何未完成包都阻断合并。
  - `usage_summary` 仅汇总实际账本中的非负、三字段一致的服务端 usage；缺失 usage 单独计数，
    不会用预检数字或零伪造实际账务。
  - 最终 `CUE_LIBRARY_SUCCESS.json` 在合并后最后原子写入；`artifact_path` 强制为
    `egopm_bench_v1` 根相对 POSIX 路径，ROOT 外输出直接拒绝，包含
    `protocol_hash_payload_version`、完整协议哈希、提示词/推理 Schema 哈希、Source 哈希和
    实际用量汇总，以满足 T4 的 Cue v2 QA 门。

- `tests/test_qwen_contracts.py`
  - 新增或恢复纯合成测试：最小模型输入、五条自适应分包、受控字段和跨 Atom 原文拒绝、
    T4 一致的完整协议载荷、清单/账本篡改恢复拒绝、逐次尝试账本及真实 usage 汇总、默认
    只读预检、最终 SUCCESS 的 `protocol_hash_payload_version`。
  - 恢复第 06 阶段同 split 两个诱饵和第 07 阶段 Seed 请求/终止静默条件回归，避免 v2
    测试取代既有第 06/07 覆盖。

## 只读输入与冻结哈希

| 输入 | SHA256 |
| --- | --- |
| `source/source_video_atoms.jsonl` | `be5f36b77970cb5147b88551c566f081589fe00fcf5ef912d8468a037e92960e` |
| `config/model_registry.yaml` | `d453e39359b8970b5afba116fa8e19796d3dfe6d6766979175490c5d7d71a59a` |
| `prompts/cue_extractor_v2.md` | `af927b5979d5f97954187a68142f4e5a039619ce08037caf2b5f7852eaef7257` |
| `schemas/cue_inference_batch_v1.schema.json` | `47a63f306184e60e22d155ddf7380d05791f9d0fc9c4b825650d5c3290b6cf25` |
| `schemas/cue_candidate.schema.json` | `c69c700f7be237b3f06bceffc2685ef3d32e3b7e5e306b7e62fcaa60d3fb3139` |

本次没有正式输出哈希：没有写入任何生产 Cue JSONL、Seed JSONL、SUCCESS 标记或模型响应。
测试工件只在 pytest 临时目录内创建并由测试框架清理。

## 中文说明与注释验收

- `scripts/05_extract_cues.py` 的首个有效内容为中文模块说明，明确第 05 阶段职责、输入、
  输出与流水线位置。
- Source SUCCESS 相对路径和哈希、完整协议哈希、双门限分包、fsync 原子写入、完成复用、
  显式失败重跑、每次限流等待、无正文异常、确定性合并和 SUCCESS 最后写入均有中文注释，
  说明对应的数据血缘、成本或评测约束。
- `tests/test_qwen_contracts.py` 的首个有效内容为中文模块说明；所有 fixture 均标记为合成，
  且假 HTTP 响应只在内存中使用。

## 验证结果

```powershell
python -m py_compile egopm_bench_v1/scripts/05_extract_cues.py egopm_bench_v1/tests/test_qwen_contracts.py
# 通过

python -m pytest -q egopm_bench_v1/tests/test_qwen_contracts.py --basetemp .pytest_cache/t2-v2-targeted
# 9 passed

python -m pytest -q --basetemp .pytest_cache/t2-v2-final
# 41 passed

git diff --check
# 通过
```

## CHANGE_REQUEST 与下一门

- `CR-2026-007`：无 API v2 代码实现已由 T2 完成，仍待 T0 审阅、合并并在状态板确认。
  不涉及 T2 改动 `config/**` 或 `schemas/**`；协议冻结由 T0 提交维护。
- Cue 正式生产仍为 `BLOCKED`：必须先由用户明确确认预算、执行范围和分批方案。该确认前，
  禁止传入 `--execute`、调用千问、写 `cues/cue_library.jsonl` 或写
  `cues/CUE_LIBRARY_SUCCESS.json`。
- T4 应在 T0 合并后审阅本交接中的全量协议哈希、SUCCESS 字段和无 API 测试结果；该 QA
  审阅不构成生产调用授权。
