# 输入目录说明

本目录把只读 Source 与冻结选择合同分开，避免把运行身份、模型参数、查询和筛选规则混在一个 JSON 中。

```text
input/
├── README.md
├── source/                         # 用户复制到 WSL；被 .gitignore 排除
│   ├── source_video_atoms.jsonl
│   └── SOURCE_ATOMS_SUCCESS.json
├── request/                        # 可审阅、可哈希的冻结小文件
│   ├── selection_request.json      # 根清单；不含自身 SHA
│   ├── selection_request.sha256    # 根清单的外部期望 SHA
│   ├── model_config.json           # 模型加载与编码参数
│   ├── query_set.jsonl             # 独立查询集
│   └── selection_policy.json       # 召回、多样性、分层和排序规则
└── schema/                         # 两个必要的冻结 Schema
    ├── source_video_atom.schema.json
    └── bge_selection_artifacts.schema.json
```

所有路径均相对于执行包根目录。`selection_request.json` 只绑定其他输入文件的 SHA256；它自己的期望值位于同目录 `selection_request.sha256`，执行器复算后再写入最终 `selection_manifest.json` 与 `BGE_FILTER_SUCCESS.json`，因此不存在自引用。

根请求、三个 request 组件及两个 Schema 都是正式冻结值，不是模板。规范化测试向量直接放在 `selection_policy.json` 对应规则内，避免另建只有六行的文件。Source SUCCESS 是已冻结的上游证明，按请求中的原始字节 SHA 精确验证；因为任何未知字段都会改变该 SHA，所以不再为它复制一份独立 Schema。候选行、五类 proof 行、report、manifest 与 SUCCESS 的严格定义统一放在一个 artifact Schema 的不同 `$defs` 中。

任何内容文件被修改后，必须重新计算对应 SHA、更新上级绑定并使用新的 `selection_id`；禁止在正式运行中原地修改。请求和三个配置组件由原始字节 SHA 与实现中的精确键集合双重约束；两个数据接口再由 Draft 2020-12 Schema 拒绝未知字段。

当前冻结身份为：selection ID `bge_m3_source_select_v3_1_20260910_01`，根请求 SHA256 `921024d8b4621fb8f8a8d600e191f4ba3d7406325bc4b5a17954863b7f435baa`。查询族固定为 `Person / Location / Object / Activity / State / Explicit-Time`，六族均不设数量配额；候选规模由策略确定为 10,000–12,000。
