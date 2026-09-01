# T2 交接：CR-2026-009 的 Cue v2.2 Batch File 无 API 生产者

## 当前结论

本交接对应 T2 已提交的实现。第 05 阶段已改为紧凑协议的本地 Batch File 计划器：默认仅
验证冻结 Source、构造内存中的五条 Atom package、十个逻辑 shard 一个任务的无正文任务
元数据，并输出费用预检。没有读取 `DASHSCOPE_API_KEY`，没有网络客户端、上传、远端任务、
下载或模型调用；`--execute` 与失败重跑参数都会在读取密钥之前报合同阻断。

## 交接元数据

| 项目 | 值 |
| --- | --- |
| 分支 | `main` |
| T2 代码提交 | `c9cc106920de178c2079c44ec7088f6c957e1ada` |
| T2 交接提交 | `a47b409` |
| 治理合同版本 | `v1.1.0` |
| 配置合同版本 | `v1.1.0` |
| 最终 Cue Schema | `v1.0.0` |
| 紧凑推理 Schema | `cue_inference_batch_compact_v1.schema.json` / `v1.0.0` |
| 生产调用状态 | 未授权、未执行 |
| 冻结只读输入 | `source_video_atoms.jsonl` SHA256 `be5f36b77970cb5147b88551c566f081589fe00fcf5ef912d8468a037e92960e`；370799 行 |
| 本次正式输出 | 无；未写 `cue_library.jsonl`、`CUE_LIBRARY_SUCCESS.json`、Batch 请求文件或远端工件 |

## 修改内容

- `prompts/cue_extractor_v3_compact.md`
  - 全中文提示词为 UTF-8 `445` 字节，不超过冻结的 `450` 字节。
  - 规定数组完整性、`n,t,p,x,c,v,e,s,a,r` 短字段、短码表、同项连续原文子串、主槽位匹配和
    受控字段禁止回显。
- `scripts/05_extract_cues.py`
  - 从冻结配置读取 `v2.2.0` Batch、紧凑码、账本终态、价格与恢复规则，并把完整 `execution`
    连同提示词/Schema SHA256 纳入协议哈希。
  - 按 `atom_id` 排序，按每逻辑 shard `500` 条、每 package 最多 `5` 条和实际请求 `24000`
    UTF-8 字节限制构造 package；Batch 请求顶层 `enable_thinking:false`，输出上限为每 Atom
    `96` token。
  - 每十个逻辑 shard 形成一个内存 Batch task，检查单行 `1MB`、单文件 `50000` 行与 `500MB`
    限制。任务元数据含固定的血缘/哈希/范围/远端句柄字段；合成写入函数只写
    `batch_tasks_manifest.jsonl` 允许的无正文元数据及 `{custom_id: package_id}` 映射。
  - 严格展开 `n,t,p,x,c,v,e,s,a,r`：短码未知、遗漏/重复索引、私加字段、跨 Atom 子串、主槽位
    不匹配均拒绝；程序回填最终 Cue 的 ID、split、原文和运行字段，默认回填空实体与 null。
  - 模拟结果行只在内存解析。服务端行级失败的终态为
    `service_line_failure_requeueable`；服务端成功但本地校验失败为
    `local_validation_quarantine`，绝不自动重传；通过为 `validated_success`。账本不保存请求、
    响应、错误正文或原文，包含冻结的 Batch 六字段和 `outcome`。
  - 同一 `batch_custom_id` 只能有一个终态；隔离项永远不在可重排队集合中。
  - 面向冻结 Source 的默认预检采用逐行读取和逐 task 哈希：内存中只暂存当前十个 shard 的
    请求行，完成哈希后立即释放；不会把全量 Atom、package 与请求正文同时常驻内存。
- `tests/test_qwen_contracts.py`
  - 保留第 06/07 的回归测试；新增紧凑提示词字节数、五条 package、Batch 分组/`custom_id`、
    三个解析终态、隔离不重排队、无正文任务清单和默认只读/执行阻断测试。

## 只读输入与产物边界

| 输入 | 约束 |
| --- | --- |
| `source/source_video_atoms.jsonl` | 仅由预检读取，必须与 `SOURCE_ATOMS_SUCCESS.json` 的 SHA256 和行数一致 |
| `config/model_registry.yaml` | T0 冻结的 v2.2 配置，仅读取 |
| 紧凑提示词与两个 Cue Schema | 仅读取，SHA256 进入协议哈希 |

没有正式输出哈希：本次没有写 `cues/cue_library.jsonl`、`CUE_LIBRARY_SUCCESS.json`、Seed、
请求文件、原始响应、错误响应或远端文件。测试中的 JSONL 均位于 pytest 临时目录。

## 中文说明与注释验收

- `scripts/05_extract_cues.py` 的首个有效内容为中文模块说明，写明第 05 阶段职责、输入、输出
  和无 API 边界。
- 分包上限、custom_id 哈希、防跨 Atom 证据、隔离不重传、账本终态和执行开关阻断均有中文注释，
  说明血缘、成本和重复计费风险。
- 提示词、测试说明和本交接均为中文；代码字段、路径、模型 ID 和配置键按合同保留原文。

## 验证结果

```powershell
python -m py_compile egopm_bench_v1/scripts/05_extract_cues.py egopm_bench_v1/tests/test_qwen_contracts.py
# 通过

python -m pytest -q egopm_bench_v1/tests/test_qwen_contracts.py --basetemp .pytest_cache/t2-v22-targeted
# 10 passed

python -m pytest -q --basetemp .pytest_cache/t2-v22-full
# 46 passed

git diff --check
# 通过
```

T0 复跑的冻结 Source 只读预检结果为：`74160` 个 package、`742` 个逻辑 shard、`75` 个
Batch task；最大 Batch 请求行 `10943` UTF-8 字节，输入字节代理上界 `217655725`，输出上界
`35596704` token。该预检未读密钥、未联网、未写正式工件。

## 未解决问题与下一门

- `CR-2026-009` 的无 API T2 实现待 T0/T4 审阅。任何真正 Batch 上传、轮询、下载、远端清理、
  正式 Cue 合并和 SUCCESS 写入均不在本提交中，须另获用户的预算与执行授权。
- T4 应针对完整协议哈希、任务总清单、账本终态和最终 SUCCESS 的 Batch 血缘字段实施独立 QA。
