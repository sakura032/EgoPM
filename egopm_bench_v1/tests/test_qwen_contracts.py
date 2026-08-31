"""第 05--07 阶段的无 API 合成合同测试。

输入仅为进程内 Atom、推理对象和临时目录；输出是断言结果，覆盖 v2 package 协议、受控字段
回填、哈希恢复和成本核算。测试不读取密钥、不访问网络，也不写正式 Cue 或 Seed。
"""
from __future__ import annotations
import importlib.util,json,sys
from pathlib import Path
from types import ModuleType
import pytest
ROOT=Path(__file__).resolve().parents[1]
def load()->ModuleType:
 p=ROOT/"scripts/05_extract_cues.py";s=importlib.util.spec_from_file_location("cue_v2",p);assert s and s.loader;m=importlib.util.module_from_spec(s);sys.modules["cue_v2"]=m;s.loader.exec_module(m);return m
def atom(n:int,text:str="A person starts cooking.")->dict:
 i=f"{n:06d}";return {"atom_id":f"src_SYNTH_DAY1_{i}","atom_kind":"source_video_atom","atom_stage":"final","participant_source_id":"SYNTH","source_day":"DAY1","session_id":"SYNTH_DAY1_SESSION","source_group_id":f"group_{i}","world_event_id":None,"source_srt_paths":{"transcript":"synthetic.srt","dense_caption":"synthetic.srt"},"source_video_path":None,"video_mapping_status":"pending","local_start_sec":float(n),"local_end_sec":float(n+1),"normalized_start_sec":float(n),"normalized_end_sec":float(n+1),"transcript_segment_ids":[f"tr_{i}"],"dense_caption_segment_ids":[f"dc_{i}"],"transcript":text,"dense_caption":text,"visible_text":text,"modality_coverage":"both","provenance":"egolife_srt","split":"train"}
def response(n:int)->dict:
 return {"items":[{"item_index":i,"entities":["person"],"scene_type":None,"activity_type":"cooking","cue_type":"activity","normalized_predicate":{"all_of":[{"slot":"activity","operator":"starts","value":"cooking"}]},"supporting_text_span":"starts cooking","confidence":.8,"ambiguity_reason":None,"validation_status":"accepted"} for i in range(n)]}
def test_v2_config_and_request_minimise_input()->None:
 m=load();c=m.settings(ROOT/"config/model_registry.yaml");schema=m.read_json(ROOT/"schemas/cue_inference_batch_v1.schema.json");r=m.request("prompt",schema,[atom(1),atom(2)])
 assert r["max_tokens"]==256 and r["enable_thinking"] is False
 payload=json.loads(r["messages"][1]["content"]);assert payload=={"items":[{"item_index":0,"text":"A person starts cooking."},{"item_index":1,"text":"A person starts cooking."}]}
 assert c.max_atoms==5 and c.max_bytes==24000
def test_adaptive_packages_cover_order_and_byte_limit()->None:
 m=load();c=m.settings(ROOT/"config/model_registry.yaml");schema=m.read_json(ROOT/"schemas/cue_inference_batch_v1.schema.json");a=[atom(3),atom(1),atom(2),atom(4),atom(5),atom(6)]
 packs=m.packages(m.ordered(a),"source","p",schema,c,"protocol","run")
 assert [len(x["atoms"]) for x in packs]==[5,1]
 assert [x["atom_id"] for p in packs for x in p["atoms"]]==[f"src_SYNTH_DAY1_{i:06d}" for i in range(1,7)]
 assert all(m.request_bytes("p",schema,[next(a for a in m.ordered(a) if a["atom_id"]==x["atom_id"]) for x in p["atoms"]])<=24000 for p in packs)
def test_v2_parser_backfills_and_rejects_private_or_cross_atom_fields()->None:
 m=load();inf=m.validator(ROOT/"schemas/cue_inference_batch_v1.schema.json");final=m.validator(ROOT/"schemas/cue_candidate.schema.json");a=[atom(1),atom(2)]
 cues=m.parse_items(response(2),a,inf,final,"run");assert [x["atom_id"] for x in cues]==[a[0]["atom_id"],a[1]["atom_id"]] and all(x["prompt_version"]=="cue_extractor_v2" for x in cues)
 bad=response(2);bad["items"][0]["atom_id"]="private"
 with pytest.raises(m.ContractError):m.parse_items(bad,a,inf,final,"run")
 bad=response(2);bad["items"][0]["supporting_text_span"]="other atom"
 with pytest.raises(m.ContractError,match="支撑原文"):m.parse_items(bad,a,inf,final,"run")
def test_protocol_and_complete_package_hashes_gate_recovery(tmp_path:Path)->None:
 m=load();c=m.settings(ROOT/"config/model_registry.yaml");schema=m.read_json(ROOT/"schemas/cue_inference_batch_v1.schema.json");p=tmp_path/"prompt.md";p.write_text("p",encoding="utf-8");s=tmp_path/"schema.json";s.write_text(json.dumps(schema),encoding="utf-8");proto=m.protocol_hash(c,p,s);pack=m.packages([atom(1)],"source","p",schema,c,proto,"run")[0];files=m.paths(tmp_path,pack,c.layout)
 m.write_rows(files["manifest"],[pack]);m.write_rows(files["result"],[]);m.write_rows(files["ledger"],[{"status":"success","raw_response_saved":False}]);m.write_json(files["complete"],{"package_id":pack["package_id"],"source_atoms_sha256":"source","cue_execution_protocol_sha256":proto,"input_manifest_sha256":m.sha(files["manifest"]),"result_sha256":m.sha(files["result"]),"ledger_sha256":m.sha(files["ledger"])})
 assert m.pending([pack],tmp_path,c.layout)==[]
 files["ledger"].write_text("tampered\n",encoding="utf-8");assert m.pending([pack],tmp_path,c.layout)==[pack]
def test_preflight_costs_are_read_only_and_retry_conservative()->None:
 m=load();c=m.settings(ROOT/"config/model_registry.yaml");schema=m.read_json(ROOT/"schemas/cue_inference_batch_v1.schema.json");a=[atom(1)];packs=m.packages(a,"source","p",schema,c,"proto","run");r=m.preflight(packs,a,"p",schema,c,"proto")
 assert r["network_called"] is False and r["formal_outputs_written"] is False
 assert r["cny_upper_bounds"]["conservative_all_packages_exhaust_max_retries"]["total_cny_upper_bound"]==pytest.approx(r["cny_upper_bounds"]["baseline_one_attempt_per_package"]["total_cny_upper_bound"]*3)
