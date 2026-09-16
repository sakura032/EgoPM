"""第 05 阶段实时 Cue 执行器离线合同测试。

输入是冻结配置、合成 Atom 和假传输；输出是实时状态与无正文账本断言。本测试不读密钥、不联网。
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any
from types import SimpleNamespace
from urllib import error as urlerror

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

# 本文件覆盖 V3.6 realtime、worker 与 BGE 协议验收历史；当前 Cue v2 使用独立轻量测试。
pytestmark = pytest.mark.legacy_v36


def module() -> Any:
    """隔离加载生产脚本，确保假传输不会访问真实服务。"""
    spec = importlib.util.spec_from_file_location("synthetic_realtime", ROOT / "scripts/05_extract_cues.py")
    assert spec and spec.loader
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


def atom(index: int) -> dict[str, Any]:
    """构造最小合成 Source Atom，仅用于第 05 阶段单元测试。"""
    return {
        "atom_id": f"src_a_{index:03d}", "split": "train",
        "transcript": f"转录第{index}条文本", "dense_caption": f"描述第{index}条文本",
        "visible_text": f"第{index}条文本", "video_id": "v", "source_srt_path": "source/x.srt",
        "start_ms": 0, "end_ms": 1, "source_segment_ids": ["s"],
    }


def setup(value: Any) -> tuple[Any, Any, dict[str, Any], dict[str, dict[str, Any]]]:
    """读取实时配置并创建不带任何 Batch 身份字段的独立 package。"""
    settings, policy = value.realtime_policy_from_registry(ROOT / "config/model_registry.yaml")
    rows = [atom(1)]
    base = value.package_manifest(rows, "source", "protocol", "synthetic", 0, 0)
    manifest = value.realtime_manifest(base)
    return settings, policy, manifest, {"src_a_001": rows[0]}


def response(valid: bool = True, costly: bool = False) -> dict[str, Any]:
    """生成内存中的紧凑模型响应；不保存服务端原始文本。"""
    payload = {"items": [{"n": 0, "f": "V", "start": 0, "end": 5, "p": [["A", "=", "活动"]], "c": 80, "v": "A"}]} if valid else {"items": []}
    amount = 1_000_000 if costly else 10
    return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}], "usage": {"prompt_tokens": amount, "completion_tokens": amount, "total_tokens": amount * 2}}


def buckets(value: Any, policy: Any) -> tuple[Any, Any]:
    """创建即时令牌桶，测试无需真实等待。"""
    return value.TokenBucket(policy.requests_per_minute), value.TokenBucket(policy.tokens_per_minute)


@pytest.mark.legacy_v36
def test_realtime_config_is_frozen() -> None:
    """模型、包大小、输出上限、重试、价格和传输必须来自 T0 冻结配置。"""
    value = module()
    settings, policy, *_ = setup(value)
    assert (settings.model_id, settings.thinking_enabled, settings.temperature) == ("qwen3.7-flash", False, 0)
    assert (settings.maximum_atoms, settings.output_tokens_per_atom, settings.max_retries) == (5, 96, 2)
    assert (policy.request_endpoint, policy.input_price_cny_per_million_tokens, policy.output_price_cny_per_million_tokens) == ("/chat/completions", 0.2, 0.8)


@pytest.mark.legacy_v36
def test_token_bucket_waits_under_fake_clock() -> None:
    """客户端 RPM/TPM 桶耗尽后必须等待补充，不能无节制发送请求。"""
    value = module(); now = [0.0]; sleeps: list[float] = []
    bucket = value.TokenBucket(2, clock=lambda: now[0], sleep=lambda seconds: (sleeps.append(seconds), now.__setitem__(0, now[0] + seconds)))
    bucket.acquire(2); bucket.acquire(1)
    assert sleeps == [30.0]


@pytest.mark.legacy_v36
def test_transient_retry_success_and_recovery_skip(tmp_path: Path) -> None:
    """临时 429 可重试，完成包恢复时必须跳过且不得再次调用传输器。"""
    value = module(); settings, policy, manifest, rows = setup(value)
    class Fake:
        calls = 0
        def complete(self, _body: dict[str, Any], _policy: Any) -> dict[str, Any]:
            self.calls += 1
            if self.calls == 1: raise value.RealtimeServiceError(429, True)
            return response()
    fake = Fake(); root = tmp_path / "realtime"
    result = value.execute_realtime_package(manifest, rows, "p", {"type": "object"}, settings, policy, fake, root, 1.0, *buckets(value, policy))
    assert result[0] == "validated_success" and result[2]["retry_count"] == 1 and fake.calls == 2
    skipped = value.execute_realtime_package(manifest, rows, "p", {"type": "object"}, settings, policy, fake, root, 1.0, *buckets(value, policy))
    assert skipped == ("recovered_skip", 0.0, {"outcome": "recovered_skip"})
    assert "choices" not in (root / "packages" / manifest["package_id"] / "realtime_state.json").read_text(encoding="utf-8")


@pytest.mark.legacy_v36
def test_quarantine_budget_and_batch_mixing_are_stopped(tmp_path: Path) -> None:
    """本地验证失败隔离不重试，预算超限熔断，实时状态拒绝 Batch 根和字段。"""
    value = module(); settings, policy, manifest, rows = setup(value)
    class Invalid:
        calls = 0
        def complete(self, _body: dict[str, Any], _policy: Any) -> dict[str, Any]: self.calls += 1; return response(False)
    invalid = Invalid()
    result = value.execute_realtime_package(manifest, rows, "p", {"type": "object"}, settings, policy, invalid, tmp_path / "realtime", 1.0, *buckets(value, policy))
    assert result[0] == "needs_item_audit" and invalid.calls == 2 and result[2]["retry_eligible"] is False
    recovered = value.execute_realtime_package(manifest, rows, "p", {"type": "object"}, settings, policy, invalid, tmp_path / "realtime", 1.0, *buckets(value, policy))
    assert recovered == ("recovered_item_audit", 0.0, {"outcome": "recovered_item_audit"}) and invalid.calls == 2
    class Costly:
        def complete(self, _body: dict[str, Any], _policy: Any) -> dict[str, Any]: return response(costly=True)
    result = value.execute_realtime_package(manifest, rows, "p", {"type": "object"}, settings, policy, Costly(), tmp_path / "other", 0.01, *buckets(value, policy))
    assert result[0] == "budget_stopped"
    with pytest.raises(value.ContractError, match="Batch"): value.realtime_package_state_path(tmp_path / "batch", manifest)
    with pytest.raises(value.ContractError, match="Batch"): value.validate_realtime_ledger_event({**result[2], "batch_custom_id": "x"})


@pytest.mark.legacy_v36
def test_wave_coverage_close_writes_ledger_then_marks_resolved(tmp_path: Path) -> None:
    """覆盖闭合成功时先原子落盘覆盖账本，再把审计 package 标为已处置。"""
    value = module(); settings, *_ = setup(value)
    base = value.package_manifest([atom(1)], "source", "protocol", "synthetic", 0, 0)
    manifest = value.realtime_manifest(base)
    root = tmp_path / "realtime"
    package_dir = root / "packages" / manifest["package_id"]
    package_dir.mkdir(parents=True)
    (package_dir / f"{manifest['package_id']}.input.jsonl").write_text(json.dumps(manifest, ensure_ascii=False) + "\n", encoding="utf-8")
    (package_dir / f"{manifest['package_id']}.result.jsonl").write_text("", encoding="utf-8")
    (package_dir / "realtime_state.json").write_text(json.dumps({"status": "needs_item_audit", "raw_response_saved": False}, ensure_ascii=False) + "\n", encoding="utf-8")
    (package_dir / "item_audit_queue.jsonl").write_text(json.dumps({"atom_id": manifest["atoms"][0]["atom_id"], "item_index": 0, "code": "X", "path": "/items/0/x", "attempt": 2, "request_identity": "rt_x", "raw_response_saved": False}, ensure_ascii=False) + "\n", encoding="utf-8")
    counts = value.close_repaired_item_audits([manifest], root, settings)
    assert counts == {"accepted_cue": 0, "excluded_after_repair": 1, "excluded_no_cue": 0, "excluded_content_filtered": 0}
    records = list(value.iter_jsonl(root / "coverage_disposition.jsonl"))
    assert len(records) == 1 and records[0]["disposition"] == "excluded_after_repair"
    state = json.loads((package_dir / "realtime_state.json").read_text(encoding="utf-8"))
    assert state["status"] == "excluded_after_repair" and state["item_audit_resolved"] is True


@pytest.mark.legacy_v36
def test_wave_coverage_close_is_transactional_on_mid_failure(tmp_path: Path) -> None:
    """覆盖闭合中途失败不得写入覆盖账本，也不得把已通过校验的 package 标为已处置。"""
    value = module(); settings, *_ = setup(value)

    def make_manifest(shard: int) -> dict[str, Any]:
        return value.realtime_manifest(value.package_manifest([atom(1 + shard)], "source", "protocol", "synthetic", shard, 0))

    manifest_a = make_manifest(0)
    manifest_b = make_manifest(1)
    root = tmp_path / "realtime"
    a_dir = root / "packages" / manifest_a["package_id"]
    a_dir.mkdir(parents=True)
    (a_dir / f"{manifest_a['package_id']}.input.jsonl").write_text(json.dumps(manifest_a, ensure_ascii=False) + "\n", encoding="utf-8")
    (a_dir / f"{manifest_a['package_id']}.result.jsonl").write_text("", encoding="utf-8")
    (a_dir / "realtime_state.json").write_text(json.dumps({"status": "needs_item_audit", "raw_response_saved": False}, ensure_ascii=False) + "\n", encoding="utf-8")
    (a_dir / "item_audit_queue.jsonl").write_text(json.dumps({"atom_id": manifest_a["atoms"][0]["atom_id"], "item_index": 0, "code": "X", "path": "/items/0/x", "attempt": 2, "request_identity": "rt_x", "raw_response_saved": False}, ensure_ascii=False) + "\n", encoding="utf-8")
    # package B 缺少结果文件，会在闭合中途触发合同失败。
    b_dir = root / "packages" / manifest_b["package_id"]
    b_dir.mkdir(parents=True)
    (b_dir / f"{manifest_b['package_id']}.input.jsonl").write_text(json.dumps(manifest_b, ensure_ascii=False) + "\n", encoding="utf-8")
    (b_dir / "realtime_state.json").write_text(json.dumps({"status": "validated_success", "raw_response_saved": False}, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(value.ContractError, match=manifest_b["package_id"]):
        value.close_repaired_item_audits([manifest_a, manifest_b], root, settings)
    assert not (root / "coverage_disposition.jsonl").exists()
    state_a = json.loads((a_dir / "realtime_state.json").read_text(encoding="utf-8"))
    assert state_a["status"] == "needs_item_audit"
    assert "item_audit_resolved" not in state_a


@pytest.mark.legacy_v36
def test_wave_coverage_close_records_content_filtered_package(tmp_path: Path) -> None:
    """被内容过滤的 package 无结果文件，闭合须为全部 Atom 写 excluded_content_filtered。"""
    value = module(); settings, *_ = setup(value)
    manifest = value.realtime_manifest(value.package_manifest([atom(1)], "source", "protocol", "synthetic", 0, 0))
    root = tmp_path / "realtime"
    package_dir = root / "packages" / manifest["package_id"]
    value.atomic_write_json(package_dir / "realtime_state.json", {
        "run_id": manifest["run_id"], "transport": "realtime_chat_completions", "realtime_shard_index": manifest["shard_index"],
        "package_id": manifest["package_id"], "realtime_request_id": manifest["realtime_request_id"], "request_sha256": manifest["request_sha256"],
        "source_atoms_sha256": manifest["source_atoms_sha256"], "cue_execution_protocol_sha256": manifest["cue_execution_protocol_sha256"],
        "status": "content_filtered", "retry_count": 1, "raw_response_saved": False,
        "service_error": {"http_status": 400, "service_code": "data_inspection_failed", "service_message": "inappropriate content"},
    })
    (package_dir / f"{manifest['package_id']}.input.jsonl").write_text(json.dumps(manifest, ensure_ascii=False) + "\n", encoding="utf-8")
    counts = value.close_repaired_item_audits([manifest], root, settings)
    assert counts == {"accepted_cue": 0, "excluded_after_repair": 0, "excluded_no_cue": 0, "excluded_content_filtered": 1}
    records = list(value.iter_jsonl(root / "coverage_disposition.jsonl"))
    assert len(records) == 1 and records[0]["disposition"] == "excluded_content_filtered"
    assert records[0]["code"] == "data_inspection_failed" and records[0]["path"] is None and records[0]["attempt"] == 1


@pytest.mark.legacy_v36
def test_realtime_run_continues_after_content_filtered_without_stopping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """内容过滤包不得停掉整波：混合 content_filtered 与成功的波次应以 completed 收尾。"""
    value = module(); settings, policy, manifest, rows = setup(value)
    manifests = []
    for index in range(2):
        base = value.package_manifest([rows["src_a_001"]], "source", "protocol", "synthetic", 0, index)
        manifests.append(value.realtime_manifest(base))

    def fake_execute(item: dict[str, Any], *_args: Any, **_kwargs: Any) -> tuple[str, float, dict[str, Any]]:
        if item["package_id"] == manifests[0]["package_id"]:
            diagnostic = {"http_status": 400, "service_code": "data_inspection_failed", "service_message": "inappropriate content"}
            return "content_filtered", 0.0, value.realtime_ledger_event(item, "content_filtered", 1, {}, "content_policy", diagnostic)
        return "validated_success", 0.001, value.realtime_ledger_event(item, "validated_success", 0, {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})

    monkeypatch.setattr(value, "materialize_realtime_wave", lambda *_args: (manifests, rows))
    monkeypatch.setattr(value, "load_realtime_authorization", lambda *_args: {"maximum_total_cny": 10.0})
    monkeypatch.setattr(value, "execute_realtime_package", fake_execute)
    monkeypatch.setattr(value, "RealtimeTransport", lambda *_args: object())
    monkeypatch.setenv("DASHSCOPE_API_KEY", "synthetic")
    args = SimpleNamespace(run_root=tmp_path / "realtime", authorization=tmp_path / "authorization.json", run_id="synthetic", wave_index=1)
    result = value.execute_realtime_run(args, settings, policy, {"sha256": "source"}, object(), "p", {"type": "object"}, "protocol")
    progress = json.loads((args.run_root / "runs" / args.run_id / "wave_01" / "progress.json").read_text(encoding="utf-8"))
    assert result["outcomes"] == {"content_filtered": 1, "validated_success": 1}
    assert progress["status"] == "completed" and progress["content_filtered_packages"] == 1
    assert progress["validated_success_packages"] + progress["content_filtered_packages"] == progress["total_packages"]


@pytest.mark.parametrize(
    ("payload", "expected_code", "expected_path"),
    [
        ("{", "JSON_PARSE", "/"),
        (json.dumps({"items": [{"n": 0, "p": [["A", "=", "活动"]], "f": "V", "start": 0, "end": 999, "c": 80, "v": "A"}]}, ensure_ascii=False), "SUPPORTING_TEXT_OFFSET_OUT_OF_RANGE", "/items/0/end"),
    ],
)
@pytest.mark.legacy_v36
def test_local_validation_failure_records_safe_category_only(tmp_path: Path, payload: str, expected_code: str, expected_path: str) -> None:
    """本地失败必须逐项审计，且状态与队列不含模型输出正文。"""
    value = module(); settings, policy, manifest, rows = setup(value)

    class Invalid:
        def complete(self, _body: dict[str, Any], _policy: Any) -> dict[str, Any]:
            return {"choices": [{"message": {"content": payload}}], "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}

    root = tmp_path / "realtime"
    result = value.execute_realtime_package(manifest, rows, "p", {"type": "object"}, settings, policy, Invalid(), root, 1.0, *buckets(value, policy))
    state = json.loads((root / "packages" / manifest["package_id"] / "realtime_state.json").read_text(encoding="utf-8"))
    assert result[0] == "needs_item_audit"
    queue = list(value.iter_jsonl(root / "packages" / manifest["package_id"] / "item_audit_queue.jsonl"))
    assert queue == [{"atom_id": "src_a_001", "item_index": 0, "code": expected_code, "path": expected_path,
                      "attempt": 2, "request_identity": queue[0]["request_identity"], "package_id": manifest["package_id"], "raw_response_saved": False}]
    persisted = json.dumps(state, ensure_ascii=False)
    assert "choices" not in persisted and "message" not in persisted
    if payload != "{":
        assert payload not in persisted
    value.validate_realtime_ledger_event(result[2])


@pytest.mark.legacy_v36
def test_json_parse_repairs_each_known_atom_without_replaying_package(tmp_path: Path) -> None:
    """整包 JSON 解析失败要把两个已知 Atom 分别修复，修复成功后不留审计队列。"""
    value = module(); settings, policy, _manifest, rows = setup(value)
    second = atom(2); rows[second["atom_id"]] = second
    manifest = value.realtime_manifest(value.package_manifest([rows["src_a_001"], second], "source", "protocol", "synthetic", 0, 0))

    class ParseThenRepair:
        calls = 0
        def complete(self, _body: dict[str, Any], _policy: Any) -> dict[str, Any]:
            self.calls += 1
            return {"choices": [{"message": {"content": "{" if self.calls == 1 else response()["choices"][0]["message"]["content"]}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}

    root = tmp_path / "realtime"; transport = ParseThenRepair(); tracker = value.BudgetTracker(1.0)
    result = value.execute_realtime_package(
        manifest, rows, "p", {"type": "object"}, settings, policy, transport, root, 1.0,
        *buckets(value, policy), budget_tracker=tracker,
    )
    package_dir = root / "packages" / manifest["package_id"]
    saved = list(value.iter_jsonl(package_dir / f"{manifest['package_id']}.result.jsonl"))
    assert result[0] == "validated_success" and transport.calls == 3
    assert [cue["atom_id"] for cue in saved] == ["src_a_001", "src_a_002"]
    assert result[2]["usage"] == {"prompt_tokens": 30, "completion_tokens": 30, "total_tokens": 60}
    assert tracker.spent_cny() == pytest.approx(value.realtime_usage_cost(result[2]["usage"], policy))
    assert not (package_dir / "item_audit_queue.jsonl").exists()
    assert "choices" not in (package_dir / "realtime_state.json").read_text(encoding="utf-8")


@pytest.mark.legacy_v36
def test_repair_usage_crossing_budget_stops_before_later_repairs(tmp_path: Path) -> None:
    """首轮已计费后，第一项 repair 越过预算时不得继续发送后续修复请求。"""
    value = module(); settings, policy, _manifest, rows = setup(value)

    class ParseThenCost:
        calls = 0
        def complete(self, _body: dict[str, Any], _policy: Any) -> dict[str, Any]:
            self.calls += 1
            return {"choices": [{"message": {"content": "{" if self.calls == 1 else json.dumps({"items": []})}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}

    tracker = value.BudgetTracker(0.000015)
    result = value.execute_realtime_package(
        _manifest, rows, "p", {"type": "object"}, settings, policy, ParseThenCost(), tmp_path / "realtime", 0.000015,
        *buckets(value, policy), budget_tracker=tracker,
    )
    assert result[0] == "budget_stopped" and result[2]["usage"] == {"prompt_tokens": 20, "completion_tokens": 20, "total_tokens": 40}
    assert tracker.spent_cny() > tracker.maximum_cny


@pytest.mark.legacy_v36
def test_http_400_has_safe_diagnostic_without_raw_body() -> None:
    """HTTP 400 必须终结为无正文诊断，且不把原始错误体暴露给运行状态。"""
    value = module(); settings, policy, *_ = setup(value)
    payload = b'{"error":{"code":"invalid_parameter","message":"body.model is invalid\\nno source text"}}'
    failure = urlerror.HTTPError("https://example.invalid", 400, "Bad Request", None, io.BytesIO(payload))
    transport = value.RealtimeTransport(settings.endpoint, "synthetic", open_call=lambda *_args, **_kwargs: (_ for _ in ()).throw(failure))
    with pytest.raises(value.RealtimeServiceError) as caught:
        transport.complete({"model": settings.model_id}, policy)
    assert caught.value.status_code == 400 and caught.value.retryable is False
    assert caught.value.safe_diagnostic() == {"http_status": 400, "service_code": "invalid_parameter", "service_message": "body.model is invalid no source text"}
    assert "{" not in str(caught.value)


@pytest.mark.legacy_v36
def test_permanent_http_400_writes_safe_failed_terminal_state(tmp_path: Path) -> None:
    """不可重试的 400 要写可恢复失败终态与诊断，但不写服务端原始正文。"""
    value = module(); settings, policy, manifest, rows = setup(value)
    class InvalidRequest:
        def complete(self, _body: dict[str, Any], _policy: Any) -> dict[str, Any]:
            raise value.RealtimeServiceError(400, False, "invalid_parameter", "body.response_format is unsupported")
    result = value.execute_realtime_package(manifest, rows, "p", {"type": "object"}, settings, policy, InvalidRequest(), tmp_path / "realtime", 1.0, *buckets(value, policy))
    state = json.loads((tmp_path / "realtime" / "packages" / manifest["package_id"] / "realtime_state.json").read_text(encoding="utf-8"))
    assert result[0] == "service_transport_exhausted" and result[2]["retry_eligible"] is False
    assert state["service_error"] == {"http_status": 400, "service_code": "invalid_parameter", "service_message": "body.response_format is unsupported"}
    assert "choices" not in json.dumps(state, ensure_ascii=False)


@pytest.mark.legacy_v36
def test_content_inspection_failure_is_content_filtered_terminal_not_wave_stop(tmp_path: Path) -> None:
    """内容安全过滤 400 必须归为逐条 content_filtered 终态，而不是停掉整波。"""
    value = module(); settings, policy, manifest, rows = setup(value)
    class ContentBlocked:
        def complete(self, _body: dict[str, Any], _policy: Any) -> dict[str, Any]:
            raise value.RealtimeServiceError(400, False, "data_inspection_failed", "Input text data may contain inappropriate content.")
    result = value.execute_realtime_package(manifest, rows, "p", {"type": "object"}, settings, policy, ContentBlocked(), tmp_path / "realtime", 1.0, *buckets(value, policy))
    assert result[0] == "content_filtered" and result[2]["outcome"] == "content_filtered"
    assert result[2]["failure_origin"] == "content_policy" and result[2]["retry_eligible"] is False
    state = json.loads((tmp_path / "realtime" / "packages" / manifest["package_id"] / "realtime_state.json").read_text(encoding="utf-8"))
    assert state["status"] == "content_filtered" and state["retry_count"] == 1
    assert state["service_error"]["service_code"] == "data_inspection_failed"
    assert "choices" not in json.dumps(state, ensure_ascii=False)
    # content_filtered 包必须补写冻结清单，离线覆盖闭合才能识别其 Atom 范围。
    manifest_path = tmp_path / "realtime" / "packages" / manifest["package_id"] / f"{manifest['package_id']}.input.jsonl"
    assert manifest_path.is_file()
    rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1 and rows[0]["package_id"] == manifest["package_id"]


@pytest.mark.legacy_v36
def test_recovery_skips_existing_content_filtered_terminal_without_transport(tmp_path: Path) -> None:
    """已落盘的 content_filtered 包在恢复时必须被识别为终态跳过，不能再次请求服务。"""
    value = module(); settings, policy, manifest, rows = setup(value)
    root = tmp_path / "realtime"
    package_dir = root / "packages" / manifest["package_id"]
    state = {
        "run_id": manifest["run_id"], "transport": "realtime_chat_completions", "realtime_shard_index": manifest["shard_index"],
        "package_id": manifest["package_id"], "realtime_request_id": manifest["realtime_request_id"], "request_sha256": manifest["request_sha256"],
        "source_atoms_sha256": manifest["source_atoms_sha256"], "cue_execution_protocol_sha256": manifest["cue_execution_protocol_sha256"],
        "status": "content_filtered", "retry_count": 1, "raw_response_saved": False,
        "service_error": {"http_status": 400, "service_code": "data_inspection_failed", "service_message": "Input text data may contain inappropriate content."},
    }
    value.atomic_write_json(package_dir / "realtime_state.json", state)
    class ShouldNotBeCalled:
        def complete(self, _body: dict[str, Any], _policy: Any) -> dict[str, Any]:
            raise AssertionError("content_filtered 包不应再次请求服务")
    value.append_ledger_event(root / settings.layout["run_ledger_filename"], value.realtime_ledger_event(manifest, "content_filtered", 1, {}, "content_policy", state["service_error"]))
    assert value.realtime_recovery_terminal_status(manifest, root, settings) == "content_filtered"
    result = value.execute_realtime_package(manifest, rows, "p", {"type": "object"}, settings, policy, ShouldNotBeCalled(), root, 1.0, *buckets(value, policy))
    assert result == ("recovered_content_filtered", 0.0, {"outcome": "recovered_content_filtered"})


@pytest.mark.legacy_v36
def test_server_compatible_inference_schema_keeps_entity_deduplication_locally() -> None:
    """服务端不支持 uniqueItems 时，本地解析仍须拒绝重复实体。"""
    value = module(); settings, _policy, _manifest, rows = setup(value)
    schema = json.loads((ROOT / "schemas/cue_inference_batch_compact_v1.schema.json").read_text(encoding="utf-8"))
    assert "uniqueItems" not in json.dumps(schema, ensure_ascii=False)
    inference_validator = value.load_validator(ROOT / "schemas/cue_inference_batch_compact_v1.schema.json")
    cue_validator = value.load_validator(ROOT / "schemas/cue_candidate.schema.json")
    duplicate = {"items": [{"n": 0, "p": [["A", "=", "活动"]], "f": "V", "start": 0, "end": 5, "c": 80, "v": "A", "e": ["物品", "物品"]}]}
    with pytest.raises(value.LocalValidationError, match="ENTITY_DUPLICATE"):
        value.parse_inference_items(duplicate, [rows["src_a_001"]], inference_validator, cue_validator, settings, "synthetic")


@pytest.mark.legacy_v36
def test_position_evidence_uses_declared_single_field_and_keeps_original_span() -> None:
    """位置证据只能在 f 指定字段切片，保存内容必须是程序从原字段取回的原文。"""
    value = module(); settings, _policy, _manifest, rows = setup(value)
    source = rows["src_a_001"]; source.update({"transcript": "转录原文", "dense_caption": "描述原文", "visible_text": "可见原文"})
    iv = value.load_validator(ROOT / "schemas/cue_inference_batch_compact_v1.schema.json"); cv = value.load_validator(ROOT / "schemas/cue_candidate.schema.json")
    cues = value.parse_inference_items({"items": [{"n": 0, "f": "D", "start": 0, "end": 4, "p": [["A", "=", "活动"]], "c": 80, "v": "A"}]}, [source], iv, cv, settings, "synthetic")
    assert cues[0]["supporting_text_field"] == "dense_caption" and cues[0]["supporting_text_span"] == "描述原文"


@pytest.mark.parametrize(("start", "end", "expected"), [(0, 0, "INFERENCE_SCHEMA_MINIMUM"), (0, 99, "SUPPORTING_TEXT_OFFSET_OUT_OF_RANGE")])
@pytest.mark.legacy_v36
def test_position_evidence_rejects_invalid_unicode_codepoint_offsets(start: int, end: int, expected: str) -> None:
    """偏移必须是同一字段的左闭右开 Unicode code-point 范围，不能借其他字段或越界。"""
    value = module(); settings, _policy, _manifest, rows = setup(value)
    iv = value.load_validator(ROOT / "schemas/cue_inference_batch_compact_v1.schema.json"); cv = value.load_validator(ROOT / "schemas/cue_candidate.schema.json")
    payload = {"items": [{"n": 0, "f": "V", "start": start, "end": end, "p": [["A", "=", "活动"]], "c": 80, "v": "A"}]}
    with pytest.raises(value.LocalValidationError, match=expected):
        value.parse_inference_items(payload, [rows["src_a_001"]], iv, cv, settings, "synthetic")


@pytest.mark.legacy_v36
def test_request_keeps_three_evidence_fields_separate() -> None:
    """请求正文必须逐字段保留证据，禁止在进入模型前拼成不可审计的 text。"""
    value = module(); settings, _policy, _manifest, rows = setup(value)
    source = rows["src_a_001"]
    source.update({"transcript": "转录", "dense_caption": "描述", "visible_text": "可见"})
    request = value.build_request("提示词", {"type": "object"}, [source], settings)
    items = json.loads(request["messages"][1]["content"])["items"]
    assert items == [{"item_index": 0, "transcript": "转录", "dense_caption": "描述", "visible_text": "可见"}]


@pytest.mark.legacy_v36
def test_item_failure_keeps_sibling_cue_and_enters_one_repair_audit_queue(tmp_path: Path) -> None:
    """五项包中的一项失败不得抹去同包有效 Cue；修复仅发送失败 Atom 一次后进入审计。"""
    value = module(); settings, policy, _manifest, rows = setup(value)
    second_atom = atom(2); rows[second_atom["atom_id"]] = second_atom
    manifest = value.realtime_manifest(value.package_manifest([rows["src_a_001"], second_atom], "source", "protocol", "synthetic", 0, 0))

    class OneGoodOneBad:
        calls = 0
        def complete(self, body: dict[str, Any], _policy: Any) -> dict[str, Any]:
            self.calls += 1
            submitted = json.loads(body["messages"][1]["content"])["items"]
            if len(submitted) == 2:
                payload = {"items": [
                    {"n": 0, "f": "V", "start": 0, "end": 5, "p": [["A", "=", "活动"]], "c": 80, "v": "A"},
                    {"n": 1, "f": "V", "start": 0, "end": 999, "p": [["A", "=", "活动"]], "c": 80, "v": "A"},
                ]}
            else:
                payload = {"items": [{"n": 0, "f": "V", "start": 0, "end": 999, "p": [["A", "=", "活动"]], "c": 80, "v": "A"}]}
            return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}

    root = tmp_path / "realtime"; transport = OneGoodOneBad()
    result = value.execute_realtime_package(manifest, rows, "p", {"type": "object"}, settings, policy, transport, root, 1.0, *buckets(value, policy))
    package_dir = root / "packages" / manifest["package_id"]
    saved = list(value.iter_jsonl(package_dir / f"{manifest['package_id']}.result.jsonl"))
    queued = list(value.iter_jsonl(package_dir / "item_audit_queue.jsonl"))
    assert result[0] == "needs_item_audit" and transport.calls == 2
    assert [cue["atom_id"] for cue in saved] == ["src_a_001"]
    assert queued[0]["atom_id"] == second_atom["atom_id"] and queued[0]["attempt"] == 2
    assert queued[0]["request_identity"].startswith(f"rt_repair_{manifest['package_id']}_1_")
    assert "choices" not in (package_dir / "realtime_state.json").read_text(encoding="utf-8")


@pytest.mark.legacy_v36
def test_position_protocol_rejects_model_text_field() -> None:
    """模型不得回传 x；Schema 要求只保留字段码与 Unicode code-point 位置。"""
    value = module(); settings, _policy, _manifest, rows = setup(value)
    iv = value.load_validator(ROOT / "schemas/cue_inference_batch_compact_v1.schema.json"); cv = value.load_validator(ROOT / "schemas/cue_candidate.schema.json")
    payload = {"items": [{"n": 0, "f": "V", "start": 0, "end": 5, "p": [["A", "=", "活动"]], "c": 80, "v": "A", "x": "第1条文本"}]}
    with pytest.raises(value.LocalValidationError, match="INFERENCE_SCHEMA_ADDITIONALPROPERTIES"):
        value.parse_inference_items(payload, [rows["src_a_001"]], iv, cv, settings, "synthetic")


@pytest.mark.legacy_v36
def test_materialize_realtime_wave_stops_after_selected_shards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Wave 1 只能保留十个 shard，并在越过边界后停止读取完整 Source。"""
    value = module(); settings, _policy, _manifest, _rows = setup(value)
    yielded = [0]

    def stream(_path: Path) -> Any:
        for index in range(6_000):
            yielded[0] += 1
            row = atom(index)
            row["atom_id"] = f"src_a_{index:05d}"
            yield row

    monkeypatch.setattr(value, "iter_jsonl", stream)
    monkeypatch.setattr(value, "validate_record", lambda *_args: None)
    progress: list[tuple[int, int]] = []
    arguments = SimpleNamespace(source_atoms=tmp_path / "synthetic.jsonl", run_id="synthetic")
    manifests, indexed = value.materialize_realtime_wave(
        arguments, settings, None, "source", "p", {"type": "object"}, "protocol", [0], 10,
        lambda scanned, selected: progress.append((scanned, selected)),
    )
    assert yielded[0] == 5_001
    assert len(indexed) == 5_000 and len(manifests) == 1_000
    assert {item["realtime_shard_index"] for item in manifests} == set(range(10))
    assert progress[-1] == (5_000, 5_000)


@pytest.mark.legacy_v36
def test_atomic_replace_retries_windows_share_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows 短暂占用应重试成功，且替换前的真实状态文件不会被预先删除。"""
    value = module(); target = tmp_path / "state.json"; target.write_text('{"old":true}\n', encoding="utf-8")
    temporary = tmp_path / "state.unique.tmp"; temporary.write_text('{"new":true}\n', encoding="utf-8")
    original = Path.replace; calls = [0]
    def replace(path: Path, destination: Path) -> Path:
        calls[0] += 1
        if calls[0] == 1:
            assert target.read_text(encoding="utf-8") == '{"old":true}\n'
            raise PermissionError(5, "share lock")
        return original(path, destination)
    monkeypatch.setattr(Path, "replace", replace)
    value.atomic_replace(temporary, target, retries=2, sleep=lambda _seconds: None)
    assert calls[0] == 2 and target.read_text(encoding="utf-8") == '{"new":true}\n'


@pytest.mark.legacy_v36
def test_realtime_run_limits_inflight_and_writes_progress(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """调度器最多保留十个在飞包，并在无正文 progress.json 记录完成数和 ETA。"""
    value = module(); settings, policy, manifest, rows = setup(value)
    manifests = []
    for index in range(12):
        base = value.package_manifest([rows["src_a_001"]], "source", "protocol", "synthetic", 0, index)
        manifests.append(value.realtime_manifest(base))
    current = [0]; peak = [0]; lock = threading.Lock()
    def fake_execute(item: dict[str, Any], *_args: Any, **_kwargs: Any) -> tuple[str, float, dict[str, Any]]:
        with lock:
            current[0] += 1; peak[0] = max(peak[0], current[0])
        time.sleep(0.02)
        with lock: current[0] -= 1
        return "validated_success", 0.001, value.realtime_ledger_event(item, "validated_success", 0, {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})
    monkeypatch.setattr(value, "materialize_realtime_wave", lambda *_args: (manifests, rows))
    monkeypatch.setattr(value, "load_realtime_authorization", lambda *_args: {"maximum_total_cny": 10.0})
    monkeypatch.setattr(value, "execute_realtime_package", fake_execute)
    monkeypatch.setattr(value, "RealtimeTransport", lambda *_args: object())
    monkeypatch.setenv("DASHSCOPE_API_KEY", "synthetic")
    args = SimpleNamespace(run_root=tmp_path / "realtime", authorization=tmp_path / "authorization.json", run_id="synthetic", wave_index=1)
    marker = {"sha256": "source"}
    result = value.execute_realtime_run(args, settings, policy, marker, object(), "p", {"type": "object"}, "protocol")
    progress = json.loads((args.run_root / "runs" / args.run_id / "wave_01" / "progress.json").read_text(encoding="utf-8"))
    assert peak[0] == policy.maximum_in_flight == 10
    assert result["outcomes"] == {"validated_success": 12}
    assert (progress["wave_index"], progress["wave_task_indexes"], progress["total_packages"], progress["completed_packages"], progress["in_flight_packages"]) == (1, [0], 12, 12, 0)
    assert "source_text" not in json.dumps(progress, ensure_ascii=False)


@pytest.mark.legacy_v36
def test_realtime_run_transient_failure_does_not_stop_wave(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """单个网络/服务端瞬断不得停整波，也不得写账本；下一轮恢复会把它当未完成重发。"""
    value = module(); settings, policy, manifest, rows = setup(value)
    manifests = []
    for index in range(3):
        base = value.package_manifest([rows["src_a_001"]], "source", "protocol", "synthetic", 0, index)
        manifests.append(value.realtime_manifest(base))

    def fake_execute(item: dict[str, Any], *_args: Any, **_kwargs: Any) -> tuple[str, float, dict[str, Any]]:
        if item["package_id"] == manifests[0]["package_id"]:
            diagnostic = {"http_status": None, "service_code": None, "service_message": None}
            return "service_transport_exhausted", 0.0, value.realtime_ledger_event(item, "service_transport_exhausted", 3, {}, "transient_service", diagnostic)
        return "validated_success", 0.001, value.realtime_ledger_event(item, "validated_success", 0, {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})

    monkeypatch.setattr(value, "materialize_realtime_wave", lambda *_args: (manifests, rows))
    monkeypatch.setattr(value, "load_realtime_authorization", lambda *_args: {"maximum_total_cny": 10.0})
    monkeypatch.setattr(value, "execute_realtime_package", fake_execute)
    monkeypatch.setattr(value, "RealtimeTransport", lambda *_args: object())
    monkeypatch.setenv("DASHSCOPE_API_KEY", "synthetic")
    args = SimpleNamespace(run_root=tmp_path / "realtime", authorization=tmp_path / "authorization.json", run_id="synthetic", wave_index=1)
    result = value.execute_realtime_run(args, settings, policy, {"sha256": "source"}, object(), "p", {"type": "object"}, "protocol")
    wave_root = args.run_root / "runs" / args.run_id / "wave_01"
    progress = json.loads((wave_root / "progress.json").read_text(encoding="utf-8"))
    # 三个包都被尝试（completed=3），瞬断包计入 service_transport_exhausted，但整波不因单点瞬断停住。
    assert result["outcomes"] == {"service_transport_exhausted": 1, "validated_success": 2}
    assert progress["completed_packages"] == 3 and progress["service_transport_exhausted_packages"] == 1
    # 瞬断包不写账本：恢复下一轮重发成功后只写一条 validated_success，不会撞“重复 request id”。
    first_id = manifests[0]["realtime_request_id"]
    ledger_ids = [json.loads(line)["realtime_request_id"] for line in open(wave_root / settings.layout["run_ledger_filename"], encoding="utf-8") if line.strip()]
    assert first_id not in ledger_ids


@pytest.mark.legacy_v36
def test_realtime_resume_skips_accounted_quarantine_and_submits_only_unseen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """恢复必须保留隔离计数、不重写账本，并只让尚未请求的包进入假执行器。"""
    value = module(); settings, policy, first, rows = setup(value)
    second = value.realtime_manifest(value.package_manifest([rows["src_a_001"]], "source", "protocol", "synthetic", 0, 1))
    manifests = [first, second]
    args = SimpleNamespace(run_root=tmp_path / "realtime", authorization=tmp_path / "authorization.json", run_id="synthetic", wave_index=1)
    wave_root = args.run_root / "runs" / args.run_id / "wave_01"

    class Invalid:
        calls = 0
        def complete(self, _body: dict[str, Any], _policy: Any) -> dict[str, Any]:
            self.calls += 1
            return response(False)

    invalid = Invalid()
    quarantined = value.execute_realtime_package(first, rows, "p", {"type": "object"}, settings, policy, invalid, wave_root, 10.0, *buckets(value, policy))
    assert quarantined[0] == "needs_item_audit" and invalid.calls == 2
    value.append_ledger_event(wave_root / settings.layout["run_ledger_filename"], quarantined[2])
    submitted: list[str] = []

    def fake_execute(item: dict[str, Any], *_args: Any, **_kwargs: Any) -> tuple[str, float, dict[str, Any]]:
        submitted.append(str(item["package_id"]))
        return "validated_success", 0.001, value.realtime_ledger_event(item, "validated_success", 0, {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})

    monkeypatch.setattr(value, "materialize_realtime_wave", lambda *_args: (manifests, rows))
    monkeypatch.setattr(value, "load_realtime_authorization", lambda *_args: {"maximum_total_cny": 10.0})
    monkeypatch.setattr(value, "execute_realtime_package", fake_execute)
    monkeypatch.setattr(value, "RealtimeTransport", lambda *_args: object())
    monkeypatch.setenv("DASHSCOPE_API_KEY", "synthetic")
    result = value.execute_realtime_run(args, settings, policy, {"sha256": "source"}, object(), "p", {"type": "object"}, "protocol")
    progress = json.loads((wave_root / "progress.json").read_text(encoding="utf-8"))
    events = list(value.iter_jsonl(wave_root / settings.layout["run_ledger_filename"]))
    assert submitted == [second["package_id"]]
    assert result["outcomes"] == {"needs_item_audit": 1, "validated_success": 1}
    assert (progress["status"], progress["completed_packages"], progress["validated_success_packages"], progress["needs_item_audit_packages"]) == ("needs_item_audit", 2, 1, 1)
    assert [event["realtime_request_id"] for event in events].count(first["realtime_request_id"]) == 1


@pytest.mark.legacy_v36
def test_legacy_json_parse_quarantine_migrates_to_item_audit_without_transport(tmp_path: Path) -> None:
    """v8 旧 JSON_PARSE 隔离仅生成安全审计项，恢复时不得重新调用服务。"""
    value = module(); settings, policy, manifest, rows = setup(value)
    root = tmp_path / "realtime"; package_dir = root / "packages" / manifest["package_id"]
    state = {
        "run_id": manifest["run_id"], "transport": "realtime_chat_completions", "realtime_shard_index": manifest["shard_index"],
        "package_id": manifest["package_id"], "realtime_request_id": manifest["realtime_request_id"], "request_sha256": manifest["request_sha256"],
        "source_atoms_sha256": manifest["source_atoms_sha256"], "cue_execution_protocol_sha256": manifest["cue_execution_protocol_sha256"],
        "status": "local_validation_quarantine", "local_validation_failure": {"code": "JSON_PARSE", "path": "/"}, "raw_response_saved": False,
    }
    value.atomic_write_json(package_dir / "realtime_state.json", state)
    value.atomic_write_json(package_dir / f"{manifest['package_id']}.failed.json", {
        "package_id": manifest["package_id"], "transport": "realtime_chat_completions", "outcome": "local_validation_quarantine",
        "local_validation_failure": {"code": "JSON_PARSE", "path": "/"}, "raw_response_saved": False,
    })
    assert value.migrate_legacy_json_parse_quarantine(manifest, root, settings) is True
    queue = list(value.iter_jsonl(package_dir / "item_audit_queue.jsonl"))
    assert queue[0]["code"] == "JSON_PARSE" and queue[0]["attempt"] == 1 and queue[0]["raw_response_saved"] is False
    assert value.realtime_recovery_terminal_status(manifest, root, settings) == "needs_item_audit_from_quarantine"

    class MustNotCall:
        def complete(self, _body: dict[str, Any], _policy: Any) -> dict[str, Any]:
            raise AssertionError("旧隔离不得重发")

    assert value.execute_realtime_package(manifest, rows, "p", {"type": "object"}, settings, policy, MustNotCall(), root, 1.0, *buckets(value, policy)) == (
        "recovered_item_audit", 0.0, {"outcome": "recovered_item_audit"},
    )


@pytest.mark.legacy_v36
def test_reconcile_package_ledger_backfills_missing_cumulative_audit_event(tmp_path: Path) -> None:
    """已有逐项审计 package 的安全账本可补回累计账本，恢复时无需重发。"""
    value = module(); settings, policy, manifest, rows = setup(value)

    class Invalid:
        def complete(self, _body: dict[str, Any], _policy: Any) -> dict[str, Any]:
            return response(False)

    execution_root = tmp_path / "runs" / "synthetic"; wave_root = execution_root / "wave_01"
    terminal = value.execute_realtime_package(manifest, rows, "p", {"type": "object"}, settings, policy, Invalid(), wave_root, 1.0, *buckets(value, policy))
    assert terminal[0] == "needs_item_audit"
    value.reconcile_realtime_terminal_ledgers([manifest], wave_root, execution_root, settings, policy)
    events = value.cumulative_realtime_events(execution_root)
    assert events[manifest["realtime_request_id"]]["outcome"] == "needs_item_audit"
    assert (wave_root / settings.layout["run_ledger_filename"]).is_file()


@pytest.mark.legacy_v36
def test_cumulative_budget_is_shared_across_wave_directories(tmp_path: Path) -> None:
    """Wave 2 必须从共享无正文账本继承 Wave 1 已发生费用，不能重新获得完整 ¥80。"""
    value = module(); _settings, policy, manifest, _rows = setup(value)
    preflight = {"run_id": "shared", "source_atoms_sha256": "source", "cue_execution_protocol_sha256": "protocol"}
    event = value.realtime_ledger_event(manifest, "validated_success", 0, {"prompt_tokens": 1_000_000, "completion_tokens": 0, "total_tokens": 1_000_000})
    event["realtime_request_id"] = "wave_01_request"
    value.append_ledger_event(tmp_path / "wave_01" / "realtime_run_ledger.jsonl", event)
    tracker = value.initialise_cumulative_budget(tmp_path, preflight, {"maximum_total_cny": 80.0}, policy)
    assert tracker.spent_cny() == pytest.approx(0.2)
    assert tracker.maximum_cny - tracker.spent_cny() == pytest.approx(79.8)
    cumulative = json.loads((tmp_path / "realtime_cumulative_progress.json").read_text(encoding="utf-8"))
    assert cumulative["accounted_request_count"] == 1 and "source_text" not in json.dumps(cumulative, ensure_ascii=False)


@pytest.mark.legacy_v36
def test_later_wave_requires_each_prior_wave_to_complete(tmp_path: Path) -> None:
    """启动 Wave 2 前必须离线确认 Wave 1 同 run/Source/协议下零失败地完整完成。"""
    value = module(); settings, _policy, *_ = setup(value)
    preflight = {"run_id": "shared", "source_atoms_sha256": "source", "cue_execution_protocol_sha256": "protocol"}
    success = {
        "status": "completed", "run_id": "shared", "source_atoms_sha256": "source", "cue_execution_protocol_sha256": "protocol",
        "wave_index": 1, "total_packages": 3, "completed_packages": 3, "in_flight_packages": 0,
            "validated_success_packages": 3, "local_validation_quarantine_packages": 0, "needs_item_audit_packages": 0,
        "service_transport_exhausted_packages": 0, "budget_stopped_packages": 0,
    }
    value.atomic_write_json(tmp_path / "wave_01" / "progress.json", success)
    value.require_completed_prior_waves(tmp_path, 2, preflight, settings)
    success["service_transport_exhausted_packages"] = 1
    value.atomic_write_json(tmp_path / "wave_01" / "progress.json", success)
    with pytest.raises(value.ContractError, match="尚未完整成功"):
        value.require_completed_prior_waves(tmp_path, 2, preflight, settings)


def cue_v2_item(disposition: str, clauses: list[dict[str, Any]], reasons: list[str] | None = None) -> dict[str, Any]:
    """构造内存 Cue v2 推理项，确保纯函数测试不写入任何正式路径。"""

    return {"item_index": 0, "disposition": disposition, "predicate": {"all_of": clauses}, "reason_codes": reasons or []}


def cue_v2_clause(dimension: str, operator: str, value: str, field: str = "transcript", span: str | None = None) -> dict[str, Any]:
    """构造具备独立同字段证据的最小 clause，正文只存在于测试内存。"""

    return {"dimension": dimension, "operator": operator, "value": value, "evidence": {"field": field, "span": span if span is not None else value}}


def cue_v2_matrix() -> dict[str, list[str]]:
    """返回与冻结配置相同的矩阵，使纯函数不依赖文件或旧 Settings。"""

    return {"person": ["present", "absent", "speaking", "mentioned"], "location": ["at", "not_at", "entering", "leaving", "mentioned"], "object": ["present", "absent", "held", "placed"], "activity": ["starts", "ongoing", "ends", "not_occurring"], "state": ["is", "is_not", "changes_to"], "explicit_time": ["stated", "planned", "hypothetical"]}


@pytest.mark.cue_v2
def test_cue_v2_normalization_and_direct_support_are_strict() -> None:
    """NFKC 和空白可以规范化，但大小写、标点、翻译或词序变化不能伪装为直接支持。"""

    value = module()
    assert value.normalize_cue_v2_text(" Ａ\u3000手机\n") == "A 手机"
    atom_value = {"transcript": "A 手机。", "dense_caption": "另一字段"}
    assert value.validate_cue_v2_inference_item(cue_v2_item("accepted_cue", [cue_v2_clause("object", "present", "手机", span="A 手机。")] ), atom_value, cue_v2_matrix())["status"] == "accepted_machine"
    for unsupported in ("a", "A手机", "phone", "手机A"):
        result = value.validate_cue_v2_inference_item(cue_v2_item("accepted_cue", [cue_v2_clause("object", "present", unsupported, span="A 手机。")]), atom_value, cue_v2_matrix())
        assert result["status"] == "rejected"


@pytest.mark.cue_v2
def test_cue_v2_evidence_and_structure_gates_are_safe() -> None:
    """字段内连续证据、终态结构与哨兵值必须在不泄露正文的前提下阻断。"""

    value = module(); atom_value = {"transcript": "手机出现", "dense_caption": "杯子出现", "visible_text": "秘密正文"}
    good = cue_v2_clause("object", "present", "手机", span="手机出现")
    assert value.validate_cue_v2_inference_item(cue_v2_item("accepted_cue", [good]), atom_value, cue_v2_matrix())["status"] == "accepted_machine"
    cross = cue_v2_clause("object", "present", "杯子", "transcript", "杯子出现")
    assert value.validate_cue_v2_inference_item(cue_v2_item("accepted_cue", [cross]), atom_value, cue_v2_matrix())["issues"][0]["code"] == "CROSS_FIELD_EVIDENCE"
    visible = cue_v2_clause("object", "present", "秘密", "visible_text", "秘密正文")
    assert value.validate_cue_v2_inference_item(cue_v2_item("accepted_cue", [visible]), atom_value, cue_v2_matrix())["status"] == "rejected"
    for sentinel in ("null", "none", "unknown", "n/a", "未知"):
        assert value.validate_cue_v2_inference_item(cue_v2_item("accepted_cue", [cue_v2_clause("object", "present", sentinel, span=sentinel)]), {"transcript": sentinel, "dense_caption": "x"}, cue_v2_matrix())["status"] == "rejected"
    assert value.validate_cue_v2_inference_item(cue_v2_item("accepted_cue", []), atom_value, cue_v2_matrix())["status"] == "rejected"
    assert value.validate_cue_v2_inference_item(cue_v2_item("accepted_cue", [good] * 4), atom_value, cue_v2_matrix())["status"] == "rejected"
    assert value.validate_cue_v2_inference_item(cue_v2_item("accepted_cue", [good], ["INSUFFICIENT_EVIDENCE"]), atom_value, cue_v2_matrix())["status"] == "rejected"
    assert value.validate_cue_v2_inference_item(cue_v2_item("no_cue", [good], ["NO_OBSERVABLE_CONDITION"]), atom_value, cue_v2_matrix())["status"] == "rejected"
    assert value.validate_cue_v2_inference_item(cue_v2_item("ambiguous", [], []), atom_value, cue_v2_matrix())["status"] == "rejected"
    assert value.validate_cue_v2_inference_item(cue_v2_item("no_cue", [], ["NO_OBSERVABLE_CONDITION"] * 2), atom_value, cue_v2_matrix())["status"] == "rejected"
    assert value.validate_cue_v2_inference_item(cue_v2_item("ambiguous", [], ["AMBIGUOUS_SCOPE"]), atom_value, cue_v2_matrix())["status"] == "needs_semantic_audit"


@pytest.mark.cue_v2
def test_cue_v2_semantic_rules_are_conservative_and_input_is_unchanged() -> None:
    """角色、极性、地点、范围和时间语气不明时审计或拒绝，且纯函数不得修改输入。"""

    value = module(); matrix = cue_v2_matrix()
    atom_value = {"transcript": "Alice 没拿手机。如果明天三点开会。", "dense_caption": "冰箱出现。门打开了。"}
    original_atom = json.loads(json.dumps(atom_value, ensure_ascii=False))
    mentioned = cue_v2_item("accepted_cue", [cue_v2_clause("person", "present", "Alice", span="Alice")])
    assert value.validate_cue_v2_inference_item(mentioned, atom_value, matrix)["status"] == "needs_semantic_audit"
    speaking = cue_v2_item("accepted_cue", [cue_v2_clause("person", "speaking", "Alice", span="Alice")])
    assert value.validate_cue_v2_inference_item(speaking, atom_value, matrix)["issues"][0]["code"] == "PERSON_ROLE_MISMATCH"
    negative = cue_v2_item("accepted_cue", [cue_v2_clause("object", "present", "手机", span="没拿手机")])
    assert value.validate_cue_v2_inference_item(negative, atom_value, matrix)["issues"][0]["code"] == "OPERATOR_POLARITY_MISMATCH"
    location = cue_v2_item("accepted_cue", [cue_v2_clause("location", "at", "厨房", "dense_caption", "冰箱出现")])
    assert value.validate_cue_v2_inference_item(location, atom_value, matrix)["status"] == "rejected"
    bad_pair = cue_v2_item("accepted_cue", [cue_v2_clause("person", "held", "Alice", span="Alice")])
    assert value.validate_cue_v2_inference_item(bad_pair, atom_value, matrix)["issues"][0]["code"] == "SEMANTIC_DIMENSION_MISMATCH"
    time = cue_v2_item("accepted_cue", [cue_v2_clause("explicit_time", "stated", "明天三点", span="如果明天三点开会")])
    assert value.validate_cue_v2_inference_item(time, atom_value, matrix)["issues"][0]["code"] == "TEMPORAL_MODALITY_MISMATCH"
    leaked = value.validate_cue_v2_inference_item(negative, atom_value, matrix)
    assert "手机" not in json.dumps(leaked, ensure_ascii=False) and atom_value == original_atom


@pytest.mark.cue_v2
def test_cue_v2_all_dimensions_and_remaining_conservative_boundaries() -> None:
    """六维合法关系可通过结构门；范围、空承载活动状态和视频数字不得被升格为事实。"""

    value = module(); matrix = cue_v2_matrix()
    cases = [
        ("person", "speaking", "Alice", "Alice: hello"), ("location", "mentioned", "厨房", "厨房"),
        ("object", "held", "手机", "拿着手机"), ("activity", "ongoing", "洗碗", "洗碗"),
        ("state", "is", "门已打开", "门已打开"), ("explicit_time", "stated", "下午3点", "下午3点"),
    ]
    for dimension, operator, item_value, span in cases:
        result = value.validate_cue_v2_inference_item(cue_v2_item("accepted_cue", [cue_v2_clause(dimension, operator, item_value, span=span)]), {"transcript": span, "dense_caption": "x"}, matrix)
        assert result["status"] in {"accepted_machine", "needs_semantic_audit"}
    clauses = [cue_v2_clause("object", "present", "手机", span="手机"), cue_v2_clause("location", "mentioned", "厨房", span="厨房"), cue_v2_clause("activity", "ongoing", "洗碗", span="洗碗")]
    assert value.validate_cue_v2_inference_item(cue_v2_item("accepted_cue", clauses), {"transcript": "手机 厨房 洗碗", "dense_caption": "x"}, matrix)["status"] == "needs_semantic_audit"
    assert value.validate_cue_v2_inference_item(cue_v2_item("accepted_cue", [cue_v2_clause("object", "present", "手机", span="所有手机")]), {"transcript": "所有手机", "dense_caption": "x"}, matrix)["issues"][0]["code"] == "SCOPE_MISMATCH"
    assert value.validate_cue_v2_inference_item(cue_v2_item("accepted_cue", [cue_v2_clause("activity", "ongoing", "正在做")]), {"transcript": "正在做", "dense_caption": "x"}, matrix)["status"] == "rejected"
    assert value.validate_cue_v2_inference_item(cue_v2_item("accepted_cue", [cue_v2_clause("state", "is", "打开了")]), {"transcript": "打开了", "dense_caption": "x"}, matrix)["status"] == "needs_semantic_audit"
    assert value.validate_cue_v2_inference_item(cue_v2_item("accepted_cue", [cue_v2_clause("explicit_time", "stated", "120")]), {"transcript": "120", "dense_caption": "x", "local_start_sec": 120}, matrix)["status"] == "rejected"


@pytest.mark.cue_v2
def test_cue_v2_english_negation_and_scope_require_whole_tokens() -> None:
    """英文否定和范围词只能按完整 token 生效，不能把普通单词的子串改造成极性或范围。"""

    value = module(); matrix = cue_v2_matrix()
    notebook = cue_v2_item("accepted_cue", [cue_v2_clause("object", "present", "notebook", span="notebook")])
    someone = cue_v2_item("accepted_cue", [cue_v2_clause("object", "present", "someone", span="someone")])
    assert value.validate_cue_v2_inference_item(notebook, {"transcript": "notebook", "dense_caption": "x"}, matrix)["status"] == "accepted_machine"
    assert value.validate_cue_v2_inference_item(someone, {"transcript": "someone", "dense_caption": "x"}, matrix)["status"] == "accepted_machine"
    no_phone = cue_v2_item("accepted_cue", [cue_v2_clause("object", "present", "phone", span="no phone")])
    assert value.validate_cue_v2_inference_item(no_phone, {"transcript": "no phone", "dense_caption": "x"}, matrix)["issues"][0]["code"] == "OPERATOR_POLARITY_MISMATCH"


@pytest.mark.cue_v2
def test_cue_v2_request_is_strict_and_has_no_controlled_metadata() -> None:
    """Cue v2 请求只传两个原文字段并绑定严格 Schema，不读取密钥或写入正式工件。"""

    value = module(); schema = json.loads((ROOT / "schemas/cue_v2_inference.schema.json").read_text(encoding="utf-8"))
    atoms = [{"atom_id": "secret", "split": "train", "visible_text": "secret", "event_timestamp": 1, "transcript": "t", "dense_caption": "d"}]
    request = value.build_cue_v2_request(atoms, schema)
    payload = json.loads(request["messages"][0]["content"])
    assert payload == {"items": [{"item_index": 0, "transcript": "t", "dense_caption": "d"}]}
    assert set(payload["items"][0]) == {"item_index", "transcript", "dense_caption"}
    assert all(f'"{key}"' not in request["messages"][0]["content"] for key in ("atom_id", "split", "visible_text", "event_timestamp", "start", "end", "n", "f", "x"))
    assert request["temperature"] == 0 and request["max_tokens"] == 128
    assert request["response_format"]["json_schema"] == {"name": "cue_v2_inference", "strict": True, "schema": schema}
    assert value.build_cue_v2_request(atoms * 5, schema)["max_tokens"] == 640
    empty = value.build_cue_v2_request([{"transcript": "", "dense_caption": ""}], schema)
    assert json.loads(empty["messages"][0]["content"])["items"][0]["transcript"] == ""
    with pytest.raises(value.ContractError, match="ATOM_COUNT"):
        value.build_cue_v2_request([], schema)


def cue_v2_acceptance_fixture() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """构造包含 10,000 候选、七层局部编号校准和完整 Source 元数据的内存验收夹具。"""

    candidates = [{"atom_id": f"src_accept_{index:05d}"} for index in range(10_000)]
    proof: list[dict[str, Any]] = []
    calibration_strata = ("Activity", "Explicit-Time", "Location", "Object", "Person", "State", "diversity_only")
    for stratum_index, sample_stratum in enumerate(calibration_strata):
        for sample_index in range(1, 51):
            index = stratum_index * 50 + sample_index - 1
            proof.append({"atom_id": candidates[index]["atom_id"], "record_type": "audit_sample", "sample_stratum": sample_stratum, "sample_index": sample_index})
    for index, candidate in enumerate(candidates):
        memberships = ["query_union", "diversity_reservoir"] if index % 4 == 0 else ["query_union"]
        proof.append({"atom_id": candidate["atom_id"], "record_type": "candidate", "selection_sequence": index + 1, "selection_memberships": memberships})
    source = [{
        "atom_id": candidate["atom_id"], "split": ("train", "dev", "test")[index % 3],
        "participant_source_id": f"P{index % 5}", "modality_coverage": ("both", "transcript_only", "dense_caption_only")[index % 3],
        "source_group_id": f"G{index % 17}",
    } for index, candidate in enumerate(candidates)]
    return candidates, proof, source


@pytest.mark.cue_v2
def test_cue_v2_two_worker_acceptance_plan_uses_closed_strata_quotas() -> None:
    """验收计划必须闭合最大余数配额，严格输出 900/120/390/390 且不等于简单排序截取。"""

    value = module()
    candidates, proof, source = cue_v2_acceptance_fixture()
    plan = value.build_protocol_acceptance_plan(candidates, proof, source)
    summary = plan["summary"]
    assert summary["candidate_count"] == 10_000 and summary["calibration_count"] == 350
    assert (summary["atom_count"], summary["overlap_count"], summary["main_count"]) == (900, 120, 780)
    assert summary["worker_counts"] == {"worker_00": 390, "worker_01": 390}
    assert summary["worker_input_counts"] == {"worker_00": 510, "worker_01": 510}
    assert set(plan["worker_partitions"]) == {"worker_00", "worker_01"}
    assert "worker_02" not in plan["worker_partitions"]
    assert len(plan["acceptance_atom_ids"]) == len(set(plan["acceptance_atom_ids"])) == 900
    assert len(plan["overlap_atom_ids"]) == len(set(plan["overlap_atom_ids"])) == 120
    assert set(plan["overlap_atom_ids"]).isdisjoint(set(plan["worker_partitions"]["worker_00"]) | set(plan["worker_partitions"]["worker_01"]))
    assert set(plan["worker_partitions"]["worker_00"]).isdisjoint(plan["worker_partitions"]["worker_01"])
    assert set(plan["worker_partitions"]["worker_00"]) | set(plan["worker_partitions"]["worker_01"]) == set(plan["acceptance_atom_ids"]) - set(plan["overlap_atom_ids"])
    assert all(set(plan["overlap_atom_ids"]).issubset(plan["worker_acceptance_inputs"][key]) for key in ("worker_00", "worker_01"))
    assert all(len(plan["worker_acceptance_inputs"][key]) == 510 for key in ("worker_00", "worker_01"))
    assert plan["acceptance_atom_ids"] != sorted(candidate["atom_id"] for candidate in candidates)[:900]
    assert sum(row["quota"] for row in plan["strata"]) == 900
    assert sum(row["actual_count"] for row in plan["strata"]) == 900
    assert all(len(row["key"]) == 5 for row in plan["strata"])
    assert len(plan["remainder_order"]) == len(plan["strata"]) and len(plan["overlap_remainder_order"]) == len(plan["overlap_strata"])
    assert len(plan["summary"]["acceptance_set_sha256"]) == 64 and len(plan["plan_sha256"]) == 64


@pytest.mark.cue_v2
def test_cue_v2_acceptance_plan_rejects_proof_source_and_calibration_gaps() -> None:
    """候选 proof 缺项、重复、越界、Source 缺项或非 350 校准必须稳定失败。"""

    value = module()
    candidates, proof, source = cue_v2_acceptance_fixture()
    candidate_start = 350
    with pytest.raises(value.BGESelectionPreflightError, match="ACCEPTANCE_CANDIDATE_PROOF_INCOMPLETE"):
        value.build_protocol_acceptance_plan(candidates, proof[:candidate_start] + proof[candidate_start + 1:], source)
    with pytest.raises(value.BGESelectionPreflightError, match="ACCEPTANCE_CANDIDATE_PROOF_DUPLICATE"):
        value.build_protocol_acceptance_plan(candidates, proof + [dict(proof[candidate_start])], source)
    out_of_range = {"atom_id": "src_out_of_range", "record_type": "candidate", "selection_sequence": 10_001, "selection_memberships": ["query_union"]}
    with pytest.raises(value.BGESelectionPreflightError, match="ACCEPTANCE_PROOF_ATOM_OUT_OF_RANGE"):
        value.build_protocol_acceptance_plan(candidates, proof + [out_of_range], source)
    with pytest.raises(value.BGESelectionPreflightError, match="ACCEPTANCE_SOURCE_ATOM_MISSING"):
        value.build_protocol_acceptance_plan(candidates, proof, source[:-1])
    with pytest.raises(value.BGESelectionPreflightError, match="ACCEPTANCE_CALIBRATION_STRATUM_COUNT_MISMATCH"):
        value.build_protocol_acceptance_plan(candidates, proof[1:], source)


@pytest.mark.cue_v2
def test_cue_v2_current_worker_identity_has_no_worker_02_leak() -> None:
    """当前配置和静态候选分区只允许两个 worker，历史文本不能成为运行身份。"""

    value = module()
    workers = value.partition_cue_v2_candidates([{"atom_id": f"src_{index:05d}"} for index in range(10_000)])
    assert list(workers) == ["worker_00", "worker_01"]
    assert [len(workers[key]) for key in workers] == [5_000, 5_000]
    config_text = (ROOT / "config/model_registry.yaml").read_text(encoding="utf-8")
    assert "worker_count: 2" in config_text and "worker_ids: [worker_00, worker_01]" in config_text
    assert "worker_02" not in config_text
    assert "worker_02" not in (ROOT / "scripts/05_extract_cues.py").read_text(encoding="utf-8")


@pytest.mark.cue_v2
def test_cue_v2_acceptance_reuses_preflight_atoms_without_scanning_source_again() -> None:
    """已有预检候选 Atom 时，验收计划不得再次遍历完整 Source。"""

    value = module()
    candidates, proof, source = cue_v2_acceptance_fixture()

    class ExplodingSource:
        def __iter__(self) -> Any:
            raise AssertionError("不应扫描完整 Source")

    plan = value.build_protocol_acceptance_plan(candidates, proof, ExplodingSource(), preflight_atoms=source)
    assert plan["summary"]["source_bound"] is True
    assert len(plan["acceptance_atom_ids"]) == 900


@pytest.mark.cue_v2
def test_cue_v2_acceptance_checks_sequence_and_audit_sample_identity() -> None:
    """selection_sequence 必须全局唯一，校准身份必须按七层局部 sample_index 闭合。"""

    value = module()
    candidates, proof, source = cue_v2_acceptance_fixture()
    duplicate_sequence = [dict(row) for row in proof]
    duplicate_sequence[351]["selection_sequence"] = duplicate_sequence[350]["selection_sequence"]
    with pytest.raises(value.BGESelectionPreflightError, match="ACCEPTANCE_SELECTION_SEQUENCE_DUPLICATE"):
        value.build_protocol_acceptance_plan(candidates, duplicate_sequence, source)
    bad_sample_index = [dict(row) for row in proof]
    bad_sample_index[0]["sample_index"] = 51
    with pytest.raises(value.BGESelectionPreflightError, match="ACCEPTANCE_CALIBRATION_SAMPLE_INDEX_INVALID"):
        value.build_protocol_acceptance_plan(candidates, bad_sample_index, source)


@pytest.mark.cue_v2
def test_cue_v2_calibration_uses_local_sample_index_and_stable_derived_index() -> None:
    """七层均可使用 sample_index=1，计划序号仍稳定派生为 1..350。"""

    value = module()
    candidates, proof, source = cue_v2_acceptance_fixture()
    plan = value.build_protocol_acceptance_plan(candidates, proof, source)
    calibration = plan["calibration"]
    assert len(calibration) == 350
    assert [row["calibration_index"] for row in calibration] == list(range(1, 351))
    assert [row["sample_stratum"] for row in calibration[::50]] == list(value._CUE_V2_CALIBRATION_STRATA)
    assert [row["sample_index"] for row in calibration[::50]] == [1] * 7
    assert all(set(row) == {"sample_stratum", "sample_index", "atom_id", "calibration_index"} for row in calibration)
    reversed_plan = value.build_protocol_acceptance_plan(candidates, list(reversed(proof)), source)
    assert reversed_plan["plan_sha256"] == plan["plan_sha256"]
    assert reversed_plan["calibration"] == calibration


@pytest.mark.cue_v2
def test_cue_v2_calibration_rejects_local_duplicates_unknown_strata_and_wrong_counts() -> None:
    """校准层名大小写、局部编号、Atom 身份和每层 50 条都是硬门。"""

    value = module()
    candidates, proof, source = cue_v2_acceptance_fixture()
    duplicate_index = [dict(row) for row in proof]
    duplicate_index[1]["sample_index"] = 1
    with pytest.raises(value.BGESelectionPreflightError, match="ACCEPTANCE_CALIBRATION_SAMPLE_INDEX_DUPLICATE"):
        value.build_protocol_acceptance_plan(candidates, duplicate_index, source)

    duplicate_atom = [dict(row) for row in proof]
    duplicate_atom[50]["atom_id"] = duplicate_atom[0]["atom_id"]
    with pytest.raises(value.BGESelectionPreflightError, match="ACCEPTANCE_CALIBRATION_ATOM_DUPLICATE"):
        value.build_protocol_acceptance_plan(candidates, duplicate_atom, source)

    unknown_stratum = [dict(row) for row in proof]
    unknown_stratum[0]["sample_stratum"] = "activity"
    with pytest.raises(value.BGESelectionPreflightError, match="ACCEPTANCE_CALIBRATION_STRATUM_INVALID"):
        value.build_protocol_acceptance_plan(candidates, unknown_stratum, source)

    missing_stratum_row = proof[0]
    missing = [dict(row) for row in proof if row is not missing_stratum_row]
    with pytest.raises(value.BGESelectionPreflightError, match="ACCEPTANCE_CALIBRATION_STRATUM_COUNT_MISMATCH"):
        value.build_protocol_acceptance_plan(candidates, missing, source)

    too_many = [dict(row) for row in proof]
    too_many[0]["sample_index"] = 51
    with pytest.raises(value.BGESelectionPreflightError, match="ACCEPTANCE_CALIBRATION_SAMPLE_INDEX_INVALID"):
        value.build_protocol_acceptance_plan(candidates, too_many, source)


@pytest.mark.cue_v2
def test_cue_v2_calibration_identity_cannot_be_reduced_to_sample_index() -> None:
    """计划暴露的校准记录必须同时携带层名、局部编号和 Atom 身份。"""

    value = module()
    candidates, proof, source = cue_v2_acceptance_fixture()
    plan = value.build_protocol_acceptance_plan(candidates, proof, source)
    assert all({"sample_stratum", "sample_index", "atom_id"}.issubset(row) for row in plan["calibration"])
    assert plan["calibration_protocol"] == {
        "identity_version": value._CUE_V2_CALIBRATION_IDENTITY_VERSION,
        "strata_order": list(value._CUE_V2_CALIBRATION_STRATA),
        "samples_per_stratum": 50,
        "index_rule": value._CUE_V2_CALIBRATION_INDEX_RULE,
    }
    sample_index_only = [dict(row) for row in proof]
    sample_index_only[0].pop("sample_stratum")
    with pytest.raises(value.BGESelectionPreflightError, match="ACCEPTANCE_CALIBRATION_STRATUM_INVALID"):
        value.build_protocol_acceptance_plan(candidates, sample_index_only, source)


@pytest.mark.cue_v2
def test_cue_v2_protocol_files_and_runtime_identities_are_disjoint() -> None:
    """Cue v2 与 legacy V3.6 必须绑定不同 prompt、Schema、路径、账本和 campaign 命名空间。"""

    registry = yaml.safe_load((ROOT / "config/model_registry.yaml").read_text(encoding="utf-8"))
    paths = yaml.safe_load((ROOT / "config/paths.yaml").read_text(encoding="utf-8"))
    v2 = registry["models"]["cue_v2_extraction"]
    legacy = registry["models"]["cue_extraction"]
    v2_schemas = {v2["inference_schema"], v2["formal_schema"], v2["inference_schema_path"], v2["formal_schema_path"]}
    legacy_schemas = {legacy["schema"], legacy["inference_schema_path"], legacy["execution"]["package_policy"]["inference_schema"]}
    assert v2_schemas.isdisjoint(legacy_schemas)
    assert v2["prompt_path"] != legacy["prompt_path"]
    assert v2["campaign_namespace"] == "cue_v2"
    assert v2["selection_id"] == "bge_m3_source_select_v3_1_20260914_02"
    assert legacy["prompt_version"] == "cue_extractor_v3_6_compact"
    assert set(v2["worker_resources"]) == {"worker_00", "worker_01"}
    assert len({v2["worker_resources"][worker]["budget_id"] for worker in v2["worker_resources"]}) == 2
    assert len({v2["worker_resources"][worker]["staging_root"] for worker in v2["worker_resources"]}) == 2
    assert len({v2["worker_resources"][worker]["ledger_path"] for worker in v2["worker_resources"]}) == 2
    assert paths["cue_v2"]["cue_v2_root"] != paths["cues_dir"]
    assert all("../cues/v2" in paths["cue_v2"][key] for key in ("cue_v2_root", "cue_v2_source_selection_root", "cue_v2_protocol_acceptance_root", "cue_v2_worker_staging_root", "cue_v2_formal_root", "cue_v2_disposition_ledger", "cue_v2_library_manifest", "cue_v2_library_success"))
    assert "../cues/formal" not in json.dumps(paths["cue_v2"], ensure_ascii=False)
    assert "worker_02" not in json.dumps(v2, ensure_ascii=False)


def cue_v2_bge_preflight_fixture(tmp_path: Path, value: Any) -> tuple[Path, Path, Path, str]:
    """构造最小五文件 BGE 快照，专门验证 origin Schema provenance 语义。"""

    snapshot = tmp_path / "selection"
    snapshot.mkdir()
    source_path = tmp_path / "source.jsonl"
    source_path.write_text(json.dumps({"atom_id": "src_1", "split": "train"}) + "\n", encoding="utf-8")
    candidate_path = snapshot / "candidate_atoms.jsonl"
    candidate_path.write_text(json.dumps({"atom_id": "src_1"}) + "\n", encoding="utf-8")
    proof_path = snapshot / "selection_proof.jsonl"
    proof_path.write_text(json.dumps({"record_type": "candidate", "atom_id": "src_1"}) + "\n", encoding="utf-8")
    schema_path = tmp_path / "effective_artifact.schema.json"
    schema_path.write_text(json.dumps({"$defs": {
        "candidate_atom": {"type": "object", "required": ["atom_id"], "properties": {"atom_id": {"type": "string"}}, "additionalProperties": False},
        "selection_proof_record": {"type": "object"},
    }}, ensure_ascii=False), encoding="utf-8")
    source_sha = value._cue_v2_sha256(source_path)
    report = {
        "selection_id": "synthetic_selection",
        "source_sha256": source_sha,
        "counts": {"final_candidates": 1},
        "blockers": [],
        "validation": {"machine_gate_passed": True},
        "solver": {"objective_statuses": ["OPTIMAL"]},
    }
    report_path = snapshot / "selection_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    files = []
    for path, rows in ((candidate_path, 1), (proof_path, 1), (report_path, 1)):
        files.append({"relative_path": path.name, "sha256": value._cue_v2_sha256(path), "byte_count": path.stat().st_size, "row_count": rows})
    bound_schema_sha = "f" * 64
    manifest = {
        "selection_id": "synthetic_selection", "artifact_schema_sha256": bound_schema_sha,
        "source_sha256": source_sha, "final_candidate_count": 1, "files": files,
    }
    manifest_path = snapshot / "selection_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    success = {
        "selection_id": "synthetic_selection", "artifact_schema_sha256": bound_schema_sha,
        "manifest_sha256": value._cue_v2_sha256(manifest_path), "candidate_count": 1, "source_sha256": source_sha,
    }
    (snapshot / "BGE_FILTER_SUCCESS.json").write_text(json.dumps(success, ensure_ascii=False), encoding="utf-8")
    return snapshot, source_path, schema_path, bound_schema_sha


@pytest.mark.cue_v2
def test_cue_v2_bge_preflight_strict_fails_but_adopted_keeps_data_gate_passed(tmp_path: Path) -> None:
    """strict 仍拒绝 Schema 身份不符；adopted 仅警告且允许候选进入 Cue 阶段。"""

    value = module()
    snapshot, source_path, schema_path, _bound_schema_sha = cue_v2_bge_preflight_fixture(tmp_path, value)
    with pytest.raises(value.BGESelectionPreflightError, match="ARTIFACT_SCHEMA_SHA_MISMATCH"):
        value.preflight_bge_selection_snapshot(snapshot, source_path, [schema_path], validation_profile="strict")
    adopted = value.preflight_bge_selection_snapshot(snapshot, source_path, [schema_path], validation_profile="adopted_external_v1")
    assert [row["atom_id"] for row in adopted["atoms"]] == ["src_1"]
    assert adopted["provenance_status"] == "origin_schema_unavailable"
    assert adopted["data_gate"] == "passed"
    assert adopted["provenance_gate"] == "warning"
    assert adopted["blockers"] == []
    assert adopted["warnings"] == ["ORIGIN_ARTIFACT_SCHEMA_UNAVAILABLE"]
    assert adopted["effective_validation_schema"]["sha256"] == value._cue_v2_sha256(schema_path)
    assert adopted["effective_validation_schema"]["origin_verified"] is False


@pytest.mark.cue_v2
def test_cue_v2_prompt_states_fact_and_protocol_boundaries() -> None:
    """Cue v2 prompt 必须明示 clause、连续 span、语义门和禁止的跨字段推断。"""

    prompt = (ROOT / "prompts/cue_extractor_v2.md").read_text(encoding="utf-8")
    required = (
        "1–3", "all_of", "连续原文", "跨字段", "跨 Atom", "常识补全", "visible_text",
        "event_timestamp", "人物角色", "否定", "范围", "时间语气", "no_cue", "ambiguous",
    )
    assert all(fragment in prompt for fragment in required)
