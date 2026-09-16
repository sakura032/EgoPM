# EgoPM-Bench v1

v1 是面向流式第一视角观察、视频可追溯且文本优先的前瞻记忆基准。正式数据只使用可回查的 Source 文本；synthetic fixture 仅用于测试，v1 不读取或复制原始视频。

## 当前进度

- **已完成**：原始 SRT 清点与解析；Source Atom 建库（`source_video_atoms.jsonl`，370,799 行）与 split；WSL 用 BGE-M3 从 Source 中筛出 10,000 个候选 Atom（`cues/wsl_BGE/`）。
- **下一步**：新版 Cue 生产器，放在 `scripts/cues/`，**尚未实现**。
- **尚未开始**：Seed 与 Life Log，目前只有设计，见 `egopm_bench_v1/DESIGN.md`。

## Python 虚拟环境

项目自带的虚拟环境位于 `.venv`。在项目根目录 `D:\scientific\EgoPM` 中打开终端后，按终端类型激活：

PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
```

Git Bash：

```bash
source .venv/Scripts/activate
```

## 目录结构

```text
D:\scientific\EgoPM\
├─ raw\EgoLifeCap\              原始 EgoLife SRT（Transcript 402 + DenseCaption 406），只读，不进 Git
├─ egopm_bench_v1\
│  ├─ config\
│  │  ├─ source.yaml            Source 阶段（01–04）的配置，此后不再修改
│  │  ├─ cue.yaml               新版 Cue 阶段的配置
│  │  └─ split_policy.yaml      split 规则，01–04 依赖
│  ├─ schemas\
│  │  ├─ source_video_atom.schema.json
│  │  ├─ source_video_atom_draft.schema.json
│  │  └─ cues\                  Cue Schema（待写）
│  ├─ prompts\cues\             Cue 提示词（待写）
│  ├─ scripts\
│  │  ├─ source\                01–04，Source 建库，已完成并封存
│  │  └─ cues\                  新版 Cue（尚未实现）
│  ├─ source\                   Source Atom 与 split，大文件不进 Git
│  ├─ cues\
│  │  ├─ wsl_BGE\               WSL BGE 筛选的原始五文件 + 交接说明 + 依赖锁，进 Git
│  │  ├─ inputs\                selected_atoms.jsonl，由程序生成，不进 Git
│  │  └─ runs\                  Cue 结果与 checkpoint，不进 Git
│  ├─ tests\
│  │  ├─ source\                Source 流水线测试
│  │  └─ cues\                  Cue 测试（待写）
│  ├─ FACT_RULES.md             十条事实边界，事实正确性的唯一权威
│  └─ DESIGN.md                 Seed / Life Log / 状态机设计
├─ AGENTS.md                    协作规则：协作方式、安全与费用、中文文档、数据事实边界
├─ pyproject.toml               Python 依赖与测试配置
├─ .gitignore / .gitattributes   忽略规则与行尾规范（统一 LF）
└─ 论文选题.md                   研究定义
```

## 运行 Source 流水线

`01`–`04` 已完成建库，正常情况下不需要重跑；重跑会覆盖 `source/` 下的产物。

```bash
cd /d/scientific/EgoPM
python egopm_bench_v1/scripts/source/01_inventory_srt.py      # 清点 SRT，写 srt_inventory.csv
python egopm_bench_v1/scripts/source/02_parse_srt.py          # 解析字幕块，写 raw_srt_segments.jsonl
python egopm_bench_v1/scripts/source/03_align_modal_text.py   # 时间对齐，写草稿原子
python egopm_bench_v1/scripts/source/04_make_source_splits.py # 验证草稿，写正式 Atom 与 split
```

四个脚本默认读取 `egopm_bench_v1/config/source.yaml`，可用 `--config` 显式覆盖。

测试：

```bash
python -m pytest -q
```

## 不进 Git 的文件

原始语料与媒体、Source 大文件（`source_video_atoms.jsonl`、`source_split_map.jsonl`、草稿原子、raw segments）、`cues/inputs/`、`cues/runs/`、模型原始响应，都只保留在本机。具体规则见 `.gitignore`。

## Cue 的事实边界

写 Cue 相关的 prompt、Schema 或代码之前，先读 `egopm_bench_v1/FACT_RULES.md`。那十条是全流程事实正确性的唯一权威，任何一处改动的理由都必须能落在其中某一条上。
