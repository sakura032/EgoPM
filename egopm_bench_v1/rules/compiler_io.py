"""T3 编译脚本共享的受门禁 I/O 工具。

职责：读取冻结配置、JSON/JSONL/CSV 与 SUCCESS 标记，验证哈希和 Schema，并以原子
方式写入编译工件及其最终标记。输入是阶段 08–10 声明的上游文件；输出是经过哈希
保护的下游文件或明确的 ``GateError``。本模块位于流水线的基础设施层，不生成任何
业务 gold，也不替代 T4 验证。
"""

from __future__ import annotations

from datetime import datetime, timezone
import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

import jsonschema
import yaml


class GateError(RuntimeError):
    """正式产物的上游 SUCCESS、哈希或协议门禁不满足。"""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # 将底层路径和解析异常统一为门禁错误，调用脚本才能停止在不可信输入边界，
        # 而不是把空值或部分内容继续传给编译器。
        raise GateError(f"无法读取 JSON：{path}") from exc
    if not isinstance(value, dict):
        raise GateError(f"JSON 根节点必须为对象：{path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        # 正式运行不允许以“没有输入”等价为空数据；这会错误地产出空 SUCCESS。
        raise GateError(f"无法读取 JSONL：{path}") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            # 精确报告行号，方便生产者修复单行 JSONL，而不是悄悄跳过损坏样本。
            raise GateError(f"{path}:{line_number} 不是合法 JSON") from exc
        if not isinstance(row, dict):
            raise GateError(f"{path}:{line_number} 的 JSONL 行必须为对象")
        rows.append(row)
    return rows


def load_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError as exc:
        raise GateError(f"无法读取 CSV：{path}") from exc


def atomic_write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    row_count = 0
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True))
            handle.write("\n")
            row_count += 1
        handle.flush()
        os.fsync(handle.fileno())
    # 先落盘到同目录临时文件再 replace，读者要么看到旧的完整版本，要么看到新的
    # 完整版本，绝不会在生成期间读到截断 JSONL。
    os.replace(temporary, path)
    return row_count


def atomic_write_yaml(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        yaml.safe_dump(dict(value), handle, allow_unicode=True, sort_keys=False)
        handle.flush()
        os.fsync(handle.fileno())
    # 策略文件也必须与数据工件享有相同原子边界，否则规则和 Seed 可能短暂失配。
    os.replace(temporary, path)


def load_config(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        # 配置解析失败必须阻断生产，因为猜测路径或参数会改变合同规定的结果。
        raise GateError(f"无法读取配置：{path}") from exc
    if not isinstance(value, dict):
        raise GateError(f"配置根节点必须为对象：{path}")
    return value


def resolve_config_path(config_path: Path, configured_path: str) -> Path:
    return (config_path.parent / configured_path).resolve()


def benchmark_root(config_path: Path, paths_config: Mapping[str, Any]) -> Path:
    root_value = paths_config.get("benchmark_root")
    if not isinstance(root_value, str):
        raise GateError("paths.yaml 缺少 benchmark_root")
    return resolve_config_path(config_path, root_value)


def relative_artifact_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def require_success_marker(marker_path: Path, artifact_path: Path) -> dict[str, Any]:
    """确认成功标记的必填字段、哈希和 JSONL 行数均与现存工件匹配。"""

    marker = load_json(marker_path)
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
        raise GateError(f"SUCCESS 标记缺少字段 {missing}：{marker_path}")
    if not artifact_path.is_file():
        raise GateError(f"SUCCESS 标记对应产物不存在：{artifact_path}")
    actual_hash = sha256_file(artifact_path)
    # SUCCESS 文件本身不是可信输入；必须重算对应工件哈希，防止标记滞后或文件被替换。
    if marker["sha256"] != actual_hash:
        raise GateError(f"SUCCESS 哈希不匹配：{artifact_path}")
    if isinstance(marker["row_count"], bool) or not isinstance(marker["row_count"], int):
        raise GateError(f"SUCCESS 的 row_count 不合法：{marker_path}")
    if artifact_path.suffix == ".jsonl" and marker["row_count"] != len(load_jsonl(artifact_path)):
        # 哈希之外再核对逻辑行数，能更早发现错误拼接、空行处理差异和错误标记对象。
        raise GateError(f"SUCCESS 行数不匹配：{artifact_path}")
    return marker


def write_success_marker(
    *,
    marker_path: Path,
    artifact_path: Path,
    row_count: int,
    contract_version: str,
    config_version: str,
    schema_versions: Mapping[str, str],
    upstream_hashes: Mapping[str, str],
    root: Path,
    additional_artifacts: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    marker: dict[str, Any] = {
        "artifact_path": relative_artifact_path(artifact_path, root),
        "sha256": sha256_file(artifact_path),
        "row_count": row_count,
        "contract_version": contract_version,
        "config_version": config_version,
        "schema_versions": dict(schema_versions),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "upstream_hashes": dict(upstream_hashes),
    }
    if additional_artifacts:
        # 主标记还携带伴生产物的哈希，确保下游不会把同一批 decisions 与另一批
        # evidence 或 pair 文件混用。
        marker["artifacts"] = {
            name: {
                "artifact_path": relative_artifact_path(path, root),
                "sha256": sha256_file(path),
                "row_count": len(load_jsonl(path)) if path.suffix == ".jsonl" else None,
            }
            for name, path in additional_artifacts.items()
        }
    path = marker_path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(marker, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    # SUCCESS 必须最后原子出现；在此之前，任何下游读取都应把本次输出视为未完成。
    os.replace(temporary, path)
    return marker


def schema_validator(schema_path: Path) -> jsonschema.Draft202012Validator:
    schema = load_json(schema_path)
    try:
        return jsonschema.Draft202012Validator(schema)
    except jsonschema.SchemaError as exc:
        # Schema 自身不可编译时继续运行没有可解释的合同语义，故转为门禁错误。
        raise GateError(f"Schema 无法编译：{schema_path}") from exc


def validate_rows(
    rows: Iterable[Mapping[str, Any]],
    validator: jsonschema.Draft202012Validator,
    label: str,
) -> None:
    for index, row in enumerate(rows, start=1):
        errors = sorted(validator.iter_errors(row), key=lambda item: list(item.path))
        if errors:
            # 只报告首个稳定排序后的错误以保持日志可复现，同时阻止非法行进入产物。
            raise GateError(f"{label} 第 {index} 行不符合 Schema：{errors[0].message}")


def require_protocol_parameters_frozen(protocol: Mapping[str, Any]) -> None:
    """阻止在数值参数仍待定时生成任何正式的 family/oracle 工件。"""

    status = protocol.get("parameterization_status")
    memory = protocol.get("memory")
    policy = protocol.get("reminder_policy")
    if (
        not isinstance(status, str)
        or status.startswith("pending")
        or not isinstance(memory, Mapping)
        or memory.get("final_budget_tokens") is None
        or not isinstance(policy, Mapping)
        or policy.get("cooldown_seconds") is None
        or policy.get("maximum_reminders_per_intention") is None
    ):
        # 预算、冷却和次数上限会改变决策可见历史及提醒语义；参数待定时生成的日志或
        # gold 无法作为正式基准复现，所以必须在写出任何正式结果前失败。
        raise GateError("协议数值参数尚未冻结，禁止生成正式 Life Log 或 oracle 输出")
