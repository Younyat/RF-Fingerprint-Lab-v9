from __future__ import annotations

import hashlib, json, shutil, uuid, zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.infrastructure.ble.campaign_policy import contract_from_session

SCHEMA="ble-dataset-studio-v1"
MODELS={"glossary_schema_version":"1.0.0","evidence_model_version":"1.0.0","quality_model_version":"1.0.0"}
MINIMUM={"ble_activity":"E1","crc_valid_packets":"E2","windows_b200_corroboration":"E3","logical_device_identification":"E4","rf_fingerprint_preparation":"E4"}
RANK={f"E{i}":i for i in range(6)}

def utc(): return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def read_json(path:Path,default=None): return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default
def jsonl(path:Path): return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.is_file() else []
def write_json(path:Path,value): path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def write_jsonl(path:Path,values): path.parent.mkdir(parents=True,exist_ok=True); path.write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in values),encoding="utf-8")
def sha(path:Path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
    return h.hexdigest()

class BleDatasetStudioManager:
    def __init__(self,root:Path,hybrid_root:Path,capture_root:Path,definitions_root:Path):
        self.root,self.hybrid_root,self.capture_root,self.definitions_root=root,hybrid_root,capture_root,definitions_root
        root.mkdir(parents=True,exist_ok=True); self._bootstrap()
    def _dir(self,dataset_id,version="1.0.0"):
        if any(x in dataset_id+version for x in ("/","\\","..")): raise ValueError("INVALID_DATASET_ID")
        return self.root/dataset_id/version
    def _bootstrap(self):
        if (self._dir("BLE-EVIDENCE-DS01")/"dataset_manifest.json").exists(): return
        self.create({"dataset_id":"BLE-EVIDENCE-DS01","version":"1.0.0","research_question":"¿Puede un segmento IQ BLE vincularse reproduciblemente con un dispositivo lógico usando Windows y B200?","intended_task":"logical_device_identification","devices":[{"model":"TI SensorTag CC2650","device_id":"ble-native-e24043b637e704bd","address":"B0:B4:48:C0:36:06","physical_unit_id":"CC2650-UNIT-01"},{"model":"TI SensorTag probable CC2541","address":"BC:6A:29:AB:DE:13","physical_unit_id":"CC2541-UNIT-01"}],"channels":[37,38,39],"duration_seconds":30,"sample_rate_sps":4000000,"bandwidth_hz":2000000,"gain_db":20,"antenna":"RX2","distances":["documentar"],"orientations":["documentar"],"locations":["laboratorio"],"days":[1],"sessions_per_condition":2,"receiver":"USRP B200 E3R04Z1B2","quality_requirements":{"fingerprint_preparation":{"overflows":0,"discontinuities":0,"physical_unit_required":True,"minimum_evidence_level":"E4"}},"acceptance_criteria":["CRC válido","corroboración Windows–B200","objetivo preseleccionado para E4","hashes verificables"],"deduplication_policy":"keep_all_events","negative_controls":["target_off","target_absent","other_device_active","multiple_devices_active","environment_capture"]})
    def create(self,body:dict[str,Any]):
        dataset_id=str(body.get("dataset_id") or "").strip(); version=str(body.get("version") or "1.0.0")
        if not dataset_id: raise ValueError("DATASET_ID_REQUIRED")
        path=self._dir(dataset_id,version)
        if path.exists(): raise RuntimeError("DATASET_VERSION_ALREADY_EXISTS")
        task=body.get("intended_task","logical_device_identification")
        protocol={**body,"dataset_id":dataset_id,"version":version,"intended_task":task,"minimum_evidence_level":MINIMUM.get(task,"E4"),**MODELS,"frozen":False,"created_at_utc":utc()}
        write_json(path/"campaign_protocol.json",protocol); write_jsonl(path/"examples.jsonl",[]); write_json(path/"devices.json",{"devices":protocol.get("devices",[])}); write_jsonl(path/"sessions.jsonl",[])
        self._materialize(dataset_id,version); return self.get(dataset_id,version)
    def freeze(self,dataset_id,version):
        p=self._dir(dataset_id,version)/"campaign_protocol.json"; protocol=read_json(p)
        if not protocol: raise FileNotFoundError(dataset_id)
        protocol.update(frozen=True,frozen_at_utc=utc(),protocol_sha256=None); write_json(p,protocol); protocol["protocol_sha256"]=sha(p); write_json(p,protocol)
        self._materialize(dataset_id,version); return self.get(dataset_id,version)
    def list(self):
        out=[]
        for p in self.root.glob("*/*/dataset_manifest.json"):
            try: out.append(read_json(p))
            except Exception: pass
        return sorted(out,key=lambda x:(x.get("dataset_id",""),x.get("version","")))
    def get(self,dataset_id,version="1.0.0"):
        path=self._dir(dataset_id,version); manifest=read_json(path/"dataset_manifest.json")
        if not manifest: raise FileNotFoundError(dataset_id)
        return {"manifest":manifest,"protocol":read_json(path/"campaign_protocol.json",{}),"matrix":self.matrix(dataset_id,version),"quality":read_json(path/"quality_report.json",{}),"split":read_json(path/"split_manifest.json",{}),"examples":jsonl(path/"examples.jsonl")}
    def matrix(self,dataset_id,version="1.0.0"):
        protocol=read_json(self._dir(dataset_id,version)/"campaign_protocol.json",{}); sessions=jsonl(self._dir(dataset_id,version)/"sessions.jsonl"); done={(s.get("target_physical_unit_id"),s.get("day"),s.get("planned_session"),s.get("channel")):s for s in sessions}
        rows=[]
        for d in protocol.get("devices",[]):
            for day in protocol.get("days",[1]):
                for session in range(1,int(protocol.get("sessions_per_condition",1))+1):
                    for channel in protocol.get("channels",[37]):
                        key=(d.get("physical_unit_id"),day,session,channel); actual=done.get(key,{})
                        rows.append({"device_model":d.get("model"),"physical_unit_id":d.get("physical_unit_id"),"day":day,"planned_session":session,"channel":channel,"distance":actual.get("distance",protocol.get("distances",[None])[0]),"orientation":actual.get("orientation",protocol.get("orientations",[None])[0]),"gain_db":protocol.get("gain_db"),"state":actual.get("state","pending"),"evidence_level":actual.get("evidence_level"),"quality":actual.get("quality"),"hybrid_session_id":actual.get("hybrid_session_id")})
        return rows
    def ingest(self,dataset_id,version,body):
        path=self._dir(dataset_id,version); protocol=read_json(path/"campaign_protocol.json")
        if not protocol: raise FileNotFoundError(dataset_id)
        if not protocol.get("frozen"): raise RuntimeError("CAMPAIGN_PROTOCOL_NOT_FROZEN")
        sid=body.get("hybrid_session_id"); session=read_json(self.hybrid_root/sid/"session_manifest.json")
        if not session or session.get("state")!="completed": raise RuntimeError("HYBRID_SESSION_NOT_COMPLETED")
        cid=session.get("capture_id"); cap=self.capture_root/cid; capture=read_json(cap/"capture_manifest.json",{}); quality=read_json(cap/"quality_report.json",{}); packets=jsonl(self.hybrid_root/sid/"correlation"/"decoded_packets.jsonl")
        campaign=contract_from_session(session)
        declared_negative=(campaign["campaign_intent"]=="negative_control" and campaign["operator_confirmation"] and bool(campaign["negative_control_type"]))
        negative_ground_truth_source={
            "target_powered_off":"OPERATOR_DECLARED_TARGET_POWERED_OFF",
            "target_physically_absent":"OPERATOR_DECLARED_TARGET_PHYSICALLY_ABSENT",
            "other_device_substituted":"OPERATOR_DECLARED_OTHER_DEVICE_SUBSTITUTED",
            "ambient_only":"OPERATOR_DECLARED_AMBIENT_ONLY",
        }.get(campaign["negative_control_type"]) if declared_negative else None
        device=next((d for d in protocol.get("devices",[]) if str(d.get("address","")).upper()==str(session.get("target_address","")).upper()),None); physical=body.get("physical_unit_id") or (device or {}).get("physical_unit_id")
        examples=[]; seen=set(); policy=protocol.get("deduplication_policy","keep_all_events")
        for packet in packets:
            corr=packet.get("correlation") or {}; level="E2" if packet.get("crc_valid") else "E1"
            if corr.get("status")=="MATCHED_BY_BOTH_STRONG": level="E4" if str(packet.get("address","")).upper()==str(session.get("target_address","")).upper() else "E3"
            overlap_unknown=bool(quality.get("overflow_count") or quality.get("discontinuity_count")); status="INCLUDED_PROTOCOL_ONLY"
            reasons=[]
            if overlap_unknown: status="QUARANTINED_SESSION_LOSS"; reasons.append(f"La captura registró {quality.get('overflow_count',0)} overflows y {quality.get('discontinuity_count',0)} discontinuidades; no existen intervalos exactos de pérdida para demostrar continuidad de esta ráfaga.")
            elif corr.get("status") in {"AMBIGUOUS","AMBIGUOUS_TIME_MATCH"}: status="EXCLUDED_AMBIGUOUS"; reasons.append(f"La correlación produjo {corr.get('candidate_count','varias')} observaciones compatibles.")
            elif level=="E4": status="INCLUDED_STRONG"
            elif not packet.get("crc_valid"): status="INCLUDED_NEGATIVE" if protocol.get("intended_task")=="ble_activity" else "EXCLUDED_UNKNOWN_TARGET"
            key=(packet.get("address"),packet.get("advertising_data_hex"))
            if policy=="one_per_payload_window" and key in seen: status="EXCLUDED_DUPLICATE"; reasons=["Dirección y payload ya fueron incluidos según one_per_payload_window."]
            seen.add(key)
            start=int(packet.get("sample_start") or 0); end=int(packet.get("sample_end") or start)
            correlation_state=corr.get("status") or "B200_ONLY"
            target_relation="CONFIRMED_TARGET" if level=="E4" else "UNKNOWN"
            examples.append({"example_id":f"EX-{hashlib.sha256((sid+str(packet.get('burst_id'))).encode()).hexdigest()[:16]}","dataset_id":dataset_id,"dataset_version":version,"session_id":sid,"capture_id":cid,"burst_id":packet.get("burst_id"),"sample_start":start,"sample_count":max(0,end-start),"channel":packet.get("channel_index") or session.get("channel"),"campaign_intent":campaign["campaign_intent"],"negative_control_type":campaign["negative_control_type"],"target_device_id":session.get("target_device_id"),"target_physical_unit_id":physical,"target_relation":target_relation,"pdu_type":packet.get("pdu_type_name"),"crc_valid":bool(packet.get("crc_valid")),"native_observed":bool(corr.get("native_observation_id")),"address_match":corr.get("address_match"),"payload_match":corr.get("payload_match"),"delta_t_ms":corr.get("time_difference_ms"),"correlation_state":correlation_state,"evidence_level":level,"inclusion_state":status,"exclusion_reasons":reasons,"overflow_overlap":None if overlap_unknown else False,"discontinuity_overlap":None if overlap_unknown else False,"iq_path":packet.get("iq_segment_path"),"iq_sha256":packet.get("iq_segment_sha256"),"packet_sha256":packet.get("packet_sha256"),"timestamp_utc":packet.get("timestamp")})
        decoded_bursts={x.get("burst_id") for x in examples}
        for burst in jsonl(cap/"burst_candidates.jsonl"):
            if burst.get("burst_id") in decoded_bursts: continue
            loss=bool(quality.get("overflow_count") or quality.get("discontinuity_count")); state="QUARANTINED_SESSION_LOSS" if loss else "INCLUDED_NEGATIVE" if protocol.get("intended_task")=="ble_activity" else "EXCLUDED_UNKNOWN_TARGET"
            reason=(f"La captura registró {quality.get('overflow_count',0)} overflows y {quality.get('discontinuity_count',0)} discontinuidades; no existen intervalos exactos de pérdida para demostrar continuidad de esta ráfaga." if loss else "La ráfaga candidata no produjo un paquete BLE con CRC válido.")
            examples.append({"example_id":f"EX-{hashlib.sha256((sid+str(burst.get('burst_id'))).encode()).hexdigest()[:16]}","dataset_id":dataset_id,"dataset_version":version,"session_id":sid,"capture_id":cid,"burst_id":burst.get("burst_id"),"sample_start":burst.get("sample_start",0),"sample_count":burst.get("sample_count",0),"channel":session.get("channel"),"campaign_intent":campaign["campaign_intent"],"negative_control_type":campaign["negative_control_type"],"target_device_id":session.get("target_device_id"),"target_physical_unit_id":physical,"target_relation":"UNKNOWN","pdu_type":None,"crc_valid":False,"native_observed":False,"address_match":None,"payload_match":None,"delta_t_ms":None,"correlation_state":"NOT_DECODED","evidence_level":"E1","inclusion_state":state,"exclusion_reasons":[reason],"overflow_overlap":None if loss else False,"discontinuity_overlap":None if loss else False,"iq_path":burst.get("iq_segment_path"),"iq_sha256":burst.get("iq_segment_sha256"),"packet_sha256":None,"timestamp_utc":None})
        if declared_negative:
            for example in examples:
                example.update(target_relation="NEGATIVE_BY_EXPERIMENTAL_CONTRACT",negative_ground_truth_source=negative_ground_truth_source,target_address=session.get("target_address"))
        existing=[x for x in jsonl(path/"examples.jsonl") if x.get("session_id")!=sid]; write_jsonl(path/"examples.jsonl",existing+examples)
        sessions=[x for x in jsonl(path/"sessions.jsonl") if x.get("hybrid_session_id")!=sid]; max_level=max((x["evidence_level"] for x in examples),key=lambda x:RANK[x],default="E0")
        sessions.append({"hybrid_session_id":sid,"capture_id":cid,"campaign_intent":campaign["campaign_intent"],"negative_control_type":campaign["negative_control_type"],"operator_confirmation":campaign["operator_confirmation"],"target_physical_unit_id":physical,"day":body.get("day",1),"planned_session":body.get("planned_session",1),"channel":session.get("channel"),"state":"completed","evidence_level":max_level,"quality":"clean" if not quality.get("overflow_count") and not quality.get("discontinuity_count") else "loss_detected","overflows":quality.get("overflow_count",0),"discontinuities":quality.get("discontinuity_count",0),"capture_sha256":capture.get("data_sha256")}); write_jsonl(path/"sessions.jsonl",sessions)
        if declared_negative:
            sessions[-1].update(negative_control_result=session.get("negative_control_result") or "PASSED_SINGLE_RUN",false_target_attributions=int(session.get("false_target_attributions",0)),negative_ground_truth_source=negative_ground_truth_source,target_address=session.get("target_address"),basic_control="PASSED_SINGLE_RUN" if int(session.get("false_target_attributions",0))==0 else "FAILED",reinforced_control="PENDING")
            write_jsonl(path/"sessions.jsonl",sessions)
        self._materialize(dataset_id,version); return self.get(dataset_id,version)
    def split(self,dataset_id,version,body):
        path=self._dir(dataset_id,version); examples=jsonl(path/"examples.jsonl"); policy=body.get("policy","session"); field={"session":"session_id","day":"day","physical_unit":"target_physical_unit_id","channel":"channel","location":"location","receiver":"receiver"}.get(policy)
        if not field: raise ValueError("INVALID_SPLIT_POLICY")
        sessions={x.get("hybrid_session_id"):x for x in jsonl(path/"sessions.jsonl")}; groups={}
        for e in examples:
            value=e.get(field) if field in e else sessions.get(e.get("session_id"),{}).get(field); groups.setdefault(str(value),[]).append(e["example_id"])
        keys=sorted(groups); train,validation,test={},{},{}
        for i,key in enumerate(keys): (test if i%5==0 else validation if i%5==1 else train)[key]=groups[key]
        manifest={"schema_version":"ble-dataset-split-v1","policy":policy,"created_at_utc":utc(),"train":train,"validation":validation,"test":test,"leakage_check":"PASSED","group_field":field}; write_json(path/"split_manifest.json",manifest); self._materialize(dataset_id,version); return manifest
    def new_version(self,dataset_id,version,new_version):
        source=self._dir(dataset_id,version); target=self._dir(dataset_id,new_version)
        if target.exists(): raise RuntimeError("DATASET_VERSION_ALREADY_EXISTS")
        shutil.copytree(source,target); protocol=read_json(target/"campaign_protocol.json"); protocol.update(version=new_version,frozen=False,derived_from=version,created_at_utc=utc()); write_json(target/"campaign_protocol.json",protocol); self._materialize(dataset_id,new_version); return self.get(dataset_id,new_version)
    def _materialize(self,dataset_id,version):
        path=self._dir(dataset_id,version); protocol=read_json(path/"campaign_protocol.json",{}); examples=jsonl(path/"examples.jsonl"); sessions=jsonl(path/"sessions.jsonl"); levels=Counter(x.get("evidence_level") for x in examples); states=Counter(x.get("inclusion_state") for x in examples); included=sum(v for k,v in states.items() if str(k).startswith("INCLUDED")); excluded=len(examples)-included
        cumulative={level:sum(count for key,count in levels.items() if RANK.get(key,0)>=RANK[level]) for level in ("E1","E2","E3","E4")}
        metrics={"captures_total":len({x.get('capture_id') for x in examples}),"sessions_total":len(sessions),"iq_seconds":sum(float(read_json(self.capture_root/s.get('capture_id')/"capture_manifest.json",{}).get("actual_duration_seconds",0)) for s in sessions),"devices":len({x.get('target_device_id') for x in examples if x.get('target_device_id')}),"physical_units":len({x.get('target_physical_unit_id') for x in examples if x.get('target_physical_unit_id')}),"channels":sorted({x.get('channel') for x in examples}),"evidence_levels":dict(levels),"evidence_levels_cumulative":cumulative,"included":included,"excluded":excluded,"exclusion_reasons":dict(states),"overflows":sum(int(x.get('overflows',0)) for x in sessions),"discontinuities":sum(int(x.get('discontinuities',0)) for x in sessions),"crc_yield_percent":round(100*sum(x.get('crc_valid',False) for x in examples)/len(examples),2) if examples else 0,"correlation_yield_percent":round(100*sum(x.get('evidence_level') in {'E3','E4'} for x in examples)/len(examples),2) if examples else 0}
        contract_negative_examples=[x for x in examples if x.get("target_relation")=="NEGATIVE_BY_EXPERIMENTAL_CONTRACT"]
        negative_sessions=[x for x in sessions if x.get("campaign_intent")=="negative_control"]
        scientific_status={
            "positive_e4_campaign":"PASSED_SINGLE_RUN" if any(x.get("evidence_level")=="E4" for x in sessions) else "PENDING",
            "exploratory_e2_campaign":"PASSED" if any(x.get("campaign_intent")=="exploratory_target_search" and RANK.get(x.get("evidence_level"),0)>=2 for x in sessions) else "PENDING",
            "declared_negative_control":"PASSED_SINGLE_RUN" if any(x.get("negative_control_result")=="PASSED_SINGLE_RUN" for x in negative_sessions) else "PENDING",
            "false_target_attributions_in_negative_controls":sum(int(x.get("false_target_attributions",0)) for x in negative_sessions),
            "negative_control_with_active_positive_reference":"PASSED_SINGLE_RUN" if any(x.get("reinforced_control")=="PASSED_SINGLE_RUN" for x in negative_sessions) else "PENDING",
            "clean_positive_capture":"PASSED_SINGLE_RUN" if any(x.get("evidence_level")=="E4" and x.get("quality")=="clean" for x in sessions) else "PENDING",
            "clean_negative_capture":"PASSED_SINGLE_RUN" if any(x.get("campaign_intent")=="negative_control" and x.get("quality")=="clean" for x in sessions) else "PENDING",
            "training_ready_examples":included,
            "fingerprinting":"NOT_VALIDATED",
        }
        metrics.update(contract_negative_examples=len(contract_negative_examples),quarantined_contract_negative_examples=sum(x.get("inclusion_state")=="QUARANTINED_SESSION_LOSS" for x in contract_negative_examples),negative_controls_basic_passed=sum(x.get("negative_control_result")=="PASSED_SINGLE_RUN" for x in negative_sessions),false_target_attributions=scientific_status["false_target_attributions_in_negative_controls"])
        warnings=[]
        if len(sessions)<2:warnings.append("una sola sesión")
        if len(metrics["channels"])<2:warnings.append("un único canal")
        if metrics["physical_units"]<2:warnings.append("una única unidad física")
        if not contract_negative_examples and not any(x.get("inclusion_state")=="INCLUDED_NEGATIVE" for x in examples):warnings.append("ausencia de negativos")
        elif contract_negative_examples and not any(str(x.get("inclusion_state","")).startswith("INCLUDED") for x in contract_negative_examples):warnings.append("negativos contractuales conservados únicamente en cuarentena")
        quality={"schema_version":"ble-dataset-quality-v1","metrics":metrics,"warnings":warnings,"scientific_status":scientific_status,"fingerprinting":"not_validated","e5":"not_implemented_not_validated"}; write_json(path/"quality_report.json",quality)
        datasheet=f"""# Dataset Datasheet — {dataset_id} {version}\n\n## Motivación y pregunta científica\n{protocol.get('research_question','No documentada')}\n\n## Composición\n{len(examples)} ejemplos procedentes de {len(sessions)} sesiones; {included} incluidos y {excluded} en cuarentena.\n\n## Dispositivos y unidades físicas\n{json.dumps(protocol.get('devices',[]),ensure_ascii=False,indent=2)}\n\n## Adquisición, etiquetado y evidencia\nIQ SigMF a {protocol.get('sample_rate_sps')} S/s, canales {protocol.get('channels')}. Niveles E0–E4 automáticos; E5 no implementado/no validado.\n\n## Control de calidad y exclusiones\nOverflows: {metrics['overflows']}. Discontinuidades: {metrics['discontinuities']}. Motivos: {dict(states)}. Los excluidos se conservan en examples.jsonl.\n\n## Sesgos, limitaciones y usos\nAdvertencias: {', '.join(warnings) or 'ninguna detectada'}. Adecuado sólo para la tarea declarada y según el split. No demuestra identidad física ni resistencia a spoofing.\n\n## Integridad, licencia y versión\nVersión {version}. Licencia: por definir por el responsable del dataset. Verificación mediante checksums.sha256.\n"""; (path/"dataset_datasheet.md").write_text(datasheet,encoding="utf-8")
        if contract_negative_examples:
            contract_section=("## Controles negativos declarados\n"
                f"Ejemplos con relación `NEGATIVE_BY_EXPERIMENTAL_CONTRACT`: {len(contract_negative_examples)}. "
                "La verdad terreno procede de una condición física declarada y confirmada por el operador antes de capturar. "
                "Esta relación significa que la muestra no pertenece al objetivo bajo ese contrato; no identifica físicamente al transmisor ambiental. "
                f"Ejemplos contractuales en cuarentena por pérdidas: {sum(x.get('inclusion_state')=='QUARANTINED_SESSION_LOSS' for x in contract_negative_examples)}.\n\n")
            datasheet=datasheet.replace("## Control de calidad y exclusiones",contract_section+"## Control de calidad y exclusiones")
            (path/"dataset_datasheet.md").write_text(datasheet,encoding="utf-8")
        files=[x for x in path.iterdir() if x.is_file() and x.name not in {"checksums.sha256","dataset_manifest.json"}]; checks="".join(f"{sha(x)}  {x.name}\n" for x in sorted(files)); (path/"checksums.sha256").write_text(checks,encoding="utf-8")
        manifest={"schema_version":SCHEMA,"dataset_id":dataset_id,"version":version,"state":"frozen" if protocol.get("frozen") else "draft","intended_task":protocol.get("intended_task"),"minimum_evidence_level":protocol.get("minimum_evidence_level"),**MODELS,"created_at_utc":protocol.get("created_at_utc"),"updated_at_utc":utc(),"maximum_evidence_level":max(levels,key=lambda x:RANK.get(x,0),default="E0"),"examples_included":included,"examples_excluded":excluded,"sessions_completed":len(sessions),"campaigns_planned":len(self.matrix(dataset_id,version)),"training_readiness":"partially_prepared" if included else "not_ready","fingerprinting":"not_validated","datasheet_available":True,"checksums_available":True}; write_json(path/"dataset_manifest.json",manifest)
        files=[x for x in path.iterdir() if x.is_file() and x.name!="checksums.sha256"]; (path/"checksums.sha256").write_text("".join(f"{sha(x)}  {x.name}\n" for x in sorted(files)),encoding="utf-8")
    def export(self,dataset_id,version,kind="complete"):
        path=self._dir(dataset_id,version); data=self.get(dataset_id,version)
        if not (path/"dataset_datasheet.md").is_file(): raise RuntimeError("DATASET_DATASHEET_REQUIRED")
        selected=data["examples"]
        if kind=="e4": selected=[x for x in selected if x.get("evidence_level")=="E4"]
        elif kind=="crc_valid": selected=[x for x in selected if x.get("crc_valid")]
        elif kind=="negatives": selected=[x for x in selected if x.get("inclusion_state")=="INCLUDED_NEGATIVE" or x.get("target_relation")=="NEGATIVE_BY_EXPERIMENTAL_CONTRACT"]
        elif kind=="clean": selected=[x for x in selected if x.get("overflow_overlap") is False and x.get("discontinuity_overlap") is False]
        elif kind not in {"complete","metadata_only","split_manifest"}: raise ValueError("INVALID_EXPORT_KIND")
        export_dir=path/"exports"/f"{kind}-{uuid.uuid4().hex[:8]}"; export_dir.mkdir(parents=True)
        write_jsonl(export_dir/"examples.jsonl",selected); shutil.copy2(path/"dataset_datasheet.md",export_dir/"dataset_datasheet.md")
        iq_included=kind not in {"metadata_only","split_manifest"}
        copied=[]
        if iq_included:
            for example in selected:
                source=self.capture_root/str(example.get("capture_id"))/str(example.get("iq_path") or "")
                if not source.is_file(): continue
                target=export_dir/"iq_segments"/str(example.get("capture_id"))/source.name; target.parent.mkdir(parents=True,exist_ok=True)
                if not target.exists(): shutil.copy2(source,target)
                copied.append({"example_id":example.get("example_id"),"path":str(target.relative_to(export_dir)),"sha256":sha(target)})
            if kind=="complete":
                for capture_id in {str(x.get("capture_id")) for x in selected}:
                    for source in (self.capture_root/capture_id).glob("*.sigmf-*"):
                        target=export_dir/"sigmf"/capture_id/source.name; target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(source,target)
        if (path/"split_manifest.json").is_file():shutil.copy2(path/"split_manifest.json",export_dir/"split_manifest.json")
        export_manifest={"schema_version":"ble-dataset-export-v1","dataset_id":dataset_id,"dataset_version":version,"export_kind":kind,"created_at_utc":utc(),"example_ids":[x["example_id"] for x in selected],"iq_included":iq_included,"iq_segments":copied,"e5_claimed":False}; write_json(export_dir/"export_manifest.json",export_manifest)
        export_files=[x for x in export_dir.rglob("*") if x.is_file() and x.name!="checksums.sha256"]; (export_dir/"checksums.sha256").write_text("".join(f"{sha(x)}  {x.relative_to(export_dir)}\n" for x in export_files),encoding="utf-8")
        archive=export_dir.with_suffix(".zip")
        with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
            for x in export_dir.rglob("*"):
                if x.is_file(): z.write(x,x.relative_to(export_dir))
        return archive
    def definitions(self):
        return {p.stem:read_json(p,{}) for p in self.definitions_root.glob("*.json")}
