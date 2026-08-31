"""Source 流水线第 04 步：冻结来源连通分量与 split，并发布 Source SUCCESS 标记。

输入是第 03 步的草稿原子、报告、inventory、raw segments 与冻结 `split_policy.yaml`；
输出是最终 `source_video_atoms.jsonl`、`source_split_map.jsonl`、更新后的报告和
`SOURCE_ATOMS_SUCCESS.json`。只有全部文件经 Schema 校验、原子替换和哈希计算完成后，
本脚本才发布 SUCCESS，使下游能可靠地读取这一边界。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import jsonschema
import yaml


class _DisjointSet:
    def __init__(self, values: Iterable[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: str, right: str) -> bool:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return False
        # 固定根节点的字典序，使跨平台/跨进程的 component 标识稳定，而非依赖输入遍历顺序。
        if left_root > right_root:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        return True


def _load_paths(config_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Path]]:
    config_path = config_path.resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError(f"配置不是对象：{config_path}")
    split_policy_path = config_path.parent / "split_policy.yaml"
    split_policy = yaml.safe_load(split_policy_path.read_text(encoding="utf-8"))
    if not isinstance(split_policy, dict):
        raise ValueError(f"划分配置不是对象：{split_policy_path}")
    config_dir = config_path.parent

    def resolve(value: str) -> Path:
        candidate = Path(value)
        return candidate if candidate.is_absolute() else (config_dir / candidate).resolve()

    paths = {
        "inventory": resolve(str(config["artifacts"]["source_inventory"])),
        "raw_segments": resolve(str(config["artifacts"]["raw_srt_segments"])),
        "atoms": resolve(str(config["artifacts"]["source_atoms"])),
        "split_map": resolve(str(config["artifacts"]["source_split_map"])),
        "report": resolve(str(config["artifacts"]["source_report"])),
        "success_marker": resolve(str(config["success_markers"]["source_atoms"])),
        "schema": resolve(str(config["schema_dir"])) / "source_video_atom.schema.json",
    }
    return config, split_policy, paths


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _char_3grams(value: str) -> set[str]:
    normalized = _normalize_text(value)
    if not normalized:
        return set()
    if len(normalized) < 3:
        return {normalized}
    return {normalized[index : index + 3] for index in range(len(normalized) - 2)}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _session_adjacency_pairs(atoms: list[dict[str, Any]]) -> Iterable[tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    """仅在同 participant/day 的相邻 session 间比较近重复，控制全量比较规模。"""

    # 只有同一 participant/day 的相邻 session 可能代表连续来源；不做全局两两比较，
    # 既遵守 policy 的 comparison_scope，也避免无关人物因常见短语被误连通。
    by_person_day: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for atom in atoms:
        by_person_day[(atom["participant_source_id"], atom["source_day"])][atom["session_id"]].append(atom)
    for sessions in by_person_day.values():
        ordered_sessions = sorted(
            sessions.items(),
            key=lambda item: (
                min(float(atom["normalized_start_sec"]) for atom in item[1]),
                item[0],
            ),
        )
        for (_, left), (_, right) in zip(ordered_sessions, ordered_sessions[1:]):
            yield left, right


def _source_components(atoms: list[dict[str, Any]], split_policy: dict[str, Any]) -> tuple[dict[str, list[str]], int]:
    atom_ids = [atom["atom_id"] for atom in atoms]
    if len(atom_ids) != len(set(atom_ids)):
        raise ValueError("source_video_atoms.jsonl 存在重复 atom_id")
    disjoint_set = _DisjointSet(atom_ids)
    by_session: dict[str, list[str]] = defaultdict(list)
    by_world_event: dict[str, list[str]] = defaultdict(list)
    by_id = {atom["atom_id"]: atom for atom in atoms}
    for atom in atoms:
        by_session[atom["session_id"]].append(atom["atom_id"])
        if atom["world_event_id"] is not None:
            by_world_event[str(atom["world_event_id"])].append(atom["atom_id"])
    for members in [*by_session.values(), *by_world_event.values()]:
        # 同 session 或显式共享 world event 必须不可拆分，否则同一现实来源会泄漏到不同 split。
        for member in members[1:]:
            disjoint_set.union(members[0], member)

    duplicate_links = 0
    near_duplicate = split_policy["grouping"]["near_duplicate"]
    if near_duplicate["enabled"]:
        threshold = float(near_duplicate["similarity_threshold"])
        gram_cache = {atom_id: _char_3grams(atom["visible_text"]) for atom_id, atom in by_id.items()}
        for left_session, right_session in _session_adjacency_pairs(atoms):
            for left_atom in left_session:
                left_grams = gram_cache[left_atom["atom_id"]]
                for right_atom in right_session:
                    right_grams = gram_cache[right_atom["atom_id"]]
                    # Jaccard 不可能超过短集合与长集合的大小比，可避免大量无意义比较。
                    if not left_grams or not right_grams:
                        continue
                    if min(len(left_grams), len(right_grams)) / max(len(left_grams), len(right_grams)) < threshold:
                        continue
                    if _jaccard(left_grams, right_grams) >= threshold:
                        # 仅达到冻结阈值的近重复才合并，不能用模型或人工“感觉相似”替代确定性规则。
                        if disjoint_set.union(left_atom["atom_id"], right_atom["atom_id"]):
                            duplicate_links += 1

    components: dict[str, list[str]] = defaultdict(list)
    for atom_id in atom_ids:
        components[disjoint_set.find(atom_id)].append(atom_id)
    stable_components = {
        hashlib.sha256("|".join(sorted(members)).encode("utf-8")).hexdigest()[:16]: sorted(members)
        for members in components.values()
    }
    return stable_components, duplicate_links


def _assign_splits(
    components: dict[str, list[str]], split_policy: dict[str, Any]
) -> dict[str, str]:
    labels = list(split_policy["split_labels"])
    ratios = {label: float(split_policy["ratios"][label]) for label in labels}
    if not math.isclose(sum(ratios.values()), 1.0, abs_tol=1e-9):
        raise ValueError("split ratios 必须和为 1")
    total_atoms = sum(len(members) for members in components.values())
    targets = {label: total_atoms * ratios[label] for label in labels}
    component_ids = sorted(components)
    # 固定 seed 先打散 component，防止按文件名排序把早期来源系统性塞进 train，同时保证可复现。
    random.Random(int(split_policy["random_seed"])).shuffle(component_ids)
    assigned_counts = {label: 0 for label in labels}
    assignments: dict[str, str] = {}
    for component_id in component_ids:
        size = len(components[component_id])
        deficits = {label: targets[label] - assigned_counts[label] for label in labels}
        positive_deficit_labels = [label for label in labels if deficits[label] > 0]
        if positive_deficit_labels:
            # 按原子数而非 component 数补齐目标比例，避免大 session 使比例产生不必要的偏差。
            split = max(positive_deficit_labels, key=lambda label: (deficits[label], -labels.index(label)))
        else:
            split = min(
                labels,
                key=lambda label: (assigned_counts[label] / ratios[label] if ratios[label] else float("inf"), labels.index(label)),
            )
        assignments[component_id] = split
        assigned_counts[split] += size
    return assignments


def _replace_source_group_and_split(
    atoms: list[dict[str, Any]], components: dict[str, list[str]], assignments: dict[str, str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    atom_to_component = {
        atom_id: component_id
        for component_id, members in components.items()
        for atom_id in members
    }
    finalized_atoms: list[dict[str, Any]] = []
    split_map: list[dict[str, Any]] = []
    for atom in sorted(atoms, key=lambda item: item["atom_id"]):
        component_id = atom_to_component[atom["atom_id"]]
        finalized = dict(atom)
        finalized["source_group_id"] = f"group_{component_id}"
        finalized["split"] = assignments[component_id]
        finalized_atoms.append(finalized)
        split_map.append(
            {
                "atom_id": finalized["atom_id"],
                "source_group_id": finalized["source_group_id"],
                "split": finalized["split"],
                "participant_source_id": finalized["participant_source_id"],
                "source_day": finalized["source_day"],
                "session_id": finalized["session_id"],
                "world_event_id": finalized["world_event_id"],
            }
        )
    return finalized_atoms, split_map


def _validate_final_atoms(
    atoms: list[dict[str, Any]], components: dict[str, list[str]], assignments: dict[str, str], schema_path: Path
) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = [
        f"{atom['atom_id']}: {error.message}"
        for atom in atoms
        for error in validator.iter_errors(atom)
    ]
    if errors:
        # 在任何文件替换前阻断 Schema 失败，确保不会以无效正式原子覆盖上一份可读产物。
        raise ValueError("Source Atom Schema 验证失败：" + "; ".join(errors))
    for component_id, members in components.items():
        split_values = {next(atom["split"] for atom in atoms if atom["atom_id"] == member) for member in members}
        if split_values != {assignments[component_id]}:
            raise AssertionError(f"来源连通分量 {component_id} 跨 split")


def _write_jsonl_tmp(output_path: Path, records: Iterable[dict[str, Any]]) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(output_path.name + ".tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        # 先完整写入并同步临时文件；SUCCESS 出现前，其他工作流都不能读取这些正式路径。
        handle.flush()
        os.fsync(handle.fileno())
    return temporary_path


def _write_json_tmp(output_path: Path, payload: dict[str, Any]) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(output_path.name + ".tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return temporary_path


def _upstream_hashes(paths: dict[str, Path]) -> dict[str, str]:
    hashes = {
        name: _sha256(paths[name])
        for name in ("inventory", "raw_segments")
        if paths[name].exists()
    }
    hashes["source_video_atoms_draft"] = _sha256(paths["atoms"])
    return hashes


def run(config_path: Path) -> tuple[Path, Path, Path]:
    """生成 split map，重写最终 atoms，并最后才发布 SUCCESS 标记。"""

    config, split_policy, paths = _load_paths(config_path)
    draft_atoms = _read_jsonl(paths["atoms"])
    if not draft_atoms:
        raise ValueError("不允许为零个 Source Atom 发布 SUCCESS 标记")
    # split 只能从冻结 policy 推导；不允许按后续模型生成质量重新分配来源。
    components, duplicate_links = _source_components(draft_atoms, split_policy)
    assignments = _assign_splits(components, split_policy)
    finalized_atoms, split_map = _replace_source_group_and_split(draft_atoms, components, assignments)
    _validate_final_atoms(finalized_atoms, components, assignments, paths["schema"])

    report = json.loads(paths["report"].read_text(encoding="utf-8"))
    report["stage"] = "source_atoms_finalized"
    report["split_status"] = "frozen_pending_t4_source_qa"
    report["split_assignment"] = {
        "policy_version": split_policy["policy_version"],
        "random_seed": split_policy["random_seed"],
        "component_count": len(components),
        "near_duplicate_component_links": duplicate_links,
        "atom_counts": dict(sorted(Counter(atom["split"] for atom in finalized_atoms).items())),
    }
    upstream_hashes = _upstream_hashes(paths)

    # 三个产物先各自落到 .tmp，再依次替换；SUCCESS 最后写入，所以观察者不会接受半完成批次。
    atom_tmp = _write_jsonl_tmp(paths["atoms"], finalized_atoms)
    split_tmp = _write_jsonl_tmp(paths["split_map"], split_map)
    report_tmp = _write_json_tmp(paths["report"], report)
    os.replace(atom_tmp, paths["atoms"])
    os.replace(split_tmp, paths["split_map"])
    os.replace(report_tmp, paths["report"])

    # 对全部正式交付物计算哈希，使 T4 可同时验证数据内容、映射和报告没有在发布后漂移。
    artifact_hashes = {
        "source_inventory": _sha256(paths["inventory"]),
        "raw_srt_segments": _sha256(paths["raw_segments"]),
        "source_video_atoms": _sha256(paths["atoms"]),
        "source_split_map": _sha256(paths["split_map"]),
        "atom_build_report": _sha256(paths["report"]),
    }
    success_marker = {
        "artifact_path": "source/source_video_atoms.jsonl",
        "sha256": artifact_hashes["source_video_atoms"],
        "row_count": len(finalized_atoms),
        "contract_version": config["contract_version"],
        "config_version": config["config_version"],
        "schema_versions": {"source_video_atom": "v1.0.0"},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "upstream_hashes": upstream_hashes,
        "artifact_hashes": artifact_hashes,
    }
    # 这是整个 Source 阶段唯一的完成信号；必须位于所有原子替换和哈希计算之后。
    success_tmp = _write_json_tmp(paths["success_marker"], success_marker)
    os.replace(success_tmp, paths["success_marker"])
    return paths["atoms"], paths["split_map"], paths["success_marker"]


def main() -> None:
    parser = argparse.ArgumentParser(description="按冻结 split policy 划分 Source Video Atom")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "config" / "paths.yaml",
        help="冻结的 paths.yaml 路径",
    )
    arguments = parser.parse_args()
    run(arguments.config)


if __name__ == "__main__":
    main()
