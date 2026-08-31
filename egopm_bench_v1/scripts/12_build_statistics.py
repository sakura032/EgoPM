#!/usr/bin/env python3
"""在全量 QA 零阻断后生成 EgoPM-Bench v1 发布统计与数据集卡。

职责：把已通过 T4 验证的冻结产物汇总成可发布、可复现的规模与分布统计。
输入：`benchmark_protocol.yaml` 及由第 11 步确认完整的 source、cue、seed、lifelog、decision 数据。
输出：`audit/final_statistics.json` 和 `benchmark/dataset_card.md`。
流水线位置：第 12 步，紧随全量验证并在 T0 发布审阅之前；有任一阻断时不写输出。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve().with_name("11_validate_all.py")


def load_validator_module() -> Any:
    spec = importlib.util.spec_from_file_location("egopm_validate_all", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 11_validate_all.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def virtual_span_seconds(log: dict[str, Any], validator: Any) -> float:
    # 虚拟跨度衡量记忆间隔，不等同于引用视频时长；两者必须分开报告才不会夸大来源覆盖。
    values = [validator.parse_virtual_time(event.get("virtual_time")) for event in log.get("events", [])]
    if not values or any(value is None for value in values):
        return 0.0
    return float(values[-1] - values[0])


def counterfactual_flip_summary(decisions: list[dict[str, Any]], lifelogs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pairs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for decision in decisions:
        pairs[str(decision.get("counterfactual_pair_id"))].append(decision)
    eligible = 0
    flipped = 0
    for pair in pairs.values():
        # 只把结构完整的正负对计入分母，避免损坏 pair 伪造一个看似很高的翻转率。
        if len(pair) != 2:
            continue
        branches = {lifelogs.get(decision.get("lifelog_id"), {}).get("counterfactual_branch"): decision for decision in pair}
        if set(branches) != {"positive", "negative"}:
            continue
        eligible += 1
        if branches["positive"].get("gold_action", {}).get("kind") == "remind" and branches["negative"].get("gold_action", {}).get("kind") == "silent":
            flipped += 1
    return {
        "eligible_pairs": eligible,
        "flipped_pairs": flipped,
        "flip_rate": None if not eligible else flipped / eligible,
    }


def build_statistics(data: dict[str, list[dict[str, Any]]], validator: Any) -> dict[str, Any]:
    source = data["source"]
    cues = data["cue"]
    candidates = data["candidate"]
    frozen = data["frozen"]
    lifelogs = data["lifelog"]
    decisions = data["decisions"]
    atom_by_id = {atom["atom_id"]: atom for atom in source}
    used_atom_ids = {
        event["atom_id"]
        for log in lifelogs
        for event in log.get("events", [])
        if event.get("event_kind") == "source_video_atom" and isinstance(event.get("atom_id"), str)
    }
    # manifest 时长允许重复引用；unique 时长按 atom 去重，二者回答的是不同研究问题。
    unique_source_seconds = sum(
        float(atom_by_id[atom_id]["local_end_sec"]) - float(atom_by_id[atom_id]["local_start_sec"])
        for atom_id in used_atom_ids
        if atom_id in atom_by_id
    )
    lifelog_by_id = {log["lifelog_id"]: log for log in lifelogs}
    return {
        "contract_version": validator.CONTRACT_VERSION,
        "source_atom_count": len(source),
        "cue_count": len(cues),
        "cue_type_distribution": dict(sorted(Counter(cue["cue_type"] for cue in cues).items())),
        "candidate_seed_audit_distribution": dict(sorted(Counter(seed["audit"]["status"] for seed in candidates).items())),
        "frozen_seed_count": len(frozen),
        "lifelog_count": len(lifelogs),
        "decision_instance_count": len(decisions),
        "source_day_distribution": dict(sorted(Counter(atom["source_day"] for atom in source).items())),
        "participant_distribution": dict(sorted(Counter(atom["participant_source_id"] for atom in source).items())),
        "split_distribution": dict(sorted(Counter(log["split"] for log in lifelogs).items())),
        "difficulty_distribution": dict(sorted(Counter(log["difficulty"] for log in lifelogs).items())),
        "branch_distribution": dict(sorted(Counter(log["counterfactual_branch"] for log in lifelogs).items())),
        "negative_type_distribution": dict(sorted(Counter(seed["counterfactual_negative_type"] for seed in frozen).items())),
        "decision_type_distribution": dict(sorted(Counter(decision["decision_type"] for decision in decisions).items())),
        "srt_alignment": {
            "modality_coverage": dict(sorted(Counter(atom["modality_coverage"] for atom in source).items())),
            "video_mapping_status": dict(sorted(Counter(atom["video_mapping_status"] for atom in source).items())),
            "source_mapping_failure_count": sum(atom["video_mapping_status"] == "unavailable" for atom in source),
        },
        "durations_hours": {
            "manifest_referenced_hours": sum(float(log["referenced_source_seconds"]) for log in lifelogs) / 3600,
            "unique_source_hours": unique_source_seconds / 3600,
            "virtual_span_hours": sum(virtual_span_seconds(log, validator) for log in lifelogs) / 3600,
        },
        "counterfactual_action_flip": counterfactual_flip_summary(decisions, lifelog_by_id),
    }


def dataset_card_markdown(stats: dict[str, Any]) -> str:
    durations = stats["durations_hours"]
    return f"""# EgoPM-Bench v1 数据集卡

## 状态

本卡仅在独立 QA 零阻断后由 `scripts/12_build_statistics.py` 生成。合同版本为 `{stats['contract_version']}`。

## 规模

| 指标 | 数值 |
| --- | ---: |
| Source Atom | {stats['source_atom_count']} |
| Cue | {stats['cue_count']} |
| 冻结 Seed | {stats['frozen_seed_count']} |
| Life Log | {stats['lifelog_count']} |
| Decision Instance | {stats['decision_instance_count']} |

## 三种时长

| 指标 | 小时 | 含义 |
| --- | ---: | --- |
| manifest_referenced_hours | {durations['manifest_referenced_hours']:.6f} | 所有正式 Life Log 引用 atom 时长之和，重复引用会重复计入。 |
| unique_source_hours | {durations['unique_source_hours']:.6f} | 对 atom 去重后的真实来源时长。 |
| virtual_span_hours | {durations['virtual_span_hours']:.6f} | 所有虚拟时间轴的首尾跨度之和。 |

不得将 `manifest_referenced_hours` 表述为互不重复的新视频时长。

## 分布与质量

详细机器可读统计见 `audit/final_statistics.json`。其中记录 split、难度、反事实分支、Cue 类型、负例类型、SRT 对齐、视频映射状态和动作翻转率。gold 仅由冻结的确定性状态机产生，模型输入中不包含 `gold_action`、`event_role`、`rule_id` 或状态字段。
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="EgoPM-Bench v1 发布统计器")
    parser.add_argument("--config", type=Path, required=True, help="benchmark_protocol.yaml 的路径")
    args = parser.parse_args()
    validator = load_validator_module()
    try:
        collector, data, readiness = validator.run_validation(args.config, write=False)
    except Exception as exc:  # 向调用者报告配置或文件系统错误，不生成半成品统计。
        print(f"统计器启动失败：{exc}", file=sys.stderr)
        return 2
    # 不为未通过 QA 的半成品写统计或数据集卡，以免它们被误当成可发布基准的描述。
    if collector.blockers or not all(readiness.values()):
        print(json.dumps({"status": "blocked", "blocker_count": len(collector.blockers), "readiness": readiness}, ensure_ascii=False))
        return 1
    statistics = build_statistics(data, validator)
    config = validator.load_run_config(args.config)
    validator.atomic_write_text(
        config.artifact("final_statistics"),
        json.dumps(statistics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    card_path = config.artifact("decision_instances").parent / "dataset_card.md"
    validator.atomic_write_text(card_path, dataset_card_markdown(statistics))
    print(json.dumps({"status": "ok", "statistics": str(config.artifact("final_statistics"))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
