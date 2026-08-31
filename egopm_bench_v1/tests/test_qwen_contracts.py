"""T2 第 05--07 阶段的手写合成 fixture 合同测试。

职责是在来源冻结前验证千问请求、JSON Schema、成功标记哈希门、同 split 诱饵和
种子硬条件；测试输入是进程内字典及 pytest 临时目录，输出仅为断言结果，位于正式
来源建库之后的开发阶段而不进入正式流水线。所有对象不属于 P0、P1、smoke 或任何
正式 source/cue/seed 数据，且假的 HTTP opener 保证测试绝不发起真实网络请求。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_script(filename: str) -> ModuleType:
    path = ROOT / "scripts" / filename
    module_name = f"test_{path.stem.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def source_atom(index: int, text: str, split: str = "train") -> dict[str, Any]:
    suffix = f"{index:06d}"
    return {
        "atom_id": f"src_SYNTH_DAY1_{suffix}",
        "atom_kind": "source_video_atom",
        "participant_source_id": "SYNTH",
        "source_day": "DAY1",
        "session_id": "SYNTH_DAY1_SESSION1",
        "source_group_id": f"group_SYNTH_DAY1_{index}",
        "world_event_id": None,
        "source_srt_paths": {
            "transcript": f"synthetic/{suffix}.srt",
            "dense_caption": f"synthetic/{suffix}.srt",
        },
        "source_video_path": None,
        "video_mapping_status": "pending",
        "local_start_sec": float(index * 10),
        "local_end_sec": float(index * 10 + 8),
        "normalized_start_sec": float(index * 10),
        "normalized_end_sec": float(index * 10 + 8),
        "transcript_segment_ids": [f"tr_SYNTH_{suffix}"],
        "dense_caption_segment_ids": [f"dc_SYNTH_{suffix}"],
        "transcript": text,
        "dense_caption": text,
        "visible_text": text,
        "modality_coverage": "both",
        "provenance": "egolife_srt",
        "split": split,
    }


def cue_for(atom: dict[str, Any], run_id: str = "run_cue_fixture") -> dict[str, Any]:
    return {
        "cue_id": f"cue_{atom['atom_id'].removeprefix('src_')}",
        "atom_id": atom["atom_id"],
        "split": atom["split"],
        "entities": ["kitchen", "cooking"],
        "scene_type": "kitchen",
        "activity_type": "cooking",
        "cue_type": "activity",
        "normalized_predicate": {
            "all_of": [{"slot": "activity", "operator": "starts", "value": "cooking"}]
        },
        "supporting_text_span": "starts cooking",
        "source_text": atom["visible_text"],
        "confidence": 0.9,
        "ambiguity_reason": None,
        "model_id": "qwen3.7-flash-2026-07-15",
        "prompt_version": "cue_extractor_v1",
        "schema_version": "v1.0.0",
        "run_id": run_id,
        "validation_status": "accepted",
        "validation_errors": [],
    }


def seed_for(
    cue: dict[str, Any], trigger: dict[str, Any], lures: list[dict[str, Any]], run_id: str
) -> dict[str, Any]:
    return {
        "seed_id": "seed_candidate_0001",
        "family_id": "family_candidate_0001",
        "split": trigger["split"],
        "source_group_id": trigger["source_group_id"],
        "intention": {
            "intention_id": "int_candidate_0001",
            "action_content": "Put the prepared meal into a container.",
        },
        "primary_cue_type": cue["cue_type"],
        "trigger_atom_id": trigger["atom_id"],
        "lure_atom_ids": [lures[0]["atom_id"], lures[1]["atom_id"]],
        "trigger_predicate": cue["normalized_predicate"],
        "valid_window": {
            "relative_to": "trigger_event",
            "start_offset_sec": 0,
            "end_offset_sec": 60,
        },
        "terminal_silent_conditions": ["completed", "cancelled", "expired", "already_reminded"],
        "counterfactual_negative_type": "cancelled",
        "rule_ids": ["rule_candidate_0001"],
        "current_trigger_leakage_checked": True,
        "audit": {
            "status": "candidate",
            "reason": "Synthetic test candidate pending human review.",
            "human_reviewer": None,
            "model_audit_run_id": None,
        },
        "generation_record": {
            "run_id": run_id,
            "model_id": "qwen3.7-plus-2026-05-26",
            "prompt_version": "seed_generator_v1",
            "schema_version": "v1.0.0",
        },
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def write_success(path: Path, artifact: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "artifact_path": str(artifact.resolve()),
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "row_count": len(artifact.read_text(encoding="utf-8").splitlines()),
                "contract_version": "v1.1.0",
                "config_version": "v1.1.0",
                "schema_versions": {"fixture": "v1.1.0"},
                "generated_at": "2026-08-31T00:00:00Z",
                "upstream_hashes": {},
            }
        ),
        encoding="utf-8",
    )


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_cue_request_uses_fixed_model_and_strict_schema() -> None:
    script = load_script("05_extract_cues.py")
    atom = source_atom(1, "A person starts cooking in a kitchen.")
    schema = json.loads((ROOT / "schemas" / "cue_candidate.schema.json").read_text(encoding="utf-8"))
    settings = script.Settings("https://example.invalid/v1", "DASHSCOPE_API_KEY", "cn-beijing", 512, 2, 500, 300, 1_000_000, {
        "root": "cues/shards", "input_manifest_suffix": ".input.jsonl", "output_suffix": ".output.jsonl",
        "ledger_suffix": ".ledger.jsonl", "completion_suffix": ".complete.json", "merge_order": "numeric_shard_index_ascending",
    })
    request = script.build_chat_request(
        prompt="synthetic unit-test prompt", schema=schema, atom=atom, run_id="run_cue_fixture", settings=settings
    )
    assert request["model"] == "qwen3.7-flash-2026-07-15"
    assert request["temperature"] == 0
    assert request["max_tokens"] == 512
    assert request["enable_thinking"] is False
    assert request["response_format"]["type"] == "json_schema"
    assert request["response_format"]["json_schema"]["strict"] is True
    assert "DASHSCOPE_API_KEY" not in json.dumps(request)


def shard_settings(script: ModuleType) -> Any:
    return script.Settings(
        "https://example.invalid/v1", "DASHSCOPE_API_KEY", "cn-beijing", 512, 2, 2, 300, 1_000_000,
        {
            "root": "cues/shards",
            "input_manifest_suffix": ".input.jsonl",
            "output_suffix": ".output.jsonl",
            "ledger_suffix": ".ledger.jsonl",
            "completion_suffix": ".complete.json",
            "merge_order": "numeric_shard_index_ascending",
        },
    )


def mark_complete(script: ModuleType, manifest: dict[str, Any], run_root: Path, settings: Any) -> None:
    file_paths = script.paths(run_root, manifest, settings.layout)
    script.write_jsonl(file_paths["manifest"], manifest["atoms"])
    script.write_jsonl(file_paths["output"], [])
    script.write_json(
        file_paths["complete"],
        {
            "shard_id": manifest["shard_id"],
            "source_atoms_sha256": manifest["source_atoms_sha256"],
            "input_manifest_sha256": script.sha256_file(file_paths["manifest"]),
            "output_sha256": script.sha256_file(file_paths["output"]),
        },
    )


def test_cue_semantic_validation_rejects_non_traceable_span() -> None:
    script = load_script("05_extract_cues.py")
    atom = source_atom(1, "A person starts cooking in a kitchen.")
    candidate = cue_for(atom)
    script.validate_cue_semantics(atom, candidate)
    candidate["supporting_text_span"] = "starts driving"
    with pytest.raises(script.ContractError, match="supporting_text_span"):
        script.validate_cue_semantics(atom, candidate)


def test_usage_ledger_extracts_only_numeric_usage_without_response_content() -> None:
    script = load_script("05_extract_cues.py")
    result = script.response_usage({"usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}, "choices": [{"message": {"content": "private model content"}}]})
    assert result == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
    assert "private" not in json.dumps(result)


def test_success_marker_hash_gate_rejects_tampered_fixture(tmp_path: Path) -> None:
    script = load_script("05_extract_cues.py")
    artifact = tmp_path / "source_video_atoms.jsonl"
    write_jsonl(artifact, [source_atom(1, "A person starts cooking in a kitchen.")])
    marker = tmp_path / "SOURCE_ATOMS_SUCCESS.json"
    write_success(marker, artifact)
    script.require_verified_success(artifact, marker, "v1.1.0")
    artifact.write_text("{}\n", encoding="utf-8")
    with pytest.raises(script.ContractError, match="SHA256"):
        script.require_verified_success(artifact, marker, "v1.1.0")


def test_success_marker_accepts_project_relative_path_and_rejects_escape(tmp_path: Path) -> None:
    script = load_script("05_extract_cues.py")
    script.ROOT = tmp_path
    artifact = tmp_path / "source" / "source_video_atoms.jsonl"
    artifact.parent.mkdir()
    write_jsonl(artifact, [source_atom(1, "A person starts cooking in a kitchen.")])
    marker = tmp_path / "source" / "SOURCE_ATOMS_SUCCESS.json"
    write_success(marker, artifact)
    contents = json.loads(marker.read_text(encoding="utf-8"))
    contents["artifact_path"] = "source/source_video_atoms.jsonl"
    marker.write_text(json.dumps(contents), encoding="utf-8")
    script.require_verified_success(artifact, marker, "v1.1.0")
    contents["artifact_path"] = "../source/source_video_atoms.jsonl"
    marker.write_text(json.dumps(contents), encoding="utf-8")
    with pytest.raises(script.ContractError, match="artifact_path"):
        script.require_verified_success(artifact, marker, "v1.1.0")


def test_shards_are_ordered_resumable_and_incomplete_merge_is_rejected(tmp_path: Path) -> None:
    script = load_script("05_extract_cues.py")
    settings = shard_settings(script)
    atoms = [source_atom(3, "three starts cooking"), source_atom(1, "one starts cooking"), source_atom(2, "two starts cooking")]
    manifests = script.manifests(atoms, "source-hash", settings.shard_size, "run_fixture")
    assert [[item["atom_id"] for item in manifest["atoms"]] for manifest in manifests] == [
        ["src_SYNTH_DAY1_000001", "src_SYNTH_DAY1_000002"], ["src_SYNTH_DAY1_000003"]
    ]
    run_root = tmp_path / "run_fixture"
    mark_complete(script, manifests[0], run_root, settings)
    assert [item["shard_id"] for item in script.pending_shards(manifests, run_root, settings.layout)] == ["shard_00001"]
    with pytest.raises(script.ContractError, match="禁止合并"):
        script.merge_completed_shards(manifests, run_root, settings.layout, tmp_path / "merged.jsonl")
    mark_complete(script, manifests[1], run_root, settings)
    assert script.pending_shards(manifests, run_root, settings.layout) == []
    assert script.merge_completed_shards(manifests, run_root, settings.layout, tmp_path / "merged.jsonl") == 0


def test_ledger_excludes_raw_response_and_preflight_is_read_only(tmp_path: Path) -> None:
    script = load_script("05_extract_cues.py")
    settings = shard_settings(script)
    ledger = tmp_path / "ledger.jsonl"
    script.append_ledger(ledger, {"status": "failed", "usage": {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}, "failure_summary": "TimeoutError: 60 seconds", "raw_response_saved": False})
    assert "response body" not in ledger.read_text(encoding="utf-8")
    atom = source_atom(1, "A person starts cooking in a kitchen.")
    schema = json.loads((ROOT / "schemas" / "cue_candidate.schema.json").read_text(encoding="utf-8"))
    report = script.preflight([atom], {"sha256": "source-hash"}, "synthetic prompt", schema, "run_fixture", settings)
    assert report["network_called"] is False
    assert report["credentials_read"] is False
    assert report["formal_outputs_written"] is False
    assert not list(tmp_path.glob("**/*cue_library*"))


def test_frozen_execution_configuration_is_loaded() -> None:
    script = load_script("05_extract_cues.py")
    settings = script.load_runtime_settings(ROOT / "config" / "model_registry.yaml")
    assert (settings.shard_size, settings.max_tokens, settings.max_retries, settings.rpm, settings.tpm) == (500, 512, 2, 300, 1_000_000)


def test_retrieval_returns_two_distinct_same_split_lures() -> None:
    script = load_script("06_retrieve_trigger_lures.py")
    trigger = source_atom(1, "A person starts cooking in a kitchen.")
    lures = [
        source_atom(2, "A person is cooking a meal in a kitchen."),
        source_atom(3, "A person cleans cooking tools in a kitchen."),
        source_atom(4, "A person closes a kitchen cabinet."),
    ]
    cue = cue_for(trigger)
    rows = script.build_lure_sets(
        atoms=[trigger, *lures], cues=[cue], lures_per_trigger=2, run_id="run_retrieval_fixture"
    )
    assert len(rows) == 1
    assert len(rows[0]["lure_atom_ids"]) == 2
    assert trigger["atom_id"] not in rows[0]["lure_atom_ids"]
    assert all(atom_id in {item["atom_id"] for item in lures} for atom_id in rows[0]["lure_atom_ids"])
    assert rows[0]["split"] == "train"
    validator = script.jsonschema.Draft202012Validator(script.TRIGGER_LURE_SCHEMA)
    script.validate_rows(rows, validator, "手写检索集合")
    script.validate_retrieval_set_semantics(rows)


def test_seed_request_and_hard_conditions_use_synthetic_fixture() -> None:
    script = load_script("07_generate_seed_candidates.py")
    trigger = source_atom(1, "A person starts cooking in a kitchen.")
    lures = [
        source_atom(2, "A person is cooking a meal in a kitchen."),
        source_atom(3, "A person cleans cooking tools in a kitchen."),
    ]
    cue = cue_for(trigger)
    run_id = "run_seed_fixture"
    identifiers = script.seed_identifiers(1)
    schema = json.loads((ROOT / "schemas" / "reminder_seed.schema.json").read_text(encoding="utf-8"))
    request = script.build_chat_request(
        prompt="synthetic unit-test prompt",
        schema=schema,
        cue=cue,
        trigger=trigger,
        lures=lures,
        identifiers=identifiers,
        run_id=run_id,
        thinking_settings={"thinking_enabled": True, "reasoning_effort": "medium"},
    )
    assert request["model"] == "qwen3.7-plus-2026-05-26"
    assert request["response_format"]["json_schema"]["strict"] is True
    assert request["enable_thinking"] is True
    candidate = seed_for(cue, trigger, lures, run_id)
    script.validate_rows([candidate], script.load_validator(ROOT / "schemas" / "reminder_seed.schema.json"), "Seed")
    script.validate_seed_semantics(
        seed=candidate,
        cue=cue,
        trigger=trigger,
        lures=lures,
        identifiers=identifiers,
        run_id=run_id,
    )
    candidate["terminal_silent_conditions"] = ["completed"]
    with pytest.raises(script.ContractError, match="终止不触发条件"):
        script.validate_seed_semantics(
            seed=candidate,
            cue=cue,
            trigger=trigger,
            lures=lures,
            identifiers=identifiers,
            run_id=run_id,
        )
