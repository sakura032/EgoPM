"""第 05--07 阶段的无 API 合成合同测试。

职责：验证 Cue v2 的打包、血缘、恢复和账本合同，并保留第 06/07 阶段同 split 诱饵与
种子终止静默条件的回归。输入仅为进程内字典和 pytest 临时目录；输出是断言结果，位于
正式 Cue 生产前的开发阶段。所有 HTTP 都替换为假的本地响应，不读取真实密钥或联网。
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_script(filename: str = "05_extract_cues.py") -> ModuleType:
    """在独立模块命名空间载入脚本，避免测试对全局 ROOT 的替换相互污染。"""

    path = ROOT / "scripts" / filename
    module_name = f"synthetic_{path.stem}_{id(path)}_{len(sys.modules)}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def source_atom(index: int, text: str = "A person starts cooking.", split: str = "train") -> dict[str, Any]:
    """构造通过 v1.1 Source Schema 的微型 Atom，绝不计入正式数据。"""

    suffix = f"{index:06d}"
    return {
        "atom_id": f"src_SYNTH_DAY1_{suffix}",
        "atom_kind": "source_video_atom",
        "atom_stage": "final",
        "participant_source_id": "SYNTH",
        "source_day": "DAY1",
        "session_id": "SYNTH_DAY1_SESSION",
        "source_group_id": f"group_{suffix}",
        "world_event_id": None,
        "source_srt_paths": {"transcript": "synthetic.srt", "dense_caption": "synthetic.srt"},
        "source_video_path": None,
        "video_mapping_status": "pending",
        "local_start_sec": float(index),
        "local_end_sec": float(index + 1),
        "normalized_start_sec": float(index),
        "normalized_end_sec": float(index + 1),
        "transcript_segment_ids": [f"tr_{suffix}"],
        "dense_caption_segment_ids": [f"dc_{suffix}"],
        "transcript": text,
        "dense_caption": text,
        "visible_text": text,
        "modality_coverage": "both",
        "provenance": "egolife_srt",
        "split": split,
    }


def inference_response(count: int) -> dict[str, Any]:
    """构造 v2.2 合法紧凑响应；仅在内存中模拟服务端推理字段。"""

    return {
        "items": [
            {
                "n": index, "t": "A", "p": [["A", "^", "cooking"]], "x": "starts cooking",
                "c": 80, "v": "A",
            }
            for index in range(count)
        ]
    }


def write_source_fixture(module: ModuleType, root: Path, atoms: list[dict[str, Any]]) -> tuple[Path, Path]:
    """构造带项目内相对路径 SUCCESS 的 Source fixture，验证路径解析而不读真实 Source。"""

    artifact = root / "source" / "source_video_atoms.jsonl"
    marker = root / "source" / "SOURCE_ATOMS_SUCCESS.json"
    module.atomic_write_jsonl(artifact, atoms)
    module.atomic_write_json(
        marker,
        {
            "artifact_path": "source/source_video_atoms.jsonl",
            "sha256": module.sha256_file(artifact),
            "row_count": len(atoms),
            "contract_version": "v1.1.0",
            "config_version": "v1.1.0",
            "schema_versions": {"source_video_atom": "v1.1.0"},
        },
    )
    return artifact, marker


def test_v22_request_only_contains_item_index_and_text() -> None:
    """紧凑协议仍不得让模型看到受控字段，固定五条包上限为 480 token。"""

    module = load_script()
    settings = module.settings_from_registry(ROOT / "config/model_registry.yaml")
    schema = module.read_json(ROOT / "schemas/cue_inference_batch_compact_v1.schema.json")
    assert len((ROOT / "prompts/cue_extractor_v3_compact.md").read_bytes()) <= 450
    request = module.build_request("测试", schema, [source_atom(index) for index in range(1, 6)], settings)

    assert request["model"] == "qwen3.7-flash-2026-07-15"
    assert request["enable_thinking"] is False
    assert request["max_tokens"] == 480
    user_payload = json.loads(request["messages"][1]["content"])
    assert user_payload == {
        "items": [{"item_index": index, "text": "A person starts cooking."} for index in range(5)]
    }
    assert "atom_id" not in request["messages"][1]["content"]


def test_adaptive_packages_are_ordered_limited_and_batch_grouped() -> None:
    """六条乱序 Atom 必须变成五加一两包，并稳定按 atom_id 排列。"""

    module = load_script()
    settings = module.settings_from_registry(ROOT / "config/model_registry.yaml")
    schema = module.read_json(ROOT / "schemas/cue_inference_batch_compact_v1.schema.json")
    atoms = module.ordered_atoms([source_atom(index) for index in (3, 1, 2, 4, 5, 6)])
    manifests = module.build_packages(atoms, "source", "p", schema, settings, "protocol", "run")

    assert [len(manifest["atoms"]) for manifest in manifests] == [5, 1]
    assert [item["atom_id"] for manifest in manifests for item in manifest["atoms"]] == [
        f"src_SYNTH_DAY1_{index:06d}" for index in range(1, 7)
    ]
    atom_by_id = {atom["atom_id"]: atom for atom in atoms}
    assert all(
        module.request_utf8_bytes("p", schema, [atom_by_id[item["atom_id"]] for item in manifest["atoms"]], settings)
        <= 24000
        for manifest in manifests
    )
    tasks = module.build_batch_tasks(manifests, {atom["atom_id"]: atom for atom in atoms}, "p", schema, settings)
    assert len(tasks) == 1 and tasks[0]["request_count"] == 2
    assert all(line["body"]["enable_thinking"] is False for line in tasks[0]["request_lines"])
    assert tasks[0]["batch_input_sha256"] and tasks[0]["remote_file_id"] is None


def test_compact_parse_backfills_defaults_and_rejects_cross_atom_text() -> None:
    """模型私传 atom_id 或引用另一个 Atom 的片段都必须在最终 Cue 前被拒绝。"""

    module = load_script()
    settings = module.settings_from_registry(ROOT / "config/model_registry.yaml")
    inference_validator = module.load_validator(ROOT / "schemas/cue_inference_batch_compact_v1.schema.json")
    cue_validator = module.load_validator(ROOT / "schemas/cue_candidate.schema.json")
    atoms = [source_atom(1), source_atom(2)]
    cues = module.parse_inference_items(
        inference_response(2), atoms, inference_validator, cue_validator, settings, "run_synthetic"
    )
    assert [cue["atom_id"] for cue in cues] == [atom["atom_id"] for atom in atoms]
    assert all(cue["prompt_version"] == "cue_extractor_v3_compact" for cue in cues)
    assert all(cue["entities"] == [] and cue["confidence"] == 0.8 for cue in cues)

    private = inference_response(2)
    private["items"][0]["atom_id"] = "src_private"
    with pytest.raises(module.ContractError):
        module.parse_inference_items(private, atoms, inference_validator, cue_validator, settings, "run")
    cross_atom = inference_response(2)
    cross_atom["items"][0]["x"] = "other atom"
    with pytest.raises(module.ContractError, match="可见文本"):
        module.parse_inference_items(cross_atom, atoms, inference_validator, cue_validator, settings, "run")


def test_protocol_hash_matches_t4_complete_canonical_payload() -> None:
    """第 05 步协议哈希必须逐字节等同 T4 的完整 canonical payload。"""

    module = load_script()
    registry_path = ROOT / "config/model_registry.yaml"
    registry = module.yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    settings = module.settings_from_registry(registry_path)
    prompt = ROOT / "prompts/cue_extractor_v3_compact.md"
    inference_schema = ROOT / "schemas/cue_inference_batch_compact_v1.schema.json"
    cue = registry["models"]["cue_extraction"]
    expected = {
        "payload_version": cue["execution"]["protocol_hash_payload_version"],
        "model": {
            "model_id": cue["model_id"],
            "thinking_enabled": cue["thinking_enabled"],
            "reasoning_effort": cue["reasoning_effort"],
            "temperature": cue["temperature"],
            "prompt_version": cue["prompt_version"],
            "final_cue_schema": cue["schema"],
            "final_cue_schema_version": cue["schema_version"],
        },
        "service": {
            "endpoint": registry["default_endpoint"],
            "region": registry["default_region"],
            "credential_policy": registry["credential_policy"],
            "raw_response_policy": registry["raw_response_policy"],
        },
        "execution": cue["execution"],
        "cue_prompt_sha256": module.sha256_file(prompt),
        "cue_inference_schema_sha256": module.sha256_file(inference_schema),
    }
    assert module.protocol_hash(settings, prompt, inference_schema) == module.canonical_sha256(expected)


def test_complete_requires_exact_manifest_and_all_hashes(tmp_path: Path) -> None:
    """同 package_id 的不同 run 清单或篡改账本都不能被恢复逻辑跳过。"""

    module = load_script()
    settings = module.settings_from_registry(ROOT / "config/model_registry.yaml")
    schema = module.read_json(ROOT / "schemas/cue_inference_batch_compact_v1.schema.json")
    manifest = module.build_packages([source_atom(1)], "source", "p", schema, settings, "protocol", "run_a")[0]
    files = module.package_paths(tmp_path, manifest, settings.layout)
    module.atomic_write_jsonl(files["manifest"], [manifest])
    module.atomic_write_jsonl(files["result"], [])
    module.atomic_write_jsonl(files["ledger"], [{"status": "success"}])
    module.atomic_write_json(
        files["complete"],
        {
            "package_id": manifest["package_id"],
            "source_atoms_sha256": "source",
            "cue_execution_protocol_sha256": "protocol",
            "input_manifest_sha256": module.sha256_file(files["manifest"]),
            "result_sha256": module.sha256_file(files["result"]),
            "ledger_sha256": module.sha256_file(files["ledger"]),
        },
    )
    assert module.is_complete(manifest, files)
    changed = copy.deepcopy(manifest)
    changed["run_id"] = "run_b"
    assert not module.is_complete(changed, files)
    files["ledger"].write_text('{"status":"tampered"}\n', encoding="utf-8")
    assert not module.is_complete(manifest, files)


def test_batch_result_success_line_failure_and_quarantine_do_not_persist_raw_response() -> None:
    """成功、行级失败和本地隔离均只产出无正文结果或账本，隔离项不得自动重跑。"""

    module = load_script()
    settings = module.settings_from_registry(ROOT / "config/model_registry.yaml")
    schema = module.read_json(ROOT / "schemas/cue_inference_batch_compact_v1.schema.json")
    atoms = [source_atom(1)]
    manifest = module.build_packages(atoms, "source", "p", schema, settings, "protocol", "run")[0]
    task = module.build_batch_tasks([manifest], {atoms[0]["atom_id"]: atoms[0]}, "p", schema, settings)[0]
    mapping = {manifest["batch_custom_id"]: manifest}
    validators = (module.load_validator(ROOT / "schemas/cue_inference_batch_compact_v1.schema.json"), module.load_validator(ROOT / "schemas/cue_candidate.schema.json"))
    success = {"custom_id": manifest["batch_custom_id"], "response": {"body": {"choices": [{"message": {"content": json.dumps(inference_response(1))}}], "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}}}}
    state, cues, event = module.parse_batch_result_line(success, mapping, {atoms[0]["atom_id"]: atoms[0]}, task, *validators, settings)
    assert state == "validated" and len(cues) == 1 and event["usage"]["total_tokens"] == 18
    failed, _, failure_event = module.parse_batch_result_line({"custom_id": manifest["batch_custom_id"], "error": {"message": "private"}}, mapping, {atoms[0]["atom_id"]: atoms[0]}, task, *validators, settings)
    assert failed == "line_failed_requeue" and failure_event["raw_response_saved"] is False
    invalid = copy.deepcopy(success)
    invalid["response"]["body"]["choices"][0]["message"]["content"] = json.dumps({"items": []})
    quarantined, _, quarantine_event = module.parse_batch_result_line(invalid, mapping, {atoms[0]["atom_id"]: atoms[0]}, task, *validators, settings)
    assert quarantined == "quarantine" and quarantine_event["outcome"] == "local_validation_quarantine"
    assert "starts cooking" not in json.dumps(event, ensure_ascii=False)
    module.validate_batch_ledger_events([event], settings)
    assert module.requeueable_batch_custom_ids([failure_event], settings) == {manifest["batch_custom_id"]}
    assert module.requeueable_batch_custom_ids([quarantine_event], settings) == set()
    with pytest.raises(module.ContractError, match="多个终态"):
        module.validate_batch_ledger_events([event, failure_event], settings)


def test_default_preflight_is_read_only_and_execute_is_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """默认预检不得创建运行目录；显式执行必须在密钥或网络之前被合同阻断。"""

    module = load_script()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    atoms = [source_atom(1)]
    source_path, source_marker = write_source_fixture(module, tmp_path, atoms)
    common = {
        "model_registry": ROOT / "config/model_registry.yaml",
        "source_atoms": source_path,
        "source_success": source_marker,
        "source_schema": ROOT / "schemas/source_video_atom.schema.json",
        "cue_schema": ROOT / "schemas/cue_candidate.schema.json",
        "inference_schema": ROOT / "schemas/cue_inference_batch_compact_v1.schema.json",
        "prompt": ROOT / "prompts/cue_extractor_v3_compact.md",
        "run_root": tmp_path / "runs",
        "output": tmp_path / "cue_library.jsonl",
        "success_marker": tmp_path / "CUE_LIBRARY_SUCCESS.json",
        "run_id": "run_synthetic",
        "rerun_failed_packages": False,
    }
    assert module.run(module.argparse.Namespace(**common, execute=False)) == 0
    assert not common["run_root"].exists() and not common["success_marker"].exists()
    with pytest.raises(module.ContractError, match="项目目录内"):
        module.managed_relative_path(tmp_path.parent / "outside" / "cue_library.jsonl")

    with pytest.raises(module.ContractError, match="仅允许无 API 预检"):
        module.run(module.argparse.Namespace(**common, execute=True))
    assert not common["success_marker"].exists()


def test_synthetic_batch_task_manifest_only_has_metadata(tmp_path: Path) -> None:
    """任务总清单可保留 custom_id 映射，但不得夹带 source_text、请求 body 或模型响应。"""

    module = load_script()
    settings = module.settings_from_registry(ROOT / "config/model_registry.yaml")
    schema = module.read_json(ROOT / "schemas/cue_inference_batch_compact_v1.schema.json")
    atoms = [source_atom(1)]
    manifests = module.build_packages(atoms, "source", "p", schema, settings, "protocol", "run")
    tasks = module.build_batch_tasks(manifests, {atoms[0]["atom_id"]: atoms[0]}, "p", schema, settings)
    destination = tmp_path / "batch_tasks_manifest.jsonl"
    module.write_synthetic_batch_task_manifest(destination, tasks, manifests)
    row = module.read_jsonl(destination)[0]
    assert row["custom_id_to_package_id"] == {manifests[0]["batch_custom_id"]: manifests[0]["package_id"]}
    encoded = destination.read_text(encoding="utf-8")
    assert "source_text" not in encoded and "starts cooking" not in encoded and '"body"' not in encoded


def test_eight_wave_authorization_requires_budget_hash_and_retention_consent(tmp_path: Path) -> None:
    """执行前核验只读授权文件；缺少同意或预算时绝不能把波次推进到联网阶段。"""

    module = load_script()
    settings = module.settings_from_registry(ROOT / "config/model_registry.yaml")
    report = {
        "package_count": 75,
        "cue_execution_protocol_sha256": "protocol",
        "cny_upper_bound_successful_requests_only": {"total_cny_upper_bound": 37.5},
        "batch_task_manifests": [{"request_count": 1} for _ in range(75)],
    }
    authorization = tmp_path / "authorization.json"
    module.atomic_write_json(authorization, {
        "authorization_version": "v1.0.0", "approved": True, "approved_by": "synthetic",
        "approved_at": "2026-09-05T00:00:00Z", "maximum_total_cny": 40.0,
        "allowed_wave_indexes": [1], "source_atoms_sha256": "source",
        "cue_execution_protocol_sha256": "protocol",
        "accept_remote_text_retention_until_t4_cue_qa": True,
        "accept_quarantine_manual_review_only": True,
    })
    readiness = module.execution_readiness_report(report, settings, "source", 1, authorization)
    assert readiness["batch_task_indexes"] == [0]
    assert readiness["batch_task_count"] == 1
    assert readiness["authorization_status"] == "valid"
    rejected = module.read_json(authorization)
    rejected["maximum_total_cny"] = 0.1
    module.atomic_write_json(authorization, rejected)
    with pytest.raises(module.ContractError, match="预算不足"):
        module.execution_readiness_report(report, settings, "source", 1, authorization)


def cue_for(atom: dict[str, Any]) -> dict[str, Any]:
    """构造第 06/07 既有回归使用的合成 accepted Cue。"""

    return {
        "cue_id": f"cue_{atom['atom_id'].removeprefix('src_')}",
        "atom_id": atom["atom_id"],
        "split": atom["split"],
        "entities": ["kitchen"],
        "scene_type": "kitchen",
        "activity_type": "cooking",
        "cue_type": "activity",
        "normalized_predicate": {"all_of": [{"slot": "activity", "operator": "starts", "value": "cooking"}]},
        "supporting_text_span": "starts cooking",
        "source_text": atom["visible_text"],
        "confidence": 0.9,
        "ambiguity_reason": None,
        "model_id": "qwen3.7-flash-2026-07-15",
        "prompt_version": "cue_extractor_v1",
        "schema_version": "v1.0.0",
        "run_id": "run_fixture",
        "validation_status": "accepted",
        "validation_errors": [],
    }


def test_retrieval_returns_two_distinct_same_split_lures() -> None:
    """保留第 06 阶段的同 split、非触发项、至少两条诱饵回归。"""

    module = load_script("06_retrieve_trigger_lures.py")
    trigger = source_atom(1, "A person starts cooking in a kitchen.")
    lures = [
        source_atom(2, "A person is cooking a meal in a kitchen."),
        source_atom(3, "A person cleans cooking tools in a kitchen."),
        source_atom(4, "A person closes a kitchen cabinet."),
    ]
    rows = module.build_lure_sets(
        atoms=[trigger, *lures],
        cues=[cue_for(trigger)],
        lures_per_trigger=2,
        run_id="run_retrieval_fixture",
    )
    assert len(rows) == 1 and len(rows[0]["lure_atom_ids"]) == 2
    assert trigger["atom_id"] not in rows[0]["lure_atom_ids"]
    assert rows[0]["split"] == "train"
    module.validate_rows(rows, module.jsonschema.Draft202012Validator(module.TRIGGER_LURE_SCHEMA), "手写检索集合")
    module.validate_retrieval_set_semantics(rows)


def test_seed_request_and_terminal_silence_conditions() -> None:
    """保留第 07 阶段的严格请求与四种终止不触发条件回归。"""

    module = load_script("07_generate_seed_candidates.py")
    trigger = source_atom(1, "A person starts cooking in a kitchen.")
    lures = [source_atom(2, "A person is cooking a meal in a kitchen."), source_atom(3, "A person cleans cooking tools in a kitchen.")]
    cue = cue_for(trigger)
    identifiers = module.seed_identifiers(1)
    schema = json.loads((ROOT / "schemas/reminder_seed.schema.json").read_text(encoding="utf-8"))
    request = module.build_chat_request(
        prompt="synthetic",
        schema=schema,
        cue=cue,
        trigger=trigger,
        lures=lures,
        identifiers=identifiers,
        run_id="run_seed",
        thinking_settings={"thinking_enabled": True, "reasoning_effort": "medium"},
    )
    assert request["model"] == "qwen3.7-plus-2026-05-26" and request["enable_thinking"] is True
    candidate = {
        "seed_id": identifiers["seed_id"], "family_id": identifiers["family_id"], "split": "train", "source_group_id": trigger["source_group_id"],
        "intention": {"intention_id": identifiers["intention_id"], "action_content": "Put the prepared meal into a container."},
        "primary_cue_type": "activity", "trigger_atom_id": trigger["atom_id"], "lure_atom_ids": [lure["atom_id"] for lure in lures],
        "trigger_predicate": cue["normalized_predicate"], "valid_window": {"relative_to": "trigger_event", "start_offset_sec": 0, "end_offset_sec": 60},
        "terminal_silent_conditions": ["completed", "cancelled", "expired", "already_reminded"], "counterfactual_negative_type": "cancelled",
        "rule_ids": ["rule_candidate_0001"], "current_trigger_leakage_checked": True,
        "audit": {"status": "candidate", "reason": "Synthetic candidate pending review.", "human_reviewer": None, "model_audit_run_id": None},
        "generation_record": {"run_id": "run_seed", "model_id": "qwen3.7-plus-2026-05-26", "prompt_version": "seed_generator_v1", "schema_version": "v1.0.0"},
    }
    module.validate_rows([candidate], module.load_validator(ROOT / "schemas/reminder_seed.schema.json"), "Seed")
    module.validate_seed_semantics(
        seed=candidate,
        cue=cue,
        trigger=trigger,
        lures=lures,
        identifiers=identifiers,
        run_id="run_seed",
    )
    candidate["terminal_silent_conditions"] = ["completed"]
    with pytest.raises(module.ContractError, match="终止不触发条件"):
        module.validate_seed_semantics(
            seed=candidate,
            cue=cue,
            trigger=trigger,
            lures=lures,
            identifiers=identifiers,
            run_id="run_seed",
        )
