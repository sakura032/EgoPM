#!/usr/bin/env python3
"""第 06 阶段：用固定 BGE-M3 混合检索为正式 Cue 选择同 split lure。

职责是读取已通过 Cue manifest/SUCCESS 的正式 Cue 分片和冻结 Source Atom，使用固定
`BAAI/bge-m3` revision、稠密+稀疏各前 64 及确定性 RRF 生成检索集合。输入为 Source
SUCCESS、Cue manifest/SUCCESS、检索配置和本地 BGE 权重；输出为带双通道 rank、RRF
分数、组别关系与失败 predicate 子句的临时 Seed 输入。它位于第 06 步，只读、不调用
千问；缺少固定权重或依赖时必须阻断，绝不退回 `lexical_jaccard_v1`。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_VERSION = "v1.1.0"
CONFIG_VERSION = "v1.1.0"
SOURCE_SCHEMA_VERSION = "v1.1.0"
CUE_SCHEMA_VERSION = "v1.1.0"
TRIGGER_LURE_SCHEMA_VERSION = "v1.1.0"
RETRIEVAL_METHOD = "bge_m3_hybrid_rrf_v1"
MODEL_ID = "BAAI/bge-m3"
MODEL_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
CHANNEL_TOP_K = 64
RRF_K = 60
MAX_INPUT_TOKENS = 512


class ContractError(RuntimeError):
    """输入、检索配置或输出违背冻结合同。"""


class EmbeddingBackend(Protocol):
    """BGE-M3 后端的最小接口，便于 synthetic 测试注入确定性假后端。"""

    def encode(self, texts: list[str]) -> tuple[list[list[float]], list[dict[str, float]]]: ...


def utc_now() -> str:
    """返回 UTC 时间，保证检索成功标记不受本地时区影响。"""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    """流式计算工件哈希，避免把 Source 或分片一次性复制到内存。"""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    """按固定 JSON 编码计算检索参数和派生缓存的绑定哈希。"""

    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    """读取一个 JSON 对象并将解析失败转换为合同错误。"""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractError(f"无法读取 JSON：{path}") from error
    if not isinstance(value, dict):
        raise ContractError(f"JSON 根节点必须是 object：{path}")
    return value


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    """逐行读取 JSONL，避免把冻结 Source 文本整体复制为多个列表。"""

    try:
        handle = path.open("r", encoding="utf-8")
    except OSError as error:
        raise ContractError(f"无法读取 JSONL：{path}") from error
    with handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ContractError(f"JSONL 不允许空行：{path}:{line_number}")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ContractError(f"JSONL 解析失败：{path}:{line_number}") from error
            if not isinstance(value, dict):
                raise ContractError(f"JSONL 行必须是 object：{path}:{line_number}")
            yield value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读取小型中间结果；正式 Cue 则通过 manifest 逐分片读取。"""

    return list(iter_jsonl(path))


def load_verified_marker(artifact: Path, marker_path: Path) -> dict[str, Any]:
    """验证 SUCCESS 的路径、哈希和行数，防止检索读取未冻结上游。"""

    if not artifact.is_file() or not marker_path.is_file():
        raise ContractError(f"缺少正式输入或 SUCCESS：{artifact}；{marker_path}")
    marker = read_json(marker_path)
    required = {"artifact_path", "sha256", "row_count", "contract_version", "config_version", "schema_versions", "upstream_hashes"}
    if required.difference(marker) or marker["contract_version"] != CONTRACT_VERSION or marker["config_version"] != CONFIG_VERSION:
        raise ContractError("上游 SUCCESS 字段或版本不兼容")
    declared = str(marker["artifact_path"]).replace("\\", "/")
    if Path(declared).is_absolute():
        declared_candidates = [Path(declared)]
    else:
        # 兼容旧标记的“相对 marker”与正式标记的“相对 benchmark 根目录”两种合同写法。
        declared_candidates = [marker_path.parent / declared, ROOT / declared]
    if not any(candidate.resolve() == artifact.resolve() for candidate in declared_candidates) or marker["sha256"] != sha256_file(artifact):
        raise ContractError("上游 SUCCESS 路径或 SHA256 不匹配")
    return marker


def load_cue_rows_from_manifest(manifest_path: Path, success_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """只从正式 Cue manifest 读取分片，禁止把 package 或便利缓存当作接口。"""

    marker = load_verified_marker(manifest_path, success_path)
    manifest = read_json(manifest_path)
    if manifest.get("artifact_type") != "cue_library_logical_snapshot" or manifest.get("shard_count") != 75:
        raise ContractError("Cue manifest 不是 75 个 task 的正式逻辑快照")
    rows: list[dict[str, Any]] = []
    shards = manifest.get("shards")
    if not isinstance(shards, list) or len(shards) != 75:
        raise ContractError("Cue manifest 分片数不是 75")
    for shard in shards:
        task_index = shard.get("task_index")
        path = (ROOT / str(shard.get("path"))).resolve()
        if not isinstance(task_index, int) or path.parent != (ROOT / "cues" / "formal").resolve() or path.name != f"task_{task_index:03d}.jsonl":
            raise ContractError("Cue manifest 分片路径越出正式 formal 目录")
        if not path.is_file() or sha256_file(path) != shard.get("sha256") or path.stat().st_size != shard.get("byte_count"):
            raise ContractError(f"Cue 分片缺失或哈希不匹配：{path}")
        part = read_jsonl(path)
        if len(part) != shard.get("row_count"):
            raise ContractError(f"Cue 分片行数不匹配：{path}")
        rows.extend(part)
    if len(rows) != marker.get("row_count") or len(rows) != manifest.get("cue_count"):
        raise ContractError("Cue manifest/SUCCESS 总行数不匹配")
    return rows, marker


def normalize_serialized_text(value: str) -> str:
    """执行合同规定的 NFKC 与空白折叠，但保留大小写和标点。"""

    return " ".join(unicodedata.normalize("NFKC", value).split()).strip()


def _nullable(value: Any) -> str:
    return "" if value is None else normalize_serialized_text(str(value))


def cue_query_text(cue: dict[str, Any]) -> str:
    """按冻结字段顺序序列化 query，不加入 participant、日期、组别或 split 捷径。"""

    entities = sorted(set(str(item) for item in cue.get("entities", [])))
    predicate = json.dumps(cue["normalized_predicate"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "\n".join((
        f"cue_type: {_nullable(cue.get('cue_type'))}",
        f"entities: {json.dumps(entities, ensure_ascii=False, separators=(',', ':'))}",
        f"scene_type: {_nullable(cue.get('scene_type'))}",
        f"activity_type: {_nullable(cue.get('activity_type'))}",
        f"normalized_predicate: {predicate}",
        f"supporting_text_span: {_nullable(cue.get('supporting_text_span'))}",
    ))


def atom_passage_text(atom: dict[str, Any]) -> str:
    """按冻结字段顺序序列化单一 Atom passage，不拼接跨 Atom 或捷径元数据。"""

    return f"transcript: {_nullable(atom.get('transcript'))}\ndense_caption: {_nullable(atom.get('dense_caption'))}"


def _sparse_dot(left: dict[str, float], right: dict[str, float]) -> float:
    """计算 BGE-M3 稀疏词项权重的精确内积。"""

    if len(left) > len(right):
        left, right = right, left
    return float(sum(float(weight) * float(right.get(token, 0.0)) for token, weight in left.items()))


def _l2_normalize(vector: list[float]) -> list[float]:
    """将 BGE 稠密输出转为 FP32 并 L2 归一化，保证内积就是余弦相似度。"""

    values = [float(item) for item in vector]
    norm = math.sqrt(sum(item * item for item in values))
    if norm == 0:
        raise ContractError("BGE-M3 返回零稠密向量")
    return [item / norm for item in values]


def _dense_dot(left: list[float], right: list[float]) -> float:
    """执行 CPU 精确 FP32 等价内积，不调用 ANN 或 reranker。"""

    if len(left) != len(right):
        raise ContractError("BGE-M3 稠密向量维度不一致")
    return float(sum(a * b for a, b in zip(left, right)))


class BGE_M3_Backend:
    """固定 revision 的本地 BGE-M3 稠密+稀疏编码器。"""

    def __init__(self, cache_dir: Path | None = None) -> None:
        try:
            from huggingface_hub import snapshot_download
            from FlagEmbedding import BGEM3FlagModel
        except ImportError as error:
            raise ContractError(
                "缺少 BGE-M3 正式检索依赖；需在项目 .venv 安装 FlagEmbedding、huggingface_hub，"
                f"并准备 {MODEL_ID}@{MODEL_REVISION} 权重；当前阶段不得退回 lexical_jaccard_v1"
            ) from error
        try:
            local_path = snapshot_download(repo_id=MODEL_ID, revision=MODEL_REVISION, cache_dir=str(cache_dir) if cache_dir else None, local_files_only=True)
            # 明确锁定 CPU，避免同一 revision 在不同设备上产生不可审计的检索漂移。
            self._model = BGEM3FlagModel(local_path, use_fp16=False, devices=["cpu"])
        except Exception as error:
            raise ContractError(
                f"缺少或无法加载固定 BGE-M3 权重：{MODEL_ID}@{MODEL_REVISION}；"
                "需要先下载该 revision，影响是第 06 步正式检索暂不能启动"
            ) from error

    def encode(self, texts: list[str]) -> tuple[list[list[float]], list[dict[str, float]]]:
        """以 CPU、FP32、512 token 上限获取 BGE-M3 两通道表示。"""

        result = self._model.encode(texts, batch_size=8, max_length=MAX_INPUT_TOKENS, return_dense=True, return_sparse=True, return_colbert_vecs=False)
        dense = result.get("dense_vecs") if isinstance(result, dict) else None
        sparse = result.get("lexical_weights") if isinstance(result, dict) else None
        if dense is None or sparse is None or len(dense) != len(texts) or len(sparse) != len(texts):
            raise ContractError("BGE-M3 两通道输出数量不匹配")
        return [[float(value) for value in row] for row in dense], [{str(k): float(v) for k, v in row.items()} for row in sparse]


def predicate_unsatisfied_indexes(cue: dict[str, Any], atom: dict[str, Any]) -> list[int]:
    """保守记录 lure 未满足的 predicate 子句，避免只保存自然语言理由。"""

    haystack = normalize_serialized_text(" ".join(str(atom.get(field) or "") for field in ("transcript", "dense_caption", "visible_text"))).casefold()
    failed: list[int] = []
    for index, clause in enumerate(cue["normalized_predicate"]["all_of"]):
        value = normalize_serialized_text(str(clause["value"])).casefold()
        present = bool(value) and value in haystack
        operator = clause["operator"]
        satisfied = present if operator in {"eq", "present", "starts", "ends", "contains"} else not present
        if not satisfied:
            failed.append(index)
    return failed


def build_lure_sets(*, atoms: list[dict[str, Any]], cues: list[dict[str, Any]], lures_per_trigger: int, run_id: str, backend: EmbeddingBackend, source_sha256: str, cue_manifest_sha256: str, retrieval_parameters_sha256: str | None = None) -> list[dict[str, Any]]:
    """编码每个 split 一次并以 BGE-M3 RRF 选出同组+跨组 lure。"""

    if lures_per_trigger < 2:
        raise ContractError("每个 trigger 至少需要两个 lure")
    by_id = {atom.get("atom_id"): atom for atom in atoms}
    if len(by_id) != len(atoms) or any(not isinstance(key, str) for key in by_id):
        raise ContractError("Source Atom 存在重复或无效 atom_id")
    parameter_hash = retrieval_parameters_sha256 or canonical_sha256({"method": RETRIEVAL_METHOD, "model_id": MODEL_ID, "model_revision": MODEL_REVISION, "channel_top_k": CHANNEL_TOP_K, "rrf_k": RRF_K, "use_fp16": False, "max_input_tokens": MAX_INPUT_TOKENS})
    indexes: dict[str, dict[str, Any]] = {}
    for split in sorted({atom["split"] for atom in atoms}):
        corpus = [atom for atom in atoms if atom["split"] == split]
        dense, sparse = backend.encode([atom_passage_text(atom) for atom in corpus])
        indexes[split] = {"atoms": corpus, "dense": [_l2_normalize(row) for row in dense], "sparse": sparse}
    rows: list[dict[str, Any]] = []
    for cue in cues:
        if cue.get("validation_status") != "accepted":
            continue
        trigger = by_id.get(cue.get("atom_id"))
        if trigger is None or cue.get("split") != trigger.get("split"):
            raise ContractError(f"Cue→Source 血缘不一致：{cue.get('cue_id')}")
        index = indexes[trigger["split"]]
        query_dense, query_sparse = backend.encode([cue_query_text(cue)])
        query_dense_norm = _l2_normalize(query_dense[0])
        dense_scored: list[tuple[float, str]] = []
        sparse_scored: list[tuple[float, str]] = []
        for atom, dense_vector, sparse_vector in zip(index["atoms"], index["dense"], index["sparse"]):
            if atom["atom_id"] != trigger["atom_id"]:
                dense_scored.append((_dense_dot(query_dense_norm, dense_vector), atom["atom_id"]))
                sparse_scored.append((_sparse_dot(query_sparse[0], sparse_vector), atom["atom_id"]))
        dense_scored.sort(key=lambda item: (-item[0], item[1]))
        sparse_scored.sort(key=lambda item: (-item[0], item[1]))
        dense_top = dense_scored[:CHANNEL_TOP_K]
        sparse_top = sparse_scored[:CHANNEL_TOP_K]
        dense_rank = {atom_id: (rank, score) for rank, (score, atom_id) in enumerate(dense_top, start=1)}
        sparse_rank = {atom_id: (rank, score) for rank, (score, atom_id) in enumerate(sparse_top, start=1)}
        ranked: list[tuple[float, str]] = []
        for atom_id in set(dense_rank) | set(sparse_rank):
            score = (1 / (RRF_K + dense_rank[atom_id][0]) if atom_id in dense_rank else 0) + (1 / (RRF_K + sparse_rank[atom_id][0]) if atom_id in sparse_rank else 0)
            ranked.append((float(score), atom_id))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        selected: list[dict[str, Any]] = []
        # 先分别锁定同组和跨组，防止排名靠前的一组耗尽名额后静默放宽合同。
        for require_different in (False, True):
            for score, atom_id in ranked:
                atom = by_id[atom_id]
                if (atom["source_group_id"] != trigger["source_group_id"]) != require_different or atom_id in {item["atom"]["atom_id"] for item in selected}:
                    continue
                failed = predicate_unsatisfied_indexes(cue, atom)
                if failed:
                    selected.append({"atom": atom, "score": score, "failed": failed})
                    break
        for score, atom_id in ranked:
            if len(selected) >= lures_per_trigger or atom_id in {item["atom"]["atom_id"] for item in selected}:
                continue
            atom = by_id[atom_id]
            failed = predicate_unsatisfied_indexes(cue, atom)
            if failed:
                selected.append({"atom": atom, "score": score, "failed": failed})
        if len(selected) < 2 or not any(item["atom"]["source_group_id"] == trigger["source_group_id"] for item in selected) or not any(item["atom"]["source_group_id"] != trigger["source_group_id"] for item in selected):
            continue
        selected = selected[:lures_per_trigger]
        lure_audit = []
        for item in selected:
            atom = item["atom"]
            atom_id = atom["atom_id"]
            lure_audit.append({"atom_id": atom_id, "source_group_id": atom["source_group_id"], "group_relation": "same_source_group" if atom["source_group_id"] == trigger["source_group_id"] else "different_source_group", "unsatisfied_predicate_clause_indexes": item["failed"], "rank_dense": dense_rank.get(atom_id, (None,))[0], "rank_sparse": sparse_rank.get(atom_id, (None,))[0], "rrf_score": round(item["score"], 12)})
        rows.append({"retrieval_id": f"retrieval_{cue['cue_id'].removeprefix('cue_')}", "cue_id": cue["cue_id"], "trigger_cue_id": cue["cue_id"], "trigger_atom_id": trigger["atom_id"], "split": trigger["split"], "source_group_id": trigger["source_group_id"], "lure_atom_ids": [item["atom"]["atom_id"] for item in selected], "lure_audit": lure_audit, "retrieval_method": RETRIEVAL_METHOD, "model_id": MODEL_ID, "model_revision": MODEL_REVISION, "channel_top_k": CHANNEL_TOP_K, "rrf_k": RRF_K, "query_serialization_version": "cue_query_v1", "passage_serialization_version": "atom_passage_v1", "retrieval_parameters_sha256": parameter_hash, "source_atoms_sha256": source_sha256, "cue_manifest_sha256": cue_manifest_sha256, "run_id": run_id, "schema_version": TRIGGER_LURE_SCHEMA_VERSION})
    return rows


def validate_retrieval_set_semantics(rows: list[dict[str, Any]]) -> None:
    """验证同组/跨组、rank/RRF 和失败子句的硬条件。"""

    seen: set[str] = set()
    for row in rows:
        if row["retrieval_method"] != RETRIEVAL_METHOD or row["retrieval_id"] in seen:
            raise ContractError("检索方法漂移或 retrieval_id 重复")
        seen.add(row["retrieval_id"])
        ids, audits = row["lure_atom_ids"], row["lure_audit"]
        if len(ids) < 2 or len(ids) != len(audits) or row["trigger_atom_id"] in ids or len(set(ids)) != len(ids):
            raise ContractError("lure 数量、唯一性或 trigger 排除不满足合同")
        if not any(item["group_relation"] == "same_source_group" for item in audits) or not any(item["group_relation"] == "different_source_group" for item in audits):
            raise ContractError("lure 必须同时包含同 source_group 与跨 source_group")
        if any(not item["unsatisfied_predicate_clause_indexes"] for item in audits) or [item["atom_id"] for item in audits] != ids:
            raise ContractError("每个 lure 必须记录失败子句且与 ID 顺序一致")


def write_jsonl_atomic(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """通过临时 JSONL 和原子替换写入检索结果。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    temporary.replace(path)


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    """通过临时 JSON 和原子替换写入成功标记。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_yaml(path: Path) -> dict[str, Any]:
    """读取检索配置并拒绝非对象根节点。"""

    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ContractError(f"无法读取 YAML：{path}") from error
    if not isinstance(value, dict):
        raise ContractError("检索配置根节点必须是 object")
    return value


def load_validator(path: Path) -> jsonschema.Draft202012Validator:
    """加载并检查 JSON Schema。"""

    schema = read_json(path)
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as error:
        raise ContractError(f"Schema 无效：{path}") from error
    return jsonschema.Draft202012Validator(schema)


def validate_rows(rows: list[dict[str, Any]], validator: jsonschema.Draft202012Validator, label: str) -> None:
    """逐行执行 Schema 门，失败时不写正式 JSONL。"""

    for index, row in enumerate(rows, start=1):
        error = next(iter(validator.iter_errors(row)), None)
        if error is not None:
            raise ContractError(f"{label} 第 {index} 行未通过 Schema：{error.message}")


def run(args: argparse.Namespace) -> int:
    """执行无千问检索；缺少 BGE 时在写任何正式输出前失败。"""

    source_marker = load_verified_marker(args.source_atoms, args.source_success)
    cue_rows, cue_marker = load_cue_rows_from_manifest(args.cue_manifest, args.cue_success)
    source_rows = read_jsonl(args.source_atoms)
    validate_rows(source_rows, load_validator(args.source_schema), "Source Atom")
    validate_rows(cue_rows, load_validator(args.cue_schema), "Cue")
    registry = read_yaml(args.model_registry)
    retrieval = registry.get("models", {}).get("seed_retrieval")
    if not isinstance(retrieval, dict) or retrieval.get("method") != RETRIEVAL_METHOD or retrieval.get("model_id") != MODEL_ID or retrieval.get("model_revision") != MODEL_REVISION or retrieval.get("use_fp16") is not False or retrieval.get("channel_top_k") != CHANNEL_TOP_K or retrieval.get("rrf_k") != RRF_K:
        raise ContractError("model_registry 未冻结为 bge_m3_hybrid_rrf_v1 的完整参数")
    run_id = args.run_id or f"run_retrieval_{uuid.uuid4().hex[:16]}"
    rows = build_lure_sets(atoms=source_rows, cues=cue_rows, lures_per_trigger=args.lures_per_trigger, run_id=run_id, backend=BGE_M3_Backend(args.cache_dir), source_sha256=source_marker["sha256"], cue_manifest_sha256=cue_marker["sha256"], retrieval_parameters_sha256=canonical_sha256(retrieval))
    validate_retrieval_set_semantics(rows)
    validate_rows(rows, load_validator(args.retrieval_schema), "trigger/lure 集")
    write_jsonl_atomic(args.output, rows)
    write_json_atomic(args.success_marker, {"artifact_path": str(args.output.resolve()), "sha256": sha256_file(args.output), "row_count": len(rows), "contract_version": CONTRACT_VERSION, "config_version": CONFIG_VERSION, "schema_versions": {"source_video_atom": SOURCE_SCHEMA_VERSION, "cue_candidate": CUE_SCHEMA_VERSION, "trigger_lure_set": TRIGGER_LURE_SCHEMA_VERSION}, "generated_at": utc_now(), "upstream_hashes": {"source_atoms": source_marker["sha256"], "cue_manifest": cue_marker["sha256"]}, "run_id": run_id, "retrieval_method": RETRIEVAL_METHOD, "model_id": MODEL_ID, "model_revision": MODEL_REVISION, "retrieval_parameters_sha256": canonical_sha256(retrieval), "validation_errors": []})
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """定义只读上游和正式 BGE 检索输出参数。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-atoms", type=Path, default=ROOT / "source/source_video_atoms.jsonl")
    parser.add_argument("--source-success", type=Path, default=ROOT / "source/SOURCE_ATOMS_SUCCESS.json")
    parser.add_argument("--cue-manifest", type=Path, help="旧 V9 输入已无默认值；阶段 D 将改为单个 Cue v2 run 输入")
    parser.add_argument("--cue-success", type=Path, help="旧 V9 输入已无默认值；阶段 D 将删除该参数")
    parser.add_argument("--source-schema", type=Path, default=ROOT / "schemas/source_video_atom.schema.json")
    parser.add_argument("--cue-schema", type=Path, default=ROOT / "schemas/cue_candidate.schema.json")
    parser.add_argument("--retrieval-schema", type=Path, default=ROOT / "schemas/trigger_lure_set.schema.json")
    parser.add_argument("--model-registry", type=Path, default=ROOT / "config/model_registry.yaml")
    parser.add_argument("--cache-dir", type=Path, default=None, help="只用于固定 BGE 权重的本地派生缓存")
    parser.add_argument("--output", type=Path, default=ROOT / "cues/trigger_lure_sets.jsonl")
    parser.add_argument("--success-marker", type=Path, default=ROOT / "cues/TRIGGER_LURES_SUCCESS.json")
    parser.add_argument("--lures-per-trigger", type=int, default=4)
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    if args.cue_manifest is None or args.cue_success is None:
        parser.error("当前阶段不允许默认读取 V9 Cue；请等待 Cue v2 下游接口切换")
    if args.lures_per_trigger < 2:
        parser.error("lures-per-trigger 至少为 2")
    return args


def main() -> int:
    """将 BGE 缺失或合同错误转换为稳定退出码。"""

    try:
        return run(parse_args())
    except ContractError as error:
        print(f"合同门禁失败：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
