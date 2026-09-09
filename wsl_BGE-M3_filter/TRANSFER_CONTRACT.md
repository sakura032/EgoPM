# BGE-M3 本目录输入、输出与用户交接合同

本合同只使用当前执行包内的相对路径。WSL Codex 不需要知道输入在别处如何产生，也不负责把结果写入任何不可见项目目录。用户负责把冻结输入复制到 `input/`，并在任务完成后把整个正式输出目录取走。

## 一、用户提供的本地输入

正式运行前，`input/` 必须包含：

| 本地文件 | 身份要求 | WSL Codex 的职责 |
| --- | --- | --- |
| `input/source_video_atoms.jsonl` | 370,799 行；SHA256 固定为 `be5f36b77970cb5147b88551c566f081589fe00fcf5ef912d8468a037e92960e` | 只读、流式验证，禁止重存或改写 |
| `input/SOURCE_ATOMS_SUCCESS.json` | 必须声明并绑定同一 Source 的行数与 SHA256 | 与实际 Source 交叉核验 |
| `input/selection_request.json` | `frozen=true`；绑定固定 Source、固定模型 revision、查询、参数、分层和 selection ID | 验证 Schema 与哈希，严格执行，不擅自补参数 |

不得只提供 Source 而遗漏 SUCCESS 或请求文件。不得用文本编辑器打开后重新保存 Source。文件传入本目录后，WSL Codex 必须独立复算 SHA256，不接受口头或文件名替代验证。

如果 `selection_request.json` 仍是模板、存在占位文本或未明确参数冲突处理，WSL Codex 可以完成环境和小型自检，但必须在全量运行前停止，列出需要用户冻结的具体字段。

## 二、输入的最小安全处理

- `input/` 始终按只读源处理；
- 输入验证日志不得复制大段 Source 正文；
- 失败项只记录 `atom_id`、行号、安全错误码和 JSON 路径；
- 不修复畸形行，不删除重复行，不另建“清洗后的 Source”冒充上游；
- passage 与 embedding 是本地派生缓存，不得反向覆盖输入；
- 不从输入中的路径尝试寻找或下载 MP4、SRT 或其他文件。

## 三、正式输出目录

每次 selection 使用独立目录：

```text
output/<selection_id>/
├── candidate_atoms.jsonl
├── candidate_manifest.json
├── distribution_manifest.json
├── distribution_summary.json
├── distribution_by_split.json
├── distribution_by_participant.json
├── distribution_by_modality.json
├── distribution_by_source_group.jsonl
├── distribution_by_query_family.json
├── distribution_by_shard.jsonl
├── retrieval_channel_summary.json
├── environment_report.json
├── model_files_manifest.json
├── source_code_manifest.json
├── cache_manifest.json
├── execution_report.md
└── BGE_FILTER_SUCCESS.json
```

如果为大体量分布增加分片，必须在 `distribution_manifest.json` 中逐文件记录相对路径、SHA256、行数和字节数。不能临时更名后漏掉 manifest 更新。

## 四、候选行合同

`candidate_atoms.jsonl` 每行至少包含：

```json
{
  "atom_id": "src_...",
  "selection_channels": ["dense_query", "sparse_query", "rrf", "diversity"],
  "query_hits": [
    {
      "query_id": "query_...",
      "dense_rank": 1,
      "rrf_score": 0.016393
    }
  ],
  "selection_reason_codes": ["query_family_hit", "coverage_retained"],
  "diversity_cluster_id": "cluster_..."
}
```

约束：

- 每个 `atom_id` 只出现一次，且必须能在本地 Source 中唯一回查；
- `selection_channels`、`query_hits` 和原因码使用确定性顺序；
- 不适用的可选字段直接省略，不写字符串 `null`、`none`、`unknown` 或虚假 0；
- 不重复保存 Source 正文、参与者、split、模态、来源组或路径；
- 分数和名次只能说明筛选来源，不能命名为 confidence 或质量标签。

## 五、manifest 合同

`candidate_manifest.json` 至少绑定：

- `selection_id`；
- Source SHA256 与行数；
- 模型仓库、revision 与模型文件 manifest SHA256；
- 请求 SHA256；
- 源码 manifest SHA256；
- passage 序列化版本；
- candidate 文件相对路径、SHA256、行数和字节数；
- 候选排序键；
- 候选总数；
- distribution manifest SHA256；
- 生成时间戳。

正式 manifest 只能使用当前输出目录内的相对路径，不写 WSL 绝对路径、用户主目录或任何主项目路径。

## 六、不交付的大型本地材料

以下内容通常留在 WSL，不放进正式输出：

- dense embedding memmap；
- sparse embedding 分片；
- passage 或规范化文本缓存；
- 模型权重副本；
- ANN/精确检索工作索引；
- `.tmp`、失败 checkpoint 和详细调试日志。

它们应由 `cache_manifest.json` 记录类型、相对路径、SHA256、字节数、所属 selection 和是否可安全重建。这里的相对路径以本执行包根目录为基准，但正式下游不能依赖这些缓存才能读取候选。

用户明确确认正式输出已接收并通过复核之前，不应清理仍可能用于恢复的缓存。WSL Codex 不负责决定用户何时删除它们。

## 七、交付前只读复核

WSL Codex 在交付前必须完成：

1. 确认输出目录不存在 `.tmp`；
2. 复算全部正式文件 SHA256；
3. 验证 Source、模型 revision、请求与源码身份；
4. 流式检查 candidate `atom_id` 唯一并可回查；
5. 从候选重新计算分布并与报告对比；
6. 验证 manifest 只含相对路径且所有文件均存在；
7. 验证 SUCCESS 绑定 candidate manifest 与 distribution manifest；
8. 确认 blocker 数为 0，且没有仍在写入的进程。

任一项失败都必须移除或不生成 SUCCESS，修复应通过程序重新生成受影响文件，禁止手改 JSONL 或哈希。

## 八、交给用户的内容

任务成功时，只需把完整且未改动的 `output/<selection_id>/` 目录交给用户，并附上一段中文摘要：

- `selection_id`；
- 候选数；
- Source SHA256；
- 模型 revision；
- 请求、candidate manifest 和 distribution manifest SHA256；
- 总运行时间与峰值显存；
- 是否发生恢复；
- 未解决问题，成功交付时应为“无”。

WSL Codex 不应猜测用户要把结果复制到哪里，也不应引用本目录外的目标路径。用户将在可见的主项目中完成导入、再次验哈希和下游授权。

任务失败或被阻断时，交给用户 `work/reports/` 中的 blocker 摘要以及可恢复 cache 身份；不要把失败目录伪装成正式输出。
