"""当前 Cue v2 入口的轻量回归测试。

输入是当前配置和两份 Cue v2 Schema；输出是本地 Schema 与默认路径断言。它位于第 05 阶段
当前开发路径，不读取 Source 全量数据、不调用模型，也不依赖 V9 manifest 或 SUCCESS。
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_current_cue_v2_config_has_one_path_source() -> None:
    """唯一配置应持有当前输入输出路径，避免 paths.yaml 与脚本默认值混用。"""

    registry = yaml.safe_load((ROOT / "config" / "model_registry.yaml").read_text(encoding="utf-8"))
    current = registry["models"]["cue_v2_extraction"]
    assert {"source_path", "candidate_path", "runs_root", "prompt_path", "inference_schema_path", "artifact_schema_path"}.issubset(current)
    assert "cue_extraction" not in registry["models"]
    assert "worker_resources" not in current and "ledger_path" not in str(current)
    paths = yaml.safe_load((ROOT / "config" / "paths.yaml").read_text(encoding="utf-8"))
    assert "cue_v2" not in paths


def test_current_cue_v2_schemas_require_anchor_and_allow_deferred_status() -> None:
    """状态和持有关系必须有 anchor，暂未开放项必须能保留为 deferred。"""

    inference = json.loads((ROOT / "schemas" / "cue_v2_inference.schema.json").read_text(encoding="utf-8"))
    artifact = json.loads((ROOT / "schemas" / "cue_v2_artifacts.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(inference)
    jsonschema.Draft202012Validator.check_schema(artifact)
    clause = inference["$defs"]["clause"]
    assert "anchor" in clause["required"]
    assert "unsupported" in inference["$defs"]["non_accepted"]["properties"]["disposition"]["enum"]
    assert "deferred_unsupported" in artifact["$defs"]["base"]["properties"]["status"]["enum"]
