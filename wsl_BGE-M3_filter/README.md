# EgoPM-Bench BGE-M3 WSL 独立执行包

本目录是交给 WSL Codex 的完整工作空间。它不依赖父项目目录，也不要求 WSL Codex 知道 Windows 仓库结构。用户只需把本目录整体放入 WSL，并按 `TRANSFER_CONTRACT.md` 将三项输入放入本地 `input/`；WSL Codex 只在本目录中安装环境、下载固定模型、编写或运行筛选程序、保存缓存并形成交付输出。

## 一句话任务

使用固定 revision 的 `BAAI/bge-m3`，对冻结的 370,799 条 Source Atom 做可恢复、可复算的 dense+sparse 语义检索与多样性筛选，输出 8,000–12,000 个互不重复的候选 `atom_id`，供后续生成式模型抽取高质量 Cue v2。

这一步是**候选召回**，不是 Cue 判定：宁可保留有潜力但尚待判断的 Atom，也不能在这里生成 predicate、判断 `accepted/no_cue/ambiguous`，或把检索得分当成最终质量标签。

## 机器条件

- WSL2：Ubuntu 24.04.3，内核 6.6.87；
- CPU：Intel Core Ultra 9 285H，16 线程；
- 可用内存：约 11 GiB，Swap 3 GiB；
- GPU：NVIDIA GeForce RTX 5060 Laptop/系列，显存约 8 GiB；
- Windows 驱动：591.74，报告支持 CUDA 13.1；
- WSL CUDA Toolkit：12.2，`nvcc` 可用；
- WSL 根盘可用空间约 932 GiB。

系统 CUDA Toolkit 与 PyTorch wheel 自带的 CUDA runtime 可以不同。不要仅因 `nvcc` 显示 12.2 而重装驱动或 Toolkit；必须以 `torch.cuda.is_available()`、实际 GPU 矩阵运算和 BGE-M3 小批编码为准。安装时使用 PyTorch 官方稳定 Linux wheel：[PyTorch 本地安装](https://pytorch.org/get-started/locally/)。

## 为什么建立独立虚拟环境

必须在本目录创建 `.venv-bge-m3`：

- Windows 的 Python 环境不能直接在 WSL Linux 中使用；
- PyTorch、CUDA runtime、`transformers`、`FlagEmbedding` 和 `huggingface_hub` 必须单独冻结；
- 避免污染系统 Python；
- 便于记录完整依赖并复算同一 selection。

建议把整个目录放在 WSL Linux 文件系统，例如 `~/EgoPM_BGE-M3_filter/`。模型、embedding 和索引缓存也应留在 Linux 文件系统，避免通过 `/mnt/c` 或 `/mnt/d` 高频随机读写。

## 包内目录

```text
EgoPM_BGE-M3_filter/
├── AGENTS.md
├── README.md
├── PROJECT_CONTEXT.md
├── SELECTION_PROTOCOL.md
├── RUNBOOK.md
├── TRANSFER_CONTRACT.md
├── .venv-bge-m3/                 # WSL 创建，不交付
├── input/                        # 用户提供，只读
├── model/                        # 固定 revision 模型
├── src/                          # WSL Codex 编写的本地执行程序
├── cache/                        # 可恢复 embedding 与检索缓存
├── work/                         # checkpoint、日志和诊断
└── output/<selection_id>/        # 正式交付目录
```

除本页列出的包内路径外，说明文件不依赖其他目录。若本目录之外还有项目文件，WSL Codex 也不得假定它们存在或可见。

## 阅读与执行顺序

1. 完整阅读六份包内说明；
2. 检查 `input/` 的三项输入，确认身份与哈希；
3. 按 `RUNBOOK.md` 创建环境并完成 GPU、模型和小批自检；
4. 按 `SELECTION_PROTOCOL.md` 实现或检查筛选流程；
5. 执行冻结的 `selection_request.json`；
6. 生成报告、manifest 和正式候选；
7. 通过全部门禁后写 SUCCESS；
8. 将完整 `output/<selection_id>/` 交给用户，由用户负责导入主项目。

## 本阶段不做什么

- 不生成 Cue predicate、Seed、lure、Life Log 或 gold；
- 不判断 `accepted/no_cue/ambiguous`；
- 不调用千问、DeepSeek 或其他生成式 API；
- 不修改或重新保存 Source；
- 不把 embedding、模型权重或 Source 正文放入正式输出；
- 不决定后续 API 分片、账号分配或最终 Cue SUCCESS。

正式结果只回答一个问题：**哪些 Source Atom 值得进入下一阶段的 Cue v2 抽取池，并且该选择能否被确定性复算和科学审计。**
