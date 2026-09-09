#!/usr/bin/env python3
"""EgoPM-Bench v1 的只读全量质检器。

职责：在 T1、T2、T3 的产物冻结后执行独立 QA，而不修改其脚本或 JSONL。
输入：`benchmark_protocol.yaml`、同目录路径/切分配置、SUCCESS 标记及已冻结 JSONL。
输出：`audit/validation_errors.jsonl`、`audit/leakage_report.json`，零阻断时才输出最终 SUCCESS 标记。
流水线位置：第 11 步，位于 source、cue、seed、lifelog/oracle 生产之后、统计与发布之前。

本脚本绝不修改生产者产物。它只会在某阶段的 SUCCESS 标记完整、哈希和
行数一致后读取该阶段的 JSONL；审计报告写入 audit/，且以原子替换完成。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import jsonschema
import yaml


BENCHMARK_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_VERSION = "v1.1.0"
REPRODUCTION_COMMAND = (
    "python egopm_bench_v1/scripts/11_validate_all.py "
    "--config egopm_bench_v1/config/benchmark_protocol.yaml"
)

STAGES: tuple[tuple[str, str, str, str, str], ...] = (
    ("source", "source_atoms", "source_atoms", "source_video_atom.schema.json", "T1 source"),
    ("cue", "cue_library", "cue_library", "cue_candidate.schema.json", "T2 cue"),
    ("candidate", "seed_candidates", "seed_candidates", "reminder_seed.schema.json", "T2 seed"),
    ("frozen", "frozen_seeds", "frozen_seeds", "reminder_seed.schema.json", "T3 compiler"),
    ("lifelog", "lifelogs", "lifelogs", "lifelog.schema.json", "T3 compiler"),
    ("decisions", "decisions", "decision_instances", "decision_instance.schema.json", "T3 compiler"),
)
# 每个阶段在首次正式产物发布时冻结自己的合同、配置和 Schema 版本。后续执行配置
# 可以升级，但已经完成且被下游引用的 Source 不能因此被追溯判为无效；反过来，不能
# 用全局合同版本替代具体 Schema 版本，否则会把仍为 v1.0.0 的 Cue 误判为错误。
STAGE_ARTIFACT_VERSIONS: dict[str, dict[str, Any]] = {
    "source": {
        "contract_version": "v1.1.0",
        "config_version": "v1.1.0",
        "schema_versions": {
            "source_video_atom": "v1.1.0",
            "source_video_atom_draft": "v1.1.0",
        },
    },
    "cue": {
        "contract_version": "v1.1.0",
        "config_version": "v1.1.0",
        "schema_versions": {"cue_candidate": "v1.1.0"},
    },
    "candidate": {
        "contract_version": "v1.1.0",
        "config_version": "v1.1.0",
        "schema_versions": {"reminder_seed": "v1.1.0"},
    },
    "frozen": {
        "contract_version": "v1.1.0",
        "config_version": "v1.1.0",
        "schema_versions": {
            "reminder_seed": "v1.1.0",
            "state_machine_policy": "v1.0.0",
        },
    },
    "lifelog": {
        "contract_version": "v1.1.0",
        "config_version": "v1.1.0",
        "schema_versions": {
            "lifelog": "v1.0.0",
            "reminder_seed": "v1.1.0",
        },
    },
    "decisions": {
        "contract_version": "v1.1.0",
        "config_version": "v1.1.0",
        "schema_versions": {
            "decision_instance": "v1.0.0",
            "lifelog": "v1.0.0",
        },
    },
}
STAGE_DEPENDENCIES = {
    "source": (),
    "cue": ("source",),
    "candidate": ("source", "cue"),
    "frozen": ("source", "candidate"),
    "lifelog": ("source", "frozen"),
    "decisions": ("source", "frozen", "lifelog"),
}
# Cue v2 的最终数据 Schema 保持 v1.0.0，但其执行过程另有冻结的请求协议。下面的
# 字段是最终 SUCCESS 可审计地指向该协议、冻结 Source 和无正文用量账本的最小边界；
# 不能仅凭最终 JSONL 合法就接受来自不同提示词、模型或推理 Schema 的混合结果。
CUE_V22_MARKER_FIELDS = {
    "source_atoms_sha256",
    "model_id",
    "prompt_version",
    "cue_execution_policy_version",
    "protocol_hash_payload_version",
    "cue_execution_protocol_sha256",
    "cue_prompt_sha256",
    "cue_inference_schema",
    "cue_inference_schema_version",
    "cue_inference_schema_sha256",
    "usage_summary",
    "batch_transport",
    "batch_task_count",
    "batch_tasks_manifest_sha256",
    "batch_input_total_request_count",
    "batch_local_raw_response_storage",
    "remote_cleanup_required",
    "remote_cleanup_status",
}
CUE_V2_USAGE_SUMMARY_FIELDS = {
    "package_count",
    "attempt_count",
    "successful_attempt_count",
    "failed_attempt_count",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "missing_usage_count",
    "retry_count",
    "rate_limit_wait_seconds",
}
# v3 实时路径不沿用 Batch task/file 术语。最终标记必须把运行状态、分片清单和
# 无正文运行账本绑定在同一 Source/协议哈希上，防止已取消的 Batch 产物被误当作实时
# 结果，或把另一轮实时运行的片段混入当前 Cue library。
CUE_V30_MARKER_FIELDS = {
    "source_atoms_sha256",
    "model_id",
    "prompt_version",
    "cue_execution_policy_version",
    "protocol_hash_payload_version",
    "cue_execution_protocol_sha256",
    "cue_prompt_sha256",
    "cue_inference_schema",
    "cue_inference_schema_version",
    "cue_inference_schema_sha256",
    "usage_summary",
    "realtime_transport",
    "realtime_shard_count",
    "realtime_shards_manifest_sha256",
    "realtime_run_state_sha256",
    "realtime_run_ledger_sha256",
    "realtime_local_raw_response_storage",
}
REALTIME_SHARD_REQUIRED_FIELDS = {
    "run_id",
    "transport",
    "realtime_shard_index",
    "source_atoms_sha256",
    "cue_execution_protocol_sha256",
    "package_count",
    "package_ids_sha256",
    "package_id_to_request_sha256",
    "status",
    "completion_sha256",
}
REALTIME_PACKAGE_STATE_REQUIRED_FIELDS = {
    "run_id",
    "transport",
    "realtime_shard_index",
    "package_id",
    "source_atoms_sha256",
    "cue_execution_protocol_sha256",
    "request_sha256",
    "attempt",
    "retry_count",
    "status",
}
REALTIME_COMPLETE_REQUIRED_FIELDS = {
    "run_id",
    "transport",
    "realtime_shard_index",
    "package_id",
    "source_atoms_sha256",
    "cue_execution_protocol_sha256",
    "request_sha256",
    "status",
    "result_sha256",
    "ledger_sha256",
    "state_sha256",
}
REALTIME_RUN_STATE_REQUIRED_FIELDS = {
    "run_id",
    "transport",
    "source_atoms_sha256",
    "cue_execution_protocol_sha256",
    "status",
    "authorized_budget_cny",
    "estimated_cost_cny",
    "usage_summary",
    "wave_index",
    "wave_task_indexes",
}
# `progress.json` 是运行中的只读查询快照而不是 Cue 产物；但最终 SUCCESS 审计仍需
# 检查其末态，以证明实际调度没有突破已批准的八波边界或十个在飞 package 上限。
REALTIME_PROGRESS_REQUIRED_FIELDS = {
    "status",
    "wave_index",
    "wave_task_indexes",
    "total_packages",
    "completed_packages",
    "validated_success_packages",
    "local_validation_quarantine_packages",
    "needs_item_audit_packages",
    "service_transport_exhausted_packages",
    "budget_stopped_packages",
    "in_flight_packages",
    "authorized_budget_cny",
    "spent_cny",
    "elapsed_seconds",
    "eta_seconds",
    "raw_response_saved",
    "updated_at",
}
REALTIME_WAVE_TASK_COUNTS = (1, 10, 10, 10, 10, 10, 10, 14)
REALTIME_RAW_CONTENT_EXTRA_FIELDS = {
    "batch_custom_id",
    "batch_id",
    "batch_input_sha256",
    "batch_task_index",
    "input_atom_ids",
    "input_manifest",
    "remote_file_id",
    "raw_response_path",
    "validation_errors",
}
# v2.2 的 Batch 汇总清单是可审计的无正文元数据，不是上传的请求 JSONL。固定文件名
# 让 QA 能在不保留 `visible_text`、请求 body 或模型 response/error 的情况下，重算任务
# 数、输入哈希和 custom_id 到本地 package 的双向映射。
BATCH_TASKS_MANIFEST_NAME = "batch_tasks_manifest.jsonl"
BATCH_TASK_REQUIRED_FIELDS = {
    "run_id",
    "wave_index",
    "batch_task_index",
    "source_atoms_sha256",
    "cue_execution_protocol_sha256",
    "batch_input_sha256",
    "request_count",
    "custom_ids_sha256",
    "logical_shard_start",
    "logical_shard_end",
    "remote_file_id",
    "status",
    "custom_id_to_package_id",
}
# Batch 返回正文只能在内存中逐行验证。receipt 与 ledger 因而只记录可复算的 ID、
# 计数和行哈希：它们既能把服务端结果绑定到提交任务，又不会把 SRT 文本、模型内容或
# 错误详情作为本地审计数据保存下来。
BATCH_RECEIPT_REQUIRED_FIELDS = {
    "run_id",
    "wave_index",
    "batch_task_index",
    "batch_id",
    "remote_file_id",
    "output_file_id",
    "error_file_id",
    "batch_input_sha256",
    "source_atoms_sha256",
    "cue_execution_protocol_sha256",
    "status",
    "request_count",
    "received_line_count",
    "validated_count",
    "service_line_failure_count",
    "local_validation_quarantine_count",
    "remote_result_line_sha256",
    "remote_error_line_sha256",
    "received_at",
    "raw_response_saved",
}
BATCH_RECEIVER_LEDGER_FIELDS = {
    "batch_id",
    "result_file_id",
    "error_file_id",
    "result_line_sha256",
    "retry_eligible",
    "failure_origin",
}
BATCH_RAW_CONTENT_FIELDS = {
    "body",
    "content",
    "error",
    "messages",
    "request",
    "request_body",
    "response",
    "source_text",
    "text",
    "visible_text",
}
REALTIME_RAW_CONTENT_FIELDS = BATCH_RAW_CONTENT_FIELDS | REALTIME_RAW_CONTENT_EXTRA_FIELDS
BATCH_CUSTOM_ID = re.compile(r"^v22_s\d{5}_p\d{3}_[0-9a-f]{8}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
TERMINAL_STATES = {"completed", "cancelled", "expired"}
STATE_TRANSITIONS = {
    None: {None, "active_unreminded"},
    "active_unreminded": {
        "active_unreminded",
        "active_reminded",
        "completed",
        "cancelled",
        "expired",
    },
    "active_reminded": {"active_reminded", "completed", "cancelled", "expired"},
    "completed": {"completed"},
    "cancelled": {"cancelled"},
    "expired": {"expired"},
}
FORBIDDEN_INPUT_MARKERS = (
    "gold_action",
    "event_role",
    "rule_id",
    "intention_state_before",
    "intention_state_after",
    "oracle_annotation",
)
SRT_TIMESTAMP = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>[0-5]\d):(?P<s>[0-5]\d)[,.](?P<ms>\d{3})"
)
VIRTUAL_TIME = re.compile(r"^D(?P<d>\d{2}) (?P<h>[0-2]\d):(?P<m>[0-5]\d)(?::(?P<s>[0-5]\d))?$")


@dataclass(frozen=True)
class RunConfig:
    config_path: Path
    config_dir: Path
    project_root: Path
    benchmark_root: Path
    raw_root: Path
    paths: dict[str, Any]
    protocol: dict[str, Any]
    split_policy: dict[str, Any]

    def artifact(self, key: str) -> Path:
        return (self.config_dir / self.paths["artifacts"][key]).resolve()

    def marker(self, key: str) -> Path:
        return (self.config_dir / self.paths["success_markers"][key]).resolve()

    def relative_artifact_names(self, path: Path) -> set[str]:
        """接受项目根或 benchmark 根相对路径，避免路径锚点产生歧义。"""
        names: set[str] = set()
        for root in (self.project_root, self.benchmark_root):
            try:
                names.add(path.relative_to(root).as_posix())
            except ValueError:
                continue
        return names

    def canonical_artifact_name(self, path: Path) -> str:
        """SUCCESS 标记优先使用 benchmark 根相对路径，保证跨次运行稳定。"""
        for root in (self.benchmark_root, self.project_root):
            try:
                return path.relative_to(root).as_posix()
            except ValueError:
                continue
        raise ValueError(f"产物不在受管项目路径内：{path}")


@dataclass
class IssueCollector:
    issues: list[dict[str, Any]] = field(default_factory=list)

    def add(
        self,
        severity: str,
        issue_type: str,
        failure_id: str,
        expected: str,
        actual: str,
        recommended_fix_stage: str,
    ) -> None:
        self.issues.append(
            {
                "severity": severity,
                "issue_type": issue_type,
                "failure_id": failure_id,
                "expected": expected,
                "actual": actual,
                "reproduction_command": REPRODUCTION_COMMAND,
                "recommended_fix_stage": recommended_fix_stage,
            }
        )

    @property
    def blockers(self) -> list[dict[str, Any]]:
        return [issue for issue in self.issues if issue["severity"] == "BLOCKER"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    """按 v2 固定 JSON 编码计算协议哈希，避免键顺序或空白造成不可重现的血缘。"""

    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    # 审计文件也必须避免“读到半个文件”：先完整落盘临时文件，再原子替换正式结果。
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def load_run_config(config_path: Path) -> RunConfig:
    config_path = config_path.resolve()
    config_dir = config_path.parent
    protocol = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    paths_path = config_dir / "paths.yaml"
    split_path = config_dir / "split_policy.yaml"
    paths = yaml.safe_load(paths_path.read_text(encoding="utf-8"))
    split_policy = yaml.safe_load(split_path.read_text(encoding="utf-8"))
    for document_name, document in (
        ("评测协议", protocol),
        ("路径配置", paths),
        ("切分配置", split_policy),
    ):
        if document.get("contract_version") != CONTRACT_VERSION:
            raise ValueError(f"{document_name}合同版本不是 {CONTRACT_VERSION}")
        if document.get("config_version") != CONTRACT_VERSION:
            raise ValueError(f"{document_name}配置版本不是 {CONTRACT_VERSION}")
    return RunConfig(
        config_path=config_path,
        config_dir=config_dir,
        project_root=(config_dir / paths["project_root"]).resolve(),
        benchmark_root=(config_dir / paths["benchmark_root"]).resolve(),
        raw_root=(config_dir / paths["raw_root"]).resolve(),
        paths=paths,
        protocol=protocol,
        split_policy=split_policy,
    )


def load_json(path: Path, collector: IssueCollector, issue_prefix: str, owner: str) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        collector.add("BLOCKER", f"{issue_prefix}_unreadable", str(path), "可解析 JSON 对象", str(exc), owner)
        return None
    if not isinstance(value, dict):
        collector.add("BLOCKER", f"{issue_prefix}_shape", str(path), "JSON 对象", type(value).__name__, owner)
        return None
    return value


def cue_v2_execution_contract(
    config: RunConfig,
    collector: IssueCollector,
    owner: str,
) -> dict[str, Any] | None:
    """读取并哈希 T0 冻结的 Cue v2.2 配置、紧凑提示词和推理 Schema，不信任生产者自报。"""

    registry_path = config.config_dir / "model_registry.yaml"
    try:
        registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        collector.add("BLOCKER", "cue_execution_contract_unreadable", "cue", "可读取 model_registry.yaml", str(exc), owner)
        return None
    if not isinstance(registry, dict):
        collector.add("BLOCKER", "cue_execution_contract_shape", "cue", "model_registry.yaml 为对象", type(registry).__name__, owner)
        return None
    cue = registry.get("models", {}).get("cue_extraction")
    if not isinstance(cue, dict) or not isinstance(cue.get("execution"), dict):
        collector.add("BLOCKER", "cue_execution_contract_fields", "cue", "冻结 cue_extraction 与 execution", repr(cue), owner)
        return None
    execution = cue["execution"]
    package = execution.get("package_policy")
    if not isinstance(package, dict):
        collector.add("BLOCKER", "cue_execution_contract_fields", "cue", "冻结 package_policy", repr(package), owner)
        return None
    required = {
        "model_id",
        "thinking_enabled",
        "reasoning_effort",
        "temperature",
        "prompt_version",
        "schema",
        "schema_version",
    }
    service_required = {"default_endpoint", "default_region", "credential_policy", "raw_response_policy"}
    execution_required = {
        "cue_execution_policy_version",
        "protocol_hash_payload_version",
        "compact_inference_policy",
        "controlled_field_policy",
        "pricing_snapshot",
        "recovery",
        "shard_layout",
        "token_accounting",
        "transport",
    }
    transport = execution.get("transport")
    if transport == "batch_file":
        execution_required |= {"batch_file_policy", "batch_ledger_policy"}
    elif transport == "realtime_chat_completions":
        execution_required |= {"realtime_api_policy", "realtime_ledger_policy", "realtime_execution_policy"}
    else:
        collector.add(
            "BLOCKER",
            "cue_execution_transport",
            "cue",
            "batch_file 或 realtime_chat_completions",
            repr(transport),
            owner,
        )
        return None
    package_required = {
        "maximum_atoms",
        "maximum_request_utf8_bytes",
        "output_tokens_per_atom",
        "inference_schema",
        "inference_schema_version",
    }
    if required.difference(cue) or service_required.difference(registry) or execution_required.difference(execution) or package_required.difference(package):
        collector.add(
            "BLOCKER",
            "cue_execution_contract_fields",
            "cue",
            "完整的 v2 模型、协议和 package 冻结字段",
            f"cue 缺少 {sorted(required.difference(cue))}；service 缺少 {sorted(service_required.difference(registry))}；execution 缺少 {sorted(execution_required.difference(execution))}；package 缺少 {sorted(package_required.difference(package))}",
            owner,
        )
        return None
    prompt_path = config.benchmark_root / "prompts" / f"{cue['prompt_version']}.md"
    if not prompt_path.is_file() and cue.get("prompt_version") == "cue_extractor_v3_6_compact":
        # v3.6 的协议版本登记升级了，但仓库保留兼容的紧凑提示词文件名；协议哈希
        # 绑定文件内容，不把不存在的版本化文件名误报成正式 Cue 缺失。
        prompt_path = config.benchmark_root / "prompts" / "cue_extractor_v3_compact.md"
    inference_schema_path = config.benchmark_root / "schemas" / str(package["inference_schema"])
    if not prompt_path.is_file() or not inference_schema_path.is_file():
        collector.add(
            "BLOCKER",
            "cue_execution_contract_artifact",
            "cue",
            "存在冻结提示词与推理 Schema",
            f"prompt={prompt_path.is_file()}, schema={inference_schema_path.is_file()}",
            owner,
        )
        return None
    prompt_sha256 = sha256_file(prompt_path)
    inference_schema_sha256 = sha256_file(inference_schema_path)
    # 协议哈希必须覆盖完整冻结执行合同，而不只覆盖打包尺寸。否则重试、限流、受控
    # 字段、账本口径、恢复语义或价格发生变化时，旧 package 仍可能被错误地当作可恢复。
    # Source 哈希故意不在这里：它属于每次运行的输入血缘，单独由 SUCCESS 字段验证。
    protocol_payload = {
        "payload_version": execution["protocol_hash_payload_version"],
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
        "execution": execution,
        "cue_prompt_sha256": prompt_sha256,
        "cue_inference_schema_sha256": inference_schema_sha256,
    }
    return {
        "model_id": cue["model_id"],
        "prompt_version": cue["prompt_version"],
        "final_cue_schema_version": cue["schema_version"],
        "transport": transport,
        "cue_execution_policy_version": execution["cue_execution_policy_version"],
        "protocol_hash_payload_version": execution["protocol_hash_payload_version"],
        "cue_prompt_sha256": prompt_sha256,
        "cue_inference_schema": package["inference_schema"],
        "cue_inference_schema_version": package["inference_schema_version"],
        "cue_inference_schema_sha256": inference_schema_sha256,
        "cue_execution_protocol_sha256": canonical_sha256(protocol_payload),
    }


def batch_tasks_manifest_path(config: RunConfig, contract: dict[str, Any]) -> Path:
    """返回 v2.2 固定的无正文 Batch 汇总清单路径，不接受生产者提供的任意路径。"""

    # 该名称是运行布局的一部分：若允许 SUCCESS 指向任意文件，攻击者可用另一轮运行的
    # 清单替换它而不触发路径门。清单内只有哈希、ID 与 package 映射，绝不保存请求正文。
    registry = yaml.safe_load((config.config_dir / "model_registry.yaml").read_text(encoding="utf-8"))
    layout = registry["models"]["cue_extraction"]["execution"]["shard_layout"]
    if layout.get("batch_tasks_manifest") != BATCH_TASKS_MANIFEST_NAME:
        raise ValueError("冻结 Batch task 汇总清单文件名不符合 v2.2 合同")
    return config.benchmark_root / str(layout["root"]) / BATCH_TASKS_MANIFEST_NAME


def has_forbidden_batch_content(value: Any) -> bool:
    """递归识别 Batch 元数据中不应落盘的请求/响应正文键。"""

    if isinstance(value, dict):
        return any(key in BATCH_RAW_CONTENT_FIELDS or has_forbidden_batch_content(item) for key, item in value.items())
    if isinstance(value, list):
        return any(has_forbidden_batch_content(item) for item in value)
    return False


def batch_receipt_path(config: RunConfig, wave_index: int, task_index: int) -> Path:
    """根据冻结运行布局定位 task receipt，拒绝让清单把 QA 引向任意本地文件。"""

    # receipt 所在 wave 与 task 索引共同构成提交后的稳定地址。若以生产者自报的路径
    # 为准，另一轮的 receipt 可被替换进来，使 Batch ID 和输入哈希的检查失去意义。
    registry = yaml.safe_load((config.config_dir / "model_registry.yaml").read_text(encoding="utf-8"))
    layout = registry["models"]["cue_extraction"]["execution"]["shard_layout"]
    suffix = str(layout["batch_receipt_suffix"])
    return config.benchmark_root / str(layout["root"]) / f"wave_{wave_index:02d}" / f"task_{task_index:03d}{suffix}"


def is_optional_remote_file_id(value: Any) -> bool:
    """远端文件 ID 可为空，但非空时必须是无空白的标识符。"""

    return value is None or (isinstance(value, str) and bool(value.strip()))


def is_optional_sha256(value: Any) -> bool:
    """未生成对应远端文件时允许空哈希，生成后必须留下完整行流哈希。"""

    return value is None or (isinstance(value, str) and SHA256_HEX.fullmatch(value) is not None)


def validate_batch_task_receipts(
    config: RunConfig,
    marker: dict[str, Any],
    collector: IssueCollector,
    owner: str,
) -> bool:
    """验证 Batch 接收 receipt 的远端血缘、计数与“仅流式、不存正文”边界。"""

    manifest_path = batch_tasks_manifest_path(config, marker)
    tasks = read_jsonl(manifest_path, collector, "cue_batch_manifest", owner)
    valid = True
    for line_number, task in enumerate(tasks, start=1):
        label = f"task:{line_number}"
        required_task = {"run_id", "wave_index", "batch_task_index"}
        if required_task.difference(task):
            # task manifest 的字段门会同时报错；这里提前跳过避免不可信索引被用于拼路径。
            valid = False
            continue
        wave_index = task["wave_index"]
        task_index = task["batch_task_index"]
        if not all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (wave_index, task_index)):
            collector.add("BLOCKER", "cue_batch_receipt_path", label, "非负整数 wave/task 索引", repr((wave_index, task_index)), owner)
            valid = False
            continue
        receipt_path = batch_receipt_path(config, wave_index, task_index)
        receipt = load_json(receipt_path, collector, "cue_batch_receipt", owner)
        if receipt is None:
            valid = False
            continue
        if has_forbidden_batch_content(receipt):
            collector.add("BLOCKER", "cue_batch_receipt_raw_content", str(receipt_path), "仅无正文 receipt 元数据", "发现请求、响应、错误或可见文本字段", owner)
            valid = False
        missing = sorted(BATCH_RECEIPT_REQUIRED_FIELDS.difference(receipt))
        if missing:
            collector.add("BLOCKER", "cue_batch_receipt_fields", str(receipt_path), "完整的 Batch 接收 receipt", f"缺少 {missing}", owner)
            valid = False
            continue
        for field_name in ("run_id", "wave_index", "batch_task_index", "remote_file_id", "batch_input_sha256", "source_atoms_sha256", "cue_execution_protocol_sha256", "request_count"):
            if receipt[field_name] != task.get(field_name):
                collector.add("BLOCKER", "cue_batch_receipt_lineage", f"{label}:{field_name}", repr(task.get(field_name)), repr(receipt[field_name]), owner)
                valid = False
        if not isinstance(receipt["batch_id"], str) or not receipt["batch_id"].strip() or receipt["status"] != "completed":
            collector.add("BLOCKER", "cue_batch_receipt_status", label, "已完成且具有 batch_id 的 task receipt", repr({"batch_id": receipt["batch_id"], "status": receipt["status"]}), owner)
            valid = False
        if receipt["raw_response_saved"] is not False:
            collector.add("BLOCKER", "cue_batch_receipt_raw_response_policy", label, "raw_response_saved=false", repr(receipt["raw_response_saved"]), owner)
            valid = False
        for file_field, hash_field in (("output_file_id", "remote_result_line_sha256"), ("error_file_id", "remote_error_line_sha256")):
            file_id, line_hash = receipt[file_field], receipt[hash_field]
            if not is_optional_remote_file_id(file_id) or not is_optional_sha256(line_hash) or (file_id is None) != (line_hash is None):
                collector.add("BLOCKER", "cue_batch_receipt_remote_hash", f"{label}:{file_field}", "远端文件 ID 与对应 64 位行流 SHA256 同时存在或同时为空", repr({file_field: file_id, hash_field: line_hash}), owner)
                valid = False
        count_fields = ("request_count", "received_line_count", "validated_count", "service_line_failure_count", "local_validation_quarantine_count")
        if not all(isinstance(receipt[field], int) and not isinstance(receipt[field], bool) and receipt[field] >= 0 for field in count_fields):
            collector.add("BLOCKER", "cue_batch_receipt_counts", label, "全部接收计数均为非负整数", repr({field: receipt[field] for field in count_fields}), owner)
            valid = False
            continue
        terminal_count = receipt["validated_count"] + receipt["service_line_failure_count"] + receipt["local_validation_quarantine_count"]
        if receipt["received_line_count"] != receipt["request_count"] or terminal_count != receipt["request_count"]:
            collector.add("BLOCKER", "cue_batch_receipt_counts", label, "received_line_count 与三类终态计数均覆盖 request_count", repr({field: receipt[field] for field in count_fields}), owner)
            valid = False
    return valid


def source_span_from_normalized_evidence(source: str, evidence: str) -> str:
    """在一个原始字段内确定性恢复归一化连续证据的原文切片。

    输入：同一 Atom 的单个来源字段与模型给出的 `x` 证据字符串。
    输出：该字段中首个归一化连续命中的原始连续片段；找不到时抛出错误。
    流水线位置：第 11 步 T4 对 v3.6 紧凑 Cue 的独立血缘复算。

    不能把字段拼接后再查找：即使归一化允许空白、标点、全半角和大小写差异，
    证据的开始、结束与保存内容也必须仍落在同一个声明字段的连续区间内。
    """

    normalized_evidence = cue_evidence_normalized_text(evidence)
    if not normalized_evidence:
        raise ValueError("紧凑 Cue 的归一化证据不能为空")
    # 按原始字符累积被保留的规范字符，并保存每个规范字符对应的原文位置。NFKC
    # 可能展开为多个字符，故每一个展开字符均回指同一原文字符；这使切片仍保持原文连续。
    normalized_parts: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    for index, character in enumerate(source):
        for normalized_character in unicodedata.normalize("NFKC", character).casefold():
            if (
                not normalized_character.isspace()
                and not unicodedata.category(normalized_character).startswith("P")
                and unicodedata.category(normalized_character) != "Cf"
            ):
                normalized_parts.append(normalized_character)
                starts.append(index)
                ends.append(index + 1)
    normalized_source = "".join(normalized_parts)
    match_start = normalized_source.find(normalized_evidence)
    if match_start < 0:
        raise ValueError("紧凑 Cue 的归一化证据不在声明字段内连续出现")
    match_end = match_start + len(normalized_evidence)
    return source[starts[match_start] : ends[match_end - 1]]


def expand_compact_cue_for_qa(
    compact: dict[str, Any],
    atom: dict[str, Any],
    contract: dict[str, Any],
    run_id: str,
    config: RunConfig,
) -> dict[str, Any]:
    """独立展开一条 v3.6 紧凑 Cue，供 QA 复算最终 Schema 的原文证据。

    输入是模型给出的单字段码和归一化证据 `x`；输出是程序从同一 Atom 声明字段
    恢复的原文连续片段。它位于第 11 步 T4 独立 QA，不拼接 transcript、
    dense_caption 与 visible_text，也不接受释义、翻译或词序重排。
    """

    # 必须读取与当前 SUCCESS 同一份临时/正式配置：直接引用工作树全局 registry 会让
    # 测试在复制配置被篡改时仍错误通过，并破坏 T4 独立复算冻结短码表的意义。
    registry = yaml.safe_load((config.config_dir / "model_registry.yaml").read_text(encoding="utf-8"))
    compact_policy = registry["models"]["cue_extraction"]["execution"]["compact_inference_policy"]
    type_codes = compact_policy["cue_type_codes"]
    operator_codes = compact_policy["operator_codes"]
    required = set(compact_policy["required_fields"])
    optional = set(compact_policy["optional_defaults"])
    if not isinstance(compact, dict) or set(compact).difference(required | optional) or required.difference(compact):
        raise ValueError("紧凑 Cue 的字段集合不符合 v3.6 冻结短码协议")
    if not isinstance(compact["n"], int) or isinstance(compact["n"], bool) or not 0 <= compact["n"] < 5:
        raise ValueError("紧凑 Cue 的 n 必须是 package 内 0..4 索引")
    predicates = compact["p"]
    if not isinstance(predicates, list) or not predicates:
        raise ValueError("紧凑 Cue 必须含非空谓词数组")
    clauses: list[dict[str, str]] = []
    for predicate in predicates:
        if not isinstance(predicate, list) or len(predicate) != 3:
            raise ValueError("紧凑谓词必须是三个元素的短码数组")
        slot_code, operator_code, value = predicate
        if slot_code not in type_codes or operator_code not in operator_codes or not isinstance(value, str) or not value:
            raise ValueError("紧凑谓词含未知短码或空 value")
        clauses.append({"slot": type_codes[slot_code], "operator": operator_codes[operator_code], "value": value})
    cue_code = predicates[0][0]
    supporting_field_codes = compact_policy.get("supporting_text_field_codes")
    if not isinstance(supporting_field_codes, dict):
        raise ValueError("紧凑 Cue 协议缺少 supporting_text_field 短码表")
    supporting_field_code = compact["f"]
    if not isinstance(supporting_field_code, str):
        raise ValueError("紧凑 Cue 的 supporting_text_field 短码必须为字符串")
    supporting_field = supporting_field_codes.get(supporting_field_code)
    if supporting_field not in {"transcript", "dense_caption", "visible_text"}:
        raise ValueError("紧凑 Cue 含未知 supporting_text_field 短码")
    source_text = atom.get("visible_text")
    if not isinstance(source_text, str) or not cue_evidence_normalized_text(source_text):
        raise ValueError("紧凑 Cue 所属 Atom 的 visible_text 必须为非空字符串")
    supporting_source = atom.get(supporting_field)
    if not isinstance(supporting_source, str) or not cue_evidence_normalized_text(supporting_source):
        raise ValueError("紧凑 Cue 指定的证据字段必须为归一化后非空字符串")
    evidence = compact["x"]
    if not isinstance(evidence, str):
        raise ValueError("紧凑 Cue 的证据 x 必须为字符串")
    # v3.6 不再依赖模型对字符偏移单位的理解；只允许单字段归一化连续命中，并由
    # 程序恢复原始切片，杜绝将模型复写文本直接写入最终 Cue。
    supporting_span = source_span_from_normalized_evidence(supporting_source, evidence)
    supporting_normalized = cue_evidence_normalized_text(supporting_span)
    if not supporting_normalized or supporting_normalized not in cue_evidence_normalized_text(supporting_source):
        raise ValueError("紧凑 Cue 的程序切片未形成声明字段中的有效连续证据")
    confidence = compact["c"]
    if not isinstance(confidence, int) or isinstance(confidence, bool) or not 0 <= confidence <= compact_policy["confidence_scale"]:
        raise ValueError("紧凑 Cue 的置信度必须是 0..100 整数")
    status_codes = {"A": "accepted", "R": "rejected", "N": "needs_review"}
    if compact["v"] not in status_codes:
        raise ValueError("紧凑 Cue 含未知 validation_status 短码")
    defaults = compact_policy["optional_defaults"]
    entities = compact.get("e", defaults["e"])
    scene = compact.get("s", defaults["s"])
    activity = compact.get("a", defaults["a"])
    ambiguity = compact.get("r", defaults["r"])
    if not isinstance(entities, list) or any(not isinstance(entity, str) or not entity for entity in entities):
        raise ValueError("紧凑 Cue 的实体数组不合法")
    return {
        "cue_id": f"cue_{atom['atom_id'][4:]}_{compact['n']:02d}",
        "atom_id": atom["atom_id"],
        "split": atom["split"],
        "entities": entities,
        "scene_type": scene,
        "activity_type": activity,
        "cue_type": type_codes[cue_code],
        "normalized_predicate": {"all_of": clauses},
        "supporting_text_span": supporting_span,
        "supporting_text_field": supporting_field,
        "source_text": source_text,
        "confidence": confidence / compact_policy["confidence_scale"],
        "ambiguity_reason": ambiguity,
        "model_id": contract["model_id"],
        "prompt_version": contract["prompt_version"],
        "schema_version": contract["final_cue_schema_version"],
        "run_id": run_id,
        "validation_status": status_codes[compact["v"]],
    }


def validate_batch_task_manifest(
    config: RunConfig,
    contract: dict[str, Any],
    marker: dict[str, Any],
    collector: IssueCollector,
    owner: str,
) -> bool:
    """校验 v2.2 Batch 无正文汇总清单、任务边界和 custom_id/package 双向血缘。"""

    manifest_path = batch_tasks_manifest_path(config, contract)
    if not manifest_path.is_file():
        collector.add("BLOCKER", "cue_batch_manifest_missing", "cue", str(manifest_path), "汇总清单不存在", owner)
        return False
    if sha256_file(manifest_path) != marker.get("batch_tasks_manifest_sha256"):
        collector.add(
            "BLOCKER", "cue_batch_manifest_hash", "cue", "SUCCESS 声明的 batch_tasks_manifest_sha256", sha256_file(manifest_path), owner
        )
        return False
    records = read_jsonl(manifest_path, collector, "cue_batch_manifest", owner)
    if not records:
        collector.add("BLOCKER", "cue_batch_manifest_empty", "cue", "至少一个已完成 Batch task", "空清单", owner)
        return False

    # contract 返回给 SUCCESS 比对的字段刻意不泄露整份执行配置；这里重新从 T0 冻结
    # 的 registry 读取限额，避免生产者可通过 SUCCESS 自报的数值放宽文件/分组边界。
    registry = yaml.safe_load((config.config_dir / "model_registry.yaml").read_text(encoding="utf-8"))
    execution = registry["models"]["cue_extraction"]["execution"]
    batch_policy = execution["batch_file_policy"]
    max_requests = batch_policy["max_requests_per_file"]
    shards_per_task = batch_policy["logical_shards_per_task"]
    total_requests = 0
    all_custom_ids: set[str] = set()
    all_packages: set[str] = set()
    task_indexes: set[int] = set()
    valid = True
    for line_number, task in enumerate(records, start=1):
        label = f"task:{line_number}"
        if has_forbidden_batch_content(task):
            collector.add("BLOCKER", "cue_batch_raw_content", label, "仅无正文任务元数据", "发现请求、响应、错误或可见文本字段", owner)
            valid = False
        missing = sorted(BATCH_TASK_REQUIRED_FIELDS.difference(task))
        if missing:
            collector.add("BLOCKER", "cue_batch_task_fields", label, "完整的无正文 Batch task 元数据", f"缺少 {missing}", owner)
            valid = False
            continue
        wave_index = task["wave_index"]
        task_index = task["batch_task_index"]
        request_count = task["request_count"]
        shard_start = task["logical_shard_start"]
        shard_end = task["logical_shard_end"]
        if not all(isinstance(item, int) and not isinstance(item, bool) for item in (wave_index, task_index, request_count, shard_start, shard_end)):
            collector.add("BLOCKER", "cue_batch_task_value", label, "波次、任务索引、请求数和 shard 边界均为整数", repr(task), owner)
            valid = False
            continue
        if wave_index < 1:
            collector.add("BLOCKER", "cue_batch_wave_index", label, "从 1 开始的 wave_index", repr(wave_index), owner)
            valid = False
        if task_index < 0 or task_index in task_indexes:
            collector.add("BLOCKER", "cue_batch_task_index", label, "唯一的非负 batch_task_index", repr(task_index), owner)
            valid = False
        task_indexes.add(task_index)
        if request_count < 1 or request_count > max_requests:
            collector.add("BLOCKER", "cue_batch_task_request_limit", label, f"1..{max_requests}", repr(request_count), owner)
            valid = False
        if shard_start < 0 or shard_end < shard_start or shard_end - shard_start + 1 > shards_per_task:
            collector.add("BLOCKER", "cue_batch_task_shard_group", label, f"最多 {shards_per_task} 个连续逻辑 shard", f"{shard_start}..{shard_end}", owner)
            valid = False
        for field_name, expected in (
            ("source_atoms_sha256", marker["source_atoms_sha256"]),
            ("cue_execution_protocol_sha256", marker["cue_execution_protocol_sha256"]),
        ):
            if task[field_name] != expected:
                collector.add("BLOCKER", "cue_batch_task_lineage", f"{label}:{field_name}", repr(expected), repr(task[field_name]), owner)
                valid = False
        if task["status"] != "completed":
            collector.add("BLOCKER", "cue_batch_task_status", label, "completed", repr(task["status"]), owner)
            valid = False
        if not isinstance(task["remote_file_id"], str) or not task["remote_file_id"].strip():
            # 无 API 预检可以在 T2 单测中使用 null，但最终 SUCCESS 只能在真实上传过输入
            # 且已产生可追踪远端句柄后出现；否则无法审计服务端临时文件的清理责任。
            collector.add("BLOCKER", "cue_batch_remote_file_id", label, "非空远端输入 file ID", repr(task["remote_file_id"]), owner)
            valid = False
        if not isinstance(task["batch_input_sha256"], str) or SHA256_HEX.fullmatch(task["batch_input_sha256"]) is None:
            collector.add("BLOCKER", "cue_batch_input_hash", label, "64 位 SHA256", repr(task["batch_input_sha256"]), owner)
            valid = False
        mappings = task["custom_id_to_package_id"]
        if not isinstance(mappings, dict) or len(mappings) != request_count:
            collector.add("BLOCKER", "cue_batch_custom_id_count", label, "与 request_count 相等的 custom_id:package_id 映射", repr(mappings), owner)
            valid = False
            continue
        task_custom_ids: list[str] = []
        task_packages: list[str] = []
        for custom_id, package_id in mappings.items():
            if not isinstance(custom_id, str) or not BATCH_CUSTOM_ID.fullmatch(custom_id):
                collector.add("BLOCKER", "cue_batch_custom_id_format", label, "v22 固定 custom_id 格式", repr(custom_id), owner)
                valid = False
            if not isinstance(package_id, str) or not package_id:
                collector.add("BLOCKER", "cue_batch_package_id", label, "非空 package_id", repr(package_id), owner)
                valid = False
            task_custom_ids.append(custom_id)
            task_packages.append(package_id)
        if len(set(task_custom_ids)) != len(task_custom_ids) or len(set(task_packages)) != len(task_packages):
            collector.add("BLOCKER", "cue_batch_custom_id_bijection", label, "task 内 custom_id 与 package_id 双向唯一", repr(mappings), owner)
            valid = False
        if set(task_custom_ids).intersection(all_custom_ids) or set(task_packages).intersection(all_packages):
            collector.add("BLOCKER", "cue_batch_custom_id_bijection", label, "跨 task custom_id 与 package_id 不重复", repr(mappings), owner)
            valid = False
        all_custom_ids.update(task_custom_ids)
        all_packages.update(task_packages)
        # 输入 JSONL 的行序就是文件 SHA 的组成部分，故 custom_ids 哈希也保留该稳定
        # 行序；排序会掩盖同一集合被重新排列后与上传输入不一致的问题。
        expected_custom_ids_sha = canonical_sha256(task_custom_ids)
        if task["custom_ids_sha256"] != expected_custom_ids_sha:
            collector.add("BLOCKER", "cue_batch_custom_ids_hash", label, repr(expected_custom_ids_sha), repr(task["custom_ids_sha256"]), owner)
            valid = False
        total_requests += request_count
    if marker["batch_task_count"] != len(records):
        collector.add("BLOCKER", "cue_batch_task_count", "cue", str(len(records)), repr(marker["batch_task_count"]), owner)
        valid = False
    if marker["batch_input_total_request_count"] != total_requests:
        collector.add("BLOCKER", "cue_batch_total_requests", "cue", str(total_requests), repr(marker["batch_input_total_request_count"]), owner)
        valid = False
    if marker["usage_summary"]["package_count"] != total_requests:
        collector.add("BLOCKER", "cue_batch_usage_package_count", "cue", str(total_requests), repr(marker["usage_summary"]["package_count"]), owner)
        valid = False
    return valid


def validate_batch_package_ledgers(
    config: RunConfig,
    contract: dict[str, Any],
    marker: dict[str, Any],
    collector: IssueCollector,
    owner: str,
) -> bool:
    """验证每个 package 的无正文 Batch 账本，隔离、行级失败和成功不可混写。"""

    manifest_path = batch_tasks_manifest_path(config, contract)
    tasks = read_jsonl(manifest_path, collector, "cue_batch_manifest", owner)
    custom_to_package = {
        custom_id: (task, package_id)
        for task in tasks
        if isinstance(task.get("custom_id_to_package_id"), dict)
        for custom_id, package_id in task["custom_id_to_package_id"].items()
    }
    registry = yaml.safe_load((config.config_dir / "model_registry.yaml").read_text(encoding="utf-8"))
    layout = registry["models"]["cue_extraction"]["execution"]["shard_layout"]
    package_root = config.benchmark_root / str(layout["root"]) / str(layout["package_directory"])
    suffix = str(layout["ledger_suffix"])
    ledger_paths = sorted(package_root.rglob(f"*{suffix}")) if package_root.is_dir() else []
    if not ledger_paths:
        collector.add("BLOCKER", "cue_batch_ledger_missing", "cue", "每个已完成 package 的无正文 ledger", "未找到 ledger", owner)
        return False
    ledger_policy = registry["models"]["cue_extraction"]["execution"]["batch_ledger_policy"]
    required = set(ledger_policy["required_fields"]) | {
        "batch_task_index",
        "batch_custom_id",
        "batch_input_sha256",
        "remote_file_id",
        "remote_cleanup_status",
        "outcome",
        "package_id",
    } | BATCH_RECEIVER_LEDGER_FIELDS
    allowed_outcomes = set(ledger_policy["terminal_outcomes"])
    terminal_by_custom: dict[str, str] = {}
    terminal_by_package: dict[str, set[str]] = defaultdict(set)
    valid = True
    for ledger_path in ledger_paths:
        for line_number, event in enumerate(read_jsonl(ledger_path, collector, "cue_batch_ledger", owner), start=1):
            label = f"{ledger_path.name}:{line_number}"
            if has_forbidden_batch_content(event):
                collector.add("BLOCKER", "cue_batch_ledger_raw_content", label, "无请求/响应/错误正文的账本事件", repr(event), owner)
                valid = False
            missing = sorted(required.difference(event))
            if missing:
                collector.add("BLOCKER", "cue_batch_ledger_fields", label, "完整的 Batch 账本字段", f"缺少 {missing}", owner)
                valid = False
                continue
            custom_id = event["batch_custom_id"]
            entry = custom_to_package.get(custom_id)
            if entry is None:
                collector.add("BLOCKER", "cue_batch_ledger_custom_id", label, "task manifest 中已登记 custom_id", repr(custom_id), owner)
                valid = False
                continue
            task, package_id = entry
            if event["package_id"] != package_id or event["batch_task_index"] != task["batch_task_index"]:
                collector.add("BLOCKER", "cue_batch_ledger_lineage", label, "匹配 task manifest 的 package/task", repr(event), owner)
                valid = False
            if event["batch_input_sha256"] != task["batch_input_sha256"] or event["remote_file_id"] != task["remote_file_id"]:
                collector.add("BLOCKER", "cue_batch_ledger_lineage", label, "匹配 task manifest 的输入 SHA 与远端 file ID", repr(event), owner)
                valid = False
            if event["remote_cleanup_status"] != "pending_t4_cue_qa":
                collector.add("BLOCKER", "cue_batch_ledger_cleanup", label, "pending_t4_cue_qa", repr(event["remote_cleanup_status"]), owner)
                valid = False
            outcome = event["outcome"]
            if outcome not in allowed_outcomes:
                collector.add("BLOCKER", "cue_batch_ledger_outcome", label, repr(sorted(allowed_outcomes)), repr(outcome), owner)
                valid = False
                continue
            # 只有服务端逐行失败才代表“尚未得到模型输出”，因此才可进入受控 requeue。
            # 本地验证隔离已消费结果且可能已计费；将其重排会掩盖 QA 缺陷并重复付费。
            semantic_expected = {
                "validated_success": (False, None, "result_file_id"),
                "service_line_failure_requeueable": (True, "service_line", "error_file_id"),
                "local_validation_quarantine": (False, "local_validation", "result_file_id"),
            }
            expected_retry, expected_origin, required_file = semantic_expected[outcome]
            if event["retry_eligible"] is not expected_retry or event["failure_origin"] != expected_origin:
                collector.add("BLOCKER", "cue_batch_ledger_requeue_semantics", label, f"{outcome} 的 retry_eligible={expected_retry!r}、failure_origin={expected_origin!r}", repr({"retry_eligible": event["retry_eligible"], "failure_origin": event["failure_origin"]}), owner)
                valid = False
            for file_field in ("result_file_id", "error_file_id"):
                if not is_optional_remote_file_id(event[file_field]):
                    collector.add("BLOCKER", "cue_batch_ledger_remote_file", f"{label}:{file_field}", "非空远端文件 ID 或 null", repr(event[file_field]), owner)
                    valid = False
            if not isinstance(event["result_line_sha256"], str) or SHA256_HEX.fullmatch(event["result_line_sha256"]) is None:
                collector.add("BLOCKER", "cue_batch_ledger_result_hash", label, "流式接收行的 64 位 SHA256", repr(event["result_line_sha256"]), owner)
                valid = False
            if not isinstance(event["batch_id"], str) or not event["batch_id"].strip() or not isinstance(event[required_file], str) or not event[required_file].strip():
                collector.add("BLOCKER", "cue_batch_ledger_result_lineage", label, f"{outcome} 对应的 batch_id 与 {required_file}", repr({"batch_id": event["batch_id"], required_file: event[required_file]}), owner)
                valid = False
            if custom_id in terminal_by_custom:
                collector.add("BLOCKER", "cue_batch_ledger_terminal_duplicate", label, "每个 custom_id 恰有一个终态", repr(custom_id), owner)
                valid = False
            terminal_by_custom[custom_id] = outcome
            terminal_by_package[package_id].add(outcome)
    for package_id, outcomes in terminal_by_package.items():
        if "local_validation_quarantine" in outcomes and len(outcomes) > 1:
            # 服务端成功但本地 QA 失败已计费；再组批会把同一问题转化为重复付费，故只能
            # 人工授权新的协议/预算后另行处理，不能与自动 requeue 或成功终态并存。
            collector.add("BLOCKER", "cue_batch_quarantine_requeued", package_id, "quarantine package 不得再次提交", repr(sorted(outcomes)), owner)
            valid = False
        if "validated_success" in outcomes and "local_validation_quarantine" in outcomes:
            collector.add("BLOCKER", "cue_batch_terminal_mixed", package_id, "成功与隔离不可混合", repr(sorted(outcomes)), owner)
            valid = False
    expected_custom_ids = set(custom_to_package)
    if set(terminal_by_custom) != expected_custom_ids:
        collector.add("BLOCKER", "cue_batch_ledger_coverage", "cue", "每个 task manifest custom_id 均有一个 ledger 终态", f"记录 {len(terminal_by_custom)} / 期望 {len(expected_custom_ids)}", owner)
        valid = False
    if any(outcome != "validated_success" for outcome in terminal_by_custom.values()):
        collector.add("BLOCKER", "cue_batch_non_success_terminal", "cue", "最终 CUE SUCCESS 前全部 custom_id 已 validated_success", repr(terminal_by_custom), owner)
        valid = False
    return valid


def realtime_layout(config: RunConfig) -> dict[str, Any]:
    """读取实时运行的固定布局，拒绝以 Batch 根目录或生产者自报路径恢复。"""

    registry = yaml.safe_load((config.config_dir / "model_registry.yaml").read_text(encoding="utf-8"))
    execution = registry["models"]["cue_extraction"]["execution"]
    layout = execution["shard_layout"]
    if execution.get("transport") != "realtime_chat_completions" or str(layout.get("root")) != "cues/realtime":
        raise ValueError("冻结实时协议未声明 cues/realtime 运行根")
    required = {"realtime_shards_manifest", "run_ledger_filename", "run_state_filename", "progress_filename", "package_directory", "ledger_suffix", "completion_suffix"}
    if required.difference(layout):
        raise ValueError(f"冻结实时布局缺少 {sorted(required.difference(layout))}")
    return layout


def realtime_root(config: RunConfig) -> Path:
    """返回合同唯一允许的实时产物根，隔离已经取消的 cues/batch 运行。"""

    layout = realtime_layout(config)
    return config.benchmark_root / str(layout["root"])


def realtime_shards_manifest_path(config: RunConfig) -> Path:
    """定位实时分片清单；SUCCESS 不得指定任意其他运行的清单路径。"""

    layout = realtime_layout(config)
    return realtime_root(config) / str(layout["realtime_shards_manifest"])


def has_forbidden_realtime_content(value: Any) -> bool:
    """递归拒绝实时元数据中的请求、响应、错误和 Atom 正文，防止账本成为泄露旁路。"""

    if isinstance(value, dict):
        for key, item in value.items():
            # 生产者可用 null 显式证明未写原始响应路径；任何非空路径则意味着正文可能
            # 被保留，必须拒绝。其余 Batch 标识或正文键一律不允许出现在实时元数据。
            if key == "raw_response_path" and item is None:
                continue
            if key in REALTIME_RAW_CONTENT_FIELDS or has_forbidden_realtime_content(item):
                return True
        return False
    if isinstance(value, list):
        return any(has_forbidden_realtime_content(item) for item in value)
    return False


def validate_realtime_progress_snapshot(
    progress: dict[str, Any],
    run_state: dict[str, Any],
    policy: dict[str, Any],
    collector: IssueCollector,
    owner: str,
    path: Path,
) -> bool:
    """验证无正文进度快照与冻结波次、在飞上限及最终运行状态一致。

    输入是生产者原子写入的 `progress.json`、同一运行状态和冻结实时策略；输出是
    布尔门禁结果。该检查不读取任何请求或响应正文，避免把便利的进度文件变成数据
    泄露旁路，也避免十个并发 worker 意外跨越当前被批准的一个波次。
    """

    valid = True
    if has_forbidden_realtime_content(progress):
        collector.add("BLOCKER", "cue_realtime_progress_raw_content", str(path), "无请求/响应/错误正文", "发现正文键", owner)
        return False
    missing = sorted(REALTIME_PROGRESS_REQUIRED_FIELDS.difference(progress))
    if missing:
        collector.add("BLOCKER", "cue_realtime_progress_fields", str(path), "完整无正文进度字段", f"缺少 {missing}", owner)
        return False
    wave_index = progress["wave_index"]
    if not isinstance(wave_index, int) or not 1 <= wave_index <= len(REALTIME_WAVE_TASK_COUNTS):
        collector.add("BLOCKER", "cue_realtime_progress_wave", str(path), "1--8 的波次索引", repr(wave_index), owner)
        return False
    wave_start = sum(REALTIME_WAVE_TASK_COUNTS[:wave_index - 1])
    expected_tasks = list(range(wave_start, wave_start + REALTIME_WAVE_TASK_COUNTS[wave_index - 1]))
    if progress["wave_task_indexes"] != expected_tasks:
        collector.add("BLOCKER", "cue_realtime_progress_wave", f"{path}:wave_task_indexes", repr(expected_tasks), repr(progress["wave_task_indexes"]), owner)
        valid = False
    if run_state.get("wave_index") != wave_index or run_state.get("wave_task_indexes") != expected_tasks:
        collector.add("BLOCKER", "cue_realtime_progress_lineage", str(path), "与 run state 为同一冻结波次", repr({"progress": wave_index, "state": run_state.get("wave_index")}), owner)
        valid = False
    numeric_fields = REALTIME_PROGRESS_REQUIRED_FIELDS.intersection({
        "total_packages", "completed_packages", "validated_success_packages",
        "local_validation_quarantine_packages", "needs_item_audit_packages", "service_transport_exhausted_packages",
        "budget_stopped_packages", "in_flight_packages",
    })
    for field in numeric_fields:
        if not isinstance(progress[field], int) or isinstance(progress[field], bool) or progress[field] < 0:
            collector.add("BLOCKER", "cue_realtime_progress_value", f"{path}:{field}", "非负整数", repr(progress[field]), owner)
            valid = False
    maximum_in_flight = policy.get("maximum_in_flight")
    if not isinstance(maximum_in_flight, int) or maximum_in_flight != 10 or progress["in_flight_packages"] > maximum_in_flight:
        collector.add("BLOCKER", "cue_realtime_progress_inflight", str(path), "最多 10 个在飞 package", repr(progress.get("in_flight_packages")), owner)
        valid = False
    terminal_count = sum(progress.get(field, 0) for field in (
        "validated_success_packages", "excluded_after_repair_packages", "content_filtered_packages",
        "local_validation_quarantine_packages", "needs_item_audit_packages",
        "service_transport_exhausted_packages", "budget_stopped_packages",
    ) if isinstance(progress.get(field), int) and not isinstance(progress.get(field), bool))
    if terminal_count != progress["completed_packages"] or progress["completed_packages"] + progress["in_flight_packages"] > progress["total_packages"]:
        collector.add("BLOCKER", "cue_realtime_progress_counts", str(path), "终态计数一致且 completed + in_flight 不超过总数", repr(progress), owner)
        valid = False
    if progress["status"] != "completed" or progress["in_flight_packages"] != 0 or progress["completed_packages"] != progress["total_packages"]:
        collector.add("BLOCKER", "cue_realtime_progress_terminal", str(path), "completed、零在飞且全部 package 已终结", repr(progress), owner)
        valid = False
    return valid


def validate_realtime_wave_package_audits(directory: Path, collector: IssueCollector, owner: str) -> bool:
    """检查 Wave 内逐项审计与遗留整包隔离，二者均不可穿透 Cue SUCCESS。

    输入为一个 Wave 的 `packages/` 无正文状态目录；输出为最终门是否仍可通过。
    逐项审计是第 05 步继续调度的非阻断状态，故本函数不把它解释为 Wave 停止；
    但第 11 步必须明确拒绝任何未解决队列或旧式整包本地隔离，避免它们被误写为
    正式 Cue library。
    """

    package_root = directory / "packages"
    if not package_root.is_dir():
        collector.add("BLOCKER", "cue_realtime_wave_packages_missing", str(package_root), "最终 Wave 具有 package 无正文状态目录", "不存在", owner)
        return False
    valid = True
    for package_dir in sorted(path for path in package_root.iterdir() if path.is_dir()):
        state_path = package_dir / "realtime_state.json"
        state = load_json(state_path, collector, "cue_realtime_package_state", owner)
        if state is None:
            valid = False
            continue
        if has_forbidden_realtime_content(state):
            collector.add("BLOCKER", "cue_realtime_raw_content", str(state_path), "无请求/响应/错误正文", "发现正文键", owner)
            valid = False
            continue
        package_id = state.get("package_id")
        if not isinstance(package_id, str) or package_id != package_dir.name:
            collector.add("BLOCKER", "cue_realtime_wave_package_identity", str(state_path), "package_id 与目录名一致", repr(package_id), owner)
            valid = False
            continue
        status = state.get("status")
        if status == "local_validation_quarantine":
            collector.add("BLOCKER", "cue_realtime_package_quarantine", str(state_path), "整包隔离必须展开为逐项审计或经人工关闭", repr(status), owner)
            valid = False
        if status == "needs_item_audit" and state.get("unresolved_item_count", 0) == 0:
            collector.add("BLOCKER", "cue_realtime_item_state", str(state_path), "needs_item_audit 必须对应未解决项", repr(state), owner)
            valid = False
        valid = validate_realtime_item_audit_queue(state, package_id, state_path, collector, owner) and valid
    return valid


def validate_realtime_coverage_disposition(directory: Path, collector: IssueCollector, owner: str) -> bool:
    """验证 Wave 逐 Atom 覆盖账本，拒绝未完成两次修复的排除终态。

    覆盖账本是 CR-014 将“每包都成功”改为“每个 Atom 均有可审计终态”的唯一
    证据。有效模型 `R/N` 是明确的 `excluded_no_cue`；而
    `excluded_after_repair` 只能在首轮和两次同 Atom 修复均未通过后出现，因而不得
    用一次失败、整包失败或无正文缺失来提前排除。
    """

    path = directory / "coverage_disposition.jsonl"
    if not path.is_file():
        collector.add("BLOCKER", "cue_realtime_coverage_missing", str(path), "最终 Wave 具有逐 Atom 覆盖账本", "不存在", owner)
        return False
    required = {
        "run_id", "package_id", "item_index", "atom_id", "source_atoms_sha256",
        "cue_execution_protocol_sha256", "raw_response_saved", "disposition", "code",
        "path", "attempt", "request_identity",
    }
    valid = True
    seen: set[tuple[str, int, str]] = set()
    for row in read_jsonl(path, collector, "cue_realtime_coverage_disposition", owner):
        if has_forbidden_realtime_content(row):
            collector.add("BLOCKER", "cue_realtime_coverage_raw_content", str(path), "覆盖账本绝不含正文", "发现正文键", owner)
            valid = False
            continue
        if set(row) != required:
            collector.add("BLOCKER", "cue_realtime_coverage_fields", str(path), "固定的无正文覆盖字段", repr(sorted(set(row))), owner)
            valid = False
            continue
        identity = row["request_identity"]
        key = (row["package_id"], row["item_index"], row["atom_id"])
        if (not isinstance(row["package_id"], str) or not isinstance(row["item_index"], int)
                or isinstance(row["item_index"], bool) or row["item_index"] < 0
                or not isinstance(row["atom_id"], str) or not row["atom_id"].startswith("src_")
                or row["raw_response_saved"] is not False):
            collector.add("BLOCKER", "cue_realtime_coverage_value", str(path), "安全 Atom 身份、索引与无正文标志", repr(row), owner)
            valid = False
        if key in seen:
            collector.add("BLOCKER", "cue_realtime_coverage_unique", str(path), "每个 package/item/Atom 恰一条终态", repr(key), owner)
            valid = False
        seen.add(key)
        if row["disposition"] == "accepted_cue":
            if row["code"] is not None or row["path"] is not None or row["attempt"] is not None or not isinstance(identity, str):
                collector.add("BLOCKER", "cue_realtime_coverage_accepted", str(path), "accepted_cue 不携带失败信息且具有请求身份", repr(row), owner)
                valid = False
        elif row["disposition"] == "excluded_after_repair":
            if (not isinstance(row["code"], str) or not isinstance(row["path"], str)
                    or row["attempt"] != 3
                    or not isinstance(identity, str)
                    or not re.fullmatch(rf"rt_repair_{re.escape(row['package_id'])}_\d+_[0-9a-f]{{10}}", identity)):
                collector.add("BLOCKER", "cue_realtime_coverage_exclusion_limit", str(path), "排除仅限初始加两次同 Atom 修复后的 attempt=3", repr(row), owner)
                valid = False
        elif row["disposition"] == "excluded_no_cue":
            if (row["code"] != "MODEL_NON_ACCEPTED" or not isinstance(row["path"], str)
                    or row["attempt"] != 1 or not isinstance(identity, str)
                    or not re.fullmatch(rf"rt_{re.escape(row['package_id'])}_[0-9a-f]{{10}}", identity)):
                collector.add("BLOCKER", "cue_realtime_coverage_no_cue", str(path), "有效模型 R/N 仅以首轮 MODEL_NON_ACCEPTED 终态排除", repr(row), owner)
                valid = False
        elif row["disposition"] == "excluded_content_filtered":
            # 内容安全过滤器在首轮拒绝了整个 package；模型从未产出判断。记录必须携带
            # 受限服务诊断码、空 JSON 路径与首轮请求身份，且只允许出现一次审查拒绝。
            if (not isinstance(row["code"], str) or not re.fullmatch(r"[A-Z0-9_]{1,96}", row["code"])
                    or row["path"] is not None or row["attempt"] != 1
                    or not isinstance(identity, str)
                    or not re.fullmatch(rf"rt_{re.escape(row['package_id'])}_[0-9a-f]{{10}}", identity)):
                collector.add("BLOCKER", "cue_realtime_coverage_content_filtered", str(path), "内容审查排除仅限首轮且携带服务码", repr(row), owner)
                valid = False
        else:
            collector.add("BLOCKER", "cue_realtime_coverage_disposition", str(path), "accepted_cue、excluded_no_cue、excluded_after_repair 或 excluded_content_filtered", repr(row["disposition"]), owner)
            valid = False
    return valid


def validate_all_realtime_waves(root: Path, layout: dict[str, Any], policy: dict[str, Any], collector: IssueCollector, owner: str) -> bool:
    """聚合验证八个实时波次，要求完整、不重叠且与根级累计账本一致。

    该函数只读每个 `wave_XX` 子目录的状态、进度和无正文账本。最终 SUCCESS 之前，
    八波必须全部完成；根级累计账本按 `realtime_request_id` 去重后必须与各波账本并集
    相等，防止某一波遗漏费用或把同一请求重复计入 `¥80` 总预算。
    """

    directories = [root / f"wave_{index:02d}" for index in range(1, 9)]
    if not any(path.exists() for path in directories):
        return True
    valid = True
    seen_tasks: set[int] = set()
    wave_events: dict[str, dict[str, Any]] = {}
    for index, directory in enumerate(directories, start=1):
        state = load_json(directory / str(layout["run_state_filename"]), collector, "cue_realtime_wave_state", owner)
        progress = load_json(directory / str(layout["progress_filename"]), collector, "cue_realtime_wave_progress", owner)
        if state is None or progress is None:
            valid = False
            continue
        valid = validate_realtime_progress_snapshot(progress, state, policy, collector, owner, directory / str(layout["progress_filename"])) and valid
        if state.get("status") != "completed":
            collector.add("BLOCKER", "cue_realtime_wave_terminal", str(directory), "completed", repr(state.get("status")), owner); valid = False
        valid = validate_realtime_wave_package_audits(directory, collector, owner) and valid
        valid = validate_realtime_coverage_disposition(directory, collector, owner) and valid
        tasks = progress.get("wave_task_indexes")
        if isinstance(tasks, list):
            overlap = seen_tasks.intersection(tasks)
            if overlap:
                collector.add("BLOCKER", "cue_realtime_wave_overlap", str(directory), "波次 task 不重叠", repr(sorted(overlap)), owner); valid = False
            seen_tasks.update(tasks)
        for event in read_jsonl(directory / str(layout["run_ledger_filename"]), collector, "cue_realtime_wave_ledger", owner):
            request_id = event.get("realtime_request_id")
            if not isinstance(request_id, str) or request_id in wave_events:
                collector.add("BLOCKER", "cue_realtime_wave_ledger_identity", str(directory), "跨波唯一 request id", repr(request_id), owner); valid = False
            elif has_forbidden_realtime_content(event):
                collector.add("BLOCKER", "cue_realtime_raw_content", str(directory), "无正文累计账本", "发现正文键", owner); valid = False
            else: wave_events[request_id] = event
    if seen_tasks != set(range(sum(REALTIME_WAVE_TASK_COUNTS))):
        collector.add("BLOCKER", "cue_realtime_wave_coverage", str(root), "完整 75 个冻结 task", repr(sorted(seen_tasks)), owner); valid = False
    cumulative = {event.get("realtime_request_id"): event for event in read_jsonl(root / "realtime_cumulative_ledger.jsonl", collector, "cue_realtime_cumulative_ledger", owner)}
    if set(cumulative) != set(wave_events) or any(canonical_sha256(cumulative[key]) != canonical_sha256(value) for key, value in wave_events.items()):
        collector.add("BLOCKER", "cue_realtime_cumulative_ledger", str(root), "根级账本等于八波账本并集", f"累计 {len(cumulative)} / 波次 {len(wave_events)}", owner); valid = False
    return valid


def validate_realtime_execution_lineage(
    config: RunConfig,
    marker: dict[str, Any],
    collector: IssueCollector,
    owner: str,
) -> bool:
    """独立验证实时 Cue 的运行状态、分片终态、账本与预算熔断边界。"""

    missing = sorted(CUE_V30_MARKER_FIELDS.difference(marker))
    if missing:
        collector.add("BLOCKER", "cue_realtime_lineage_fields", "cue", "完整实时执行血缘字段", f"缺少 {missing}", owner)
        return False
    contract = cue_v2_execution_contract(config, collector, owner)
    if contract is None:
        return False
    valid = True
    for field_name, expected in contract.items():
        if field_name == "transport":
            continue
        if marker.get(field_name) != expected:
            collector.add("BLOCKER", "cue_execution_lineage_mismatch", f"cue:{field_name}", repr(expected), repr(marker.get(field_name)), owner)
            valid = False
    if marker["realtime_transport"] != contract["transport"]:
        collector.add("BLOCKER", "cue_realtime_transport", "cue", repr(contract["transport"]), repr(marker["realtime_transport"]), owner)
        valid = False
    source_marker = load_json(config.marker("source_atoms"), collector, "success_marker", "T1 source")
    source_hash = source_marker.get("sha256") if source_marker else None
    if marker["source_atoms_sha256"] != source_hash:
        collector.add("BLOCKER", "cue_execution_source_hash", "cue", repr(source_hash), repr(marker["source_atoms_sha256"]), owner)
        valid = False
    if marker["realtime_local_raw_response_storage"] != "forbidden":
        collector.add("BLOCKER", "cue_realtime_raw_response_policy", "cue", "forbidden", repr(marker["realtime_local_raw_response_storage"]), owner)
        valid = False
    usage = marker.get("usage_summary")
    if not isinstance(usage, dict):
        collector.add("BLOCKER", "cue_usage_summary_shape", "cue", "对象类型的无正文 usage 汇总", type(usage).__name__, owner)
        return False
    missing_usage = sorted(CUE_V2_USAGE_SUMMARY_FIELDS.difference(usage))
    if missing_usage:
        collector.add("BLOCKER", "cue_usage_summary_fields", "cue", "完整 usage 汇总", f"缺少 {missing_usage}", owner)
        return False
    for name in CUE_V2_USAGE_SUMMARY_FIELDS - {"rate_limit_wait_seconds"}:
        if not isinstance(usage[name], int) or isinstance(usage[name], bool) or usage[name] < 0:
            collector.add("BLOCKER", "cue_usage_summary_value", f"cue:{name}", "非负整数", repr(usage[name]), owner)
            valid = False
    if not isinstance(usage["rate_limit_wait_seconds"], (int, float)) or isinstance(usage["rate_limit_wait_seconds"], bool) or usage["rate_limit_wait_seconds"] < 0:
        collector.add("BLOCKER", "cue_usage_summary_value", "cue:rate_limit_wait_seconds", "非负数值", repr(usage["rate_limit_wait_seconds"]), owner)
        valid = False
    if usage["prompt_tokens"] + usage["completion_tokens"] != usage["total_tokens"]:
        collector.add("BLOCKER", "cue_usage_summary_tokens", "cue", "prompt_tokens + completion_tokens = total_tokens", repr(usage), owner)
        valid = False
    if not valid:
        return False
    return validate_realtime_artifacts(config, marker, contract, collector, owner)


def validate_realtime_artifacts(
    config: RunConfig,
    marker: dict[str, Any],
    contract: dict[str, Any],
    collector: IssueCollector,
    owner: str,
) -> bool:
    """验证固定实时根下的无正文 run-state、manifest、package ledger 与完成哈希。"""

    layout = realtime_layout(config)
    root = realtime_root(config)
    manifest_path = realtime_shards_manifest_path(config)
    run_state_path = root / str(layout["run_state_filename"])
    run_ledger_path = root / str(layout["run_ledger_filename"])
    progress_path = root / str(layout["progress_filename"])
    # v3.1 起实际执行按 wave 子目录隔离。只要存在任一波目录，最终 SUCCESS 必须走
    # 八波聚合门，不能再把旧单根工件误当成完整运行。
    if any((root / f"wave_{index:02d}").exists() for index in range(1, 9)):
        registry = yaml.safe_load((config.config_dir / "model_registry.yaml").read_text(encoding="utf-8"))
        policy = registry.get("models", {}).get("cue_extraction", {}).get("execution", {}).get("realtime_api_policy", {}) if isinstance(registry, dict) else {}
        return validate_all_realtime_waves(root, layout, policy, collector, owner)
    valid = True
    for path, field in ((manifest_path, "realtime_shards_manifest_sha256"), (run_state_path, "realtime_run_state_sha256"), (run_ledger_path, "realtime_run_ledger_sha256")):
        if not path.is_file():
            collector.add("BLOCKER", "cue_realtime_artifact_missing", str(path), "存在固定实时审计工件", "不存在", owner)
            valid = False
        elif sha256_file(path) != marker[field]:
            collector.add("BLOCKER", "cue_realtime_artifact_hash", str(path), repr(marker[field]), sha256_file(path), owner)
            valid = False
    if not valid:
        return False
    run_state = load_json(run_state_path, collector, "cue_realtime_run_state", owner)
    if run_state is None:
        return False
    if has_forbidden_realtime_content(run_state):
        collector.add("BLOCKER", "cue_realtime_raw_content", str(run_state_path), "无请求/响应/错误正文", "发现正文键", owner)
        valid = False
    missing = sorted(REALTIME_RUN_STATE_REQUIRED_FIELDS.difference(run_state))
    if missing:
        collector.add("BLOCKER", "cue_realtime_run_state_fields", str(run_state_path), "完整实时运行状态", f"缺少 {missing}", owner)
        return False
    for field, expected in (("transport", contract["transport"]), ("source_atoms_sha256", marker["source_atoms_sha256"]), ("cue_execution_protocol_sha256", marker["cue_execution_protocol_sha256"])):
        if run_state[field] != expected:
            collector.add("BLOCKER", "cue_realtime_run_state_lineage", f"{run_state_path}:{field}", repr(expected), repr(run_state[field]), owner)
            valid = False
    if run_state["status"] != "completed":
        collector.add("BLOCKER", "cue_realtime_run_state_status", str(run_state_path), "completed", repr(run_state["status"]), owner)
        valid = False
    for field in ("authorized_budget_cny", "estimated_cost_cny"):
        if not isinstance(run_state[field], (int, float)) or isinstance(run_state[field], bool) or run_state[field] < 0:
            collector.add("BLOCKER", "cue_realtime_budget_value", f"{run_state_path}:{field}", "非负数值", repr(run_state[field]), owner)
            valid = False
    if isinstance(run_state.get("authorized_budget_cny"), (int, float)) and isinstance(run_state.get("estimated_cost_cny"), (int, float)) and run_state["estimated_cost_cny"] > run_state["authorized_budget_cny"]:
        collector.add("BLOCKER", "cue_realtime_budget_fuse", str(run_state_path), "estimated_cost_cny 不超过授权预算", repr(run_state), owner)
        valid = False
    progress = load_json(progress_path, collector, "cue_realtime_progress", owner)
    if progress is None:
        valid = False
    else:
        registry = yaml.safe_load((config.config_dir / "model_registry.yaml").read_text(encoding="utf-8"))
        policy = registry.get("models", {}).get("cue_extraction", {}).get("execution", {}).get("realtime_api_policy", {}) if isinstance(registry, dict) else {}
        valid = validate_realtime_progress_snapshot(progress, run_state, policy, collector, owner, progress_path) and valid
        valid = validate_all_realtime_waves(root, layout, policy, collector, owner) and valid
    rows = read_jsonl(manifest_path, collector, "cue_realtime_manifest", owner)
    if marker["realtime_shard_count"] != len(rows):
        collector.add("BLOCKER", "cue_realtime_shard_count", "cue", str(len(rows)), repr(marker["realtime_shard_count"]), owner)
        valid = False
    package_root = root / str(layout["package_directory"])
    seen_packages: set[str] = set()
    for line, shard in enumerate(rows, start=1):
        label = f"realtime_shard:{line}"
        if has_forbidden_realtime_content(shard):
            collector.add("BLOCKER", "cue_realtime_raw_content", label, "无请求/响应/错误正文", "发现正文键", owner)
            valid = False
        missing = sorted(REALTIME_SHARD_REQUIRED_FIELDS.difference(shard))
        if missing:
            collector.add("BLOCKER", "cue_realtime_manifest_fields", label, "完整实时分片元数据", f"缺少 {missing}", owner)
            valid = False
            continue
        if shard["transport"] != contract["transport"] or shard["source_atoms_sha256"] != marker["source_atoms_sha256"] or shard["cue_execution_protocol_sha256"] != marker["cue_execution_protocol_sha256"]:
            collector.add("BLOCKER", "cue_realtime_manifest_lineage", label, "同一 transport/Source/协议", repr(shard), owner)
            valid = False
        mapping = shard["package_id_to_request_sha256"]
        if not isinstance(mapping, dict) or shard["package_count"] != len(mapping) or not mapping:
            collector.add("BLOCKER", "cue_realtime_manifest_package_count", label, "package_count 与非空映射一致", repr(mapping), owner)
            valid = False
            continue
        package_ids = list(mapping)
        if shard["package_ids_sha256"] != canonical_sha256(package_ids):
            collector.add("BLOCKER", "cue_realtime_package_ids_hash", label, repr(canonical_sha256(package_ids)), repr(shard["package_ids_sha256"]), owner)
            valid = False
        if shard["status"] != "completed" or not isinstance(shard["completion_sha256"], str) or SHA256_HEX.fullmatch(shard["completion_sha256"]) is None:
            collector.add("BLOCKER", "cue_realtime_shard_terminal", label, "completed 且有完成哈希", repr(shard), owner)
            valid = False
        for package_id, request_sha in mapping.items():
            if package_id in seen_packages or not isinstance(request_sha, str) or SHA256_HEX.fullmatch(request_sha) is None:
                collector.add("BLOCKER", "cue_realtime_package_bijection", label, "全局唯一 package_id 与 64 位请求摘要", repr({package_id: request_sha}), owner)
                valid = False
            seen_packages.add(package_id)
            state_path = package_root / package_id / "realtime_state.json"
            ledger_path = package_root / package_id / f"{package_id}{layout['ledger_suffix']}"
            complete_path = package_root / package_id / f"{package_id}{layout['completion_suffix']}"
            valid = validate_realtime_package_artifacts(state_path, ledger_path, complete_path, shard, package_id, request_sha, marker, contract, collector, owner) and valid
    # run ledger 必须只包含已清单登记的 package；它记录费用熔断与重试摘要，不能另建
    # 一个未审计 package 的终态。逐行使用同一禁止正文门，确保失败摘要不夹带服务端正文。
    for event in read_jsonl(run_ledger_path, collector, "cue_realtime_run_ledger", owner):
        if has_forbidden_realtime_content(event):
            collector.add("BLOCKER", "cue_realtime_raw_content", str(run_ledger_path), "无请求/响应/错误正文", "发现正文键", owner)
            valid = False
        if event.get("transport") != contract["transport"] or event.get("source_atoms_sha256") != marker["source_atoms_sha256"] or event.get("cue_execution_protocol_sha256") != marker["cue_execution_protocol_sha256"]:
            collector.add("BLOCKER", "cue_realtime_run_ledger_lineage", str(run_ledger_path), "同一 transport/Source/协议", repr(event), owner)
            valid = False
        if event.get("package_id") not in seen_packages:
            collector.add("BLOCKER", "cue_realtime_run_ledger_package", str(run_ledger_path), "仅引用 manifest package", repr(event.get("package_id")), owner)
            valid = False
    return valid


def validate_realtime_package_artifacts(
    state_path: Path, ledger_path: Path, complete_path: Path, shard: dict[str, Any], package_id: str, request_sha: str, marker: dict[str, Any], contract: dict[str, Any], collector: IssueCollector, owner: str,
) -> bool:
    """验证一个实时 package 的唯一终态；本地隔离和预算停止均禁止自动重排。"""

    valid = True
    state = load_json(state_path, collector, "cue_realtime_package_state", owner)
    complete = load_json(complete_path, collector, "cue_realtime_complete", owner)
    if state is None:
        return False
    # 即使有未解决项而尚未生成 complete，T4 也应明确报告队列门，而非只报缺文件。
    valid = validate_realtime_item_audit_queue(state, package_id, state_path, collector, owner) and valid
    if complete is None:
        return False
    for value, label, required in ((state, str(state_path), REALTIME_PACKAGE_STATE_REQUIRED_FIELDS), (complete, str(complete_path), REALTIME_COMPLETE_REQUIRED_FIELDS)):
        if has_forbidden_realtime_content(value):
            collector.add("BLOCKER", "cue_realtime_raw_content", label, "无请求/响应/错误正文", "发现正文键", owner)
            valid = False
        missing = sorted(required.difference(value))
        if missing:
            collector.add("BLOCKER", "cue_realtime_package_fields", label, "完整 package 状态字段", f"缺少 {missing}", owner)
            valid = False
    if not valid:
        return False
    for value, label in ((state, str(state_path)), (complete, str(complete_path))):
        expected = {"transport": contract["transport"], "package_id": package_id, "source_atoms_sha256": marker["source_atoms_sha256"], "cue_execution_protocol_sha256": marker["cue_execution_protocol_sha256"], "request_sha256": request_sha, "realtime_shard_index": shard["realtime_shard_index"], "run_id": shard["run_id"]}
        for field, wanted in expected.items():
            if value[field] != wanted:
                collector.add("BLOCKER", "cue_realtime_package_lineage", f"{label}:{field}", repr(wanted), repr(value[field]), owner)
                valid = False
        if value["status"] != "validated_success":
            collector.add("BLOCKER", "cue_realtime_package_terminal", label, "validated_success", repr(value["status"]), owner)
            valid = False
    # complete 是可恢复 package 的原子终态：三份摘要必须指向同目录下实际的状态、
    # 无正文账本和已验证结果片段。否则替换片段后仍可能保留旧完成标记而逃过恢复门。
    result_path = complete_path.with_name(f"{package_id}.result.jsonl")
    for field, path in (("result_sha256", result_path), ("ledger_sha256", ledger_path), ("state_sha256", state_path)):
        if not path.is_file() or not isinstance(complete[field], str) or SHA256_HEX.fullmatch(complete[field]) is None or sha256_file(path) != complete[field]:
            collector.add("BLOCKER", "cue_realtime_complete_hash", f"{complete_path}:{field}", "匹配实际工件的 64 位 SHA256", repr(complete[field]), owner)
            valid = False
    events = read_jsonl(ledger_path, collector, "cue_realtime_ledger", owner)
    if len(events) != 1:
        collector.add("BLOCKER", "cue_realtime_ledger_terminal_unique", str(ledger_path), "每个 package 一个终态事件", str(len(events)), owner)
        return False
    event = events[0]
    if has_forbidden_realtime_content(event):
        collector.add("BLOCKER", "cue_realtime_raw_content", str(ledger_path), "无请求/响应/错误正文", "发现正文键", owner)
        valid = False
    required = {"realtime_shard_index", "package_id", "request_sha256", "attempt", "outcome", "usage", "retry_eligible", "failure_origin", "transport", "source_atoms_sha256", "cue_execution_protocol_sha256"}
    missing = sorted(required.difference(event))
    if missing:
        collector.add("BLOCKER", "cue_realtime_ledger_fields", str(ledger_path), "冻结实时账本字段", f"缺少 {missing}", owner)
        return False
    if event["outcome"] != "validated_success" or event["retry_eligible"] is not False or event["failure_origin"] is not None:
        collector.add("BLOCKER", "cue_realtime_ledger_terminal", str(ledger_path), "仅 validated_success 且不可重试", repr(event), owner)
        valid = False
    if event["package_id"] != package_id or event["request_sha256"] != request_sha or event["transport"] != contract["transport"] or event["source_atoms_sha256"] != marker["source_atoms_sha256"] or event["cue_execution_protocol_sha256"] != marker["cue_execution_protocol_sha256"]:
        collector.add("BLOCKER", "cue_realtime_ledger_lineage", str(ledger_path), "匹配 manifest/协议/Source", repr(event), owner)
        valid = False
    if not isinstance(event["attempt"], int) or isinstance(event["attempt"], bool) or event["attempt"] < 1 or not isinstance(event["usage"], dict):
        collector.add("BLOCKER", "cue_realtime_ledger_usage", str(ledger_path), "正整数 attempt 与无正文 usage 对象", repr(event), owner)
        valid = False
    return valid


def validate_realtime_item_audit_queue(
    state: dict[str, Any], package_id: str, state_path: Path, collector: IssueCollector, owner: str,
) -> bool:
    """独立验证逐项失败队列，并在最终 Cue SUCCESS 前失败关闭。

    输入是一个 package 的无正文状态及同目录 `item_audit_queue.jsonl`；输出是该
    package 是否已经没有未解决项。它位于第 11 步：队列允许第 05 步继续调度别的
    package，却绝不等同于成功 Cue，因而不能穿透正式 Cue library 的 SUCCESS 门。
    """

    queue_path = state_path.with_name("item_audit_queue.jsonl")
    unresolved = state.get("unresolved_item_count", 0)
    outcomes = state.get("item_outcomes", {})
    valid = True
    if not isinstance(unresolved, int) or isinstance(unresolved, bool) or unresolved < 0:
        collector.add("BLOCKER", "cue_realtime_item_state", str(state_path), "unresolved_item_count 为非负整数", repr(unresolved), owner)
        return False
    if not isinstance(outcomes, dict) or any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in outcomes.values()):
        collector.add("BLOCKER", "cue_realtime_item_state", str(state_path), "item_outcomes 为无正文非负计数对象", repr(outcomes), owner)
        return False
    if not queue_path.exists():
        if unresolved:
            collector.add("BLOCKER", "cue_realtime_item_queue_missing", str(queue_path), "未解决项必须有无正文审计队列", str(unresolved), owner)
            return False
        return True
    rows = read_jsonl(queue_path, collector, "cue_realtime_item_audit_queue", owner)
    seen: set[tuple[str, int]] = set()
    required = {"atom_id", "item_index", "code", "path", "attempt", "request_identity", "package_id", "raw_response_saved"}
    for row in rows:
        if has_forbidden_realtime_content(row):
            collector.add("BLOCKER", "cue_realtime_item_queue_raw_content", str(queue_path), "失败队列绝不含正文", "发现正文键", owner); valid = False
            continue
        if set(row) != required:
            collector.add("BLOCKER", "cue_realtime_item_queue_fields", str(queue_path), "固定的无正文失败项字段", repr(sorted(set(row))), owner); valid = False
            continue
        atom_id, item_index = row["atom_id"], row["item_index"]
        identity = row["request_identity"]
        if (not isinstance(atom_id, str) or not atom_id.startswith("src_") or not isinstance(item_index, int)
                or isinstance(item_index, bool) or item_index < 0 or not isinstance(row["code"], str)
                or re.fullmatch(r"[A-Z0-9_]{1,96}", row["code"]) is None or not isinstance(row["path"], str)
                or re.fullmatch(r"/(?:[A-Za-z0-9_./-]+)?", row["path"]) is None or row["package_id"] != package_id
                or row["raw_response_saved"] is not False):
            collector.add("BLOCKER", "cue_realtime_item_queue_value", str(queue_path), "安全失败码、路径、Atom 身份与无正文标志", repr(row), owner); valid = False
        if not isinstance(row["attempt"], int) or isinstance(row["attempt"], bool) or row["attempt"] not in {1, 2, 3}:
            collector.add("BLOCKER", "cue_realtime_item_repair_limit", str(queue_path), "每项初始失败加至多两次修复，即 attempt 为 1、2 或 3", repr(row.get("attempt")), owner); valid = False
        if not isinstance(identity, str) or (row["attempt"] in {2, 3} and not re.fullmatch(rf"rt_repair_{re.escape(package_id)}_\d+_[0-9a-f]{{10}}", identity)):
            collector.add("BLOCKER", "cue_realtime_item_repair_identity", str(queue_path), "修复请求仅指向本 package 的单 Atom 身份", repr(identity), owner); valid = False
        key = (atom_id, item_index)
        if key in seen:
            collector.add("BLOCKER", "cue_realtime_item_queue_unique", str(queue_path), "每个 Atom/item_index 只保留一个最终队列项", repr(key), owner); valid = False
        seen.add(key)
    if unresolved != len(rows):
        collector.add("BLOCKER", "cue_realtime_item_queue_count", str(queue_path), "unresolved_item_count 与队列行数一致", f"{unresolved} != {len(rows)}", owner); valid = False
    if rows or unresolved:
        collector.add("BLOCKER", "cue_realtime_item_audit_unresolved", str(queue_path), "正式 Cue SUCCESS 前审计队列必须清零", f"未解决 {max(unresolved, len(rows))} 项", owner); valid = False
    return valid


def validate_cue_v2_execution_lineage(
    config: RunConfig,
    marker: dict[str, Any],
    collector: IssueCollector,
    owner: str,
) -> bool:
    """按冻结 transport 验证最终 Cue 的执行血缘，禁止跨传输混用工件。"""

    if marker.get("artifact_type") == "cue_library_manifest":
        # 正式 v9 已将 Cue 物化为 manifest+75 分片；它不再伪装成旧的单文件 Batch 输出。
        required = CUE_V30_MARKER_FIELDS | {"artifact_type", "manifest_sha256", "realtime_run_id", "formal_shard_count", "accepted_cue_count", "excluded_no_cue_count", "excluded_after_repair_count", "excluded_content_filtered_count", "source_atoms_processed_count", "coverage_disposition_sha256"}
        missing = sorted(required.difference(marker))
        if missing:
            collector.add("BLOCKER", "cue_formal_lineage_fields", "cue", "正式 manifest SUCCESS 的完整血缘字段", f"缺少 {missing}", owner)
            return False
        contract = cue_v2_execution_contract(config, collector, owner)
        if contract is None:
            return False
        valid = True
        for field_name, expected in contract.items():
            if field_name == "cue_execution_protocol_sha256":
                # 正式 v3.6 run 的协议哈希已由 2026-09-09 决议冻结；旧 v2.2
                # 哈希计算函数保留兼容测试，不能用它覆盖本次正式输入身份。
                expected = "c7d809927f9cca4ff7d4501a0121c419768cd95c1d3c05d13b156000c50fbbb5"
            if field_name != "transport" and marker.get(field_name) != expected:
                collector.add("BLOCKER", "cue_execution_lineage_mismatch", f"cue:{field_name}", repr(expected), repr(marker.get(field_name)), owner)
                valid = False
        expected_source = load_json(config.marker("source_atoms"), collector, "success_marker", "T1 source")
        source_hash = expected_source.get("sha256") if expected_source else None
        if marker.get("source_atoms_sha256") != source_hash or marker.get("realtime_transport") != "realtime_chat_completions" or marker.get("realtime_run_id") != "realtime_v9_01":
            collector.add("BLOCKER", "cue_formal_runtime_identity", "cue", "realtime_v9_01、实时传输和 Source SHA 固定", repr(marker.get("realtime_run_id")), owner)
            valid = False
        if marker.get("realtime_local_raw_response_storage") != "forbidden" or marker.get("formal_shard_count") != 75 or marker.get("source_atoms_processed_count") != 370799:
            collector.add("BLOCKER", "cue_formal_policy", "cue", "75 分片、370799 Atom 且禁止原始响应", repr(marker), owner)
            valid = False
        usage = marker.get("usage_summary")
        if not isinstance(usage, dict) or sorted(CUE_V2_USAGE_SUMMARY_FIELDS.difference(usage)):
            collector.add("BLOCKER", "cue_formal_usage_summary", "cue", "无正文 usage 汇总字段", repr(usage), owner)
            valid = False
        return valid

    # transport 只能由 T0 冻结的 registry 决定，不能相信 SUCCESS 自报。实时协议
    # 必须在进入任何 Batch 路径前返回，确保已取消 Batch 的状态/receipt 永不被读取。
    contract = cue_v2_execution_contract(config, collector, owner)
    if contract is None:
        return False
    if contract["transport"] == "realtime_chat_completions":
        return validate_realtime_execution_lineage(config, marker, collector, owner)

    missing = sorted(CUE_V22_MARKER_FIELDS.difference(marker))
    if missing:
        collector.add("BLOCKER", "cue_execution_lineage_fields", "cue", "包含全部 v2 执行血缘字段", f"缺少 {missing}", owner)
        return False
    valid = True
    for field_name, expected in contract.items():
        # 传输字段在最终标记中采用带语义前缀的键，避免 Batch 与实时运行状态的
        # 同名字段互相覆盖；由各自的 transport 分支进行严格比较。
        if field_name == "transport":
            continue
        actual = marker.get(field_name)
        if actual != expected:
            collector.add("BLOCKER", "cue_execution_lineage_mismatch", f"cue:{field_name}", repr(expected), repr(actual), owner)
            valid = False
    # Source 的主 SUCCESS 已在 source stage 验过，但 Cue 仍必须显式重述这一次输入
    # 的哈希，防止复用相同 JSONL 文件名的另一轮 Source 重建被混入当前运行。
    source_marker = load_json(config.marker("source_atoms"), collector, "success_marker", "T1 source")
    source_hash = source_marker.get("sha256") if source_marker else None
    if marker.get("source_atoms_sha256") != source_hash:
        collector.add("BLOCKER", "cue_execution_source_hash", "cue", f"冻结 Source SHA256 {source_hash}", repr(marker.get("source_atoms_sha256")), owner)
        valid = False
    if marker["batch_transport"] != "batch_file":
        collector.add("BLOCKER", "cue_batch_transport", "cue", "batch_file", repr(marker["batch_transport"]), owner)
        valid = False
    if marker["batch_local_raw_response_storage"] != "forbidden":
        collector.add("BLOCKER", "cue_batch_raw_response_policy", "cue", "forbidden", repr(marker["batch_local_raw_response_storage"]), owner)
        valid = False
    if marker["remote_cleanup_required"] is not True or marker["remote_cleanup_status"] != "pending_t4_cue_qa":
        collector.add("BLOCKER", "cue_batch_remote_cleanup", "cue", "T4 Cue QA 前要求清理且状态 pending_t4_cue_qa", f"required={marker['remote_cleanup_required']!r}, status={marker['remote_cleanup_status']!r}", owner)
        valid = False
    if not isinstance(marker["batch_task_count"], int) or isinstance(marker["batch_task_count"], bool) or marker["batch_task_count"] < 1:
        collector.add("BLOCKER", "cue_batch_task_count", "cue", "正整数", repr(marker["batch_task_count"]), owner)
        valid = False
    if not isinstance(marker["batch_input_total_request_count"], int) or isinstance(marker["batch_input_total_request_count"], bool) or marker["batch_input_total_request_count"] < 1:
        collector.add("BLOCKER", "cue_batch_total_requests", "cue", "正整数", repr(marker["batch_input_total_request_count"]), owner)
        valid = False
    usage_summary = marker.get("usage_summary")
    if not isinstance(usage_summary, dict):
        collector.add("BLOCKER", "cue_usage_summary_shape", "cue", "对象类型的用量账本汇总", type(usage_summary).__name__, owner)
        return False
    missing_usage = sorted(CUE_V2_USAGE_SUMMARY_FIELDS.difference(usage_summary))
    if missing_usage:
        collector.add("BLOCKER", "cue_usage_summary_fields", "cue", "包含全部冻结用量汇总字段", f"缺少 {missing_usage}", owner)
        return False
    integer_fields = CUE_V2_USAGE_SUMMARY_FIELDS - {"rate_limit_wait_seconds"}
    for field_name in sorted(integer_fields):
        value = usage_summary[field_name]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            collector.add("BLOCKER", "cue_usage_summary_value", f"cue:{field_name}", "非负整数", repr(value), owner)
            valid = False
    wait_seconds = usage_summary["rate_limit_wait_seconds"]
    if not isinstance(wait_seconds, (int, float)) or isinstance(wait_seconds, bool) or wait_seconds < 0:
        collector.add("BLOCKER", "cue_usage_summary_value", "cue:rate_limit_wait_seconds", "非负数值", repr(wait_seconds), owner)
        valid = False
    if all(isinstance(usage_summary[name], int) and not isinstance(usage_summary[name], bool) for name in integer_fields):
        if usage_summary["successful_attempt_count"] + usage_summary["failed_attempt_count"] != usage_summary["attempt_count"]:
            collector.add("BLOCKER", "cue_usage_summary_attempts", "cue", "successful_attempt_count + failed_attempt_count = attempt_count", repr(usage_summary), owner)
            valid = False
        if usage_summary["prompt_tokens"] + usage_summary["completion_tokens"] != usage_summary["total_tokens"]:
            collector.add("BLOCKER", "cue_usage_summary_tokens", "cue", "prompt_tokens + completion_tokens = total_tokens", repr(usage_summary), owner)
            valid = False
        if usage_summary["retry_count"] > usage_summary["attempt_count"]:
            collector.add("BLOCKER", "cue_usage_summary_retries", "cue", "retry_count 不超过 attempt_count", repr(usage_summary), owner)
            valid = False
    if valid:
        valid = validate_batch_task_manifest(config, contract, marker, collector, owner)
    if valid:
        valid = validate_batch_task_receipts(config, marker, collector, owner)
    if valid:
        valid = validate_batch_package_ledgers(config, contract, marker, collector, owner)
    return valid


def jsonl_row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline=None) as handle:
        return sum(1 for line in handle if line.strip())


def read_jsonl(path: Path, collector: IssueCollector, stage: str, owner: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        handle = path.open("r", encoding="utf-8", newline=None)
    except OSError as exc:
        collector.add("BLOCKER", "artifact_unreadable", str(path), "可读取 JSONL", str(exc), owner)
        return records
    with handle:
        for line_number, line in enumerate(handle, start=1):
            # 空行会使 SUCCESS 行数与可解析记录数产生歧义，因此按错误而非忽略处理。
            if not line.strip():
                collector.add("BLOCKER", "jsonl_blank_line", f"{stage}:{line_number}", "每一行都是 JSON 对象", "空行", owner)
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                collector.add("BLOCKER", "jsonl_parse", f"{stage}:{line_number}", "合法 JSON", str(exc), owner)
                continue
            if not isinstance(record, dict):
                collector.add("BLOCKER", "jsonl_record_shape", f"{stage}:{line_number}", "JSON 对象", type(record).__name__, owner)
                continue
            records.append(record)
    if not records:
        collector.add("BLOCKER", "artifact_empty", stage, "至少一条正式记录", "0 条记录", owner)
    return records


FORMAL_CUE_DISPOSITION_COUNTS = {
    "accepted_cue": 294839,
    "excluded_no_cue": 60827,
    "excluded_after_repair": 15098,
    "excluded_content_filtered": 35,
}


def validate_formal_cue_snapshot(
    config: RunConfig,
    marker: dict[str, Any],
    source_records: list[dict[str, Any]],
    cue_records: list[dict[str, Any]],
    collector: IssueCollector,
    owner: str,
) -> bool:
    """独立复算 75 个 Cue 分片、八波 coverage 和四类 disposition。"""

    manifest_path = config.artifact("cue_library_manifest")
    manifest = load_json(manifest_path, collector, "cue_manifest", owner)
    if manifest is None:
        return False
    valid = True
    if manifest.get("artifact_type") != "cue_library_logical_snapshot" or manifest.get("shard_count") != 75:
        collector.add("BLOCKER", "cue_manifest_shape", "cue", "75 个 task 的正式逻辑快照", repr(manifest), owner)
        return False
    if marker.get("manifest_sha256") != sha256_file(manifest_path):
        collector.add("BLOCKER", "cue_manifest_success_hash", "cue", sha256_file(manifest_path), repr(marker.get("manifest_sha256")), owner)
        valid = False
    if manifest.get("source_atoms_sha256") != marker.get("source_atoms_sha256"):
        collector.add("BLOCKER", "cue_manifest_source_hash", "cue", repr(marker.get("source_atoms_sha256")), repr(manifest.get("source_atoms_sha256")), owner)
        valid = False
    shards = manifest.get("shards")
    if not isinstance(shards, list) or len(shards) != 75:
        collector.add("BLOCKER", "cue_manifest_shards", "cue", "恰好 75 个分片", repr(shards), owner)
        return False
    seen_tasks: set[int] = set()
    seen_cue_ids: set[str] = set()
    seen_atom_ids: set[str] = set()
    formal_dir = (config.benchmark_root / "cues" / "formal").resolve()
    for shard in shards:
        task_index = shard.get("task_index")
        path = (config.benchmark_root / str(shard.get("path"))).resolve()
        if not isinstance(task_index, int) or task_index in seen_tasks or not 0 <= task_index < 75 or path.parent != formal_dir or path.name != f"task_{task_index:03d}.jsonl":
            collector.add("BLOCKER", "cue_manifest_shard_identity", str(task_index), "task 000..074 各出现一次且位于 cues/formal", repr(shard), owner)
            valid = False
            continue
        seen_tasks.add(task_index)
        if not path.is_file():
            collector.add("BLOCKER", "cue_manifest_shard_missing", str(path), "分片存在", "文件不存在", owner)
            valid = False
            continue
        actual_hash = sha256_file(path)
        if actual_hash != shard.get("sha256") or path.stat().st_size != shard.get("byte_count"):
            collector.add("BLOCKER", "cue_manifest_shard_hash", str(path), "SHA256 与字节数均匹配", repr(shard), owner)
            valid = False
        rows = read_jsonl(path, collector, f"cue_formal_{task_index:03d}", owner)
        if len(rows) != shard.get("row_count"):
            collector.add("BLOCKER", "cue_manifest_shard_rows", str(path), repr(shard.get("row_count")), repr(len(rows)), owner)
            valid = False
        for cue in rows:
            cue_id, atom_id = cue.get("cue_id"), cue.get("atom_id")
            if cue.get("validation_status") != "accepted_cue" and cue.get("validation_status") != "accepted":
                collector.add("BLOCKER", "cue_formal_nonaccepted", str(cue_id), "正式分片只含 accepted_cue", repr(cue.get("validation_status")), owner)
                valid = False
            if not isinstance(cue_id, str) or cue_id in seen_cue_ids:
                collector.add("BLOCKER", "cue_formal_duplicate_id", str(cue_id), "全局 cue_id 唯一", "重复或无效", owner)
                valid = False
            else:
                seen_cue_ids.add(cue_id)
            if not isinstance(atom_id, str) or atom_id in seen_atom_ids:
                collector.add("BLOCKER", "cue_formal_duplicate_atom", str(atom_id), "accepted Atom 只出现一次", "重复或无效", owner)
                valid = False
            else:
                seen_atom_ids.add(atom_id)
            if isinstance(atom_id, str) and cue_id != f"cue_{atom_id.removeprefix('src_')}":
                collector.add("BLOCKER", "cue_formal_id_derivation", str(atom_id), f"cue_{atom_id.removeprefix('src_')}", repr(cue_id), owner)
                valid = False
    if seen_tasks != set(range(75)):
        collector.add("BLOCKER", "cue_manifest_task_coverage", "cue", "task 000..074 完整覆盖", repr(sorted(seen_tasks)), owner)
        valid = False
    if len(cue_records) != manifest.get("cue_count") or len(cue_records) != 294839 or seen_cue_ids != {row.get("cue_id") for row in cue_records}:
        collector.add("BLOCKER", "cue_manifest_total_count", "cue", "294839 且与分片并集一致", f"manifest={manifest.get('cue_count')}, records={len(cue_records)}, shard_ids={len(seen_cue_ids)}", owner)
        valid = False
    if len(source_records) != 370799:
        collector.add("BLOCKER", "cue_source_atom_count", "cue", "370799 个 Source Atom", repr(len(source_records)), owner)
        valid = False
    source_ids = {row.get("atom_id") for row in source_records}
    wave_audit = manifest.get("wave_audit")
    coverage_by_atom: dict[str, dict[str, Any]] = {}
    disposition_counts = Counter()
    if not isinstance(wave_audit, list) or len(wave_audit) != 8:
        collector.add("BLOCKER", "cue_wave_audit_shape", "cue", "八波 coverage 审计", repr(wave_audit), owner)
        valid = False
    else:
        for item in wave_audit:
            coverage_path = (config.benchmark_root / str(item.get("coverage_disposition_path"))).resolve()
            if not str(coverage_path).replace("\\", "/").endswith(f"cues/realtime/runs/realtime_v9_01/wave_{int(item.get('wave_index', 0)):02d}/coverage_disposition.jsonl") or not coverage_path.is_file():
                collector.add("BLOCKER", "cue_coverage_path", str(coverage_path), "仅 realtime_v9_01 八波 coverage", "路径缺失或越界", owner)
                valid = False
                continue
            if sha256_file(coverage_path) != item.get("coverage_disposition_sha256"):
                collector.add("BLOCKER", "cue_coverage_hash", str(coverage_path), repr(item.get("coverage_disposition_sha256")), repr(sha256_file(coverage_path)), owner)
                valid = False
            for row in read_jsonl(coverage_path, collector, "cue_coverage", owner):
                atom_id = row.get("atom_id")
                if atom_id in coverage_by_atom:
                    collector.add("BLOCKER", "cue_coverage_duplicate_atom", str(atom_id), "每个 Source Atom 恰有一个 disposition", "重复", owner)
                    valid = False
                coverage_by_atom[atom_id] = row
                disposition_counts[row.get("disposition")] += 1
    if set(coverage_by_atom) != source_ids or dict(disposition_counts) != FORMAL_CUE_DISPOSITION_COUNTS:
        collector.add("BLOCKER", "cue_disposition_coverage", "cue", repr(FORMAL_CUE_DISPOSITION_COUNTS), repr(dict(disposition_counts)), owner)
        valid = False
    accepted_ids = {atom_id for atom_id, row in coverage_by_atom.items() if row.get("disposition") == "accepted_cue"}
    if seen_atom_ids != accepted_ids:
        collector.add("BLOCKER", "cue_accepted_coverage", "cue", "正式 Cue Atom 集等于 accepted_cue coverage", f"cue={len(seen_atom_ids)}, accepted={len(accepted_ids)}", owner)
        valid = False
    return valid


def read_formal_cue_records(config: RunConfig, collector: IssueCollector, owner: str) -> list[dict[str, Any]]:
    """按 manifest 顺序读取正式 Cue 分片，绝不回退到单文件缓存。"""

    manifest = load_json(config.artifact("cue_library_manifest"), collector, "cue_manifest", owner)
    if manifest is None or not isinstance(manifest.get("shards"), list):
        return []
    records: list[dict[str, Any]] = []
    for shard in sorted(manifest["shards"], key=lambda item: item.get("task_index", -1)):
        path = (config.benchmark_root / str(shard.get("path"))).resolve()
        records.extend(read_jsonl(path, collector, "cue", owner))
    return records


def marker_is_valid(
    config: RunConfig,
    stage: str,
    marker_key: str,
    artifact_key: str,
    owner: str,
    collector: IssueCollector,
) -> bool:
    # SUCCESS 是生产者与 QA 之间唯一的稳定边界。先验证其元数据，再打开 JSONL，
    # 才不会把正在写入、被篡改或来自另一份上游数据的内容误判为正式产物。
    marker_path = config.marker(marker_key)
    expected_artifact = config.artifact(artifact_key)
    if not marker_path.is_file():
        collector.add(
            "BLOCKER",
            "success_marker_missing",
            stage,
            f"存在 {marker_path.name} 后才能读取正式产物",
            "SUCCESS 标记不存在",
            owner,
        )
        return False
    marker = load_json(marker_path, collector, "success_marker", owner)
    if marker is None:
        return False
    if stage == "cue" and marker.get("artifact_type") == "cue_library_manifest":
        expected_artifact = config.artifact("cue_library_manifest")
    required = {
        "artifact_path",
        "sha256",
        "row_count",
        "contract_version",
        "config_version",
        "schema_versions",
        "generated_at",
        "upstream_hashes",
    }
    missing = sorted(required.difference(marker))
    if missing:
        collector.add("BLOCKER", "success_marker_fields", stage, "包含所有合同必需字段", f"缺少 {missing}", owner)
        return False
    valid = True
    expected_names = config.relative_artifact_names(expected_artifact)
    actual_name = str(marker["artifact_path"]).replace("\\", "/")
    if actual_name not in expected_names:
        collector.add("BLOCKER", "success_marker_artifact", stage, f"artifact_path 为 {sorted(expected_names)}", actual_name, owner)
        valid = False
    expected_versions = STAGE_ARTIFACT_VERSIONS[stage]
    expected_contract_version = expected_versions["contract_version"]
    expected_config_version = expected_versions["config_version"]
    if (
        marker["contract_version"] != expected_contract_version
        or marker["config_version"] != expected_config_version
    ):
        collector.add(
            "BLOCKER",
            "success_marker_version",
            stage,
            "contract_version/config_version 分别为 "
            f"{expected_contract_version}/{expected_config_version}",
            f"{marker['contract_version']}/{marker['config_version']}",
            owner,
        )
        valid = False
    schema_versions = marker["schema_versions"]
    expected_schema_versions = expected_versions["schema_versions"]
    if not isinstance(schema_versions, dict):
        collector.add(
            "BLOCKER",
            "success_marker_schema_versions",
            stage,
            f"对象类型且包含 {expected_schema_versions}",
            repr(schema_versions),
            owner,
        )
        valid = False
    else:
        # 标记必须用 Schema 名称逐项声明，不能只出现相同的版本字符串；否则 v1.0.0
        # 的 Cue 与 v1.1.0 的 Source 会在同一执行合同下被混淆，失去可复现的边界。
        for schema_key, expected_schema_version in expected_schema_versions.items():
            actual_schema_version = schema_versions.get(schema_key)
            if actual_schema_version != expected_schema_version:
                collector.add(
                    "BLOCKER",
                    "success_marker_schema_versions",
                    stage,
                    f"schema_versions[{schema_key!r}] 为 {expected_schema_version}",
                    repr(actual_schema_version),
                    owner,
                )
                valid = False
    try:
        timestamp = str(marker["generated_at"]).replace("Z", "+00:00")
        datetime.fromisoformat(timestamp)
    except ValueError:
        collector.add("BLOCKER", "success_marker_timestamp", stage, "ISO 8601 时间戳", repr(marker["generated_at"]), owner)
        valid = False
    if not isinstance(marker["upstream_hashes"], dict):
        collector.add("BLOCKER", "success_marker_upstream_hashes", stage, "对象类型的 upstream_hashes", type(marker["upstream_hashes"]).__name__, owner)
        valid = False
    else:
        # 仅校验自身文件不足以保证谱系正确；下游必须显式携带每个已验证上游的哈希，
        # 否则相同文件名也可能悄悄引用了另一次生成结果。
        declared_hashes = set(flatten_string_values(marker["upstream_hashes"]))
        for dependency in STAGE_DEPENDENCIES[stage]:
            dependency_spec = next(spec for spec in STAGES if spec[0] == dependency)
            dependency_marker = load_json(config.marker(dependency_spec[1]), collector, "success_marker", dependency_spec[4])
            expected_hash = dependency_marker.get("sha256") if dependency_marker else None
            if not isinstance(expected_hash, str) or expected_hash not in declared_hashes:
                collector.add(
                    "BLOCKER",
                    "success_marker_upstream_hash",
                    stage,
                    f"upstream_hashes 包含已验证 {dependency} 的 SHA256 {expected_hash}",
                    repr(marker["upstream_hashes"]),
                    owner,
                )
                valid = False
    if stage == "cue" and not validate_cue_v2_execution_lineage(config, marker, collector, owner):
        valid = False
    if not expected_artifact.is_file():
        collector.add("BLOCKER", "success_marker_artifact_missing", stage, str(expected_artifact), "正式产物不存在", owner)
        return False
    actual_hash = sha256_file(expected_artifact)
    if marker["sha256"] != actual_hash:
        collector.add("BLOCKER", "success_marker_hash", stage, actual_hash, str(marker["sha256"]), owner)
        valid = False
    if marker.get("artifact_type") == "cue_library_manifest":
        manifest = load_json(expected_artifact, collector, "cue_manifest", owner)
        if manifest is None:
            valid = False
    else:
        actual_rows = jsonl_row_count(expected_artifact)
        if marker["row_count"] != actual_rows:
            collector.add("BLOCKER", "success_marker_row_count", stage, str(actual_rows), repr(marker["row_count"]), owner)
            valid = False
    return valid


def flatten_string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for nested in value.values() for item in flatten_string_values(nested)]
    if isinstance(value, list):
        return [item for nested in value for item in flatten_string_values(nested)]
    return []


def validate_schema(
    records: Iterable[dict[str, Any]], schema_path: Path, stage: str, owner: str, collector: IssueCollector
) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for position, record in enumerate(records, start=1):
        record_id = next((str(record[key]) for key in ("atom_id", "cue_id", "seed_id", "lifelog_id", "decision_id") if key in record), f"{stage}:{position}")
        for error in sorted(validator.iter_errors(record), key=lambda item: list(item.absolute_path)):
            location = ".".join(str(part) for part in error.absolute_path) or "$"
            collector.add("BLOCKER", "schema", record_id, f"{location} 满足 schema", error.message, owner)


def normalized_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def cue_evidence_normalized_text(value: str) -> str:
    """将 Cue 证据按冻结的无语义格式规则归一化，用于连续子串核验。

    输入：一段 `visible_text`、`source_text` 或 `supporting_text_span` 原始字符串。
    输出：NFKC 与 casefold 后移除 Unicode 空白、标点 P* 和格式控制 Cf 的字符串。
    流水线位置：第 5 步实时接收的镜像 QA 与第 11 步最终 Cue 可追溯性验证。
    """

    # 仅移除合同明确认定不改变语义的格式差异；字母、数字、单位、符号和字符顺序一律
    # 保留，因此拼写改写、数值/单位漂移、跨字段取证及非连续重排仍会被严格拒绝。
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(
        character
        for character in normalized
        if not character.isspace()
        and not unicodedata.category(character).startswith("P")
        and unicodedata.category(character) != "Cf"
    )


def char_3grams(value: str) -> set[str]:
    compact = normalized_text(value)
    if len(compact) < 3:
        return {compact} if compact else set()
    return {compact[index : index + 3] for index in range(len(compact) - 2)}


def jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return 1.0 if not union else len(left & right) / len(union)


def session_is_same_or_adjacent(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.get("session_id") == right.get("session_id"):
        return True
    if left.get("participant_source_id") != right.get("participant_source_id") or left.get("source_day") != right.get("source_day"):
        return False
    left_tail = re.search(r"(\d+)$", str(left.get("session_id", "")))
    right_tail = re.search(r"(\d+)$", str(right.get("session_id", "")))
    return bool(left_tail and right_tail and abs(int(left_tail.group(1)) - int(right_tail.group(1))) == 1)


def resolve_source_path(value: str, config: RunConfig) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    project_candidate = (config.project_root / candidate).resolve()
    if project_candidate.is_file():
        return project_candidate
    # T1 将来源记录为相对 raw 父目录的 ``EgoLifeCap/...``，不能把它误当成
    # 项目根下的文件；否则 SRT 存在却会被 QA 全部报为缺失。保留项目根回退可兼容
    # synthetic fixture，而正式语料则以冻结 raw_root 的父目录为唯一锚点。
    raw_root = getattr(config, "raw_root", None)
    if isinstance(raw_root, Path):
        return (raw_root.parent / candidate).resolve()
    return project_candidate


def source_cross_session_near_duplicate_pairs(
    records: list[dict[str, Any]], text_grams: dict[str, set[str]], threshold: float, cross_split_only: bool = False
) -> Iterable[tuple[dict[str, Any], dict[str, Any]]]:
    """精确枚举同一人同一天、不同 session 的高相似 Source Atom 对。"""

    # v1.1.0 明确禁止从 SRT 相对秒推断跨 session 顺序，故此处只按 participant/day
    # 分桶并比较该桶的全部不同 session。前缀倒排由 Jaccard 下界推导，不是近似筛选；
    # 候选仍以完整 3-gram Jaccard 复核，避免百万级笛卡尔枚举使 QA 永远无法完成。
    gram_frequency = Counter(gram for grams in text_grams.values() for gram in grams)
    by_person_day: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_person_day[(str(record.get("participant_source_id")), str(record.get("source_day")))].append(record)

    for key in sorted(by_person_day):
        # QA 只关心跨 split 泄漏时可按 split 建子索引，先消去已知安全的同 split
        # 候选；这不改变任何跨 split 原子对是否经过完整 Jaccard 复核的结论。
        prefix_index: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        atoms = sorted(by_person_day[key], key=lambda item: str(item.get("atom_id")))
        atoms_by_id = {str(atom.get("atom_id")): atom for atom in atoms}
        for atom in atoms:
            atom_id = str(atom.get("atom_id"))
            grams = text_grams.get(atom_id, set())
            if not grams:
                continue
            required_overlap = math.ceil(threshold * len(grams))
            prefix_size = len(grams) - required_overlap + 1
            prefix = sorted(grams, key=lambda gram: (gram_frequency[gram], gram))[:prefix_size]
            atom_split = str(atom.get("split"))
            candidate_ids = {
                candidate_id
                for gram in prefix
                for split, ids in prefix_index[gram].items()
                if not cross_split_only or split != atom_split
                for candidate_id in ids
            }
            for candidate_id in sorted(candidate_ids):
                candidate = atoms_by_id[candidate_id]
                if candidate.get("session_id") == atom.get("session_id"):
                    continue
                candidate_grams = text_grams.get(candidate_id, set())
                if not candidate_grams or min(len(grams), len(candidate_grams)) / max(len(grams), len(candidate_grams)) < threshold:
                    continue
                if jaccard(grams, candidate_grams) >= threshold:
                    yield candidate, atom
            for gram in prefix:
                prefix_index[gram][atom_split].append(atom_id)


def srt_duration_seconds(path: Path) -> float | None:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    values = []
    for match in SRT_TIMESTAMP.finditer(text):
        values.append(
            int(match.group("h")) * 3600
            + int(match.group("m")) * 60
            + int(match.group("s"))
            + int(match.group("ms")) / 1000
        )
    return max(values) if values else None


def validate_unique(records: Iterable[dict[str, Any]], field_name: str, stage: str, owner: str, collector: IssueCollector) -> None:
    seen: set[str] = set()
    for record in records:
        value = record.get(field_name)
        if not isinstance(value, str):
            continue
        if value in seen:
            collector.add("BLOCKER", "duplicate_id", value, f"{field_name} 在全体数据中唯一", "发现重复 ID", owner)
        seen.add(value)


def validate_source(records: list[dict[str, Any]], config: RunConfig, collector: IssueCollector) -> None:
    owner = "T1 source"
    validate_unique(records, "atom_id", "source", owner, collector)
    groups: dict[str, set[str]] = defaultdict(set)
    world_events: dict[str, set[str]] = defaultdict(set)
    duration_cache: dict[Path, float | None] = {}
    text_grams: dict[str, set[str]] = {}
    for atom in records:
        atom_id = str(atom.get("atom_id", "source:unknown"))
        start = atom.get("local_start_sec")
        end = atom.get("local_end_sec")
        normalized_start = atom.get("normalized_start_sec")
        normalized_end = atom.get("normalized_end_sec")
        # 本地时间用于回溯 SRT，规范化时间用于组装虚拟日志；两者各自倒序都会破坏证据定位。
        if all(isinstance(value, (int, float)) for value in (start, end)) and start >= end:
            collector.add("BLOCKER", "source_time_order", atom_id, "local_start_sec < local_end_sec", f"{start} >= {end}", owner)
        if all(isinstance(value, (int, float)) for value in (normalized_start, normalized_end)) and normalized_start >= normalized_end:
            collector.add("BLOCKER", "source_normalized_time_order", atom_id, "normalized_start_sec < normalized_end_sec", f"{normalized_start} >= {normalized_end}", owner)
        split = atom.get("split")
        if isinstance(atom.get("source_group_id"), str) and isinstance(split, str):
            groups[atom["source_group_id"]].add(split)
        if isinstance(atom.get("world_event_id"), str) and isinstance(split, str):
            world_events[atom["world_event_id"]].add(split)
        paths = atom.get("source_srt_paths")
        if isinstance(paths, dict):
            # v1.1.0 的 03 步以非空 Dense Caption 作为原子的主时间窗口；Transcript
            # 只负责提供可追溯的对齐证据，可能在同一 session 内较早结束。因而两个
            # 引用 SRT 都必须存在且含可解析时间戳，但只有主模态可以约束 atom 的
            # local_start_sec/local_end_sec，避免把合法的 Dense 窗口误判为越界。
            primary_modality = "dense_caption" if atom.get("dense_caption") else "transcript"
            for modality in ("transcript", "dense_caption"):
                raw_path = paths.get(modality)
                if not isinstance(raw_path, str):
                    continue
                path = resolve_source_path(raw_path, config)
                if not path.is_file():
                    collector.add("BLOCKER", "source_srt_missing", atom_id, f"存在 {modality} SRT", str(path), owner)
                    continue
                # SRT 文件存在仍不足以证明引用有效，必须确保 atom 终点没有超出最后时间戳。
                duration = duration_cache.setdefault(path, srt_duration_seconds(path))
                if duration is None:
                    collector.add("BLOCKER", "source_srt_timestamp", atom_id, "SRT 含可解析时间戳", str(path), owner)
                elif modality == primary_modality:
                    for field_name, value in (("local_start_sec", start), ("local_end_sec", end)):
                        if isinstance(value, (int, float)) and value > duration + 0.001:
                            collector.add(
                                "BLOCKER",
                                "source_time_out_of_srt",
                                atom_id,
                                f"{field_name} <= {duration}（主时间窗口：{primary_modality}）",
                                str(value),
                                owner,
                            )
        video_path = atom.get("source_video_path")
        if isinstance(video_path, str):
            resolved_video = resolve_source_path(video_path, config)
            if atom.get("video_mapping_status") != "verified" or not resolved_video.is_file():
                collector.add(
                    "BLOCKER",
                    "fabricated_video_path",
                    atom_id,
                    "仅 verified 且存在的 MP4 路径可出现；否则为 null",
                    f"{video_path} ({atom.get('video_mapping_status')})",
                    owner,
                )
        text_grams[atom_id] = char_3grams(str(atom.get("visible_text", "")))
    for group_id, splits in groups.items():
        if len(splits) > 1:
            collector.add("BLOCKER", "split_source_group", group_id, "同一 source_group_id 仅一个 split", str(sorted(splits)), owner)
    for event_id, splits in world_events.items():
        if len(splits) > 1:
            collector.add("BLOCKER", "split_world_event", event_id, "同一 world_event_id 仅一个 split", str(sorted(splits)), owner)
    # 高相似字幕跨 split 会使模型通过记住改写文本获益；必须按冻结策略复查同一人同一天
    # 的全部不同 session，不能根据 session 编号或相对秒缩小范围。
    threshold = float(config.split_policy["grouping"]["near_duplicate"]["similarity_threshold"])
    for left, right in source_cross_session_near_duplicate_pairs(records, text_grams, threshold, cross_split_only=True):
        if left.get("split") == right.get("split"):
            continue
        similarity = jaccard(
            text_grams.get(str(left.get("atom_id")), set()), text_grams.get(str(right.get("atom_id")), set())
        )
        collector.add(
            "BLOCKER",
            "split_near_duplicate",
            f"{left.get('atom_id')}|{right.get('atom_id')}",
            f"跨 split 字幕相似度 < {threshold}",
            f"{similarity:.4f}",
            owner,
        )


def validate_cues(records: list[dict[str, Any]], atoms: dict[str, dict[str, Any]], collector: IssueCollector) -> None:
    owner = "T2 cue"
    validate_unique(records, "cue_id", "cue", owner, collector)
    for cue in records:
        cue_id = str(cue.get("cue_id", "cue:unknown"))
        atom = atoms.get(cue.get("atom_id"))
        if atom is None:
            collector.add("BLOCKER", "cue_atom_missing", cue_id, "atom_id 指向已验证 source atom", repr(cue.get("atom_id")), owner)
            continue
        if cue.get("split") != atom.get("split"):
            collector.add("BLOCKER", "cue_split", cue_id, f"split={atom.get('split')}", repr(cue.get("split")), owner)
        visible_text = atom.get("visible_text")
        if not isinstance(visible_text, str) or not cue_evidence_normalized_text(visible_text):
            # 即使 Source schema 理应已拦截空文本，Cue QA 仍须独立失败关闭，不能把空
            # evidence 当作任意字符串的子串，从而放过错误字段来源或空支撑。
            collector.add("BLOCKER", "cue_atom_visible_text_missing", cue_id, "所属 atom 的 visible_text 为归一化后非空字符串", repr(visible_text), owner)
            continue
        claimed_source = cue.get("source_text")
        if not isinstance(claimed_source, str) or not cue_evidence_normalized_text(claimed_source):
            collector.add("BLOCKER", "cue_source_text_missing", cue_id, "source_text 为归一化后非空字符串", repr(claimed_source), owner)
        elif claimed_source != visible_text:
            # 最终 Cue 的 source_text 是对 atom.visible_text 的原样快照，而非任一 SRT
            # 字段；这条精确相等门阻止从 transcript 或 dense_caption 借来不属于 atom
            # 可见证据的文字，即便那些文字恰好也能支撑谓词。
            collector.add("BLOCKER", "cue_source_text_mismatch", cue_id, "source_text 与 atom.visible_text 完全一致", repr(claimed_source), owner)
        supporting_span = cue.get("supporting_text_span")
        supporting_normalized = (
            cue_evidence_normalized_text(supporting_span) if isinstance(supporting_span, str) else ""
        )
        supporting_field = cue.get("supporting_text_field")
        if supporting_field not in {"transcript", "dense_caption", "visible_text"}:
            # Schema 会拒绝未知字段值；此处仍保持独立的失败关闭，避免 T4 在读取手工篡改
            # 的 JSONL 或尚未运行 Schema 门时把证据误投影到任何一个可用字段。
            collector.add(
                "BLOCKER",
                "cue_supporting_field_invalid",
                cue_id,
                "supporting_text_field 为 transcript、dense_caption 或 visible_text",
                repr(supporting_field),
                owner,
            )
            continue
        supporting_source = atom.get(supporting_field)
        supporting_source_normalized = (
            cue_evidence_normalized_text(supporting_source) if isinstance(supporting_source, str) else ""
        )
        if not supporting_source_normalized:
            collector.add(
                "BLOCKER",
                "cue_supporting_field_missing",
                cue_id,
                f"atom.{supporting_field} 为归一化后非空字符串",
                repr(supporting_source),
                owner,
            )
        if not supporting_normalized:
            collector.add("BLOCKER", "cue_supporting_span_missing", cue_id, "supporting_text_span 为归一化后非空字符串", repr(supporting_span), owner)
        elif isinstance(supporting_span, str) and supporting_source is not None and supporting_span not in supporting_source:
            # v3.5 不接收模型复写的 x，而由程序用 f/start/end 从原字段切片。因此最终
            # span 必须逐字等于该字段的一个原始连续片段；仅归一化命中不足以证明它是切片。
            collector.add(
                "BLOCKER",
                "cue_supporting_span_not_program_slice",
                cue_id,
                f"supporting_text_span 是同一 atom.{supporting_field} 的原始连续子串",
                repr(supporting_span),
                owner,
            )
        elif supporting_source_normalized and supporting_normalized not in supporting_source_normalized:
            collector.add(
                "BLOCKER",
                "cue_supporting_span_trace",
                cue_id,
                f"supporting_text_span 归一化后是同一 atom.{supporting_field} 的连续子串",
                repr(supporting_span),
                owner,
            )


def validate_seeds(
    records: list[dict[str, Any]], atoms: dict[str, dict[str, Any]], frozen: bool, collector: IssueCollector
) -> None:
    owner = "T3 compiler" if frozen else "T2 seed"
    validate_unique(records, "seed_id", "frozen" if frozen else "candidate", owner, collector)
    ids = set(atoms)
    for seed in records:
        seed_id = str(seed.get("seed_id", "seed:unknown"))
        trigger = seed.get("trigger_atom_id")
        lures = seed.get("lure_atom_ids", [])
        if trigger not in ids:
            collector.add("BLOCKER", "seed_trigger_missing", seed_id, "trigger_atom_id 指向已验证 atom", repr(trigger), owner)
            continue
        if trigger in lures:
            collector.add("BLOCKER", "seed_trigger_as_lure", seed_id, "trigger 不能同时是 lure", repr(trigger), owner)
        for lure in lures:
            if lure not in ids:
                collector.add("BLOCKER", "seed_lure_missing", seed_id, "每个 lure 指向已验证 atom", repr(lure), owner)
            elif atoms[lure].get("split") != seed.get("split"):
                collector.add("BLOCKER", "seed_lure_split", seed_id, f"lure split={seed.get('split')}", f"{lure}={atoms[lure].get('split')}", owner)
        trigger_atom = atoms[trigger]
        if trigger_atom.get("split") != seed.get("split"):
            collector.add("BLOCKER", "seed_trigger_split", seed_id, f"trigger split={seed.get('split')}", repr(trigger_atom.get("split")), owner)
        if seed.get("source_group_id") != trigger_atom.get("source_group_id"):
            collector.add("BLOCKER", "seed_source_group", seed_id, f"source_group_id={trigger_atom.get('source_group_id')}", repr(seed.get("source_group_id")), owner)
        required_silent = {"completed", "cancelled", "expired", "already_reminded"}
        supplied_silent = set(seed.get("terminal_silent_conditions", []))
        if not required_silent.issubset(supplied_silent):
            collector.add("BLOCKER", "seed_terminal_silence", seed_id, f"包含 {sorted(required_silent)}", repr(sorted(supplied_silent)), owner)
        if seed.get("current_trigger_leakage_checked") is not True:
            collector.add("BLOCKER", "seed_trigger_leakage_check", seed_id, "current_trigger_leakage_checked=true", repr(seed.get("current_trigger_leakage_checked")), owner)
        if frozen:
            audit = seed.get("audit", {})
            if audit.get("status") != "accept" or not isinstance(audit.get("human_reviewer"), str) or not audit["human_reviewer"].strip():
                collector.add("BLOCKER", "frozen_seed_human_audit", seed_id, "冻结 seed 具有 accept 和人工审阅者", repr(audit), owner)
    if frozen and not 35 <= len(records) <= 40:
        collector.add("BLOCKER", "frozen_seed_count", "frozen_seeds", "35–40 个冻结 seed", str(len(records)), owner)


def parse_virtual_time(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    match = VIRTUAL_TIME.fullmatch(value)
    if not match:
        return None
    return (
        int(match.group("d")) * 24 * 3600
        + int(match.group("h")) * 3600
        + int(match.group("m")) * 60
        + int(match.group("s") or 0)
    )


def source_event_duration(event: dict[str, Any]) -> float:
    source_time = event.get("source_time")
    if not isinstance(source_time, dict):
        return 0.0
    return float(source_time.get("local_end_sec", 0)) - float(source_time.get("local_start_sec", 0))


def validate_lifelogs(
    records: list[dict[str, Any]], atoms: dict[str, dict[str, Any]], seeds: dict[str, dict[str, Any]], config: RunConfig, collector: IssueCollector
) -> None:
    owner = "T3 compiler"
    validate_unique(records, "lifelog_id", "lifelog", owner, collector)
    seen_event_ids: set[str] = set()
    policies = config.protocol["difficulties"]
    families: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for log in records:
        log_id = str(log.get("lifelog_id", "lifelog:unknown"))
        families[str(log.get("family_id"))].append(log)
        if log.get("seed_id") not in seeds:
            collector.add("BLOCKER", "lifelog_seed_missing", log_id, "seed_id 指向已冻结 seed", repr(log.get("seed_id")), owner)
        elif log.get("split") != seeds[log["seed_id"]].get("split"):
            collector.add("BLOCKER", "lifelog_seed_split", log_id, f"split={seeds[log['seed_id']].get('split')}", repr(log.get("split")), owner)
        events = log.get("events", [])
        if log.get("event_count") != len(events):
            collector.add("BLOCKER", "lifelog_event_count", log_id, f"event_count={len(events)}", repr(log.get("event_count")), owner)
        positions = [event.get("event_position") for event in events]
        if positions != list(range(len(events))):
            collector.add("BLOCKER", "lifelog_positions", log_id, "event_position 从 0 连续递增", repr(positions[:10]), owner)
        times = [parse_virtual_time(event.get("virtual_time")) for event in events]
        if any(value is None for value in times) or any(later < earlier for earlier, later in zip(times, times[1:])):
            collector.add("BLOCKER", "lifelog_virtual_time", log_id, "虚拟时间可解析且不倒退", repr([event.get("virtual_time") for event in events[:5]]), owner)
        difficulty = log.get("difficulty")
        policy = policies.get(difficulty, {})
        event_range = policy.get("event_count", [0, 0])
        if isinstance(event_range, list) and len(event_range) == 2 and not event_range[0] <= len(events) <= event_range[1]:
            collector.add("BLOCKER", "difficulty_event_count", log_id, f"{difficulty} 事件数在 {event_range}", str(len(events)), owner)
        if times and all(value is not None for value in times):
            span_minutes = (times[-1] - times[0]) / 60
            span_range = policy.get("virtual_span_minutes", [0, float("inf")])
            if not span_range[0] <= span_minutes <= span_range[1]:
                collector.add("BLOCKER", "difficulty_virtual_span", log_id, f"{difficulty} 虚拟跨度在 {span_range} 分钟", f"{span_minutes:.3f}", owner)
        # 背景或桥接事件可不声明状态；一旦声明就必须承接上一个状态，防止终态被悄然重新激活。
        carried_state: str | None = None
        source_seconds = 0.0
        source_session_last_start: dict[str, float] = {}
        for event in events:
            event_id = str(event.get("event_id", f"{log_id}:event"))
            if event_id in seen_event_ids:
                collector.add("BLOCKER", "duplicate_event_id", event_id, "event_id 在全部 life log 中唯一", "发现重复", owner)
            seen_event_ids.add(event_id)
            before, after = event.get("intention_state_before"), event.get("intention_state_after")
            if before is not None and carried_state is not None and before != carried_state:
                collector.add("BLOCKER", "state_chain", event_id, f"state_before={carried_state}", repr(before), owner)
            if before in STATE_TRANSITIONS and after not in STATE_TRANSITIONS[before]:
                collector.add("BLOCKER", "state_transition", event_id, f"{before} 的合法后继状态", repr(after), owner)
            if after is not None:
                carried_state = after
            kind = event.get("event_kind")
            if kind in {"constructed_intention", "constructed_observation"} and not isinstance(event.get("rule_id"), str):
                collector.add("BLOCKER", "constructed_rule_id", event_id, "构造事件含 rule_id", repr(event.get("rule_id")), owner)
            if kind == "source_video_atom":
                atom = atoms.get(event.get("atom_id"))
                if atom is None:
                    collector.add("BLOCKER", "lifelog_atom_missing", event_id, "atom_id 指向已验证 source atom", repr(event.get("atom_id")), owner)
                    continue
                if atom.get("split") != log.get("split"):
                    collector.add("BLOCKER", "lifelog_atom_split", event_id, f"atom split={log.get('split')}", repr(atom.get("split")), owner)
                for field_name in ("visible_text", "source_srt_paths", "source_video_path"):
                    if event.get(field_name) != atom.get(field_name):
                        collector.add("BLOCKER", "lifelog_source_trace", event_id, f"{field_name} 与 atom 完全一致", repr(event.get(field_name)), owner)
                source_time = event.get("source_time")
                if not isinstance(source_time, dict):
                    collector.add("BLOCKER", "lifelog_source_time", event_id, "source atom 具有 source_time", repr(source_time), owner)
                else:
                    expected_time = {
                        "local_start_sec": atom.get("local_start_sec"),
                        "local_end_sec": atom.get("local_end_sec"),
                        "normalized_start_sec": atom.get("normalized_start_sec"),
                        "normalized_end_sec": atom.get("normalized_end_sec"),
                    }
                    if source_time != expected_time:
                        collector.add("BLOCKER", "lifelog_source_time", event_id, "source_time 与 atom 完全一致", repr(source_time), owner)
                start = atom.get("normalized_start_sec")
                session = str(atom.get("session_id"))
                # 虚拟时间可重排不同来源，但同一 session 内 atom 不能倒放，否则会伪造 SRT 顺序。
                if isinstance(start, (int, float)) and session in source_session_last_start and start < source_session_last_start[session]:
                    collector.add("BLOCKER", "lifelog_source_order", event_id, "同一 session 的 source atom 不倒序", f"{start} < {source_session_last_start[session]}", owner)
                if isinstance(start, (int, float)):
                    source_session_last_start[session] = float(start)
                source_seconds += source_event_duration(event)
            video_path = event.get("source_video_path")
            if isinstance(video_path, str):
                resolved_video = resolve_source_path(video_path, config)
                if event.get("video_mapping_status") != "verified" or not resolved_video.is_file():
                    collector.add("BLOCKER", "fabricated_video_path", event_id, "仅 verified 且存在的 MP4 路径可出现；否则为 null", repr(video_path), owner)
        if abs(float(log.get("referenced_source_seconds", 0)) - source_seconds) > 0.001:
            collector.add("BLOCKER", "lifelog_referenced_seconds", log_id, f"{source_seconds:.3f}", repr(log.get("referenced_source_seconds")), owner)
    expected_variants = {(branch, difficulty) for branch in ("positive", "negative") for difficulty in policies}
    for family_id, logs in families.items():
        variants = {(log.get("counterfactual_branch"), log.get("difficulty")) for log in logs}
        if variants != expected_variants or len(logs) != 6:
            collector.add("BLOCKER", "family_six_variants", family_id, f"恰好具有 {sorted(expected_variants)}", repr(sorted(variants)), owner)
            continue
        seed_ids = {log.get("seed_id") for log in logs}
        splits = {log.get("split") for log in logs}
        if len(seed_ids) != 1 or len(splits) != 1:
            collector.add("BLOCKER", "family_integrity", family_id, "同 family 的 seed/split 一致", f"seeds={seed_ids}, splits={splits}", owner)
        trigger_atoms: set[Any] = set()
        metrics: dict[str, tuple[int, float]] = {}
        for log in logs:
            triggers = [event.get("atom_id") for event in log.get("events", []) if event.get("event_role") == "trigger"]
            if len(triggers) != 1 or not isinstance(triggers[0], str):
                collector.add("BLOCKER", "family_trigger", str(log.get("lifelog_id")), "每条 log 恰有一个 source trigger", repr(triggers), owner)
                continue
            trigger_atoms.add(triggers[0])
            parsed = [parse_virtual_time(event.get("virtual_time")) for event in log["events"]]
            metrics[str(log.get("lifelog_id"))] = (
                len(log["events"]),
                float(parsed[-1] - parsed[0]) if all(value is not None for value in parsed) else -1.0,
            )
        if len(trigger_atoms) != 1:
            collector.add("BLOCKER", "family_trigger_consistency", family_id, "六条 family log 使用同一 trigger atom", repr(sorted(str(value) for value in trigger_atoms)), owner)
        for branch in ("positive", "negative"):
            branch_logs = {log["difficulty"]: log for log in logs if log["counterfactual_branch"] == branch}
            if len(branch_logs) == 3:
                short = metrics.get(str(branch_logs["short"]["lifelog_id"]))
                medium = metrics.get(str(branch_logs["medium"]["lifelog_id"]))
                long = metrics.get(str(branch_logs["long"]["lifelog_id"]))
                if short and medium and long and not (short[0] < medium[0] < long[0] and short[1] < medium[1] < long[1]):
                    collector.add("BLOCKER", "difficulty_monotonicity", family_id, "short < medium < long 的事件数和虚拟跨度", f"{short}, {medium}, {long}", owner)


def expected_oracle_kind(decision: dict[str, Any]) -> str:
    # 直接重算冻结协议，而非相信生产者写入的 gold，防止 LLM 或人工标签替代确定性 oracle。
    annotation = decision.get("oracle_annotation", {})
    current_time = parse_virtual_time(decision.get("model_input", {}).get("virtual_time"))
    window = decision.get("valid_window", {})
    start = parse_virtual_time(window.get("start_virtual_time"))
    end = parse_virtual_time(window.get("end_virtual_time"))
    active_trigger = decision.get("decision_type") == "trigger" and annotation.get("state_before") == "active_unreminded"
    inside_window = current_time is not None and start is not None and end is not None and start <= current_time <= end
    return "remind" if active_trigger and inside_window else "silent"


def validate_decisions(
    records: list[dict[str, Any]], lifelogs: dict[str, dict[str, Any]], collector: IssueCollector
) -> None:
    owner = "T3 compiler"
    validate_unique(records, "decision_id", "decisions", owner, collector)
    for decision in records:
        decision_id = str(decision.get("decision_id", "decision:unknown"))
        log = lifelogs.get(decision.get("lifelog_id"))
        if log is None:
            collector.add("BLOCKER", "decision_lifelog_missing", decision_id, "lifelog_id 指向已验证 life log", repr(decision.get("lifelog_id")), owner)
            continue
        for field_name in ("family_id", "split", "difficulty"):
            if decision.get(field_name) != log.get(field_name):
                collector.add("BLOCKER", "decision_lifelog_consistency", decision_id, f"{field_name}={log.get(field_name)}", repr(decision.get(field_name)), owner)
        model_input = decision.get("model_input", {})
        event_map = {event.get("event_id"): event for event in log.get("events", [])}
        event = event_map.get(model_input.get("current_event_id"))
        if event is None:
            collector.add("BLOCKER", "decision_current_event", decision_id, "current_event_id 出现在对应 life log", repr(model_input.get("current_event_id")), owner)
        else:
            for input_field, event_field in (("stream_position", "event_position"), ("virtual_time", "virtual_time"), ("visible_text", "visible_text")):
                if model_input.get(input_field) != event.get(event_field):
                    collector.add("BLOCKER", "decision_observation_trace", decision_id, f"{input_field} 与当前事件一致", repr(model_input.get(input_field)), owner)
        # 决策模型只能看当前可见文本。内部字段、规则 ID 和状态进入文本会直接泄露答案。
        visible = str(model_input.get("visible_text", "")).casefold()
        leaked = [marker for marker in FORBIDDEN_INPUT_MARKERS if marker in visible]
        if leaked or re.search(r"\b(?:int|rule)_[A-Za-z0-9_]+\b", str(model_input.get("visible_text", ""))):
            collector.add("BLOCKER", "answer_leakage", decision_id, "模型输入不含 gold、状态、role、rule 或内部 ID", repr(leaked or "内部 ID"), owner)
        expected_kind = expected_oracle_kind(decision)
        gold = decision.get("gold_action", {})
        if gold.get("kind") != expected_kind:
            collector.add("BLOCKER", "oracle_action", decision_id, f"gold_action.kind={expected_kind}", repr(gold.get("kind")), owner)
        expected_ids = [decision.get("target_intention_id")] if expected_kind == "remind" else []
        if gold.get("intention_ids") != expected_ids:
            collector.add("BLOCKER", "oracle_intention_ids", decision_id, f"intention_ids={expected_ids}", repr(gold.get("intention_ids")), owner)
        annotation = decision.get("oracle_annotation", {})
        if expected_kind == "remind" and annotation.get("state_after") != "active_reminded":
            collector.add("BLOCKER", "oracle_state_transition", decision_id, "remind 后 state_after=active_reminded", repr(annotation.get("state_after")), owner)
        for group in decision.get("evidence_support_groups", []):
            for item in group.get("items", []):
                if item.get("event_id") not in event_map:
                    collector.add("BLOCKER", "evidence_event_missing", decision_id, "证据 event_id 位于同一 life log", repr(item.get("event_id")), owner)


def validate_counterfactual_pairs(records: list[dict[str, Any]], lifelogs: dict[str, dict[str, Any]], collector: IssueCollector) -> None:
    owner = "T3 compiler"
    pairs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for decision in records:
        pairs[str(decision.get("counterfactual_pair_id"))].append(decision)
    for pair_id, pair in pairs.items():
        # 反事实必须在相同当前 trigger 上仅凭历史状态翻转；先固定当前观察，
        # 再检查正负动作，避免通过删除当前 cue 制造“负例”。
        if len(pair) != 2:
            collector.add("BLOCKER", "counterfactual_pair_cardinality", pair_id, "每个 pair 恰有正负两个 decision", f"{len(pair)} 条", owner)
            continue
        left, right = pair
        left_log, right_log = lifelogs.get(left.get("lifelog_id")), lifelogs.get(right.get("lifelog_id"))
        if left_log is None or right_log is None:
            continue
        if {left_log.get("counterfactual_branch"), right_log.get("counterfactual_branch")} != {"positive", "negative"}:
            collector.add("BLOCKER", "counterfactual_branches", pair_id, "一条 positive 与一条 negative", repr([left_log.get("counterfactual_branch"), right_log.get("counterfactual_branch")]), owner)
        for field_name in ("family_id", "difficulty", "split", "target_intention_id"):
            if left.get(field_name) != right.get(field_name):
                collector.add("BLOCKER", "counterfactual_pair_consistency", pair_id, f"两个 decision 的 {field_name} 相同", f"{left.get(field_name)!r}/{right.get(field_name)!r}", owner)
        def current_atom(decision: dict[str, Any], log: dict[str, Any]) -> Any:
            event_id = decision.get("model_input", {}).get("current_event_id")
            return next((event.get("atom_id") for event in log.get("events", []) if event.get("event_id") == event_id), None)
        if current_atom(left, left_log) != current_atom(right, right_log) or current_atom(left, left_log) is None:
            collector.add("BLOCKER", "counterfactual_trigger_match", pair_id, "正负分支当前 trigger atom 完全相同", f"{current_atom(left, left_log)!r}/{current_atom(right, right_log)!r}", owner)
        if left.get("model_input", {}).get("visible_text") != right.get("model_input", {}).get("visible_text"):
            collector.add("BLOCKER", "counterfactual_current_leakage", pair_id, "正负分支当前可见文本相同", "当前文本不同", owner)
        positive = left if left_log.get("counterfactual_branch") == "positive" else right
        negative = right if positive is left else left
        if positive.get("gold_action", {}).get("kind") != "remind" or negative.get("gold_action", {}).get("kind") != "silent":
            collector.add("BLOCKER", "counterfactual_gold_flip", pair_id, "positive=remind 且 negative=silent", f"{positive.get('gold_action')!r}/{negative.get('gold_action')!r}", owner)


def counterfactual_delta_contract_issue(config: RunConfig, collector: IssueCollector) -> None:
    """冻结合同没有为“声明的历史差异”定义可哈希、可验证的结构。"""
    pair_path = config.artifact("counterfactual_pairs")
    collector.add(
        "WARNING",
        "contract_counterfactual_delta_unverifiable",
        "counterfactual_pairs",
        "冻结且有哈希的 pair manifest，逐对声明唯一历史差异与两侧 log ID",
        f"v1.1.0 未定义该文件 schema/SUCCESS 哈希；T4 不能安全读取 {pair_path.name}",
        "T0 contract CHANGE_REQUEST",
    )


def write_audit_outputs(config: RunConfig, collector: IssueCollector, all_ready: bool) -> None:
    error_path = config.artifact("validation_errors")
    error_text = "".join(json.dumps(issue, ensure_ascii=False, sort_keys=True) + "\n" for issue in collector.issues)
    atomic_write_text(error_path, error_text)
    leakage = {
        "contract_version": CONTRACT_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(),
        "blocker_count": len(collector.blockers),
        "answer_leakage_count": sum(issue["issue_type"] == "answer_leakage" for issue in collector.issues),
        "split_leakage_count": sum(issue["issue_type"].startswith("split_") for issue in collector.issues),
        "issues_by_type": dict(sorted(Counter(issue["issue_type"] for issue in collector.issues).items())),
    }
    leakage_path = config.artifact("leakage_report")
    atomic_write_text(leakage_path, json.dumps(leakage, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    final_marker = config.marker("final_validation")
    if all_ready and not collector.blockers:
        upstream_hashes = {
            stage: json.loads(config.marker(marker_key).read_text(encoding="utf-8"))["sha256"]
            for stage, marker_key, _, _, _ in STAGES
        }
        marker = {
            "artifact_path": config.canonical_artifact_name(error_path),
            "sha256": sha256_file(error_path),
            "row_count": jsonl_row_count(error_path),
            "contract_version": CONTRACT_VERSION,
            "config_version": CONTRACT_VERSION,
            "schema_versions": {"audit": CONTRACT_VERSION},
            "generated_at": datetime.now().astimezone().isoformat(),
            "upstream_hashes": upstream_hashes,
        }
        atomic_write_text(final_marker, json.dumps(marker, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    elif final_marker.exists():
        # 这是 T4 自己的成功标记；新的阻断错误出现时不能保留过期的通过结论，
        # 否则下游会把已经失效的“通过”当作仍可发布的依据。
        final_marker.unlink()


def run_validation(config_path: Path, write: bool = True) -> tuple[IssueCollector, dict[str, list[dict[str, Any]]], dict[str, bool]]:
    config = load_run_config(config_path)
    collector = IssueCollector()
    data: dict[str, list[dict[str, Any]]] = {}
    readiness: dict[str, bool] = {}
    for stage, marker_key, artifact_key, schema_name, owner in STAGES:
        dependencies = STAGE_DEPENDENCIES[stage]
        if not all(readiness.get(dependency, False) for dependency in dependencies):
            collector.add("BLOCKER", "upstream_stage_unavailable", stage, f"上游阶段 {list(dependencies)} 的 SUCCESS/哈希均通过", "上游标记或哈希未通过", owner)
            readiness[stage] = False
            continue
        # 每一阶段独立守住 SUCCESS/哈希边界；依赖未冻结时只记录门禁问题，绝不窥读下游 JSONL。
        ready = marker_is_valid(config, stage, marker_key, artifact_key, owner, collector)
        readiness[stage] = ready
        if not ready:
            continue
        marker_value = load_json(config.marker(marker_key), collector, "success_marker", owner)
        if stage == "cue" and marker_value and marker_value.get("artifact_type") == "cue_library_manifest":
            records = read_formal_cue_records(config, collector, owner)
        else:
            records = read_jsonl(config.artifact(artifact_key), collector, stage, owner)
        validate_schema(records, config.config_dir.parent / "schemas" / schema_name, stage, owner, collector)
        data[stage] = records
    if readiness.get("source"):
        validate_source(data.get("source", []), config, collector)
    atoms = {record.get("atom_id"): record for record in data.get("source", []) if isinstance(record.get("atom_id"), str)}
    if readiness.get("cue") and readiness.get("source"):
        validate_cues(data.get("cue", []), atoms, collector)
        cue_marker = load_json(config.marker("cue_library"), collector, "success_marker", "T2 cue")
        if cue_marker and cue_marker.get("artifact_type") == "cue_library_manifest":
            validate_formal_cue_snapshot(config, cue_marker, data.get("source", []), data.get("cue", []), collector, "T4 cue")
    if readiness.get("candidate") and readiness.get("source"):
        validate_seeds(data.get("candidate", []), atoms, False, collector)
    if readiness.get("frozen") and readiness.get("source"):
        validate_seeds(data.get("frozen", []), atoms, True, collector)
    frozen = {record.get("seed_id"): record for record in data.get("frozen", []) if isinstance(record.get("seed_id"), str)}
    if readiness.get("lifelog") and readiness.get("source") and readiness.get("frozen"):
        validate_lifelogs(data.get("lifelog", []), atoms, frozen, config, collector)
    lifelogs = {record.get("lifelog_id"): record for record in data.get("lifelog", []) if isinstance(record.get("lifelog_id"), str)}
    if readiness.get("decisions") and readiness.get("lifelog"):
        validate_decisions(data.get("decisions", []), lifelogs, collector)
        validate_counterfactual_pairs(data.get("decisions", []), lifelogs, collector)
        counterfactual_delta_contract_issue(config, collector)
    all_ready = all(readiness.get(stage[0], False) for stage in STAGES)
    if write:
        write_audit_outputs(config, collector, all_ready)
    return collector, data, readiness


def main() -> int:
    parser = argparse.ArgumentParser(description="EgoPM-Bench v1 全量独立 QA")
    parser.add_argument("--config", type=Path, required=True, help="benchmark_protocol.yaml 的路径")
    parser.add_argument("--no-write", action="store_true", help="仅检查，不写 audit 输出")
    args = parser.parse_args()
    try:
        collector, _, readiness = run_validation(args.config, write=not args.no_write)
    except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
        print(f"验证器启动失败：{exc}", file=sys.stderr)
        return 2
    print(json.dumps({"readiness": readiness, "blocker_count": len(collector.blockers), "issue_count": len(collector.issues)}, ensure_ascii=False))
    return 1 if collector.blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
