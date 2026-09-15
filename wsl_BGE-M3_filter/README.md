# EgoPM-Bench BGE-M3 WSL 执行包

本包用固定 BGE-M3 对 370,799 条冻结 Source Atom 做 dense+sparse 召回、语义聚类和确定性多样性筛选，输出 10,000–12,000 个唯一 `atom_id`，供后续统一 `qwen3.7-flash` 协议抽取 Cue v2。

它只回答“哪些 Atom 值得进入 Cue 抽取”，不生成 predicate，不判断 `accepted/no_cue/ambiguous`，也不把视频时间戳解释成 prospective-memory 时间条件。

## 流水线位置

```text
370,799 Source Atom
        ↓ 本包：BGE-M3 检索 + 聚类 + 去近重复 + 分层
10,000–12,000 candidate Atom
        ↓ 三个阿里云账号、同一 qwen3.7-flash 协议
约 3,000–5,000 accepted Cue v2
        ↓
900–1,400 Seed candidates → 480 Frozen Seed → 2,880 Life Log
```

## 机器与专用环境

目标环境是 WSL2 Ubuntu 24.04.3、RTX 5060 Laptop 约 8 GiB、11 GiB 可用内存。系统 CUDA Toolkit 12.2 与驱动支持 CUDA 13.1 并不冲突；正式判据是所选 PyTorch wheel 的 CUDA runtime 能被当前驱动加载，并通过 `torch.cuda.is_available()`、GPU 运算和 BGE dense+sparse 小批编码。

必须创建 `.venv-bge-m3`。模型、依赖和缓存均放在 WSL Linux 文件系统，不在 `/mnt/c` 或 `/mnt/d` 上做高频读写。PyTorch 安装参考 [官方安装页](https://pytorch.org/get-started/locally/)，模型接口参考 [FlagEmbedding BGE-M3](https://github.com/FlagOpen/FlagEmbedding/blob/master/research/BGE_M3/README.md) 和 [BAAI/bge-m3 模型卡](https://huggingface.co/BAAI/bge-m3)。

## 文件导航

| 文件 | 只回答什么 |
| --- | --- |
| `AGENTS.md` | 不可违反的身份、边界和停止条件 |
| `SELECTION_PROTOCOL.md` | 唯一算法定义与验证边界 |
| `RUNBOOK.md` | 从接收到交付的执行顺序 |
| `TRANSFER_CONTRACT.md` | 输入、五文件回传、字段去向 |
| `input/README.md` | 输入目录和 SHA 绑定方式 |

本包刻意不再设置 `PROJECT_CONTEXT.md` 等重复说明；相同阶段、相似职责只保留一处权威定义。

## 目录

```text
EgoPM_BGE-M3_filter/
├── AGENTS.md
├── README.md
├── SELECTION_PROTOCOL.md
├── RUNBOOK.md
├── TRANSFER_CONTRACT.md
├── input/
│   ├── README.md
│   ├── source/               # 用户复制；只读；不提交
│   ├── request/              # 三组件、根请求和旁路 SHA
│   └── schema/               # Source 行与统一 artifact 两个必要 Schema
├── src/                      # WSL Codex 实现；结束后回传工程材料
├── model/                    # 本地模型；不回传
├── cache/                    # embedding/索引；不回传
├── work/                     # 审计/checkpoint/log；不回传
└── output/<selection_id>/    # 恰有五个正式文件
```

## 最短路径

1. 把 Source 与 Source SUCCESS 复制到 `input/source/`。
2. 验证旁路根 SHA、组件 SHA、两个 Schema、Source/Source SUCCESS SHA 和严格键集合。
3. 建立专用环境，下载固定 revision，冻结依赖与源码 manifest。
4. 单 GPU 完成分片编码；CPU 完成检索、投影聚类、选择和本地完整验证。
5. 生成候选、精简 proof、综合 report、manifest，最后写 SUCCESS。
6. 把五文件正式目录交回 Windows；另把 `src/`、依赖锁和 `WSL_HANDOFF.md` 同步回本目录。
7. Windows T4 从 Source + proof 独立复核离散选择逻辑并进行人工抽样，不重新跑 BGE。
