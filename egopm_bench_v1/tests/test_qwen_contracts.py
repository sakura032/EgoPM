"""第 05 阶段实时 Cue 执行器离线合同测试。

输入是冻结配置、合成 Atom 和假传输；输出是实时状态与无正文账本断言。本测试不读密钥、不联网。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

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
    payload = {"items": [{"n": 0, "t": "A", "p": [["A", "=", "活动"]], "x": "第1条文本", "c": 80, "v": "A"}]} if valid else {"items": []}
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
