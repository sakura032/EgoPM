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

ROOT = Path(__file__).resolve().parents[1]


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
    return {"atom_id": f"src_a_{index:03d}", "split": "train", "visible_text": f"第{index}条文本", "video_id": "v", "source_srt_path": "source/x.srt", "start_ms": 0, "end_ms": 1, "source_segment_ids": ["s"]}


def setup(value: Any) -> tuple[Any, Any, dict[str, Any], dict[str, dict[str, Any]]]:
    """读取实时配置并创建不带任何 Batch 身份字段的独立 package。"""
    settings, policy = value.realtime_policy_from_registry(ROOT / "config/model_registry.yaml")
    rows = [atom(1)]
    base = value.package_manifest(rows, "source", "protocol", "synthetic", 0, 0)
    manifest = value.realtime_manifest(base)
    return settings, policy, manifest, {"src_a_001": rows[0]}


def response(valid: bool = True, costly: bool = False) -> dict[str, Any]:
    """生成内存中的紧凑模型响应；不保存服务端原始文本。"""
    payload = {"items": [{"n": 0, "p": [["A", "=", "活动"]], "x": "第1条文本", "c": 80, "v": "A"}]} if valid else {"items": []}
    amount = 1_000_000 if costly else 10
    return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}], "usage": {"prompt_tokens": amount, "completion_tokens": amount, "total_tokens": amount * 2}}


def buckets(value: Any, policy: Any) -> tuple[Any, Any]:
    """创建即时令牌桶，测试无需真实等待。"""
    return value.TokenBucket(policy.requests_per_minute), value.TokenBucket(policy.tokens_per_minute)


def test_realtime_config_is_frozen() -> None:
    """模型、包大小、输出上限、重试、价格和传输必须来自 T0 冻结配置。"""
    value = module()
    settings, policy, *_ = setup(value)
    assert (settings.model_id, settings.thinking_enabled, settings.temperature) == ("qwen3.7-flash", False, 0)
    assert (settings.maximum_atoms, settings.output_tokens_per_atom, settings.max_retries) == (5, 96, 2)
    assert (policy.request_endpoint, policy.input_price_cny_per_million_tokens, policy.output_price_cny_per_million_tokens) == ("/chat/completions", 0.2, 0.8)


def test_token_bucket_waits_under_fake_clock() -> None:
    """客户端 RPM/TPM 桶耗尽后必须等待补充，不能无节制发送请求。"""
    value = module(); now = [0.0]; sleeps: list[float] = []
    bucket = value.TokenBucket(2, clock=lambda: now[0], sleep=lambda seconds: (sleeps.append(seconds), now.__setitem__(0, now[0] + seconds)))
    bucket.acquire(2); bucket.acquire(1)
    assert sleeps == [30.0]


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


def test_quarantine_budget_and_batch_mixing_are_stopped(tmp_path: Path) -> None:
    """本地验证失败隔离不重试，预算超限熔断，实时状态拒绝 Batch 根和字段。"""
    value = module(); settings, policy, manifest, rows = setup(value)
    class Invalid:
        calls = 0
        def complete(self, _body: dict[str, Any], _policy: Any) -> dict[str, Any]: self.calls += 1; return response(False)
    invalid = Invalid()
    result = value.execute_realtime_package(manifest, rows, "p", {"type": "object"}, settings, policy, invalid, tmp_path / "realtime", 1.0, *buckets(value, policy))
    assert result[0] == "local_validation_quarantine" and invalid.calls == 1 and result[2]["retry_eligible"] is False
    class Costly:
        def complete(self, _body: dict[str, Any], _policy: Any) -> dict[str, Any]: return response(costly=True)
    result = value.execute_realtime_package(manifest, rows, "p", {"type": "object"}, settings, policy, Costly(), tmp_path / "other", 0.01, *buckets(value, policy))
    assert result[0] == "budget_stopped"
    with pytest.raises(value.ContractError, match="Batch"): value.realtime_package_state_path(tmp_path / "batch", manifest)
    with pytest.raises(value.ContractError, match="Batch"): value.validate_realtime_ledger_event({**result[2], "batch_custom_id": "x"})


@pytest.mark.parametrize(
    ("payload", "expected_code", "expected_path"),
    [
        ("{", "JSON_PARSE", "/"),
        (json.dumps({"items": [{"n": 0, "p": [["A", "=", "活动"]], "x": "不存在", "c": 80, "v": "A"}]}, ensure_ascii=False), "SUPPORTING_TEXT_NOT_SUBSTRING", "/items/0/x"),
    ],
)
def test_local_validation_quarantine_records_safe_category_only(tmp_path: Path, payload: str, expected_code: str, expected_path: str) -> None:
    """已计费的本地失败必须落盘固定类别/路径，且诊断不含模型输出正文。"""
    value = module(); settings, policy, manifest, rows = setup(value)

    class Invalid:
        def complete(self, _body: dict[str, Any], _policy: Any) -> dict[str, Any]:
            return {"choices": [{"message": {"content": payload}}], "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}

    root = tmp_path / "realtime"
    result = value.execute_realtime_package(manifest, rows, "p", {"type": "object"}, settings, policy, Invalid(), root, 1.0, *buckets(value, policy))
    state = json.loads((root / "packages" / manifest["package_id"] / "realtime_state.json").read_text(encoding="utf-8"))
    assert result[0] == "local_validation_quarantine"
    assert result[2]["local_validation_failure"] == {"code": expected_code, "path": expected_path}
    assert state["local_validation_failure"] == {"code": expected_code, "path": expected_path}
    persisted = json.dumps(state, ensure_ascii=False)
    assert "choices" not in persisted and "message" not in persisted
    if payload != "{":
        assert payload not in persisted
    value.validate_realtime_ledger_event(result[2])


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


def test_server_compatible_inference_schema_keeps_entity_deduplication_locally() -> None:
    """服务端不支持 uniqueItems 时，本地解析仍须拒绝重复实体。"""
    value = module(); settings, _policy, _manifest, rows = setup(value)
    schema = json.loads((ROOT / "schemas/cue_inference_batch_compact_v1.schema.json").read_text(encoding="utf-8"))
    assert "uniqueItems" not in json.dumps(schema, ensure_ascii=False)
    inference_validator = value.load_validator(ROOT / "schemas/cue_inference_batch_compact_v1.schema.json")
    cue_validator = value.load_validator(ROOT / "schemas/cue_candidate.schema.json")
    duplicate = {"items": [{"n": 0, "p": [["A", "=", "活动"]], "x": "第1条文本", "c": 80, "v": "A", "e": ["物品", "物品"]}]}
    with pytest.raises(value.LocalValidationError, match="ENTITY_DUPLICATE"):
        value.parse_inference_items(duplicate, [rows["src_a_001"]], inference_validator, cue_validator, settings, "synthetic")


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


def test_later_wave_requires_each_prior_wave_to_complete(tmp_path: Path) -> None:
    """启动 Wave 2 前必须离线确认 Wave 1 同 run/Source/协议下零失败地完整完成。"""
    value = module(); settings, _policy, *_ = setup(value)
    preflight = {"run_id": "shared", "source_atoms_sha256": "source", "cue_execution_protocol_sha256": "protocol"}
    success = {
        "status": "completed", "run_id": "shared", "source_atoms_sha256": "source", "cue_execution_protocol_sha256": "protocol",
        "wave_index": 1, "total_packages": 3, "completed_packages": 3, "in_flight_packages": 0,
        "validated_success_packages": 3, "local_validation_quarantine_packages": 0,
        "service_transport_exhausted_packages": 0, "budget_stopped_packages": 0,
    }
    value.atomic_write_json(tmp_path / "wave_01" / "progress.json", success)
    value.require_completed_prior_waves(tmp_path, 2, preflight, settings)
    success["service_transport_exhausted_packages"] = 1
    value.atomic_write_json(tmp_path / "wave_01" / "progress.json", success)
    with pytest.raises(value.ContractError, match="尚未完整成功"):
        value.require_completed_prior_waves(tmp_path, 2, preflight, settings)
