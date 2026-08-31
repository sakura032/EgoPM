#!/usr/bin/env python3
"""第 05 阶段：以 v2 自适应 package 从冻结 Source Atom 提取 Cue。

输入是 Source SUCCESS、Atom、v2 配置、提示词和推理 Schema；默认预检只读地输出 package
与预算核算。只有显式执行时才会产生 package 工件；每包结果经程序回填后才成为最终 Cue。
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys, time, uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import jsonschema, yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_VERSION = CONFIG_VERSION = SOURCE_SCHEMA_VERSION = "v1.1.0"
CUE_SCHEMA_VERSION, MODEL, PROMPT_VERSION = "v1.0.0", "qwen3.7-flash-2026-07-15", "cue_extractor_v2"

class ContractError(RuntimeError): """冻结合同、输入、响应或恢复边界不一致。"""

@dataclass(frozen=True)
class Settings:
    endpoint:str; credential:str; shard_size:int; max_atoms:int; max_bytes:int; tokens_per_atom:int; retries:int; rpm:int; tpm:int
    layout:dict[str,str]; input_price:float; output_price:float; context_tokens:int
    execution:dict[str,Any]
    protocol_context:dict[str,Any]

def sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""):h.update(b)
    return h.hexdigest()
def stable(v:Any)->str:return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def now()->str:return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")
def read_json(path:Path)->dict[str,Any]:
    try:v=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as e:raise ContractError(f"无法读取 JSON：{path}") from e
    if not isinstance(v,dict):raise ContractError("JSON 根节点必须是 object")
    return v
def rows(path:Path)->list[dict[str,Any]]:
    try:lines=path.read_text(encoding="utf-8").splitlines()
    except OSError as e:raise ContractError(f"无法读取 JSONL：{path}") from e
    out=[]
    for n,line in enumerate(lines,1):
        try:v=json.loads(line)
        except json.JSONDecodeError as e:raise ContractError(f"JSONL 无效：{path}:{n}") from e
        if not line.strip() or not isinstance(v,dict):raise ContractError(f"JSONL 行无效：{path}:{n}")
        out.append(v)
    return out
def write_json(path:Path,v:Any)->None:
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(path.name+".tmp")
    with tmp.open("w",encoding="utf-8",newline="\n") as f:
        f.write(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+"\n");f.flush();os.fsync(f.fileno())
    tmp.replace(path)
def write_rows(path:Path,items:Iterable[dict[str,Any]])->None:
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(path.name+".tmp")
    with tmp.open("w",encoding="utf-8",newline="\n") as f:
        for x in items:f.write(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n")
        f.flush();os.fsync(f.fileno())
    tmp.replace(path)
def validator(path:Path)->jsonschema.Draft202012Validator:return jsonschema.Draft202012Validator(read_json(path))
def check(v:jsonschema.Draft202012Validator,x:dict[str,Any],label:str)->None:
    e=list(v.iter_errors(x))
    if e:raise ContractError(f"{label} 未通过 Schema：{e[0].message}")

def verified_source(artifact:Path,marker_path:Path)->dict[str,Any]:
    m=read_json(marker_path);decl=Path(str(m.get("artifact_path","")))
    if not artifact.is_file() or not marker_path.is_file() or decl.is_absolute() or ".." in decl.parts or (ROOT/decl).resolve()!=artifact.resolve():raise ContractError("Source SUCCESS 路径无效")
    if m.get("contract_version")!=CONTRACT_VERSION or m.get("config_version")!=CONFIG_VERSION or SOURCE_SCHEMA_VERSION not in json.dumps(m.get("schema_versions",{})) or m.get("sha256")!=sha(artifact) or m.get("row_count")!=len(rows(artifact)):raise ContractError("Source SUCCESS 哈希、版本或行数无效")
    return m

def settings(path:Path)->Settings:
    try:r=yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError,yaml.YAMLError) as e:raise ContractError("无法读取模型配置") from e
    c=r.get("models",{}).get("cue_extraction",{});e=c.get("execution",{});p=e.get("package_policy",{});l=e.get("rate_limit_policy",{});layout=e.get("shard_layout",{});price=e.get("pricing_snapshot",{})
    exact={"cue_execution_policy_version":"v2.0.0","mode":"explicit_execute_only","shard_size_atoms":500,"max_retries":2,"transport":"realtime_chat_completions"}
    if r.get("contract_version")!=CONTRACT_VERSION or r.get("config_version")!=CONFIG_VERSION or any(e.get(k)!=v for k,v in exact.items()) or c.get("model_id")!=MODEL or c.get("prompt_version")!=PROMPT_VERSION or c.get("thinking_enabled") is not False or c.get("temperature")!=0:raise ContractError("v2 模型或执行配置未冻结")
    if p!={"maximum_atoms":5,"maximum_request_utf8_bytes":24000,"ordering":"atom_id_lexicographic","output_tokens_per_atom":128,"output_max_tokens_formula":"output_tokens_per_atom_times_package_atom_count","inference_schema":"cue_inference_batch_v1.schema.json","inference_schema_version":"v1.0.0","response_top_level_field":"items","response_correlation_field":"item_index"}:raise ContractError("v2 package_policy 漂移")
    if e.get("controlled_field_policy")!={"model_input_fields":["item_index","text"],"model_output_fields":["item_index","entities","scene_type","activity_type","cue_type","normalized_predicate","supporting_text_span","confidence","ambiguity_reason","validation_status"],"program_backfilled_fields":["cue_id","atom_id","split","source_text","model_id","prompt_version","schema_version","run_id"],"raw_model_response_storage":"forbidden"}:raise ContractError("v2 受控字段策略漂移")
    if layout!={"root":"cues/shards","package_directory":"packages","input_manifest_suffix":".input.jsonl","output_suffix":".result.jsonl","ledger_suffix":".ledger.jsonl","completion_suffix":".complete.json","failed_suffix":".failed.json","merge_order":"numeric_shard_index_ascending"}:raise ContractError("v2 package 布局漂移")
    if l.get("target_requests_per_minute")!=300 or l.get("target_total_tokens_per_minute")!=1000000 or price!={"pricing_version":"2026-09-01_cn-beijing_list","official_pricing_url":"https://help.aliyun.com/zh/model-studio/model-pricing","input_price_cny_per_million_tokens":0.2,"output_price_cny_per_million_tokens":0.8,"price_region":"cn-beijing","input_context_window_tokens":32000,"retry_attempts_billed_independently":True}:raise ContractError("v2 限流或价格快照漂移")
    context={"payload_version":e.get("protocol_hash_payload_version"),"model":{"model_id":c.get("model_id"),"thinking_enabled":c.get("thinking_enabled"),"reasoning_effort":c.get("reasoning_effort"),"temperature":c.get("temperature"),"prompt_version":c.get("prompt_version"),"final_cue_schema":c.get("schema"),"final_cue_schema_version":c.get("schema_version")},"service":{"endpoint":r.get("default_endpoint"),"region":r.get("default_region"),"credential_policy":r.get("credential_policy"),"raw_response_policy":r.get("raw_response_policy")}}
    if context["payload_version"] != "v1.0.0":raise ContractError("protocol_hash_payload_version 未冻结")
    return Settings(str(r["default_endpoint"]).rstrip("/"),"DASHSCOPE_API_KEY",500,5,24000,128,2,300,1000000,layout,.2,.8,32000,e,context)

def request(prompt:str,schema:dict[str,Any],atoms:list[dict[str,Any]])->dict[str,Any]:
    # 模型输入刻意只保留局部索引和可见文本；所有标识与血缘字段由程序回填。
    items=[{"item_index":i,"text":a["visible_text"]} for i,a in enumerate(atoms)]
    return {"model":MODEL,"temperature":0,"enable_thinking":False,"max_tokens":128*len(atoms),"stream":False,"messages":[{"role":"system","content":prompt},{"role":"user","content":json.dumps({"items":items},ensure_ascii=False,separators=(",",":"))}],"response_format":{"type":"json_schema","json_schema":{"name":"cue_inference_batch_v1","strict":True,"schema":schema}}}
def request_bytes(prompt:str,schema:dict[str,Any],atoms:list[dict[str,Any]])->int:return len(json.dumps(request(prompt,schema,atoms),ensure_ascii=False,separators=(",",":")).encode())
def protocol_hash(config:Settings,prompt:Path,inference:Path)->str:
    """协议哈希覆盖所有冻结执行字段，避免恢复时混用不同模型、价格、限流或布局。"""
    return stable({**config.protocol_context,"execution":config.execution,"cue_prompt_sha256":sha(prompt),"cue_inference_schema_sha256":sha(inference)})
def ordered(atoms:list[dict[str,Any]])->list[dict[str,Any]]:
    x=sorted(atoms,key=lambda a:str(a.get("atom_id","")));ids=[a.get("atom_id") for a in x]
    if not all(isinstance(i,str) and i for i in ids) or len(ids)!=len(set(ids)):raise ContractError("atom_id 必须非空且唯一")
    return x
def packages(atoms:list[dict[str,Any]],source_sha:str,prompt:str,schema:dict[str,Any],cfg:Settings,protocol:str,run_id:str)->list[dict[str,Any]]:
    out=[]
    for shard_index,start in enumerate(range(0,len(atoms),cfg.shard_size)):
        shard=atoms[start:start+cfg.shard_size]; current=[];pi=0
        for atom in shard:
            candidate=current+[atom]
            if len(candidate)>cfg.max_atoms or request_bytes(prompt,schema,candidate)>cfg.max_bytes:
                if not current:raise ContractError("单条 Atom 超过 24000 UTF-8 字节保护线")
                out.append(_manifest(current,source_sha,protocol,run_id,shard_index,pi));pi+=1;current=[atom]
                if request_bytes(prompt,schema,current)>cfg.max_bytes:raise ContractError("单条 Atom 超过 24000 UTF-8 字节保护线")
            else:current=candidate
        if current:out.append(_manifest(current,source_sha,protocol,run_id,shard_index,pi))
    return out
def _manifest(items:list[dict[str,Any]],source_sha:str,protocol:str,run:str,si:int,pi:int)->dict[str,Any]:return {"run_id":run,"shard_index":si,"package_index":pi,"package_id":f"shard_{si:05d}_package_{pi:03d}","source_atoms_sha256":source_sha,"cue_execution_protocol_sha256":protocol,"atoms":[{"atom_id":a["atom_id"],"atom_sha256":stable(a)} for a in items]}
def paths(root:Path,m:dict[str,Any],l:dict[str,str])->dict[str,Path]:
    b=root/l["package_directory"]/m["package_id"];n=m["package_id"]
    return {"manifest":b/(n+l["input_manifest_suffix"]),"result":b/(n+l["output_suffix"]),"ledger":b/(n+l["ledger_suffix"]),"complete":b/(n+l["completion_suffix"]),"failed":b/(n+l["failed_suffix"])}
def complete(m:dict[str,Any],p:dict[str,Path])->bool:
    if not all(p[k].is_file() for k in("manifest","result","ledger","complete")):return False
    try:
        c=read_json(p["complete"])
        if rows(p["manifest"]) != [m]:return False
    except ContractError:return False
    return c.get("package_id")==m["package_id"] and c.get("source_atoms_sha256")==m["source_atoms_sha256"] and c.get("cue_execution_protocol_sha256")==m["cue_execution_protocol_sha256"] and c.get("input_manifest_sha256")==sha(p["manifest"]) and c.get("result_sha256")==sha(p["result"]) and c.get("ledger_sha256")==sha(p["ledger"])
def pending(ms:list[dict[str,Any]],root:Path,l:dict[str,str],rerun_failed:bool=False)->list[dict[str,Any]]:
    return [m for m in ms if not complete(m,paths(root,m,l)) and (rerun_failed or not paths(root,m,l)["failed"].is_file())]
def parse_items(response:dict[str,Any],atoms:list[dict[str,Any]],v:jsonschema.Draft202012Validator,final:jsonschema.Draft202012Validator,run:str)->list[dict[str,Any]]:
    check(v,response,"v2 推理响应");items=response["items"]
    if len(items)!=len(atoms) or sorted(x["item_index"] for x in items)!=list(range(len(atoms))):raise ContractError("v2 item_index 不完整、重复或越界")
    result=[]
    for x in sorted(items,key=lambda z:z["item_index"]):
        atom=atoms[x["item_index"]]
        if x["supporting_text_span"] not in atom["visible_text"] or not any(q.get("slot")==x["cue_type"] for q in x["normalized_predicate"]["all_of"]):raise ContractError("v2 支撑原文或谓词不符合对应 Atom")
        inferred={k:v for k,v in x.items() if k!="item_index"}
        cue={**inferred,"cue_id":"cue_"+atom["atom_id"].removeprefix("src_"),"atom_id":atom["atom_id"],"split":atom["split"],"source_text":atom["visible_text"],"model_id":MODEL,"prompt_version":PROMPT_VERSION,"schema_version":CUE_SCHEMA_VERSION,"run_id":run}
        check(final,cue,"回填 Cue")
        if cue["validation_status"]=="accepted":result.append(cue)
    return result
def preflight(ms:list[dict[str,Any]],atoms:list[dict[str,Any]],prompt:str,schema:dict[str,Any],cfg:Settings,protocol:str)->dict[str,Any]:
    # 预检建立一次映射，避免每个 package 重扫全部 Atom 而把线性核算退化为平方复杂度。
    atom_map={a["atom_id"]:a for a in atoms};sizes=[]
    for m in ms:
        subset=[atom_map[x["atom_id"]] for x in m["atoms"]];sizes.append(request_bytes(prompt,schema,subset))
    inp=sum(sizes);out=sum(cfg.tokens_per_atom*len(m["atoms"]) for m in ms);factor=cfg.retries+1
    def fee(n:int)->dict[str,float]:
        i=inp*n/1e6*cfg.input_price;o=out*n/1e6*cfg.output_price;return {"input_cny_upper_bound":i,"output_cny_upper_bound":o,"total_cny_upper_bound":i+o}
    return {"mode":"preflight","network_called":False,"credentials_read":False,"formal_outputs_written":False,"atom_count":len(atoms),"package_count":len(ms),"max_package_request_utf8_bytes":max(sizes,default=0),"cue_execution_protocol_sha256":protocol,"cny_upper_bounds":{"baseline_one_attempt_per_package":fee(1),"conservative_all_packages_exhaust_max_retries":fee(factor)},"recovery":"仅协议、来源、清单、结果和账本哈希均匹配的完成 package 跳过"}
class Limiter:
    """每次尝试按请求字节加输出预留令牌，取 RPM/TPM 中较严格的无突发间隔。"""
    def __init__(self,cfg:Settings):self.cfg,self.next=cfg,None
    def wait(self,reserved:int)->float:
        t=time.monotonic();target=t if self.next is None else self.next;w=max(0,target-t)
        if w:time.sleep(w)
        left=time.monotonic();self.next=max(target,left)+max(60/self.cfg.rpm,reserved*60/self.cfg.tpm);return max(0,left-t)
def append(path:Path,event:dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a",encoding="utf-8",newline="\n") as f:f.write(json.dumps(event,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n");f.flush();os.fsync(f.fileno())
def execute_package(m:dict[str,Any],atom_map:dict[str,dict[str,Any]],root:Path,prompt:str,inference:dict[str,Any],iv:jsonschema.Draft202012Validator,fv:jsonschema.Draft202012Validator,cfg:Settings,limit:Limiter)->None:
    """正式分包路径：原始响应只在内存解析，失败写无正文标记且须显式选择后才重跑。"""
    p=paths(root,m,cfg.layout);write_rows(p["manifest"],[m]);atoms=[atom_map[x["atom_id"]] for x in m["atoms"]];payload=request(prompt,inference,atoms);body=json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode();reserved=len(body)+payload["max_tokens"];key=os.environ.get(cfg.credential)
    if not key:raise ContractError("未设置 DASHSCOPE_API_KEY")
    req=Request(cfg.endpoint+"/chat/completions",data=body,headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},method="POST");waited=0.0
    for attempt in range(cfg.retries+1):
        waited+=limit.wait(reserved)
        try:
            with urlopen(req,timeout=60) as h:r=json.loads(h.read().decode())
            raw=json.loads(r["choices"][0]["message"]["content"]);fragment=parse_items(raw,atoms,iv,fv,m["run_id"]);usage=r.get("usage") if isinstance(r.get("usage"),dict) else {};event={"status":"success","attempt_count":1,"prompt_tokens":usage.get("prompt_tokens"),"completion_tokens":usage.get("completion_tokens"),"total_tokens":usage.get("total_tokens"),"reserved_tokens":reserved,"rate_limit_wait_seconds":waited,"raw_response_saved":False};append(p["ledger"],event);write_rows(p["result"],fragment);write_json(p["complete"],{"package_id":m["package_id"],"source_atoms_sha256":m["source_atoms_sha256"],"cue_execution_protocol_sha256":m["cue_execution_protocol_sha256"],"input_manifest_sha256":sha(p["manifest"]),"result_sha256":sha(p["result"]),"ledger_sha256":sha(p["ledger"]),"completed_at":now(),"accepted_row_count":len(fragment)});return
        except (HTTPError,URLError,TimeoutError,json.JSONDecodeError,ContractError) as e:
            event={"status":"failed","attempt_count":1,"prompt_tokens":None,"completion_tokens":None,"total_tokens":None,"reserved_tokens":reserved,"rate_limit_wait_seconds":waited,"failure_category":type(e).__name__,"failure_summary":str(e)[:160],"raw_response_saved":False};append(p["ledger"],event)
            if attempt==cfg.retries:write_json(p["failed"],{"package_id":m["package_id"],"source_atoms_sha256":m["source_atoms_sha256"],"cue_execution_protocol_sha256":m["cue_execution_protocol_sha256"],"ledger_sha256":sha(p["ledger"]),"failure_category":type(e).__name__});raise
            time.sleep(min(2**attempt,4))
def merge(ms:list[dict[str,Any]],root:Path,cfg:Settings,target:Path)->int:
    if pending(ms,root,cfg.layout,True):raise ContractError("禁止合并未完成 package")
    out=[]
    for m in sorted(ms,key=lambda x:(x["shard_index"],x["package_index"])):out.extend(rows(paths(root,m,cfg.layout)["result"]))
    ids=[x["cue_id"] for x in out]
    if len(ids)!=len(set(ids)):raise ContractError("合并 Cue ID 重复")
    write_rows(target,out);return len(out)
def usage_summary(ms:list[dict[str,Any]],root:Path,cfg:Settings)->dict[str,Any]:
    """从已封存 package 账本聚合真实服务端用量；绝不以预检上界或零值伪造账务。"""
    events=[e for m in ms for e in rows(paths(root,m,cfg.layout)["ledger"])]
    ok=[e for e in events if e.get("status")=="success"];bad=[e for e in events if e.get("status")!="success"]
    def total(k:str)->int:return sum(e[k] for e in events if isinstance(e.get(k),int) and e[k]>=0)
    return {"package_count":len(ms),"attempt_count":len(events),"successful_attempt_count":len(ok),"failed_attempt_count":len(bad),"prompt_tokens":total("prompt_tokens"),"completion_tokens":total("completion_tokens"),"total_tokens":total("total_tokens"),"missing_usage_count":sum(1 for e in events if not all(isinstance(e.get(k),int) and e[k]>=0 for k in ("prompt_tokens","completion_tokens","total_tokens"))),"retry_count":max(0,len(events)-len(ms)),"rate_limit_wait_seconds":sum(float(e.get("rate_limit_wait_seconds",0)) for e in events)}
def run(args:argparse.Namespace)->int:
    cfg=settings(args.model_registry);source=verified_source(args.source_atoms,args.source_success);sv,iv,fv=validator(args.source_schema),validator(args.inference_schema),validator(args.cue_schema);atoms=ordered(rows(args.source_atoms))
    for a in atoms:check(sv,a,"Source Atom")
    prompt=args.prompt.read_text(encoding="utf-8");inference=read_json(args.inference_schema);run_id=args.run_id or "run_cue_"+uuid.uuid4().hex[:16];proto=protocol_hash(cfg,args.prompt,args.inference_schema);ms=packages(atoms,source["sha256"],prompt,inference,cfg,proto,run_id);report=preflight(ms,atoms,prompt,inference,cfg,proto)
    if not args.execute:print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True));return 0
    root=args.run_root/run_id;atom_map={a["atom_id"]:a for a in atoms};limit=Limiter(cfg)
    for m in pending(ms,root,cfg.layout,args.rerun_failed_packages):execute_package(m,atom_map,root,prompt,inference,iv,fv,cfg,limit)
    count=merge(ms,root,cfg,args.output);write_json(args.success_marker,{"artifact_path":str(args.output.resolve()),"sha256":sha(args.output),"row_count":count,"contract_version":CONTRACT_VERSION,"config_version":CONFIG_VERSION,"schema_versions":{"cue_candidate":CUE_SCHEMA_VERSION},"generated_at":now(),"upstream_hashes":{"source_atoms":source["sha256"]},"model_id":MODEL,"prompt_version":PROMPT_VERSION,"cue_execution_protocol_sha256":proto,"cue_execution_policy_version":"v2.0.0","cue_prompt_sha256":sha(args.prompt),"cue_inference_schema_sha256":sha(args.inference_schema),"cue_inference_schema_version":"v1.0.0","cue_inference_schema":"cue_inference_batch_v1.schema.json","source_atoms_sha256":source["sha256"],"usage_summary":usage_summary(ms,root,cfg)});return 0
def parse_args(argv:list[str]|None=None)->argparse.Namespace:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--model-registry",type=Path,default=ROOT/"config/model_registry.yaml");p.add_argument("--source-atoms",type=Path,default=ROOT/"source/source_video_atoms.jsonl");p.add_argument("--source-success",type=Path,default=ROOT/"source/SOURCE_ATOMS_SUCCESS.json");p.add_argument("--source-schema",type=Path,default=ROOT/"schemas/source_video_atom.schema.json");p.add_argument("--cue-schema",type=Path,default=ROOT/"schemas/cue_candidate.schema.json");p.add_argument("--inference-schema",type=Path,default=ROOT/"schemas/cue_inference_batch_v1.schema.json");p.add_argument("--prompt",type=Path,default=ROOT/"prompts/cue_extractor_v2.md");p.add_argument("--run-root",type=Path,default=ROOT/"cues/shards");p.add_argument("--output",type=Path,default=ROOT/"cues/cue_library.jsonl");p.add_argument("--success-marker",type=Path,default=ROOT/"cues/CUE_LIBRARY_SUCCESS.json");p.add_argument("--run-id");p.add_argument("--execute",action="store_true");p.add_argument("--rerun-failed-packages",action="store_true");return p.parse_args(argv)
def main()->int:
    try:return run(parse_args())
    except ContractError as e:print(f"合同门禁失败：{e}",file=sys.stderr);return 2
if __name__=="__main__":raise SystemExit(main())
