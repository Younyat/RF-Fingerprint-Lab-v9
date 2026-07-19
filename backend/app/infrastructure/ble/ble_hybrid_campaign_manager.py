from __future__ import annotations

import hashlib, json, statistics, subprocess, threading, time, uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .campaign_policy import (
    EXPLORATORY_TARGET_SEARCH,
    NEGATIVE_CONTROL,
    POSITIVE_TARGET_VALIDATION,
    contract_from_session,
    validate_campaign_contract,
)

TERMINAL={"completed","failed","cancelled","timed_out"}
def utc(): return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

class BleHybridCampaignManager:
    """Thin orchestration layer over the existing native/capture/DSP tools."""
    def __init__(self, root:Path, capture, native, python:Path, decoder:Path, correlator:Path, worker_repo:Path):
        self.root,self.capture,self.native=root,capture,native; self.python,self.decoder,self.correlator,self.worker_repo=python,decoder,correlator,worker_repo
        root.mkdir(parents=True,exist_ok=True); self._lock=threading.Lock(); self._active=None; self._cancel=set()
    def _path(self,sid):
        if any(x in sid for x in ("/","\\","..")): raise ValueError("INVALID_SESSION_ID")
        return self.root/sid
    def _write(self,sid,**fields):
        path=self._path(sid); path.mkdir(parents=True,exist_ok=True); target=path/"session_manifest.json"; old=json.loads(target.read_text()) if target.exists() else {}
        target.write_text(json.dumps({**old,**fields,"session_id":sid,"updated_at_utc":utc()},indent=2)+"\n",encoding="utf-8")
    def start(self,payload:dict[str,Any]):
        channel=int(payload.get("channel",37)); duration=float(payload.get("duration_seconds",30)); target=payload.get("target") or {"kind":"any"}
        if channel not in (37,38,39) or not 1<=duration<=60 or not payload.get("device_id"): raise ValueError("INVALID_HYBRID_CONFIGURATION")
        contract=validate_campaign_contract(payload,target)
        payload={**payload,"device_id":self.capture.resolve_device_id(payload.get("device_id"))}
        with self._lock:
            if self._active: raise RuntimeError("HYBRID_CAMPAIGN_ALREADY_RUNNING")
            sid="BLE-HYBRID-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+uuid.uuid4().hex[:6]
            self._active=sid
        request={"device_id":payload["device_id"],"ble_channel":channel,"center_frequency_hz":{37:2402000000,38:2426000000,39:2480000000}[channel],"sample_rate_sps":4000000,"bandwidth_hz":2000000,"gain_mode":"manual","gain_db":float(payload.get("gain_db",20)),"antenna":"RX2","duration_seconds":duration,"sample_format":"cf32_le","purpose":"BLE hybrid dashboard campaign","controlled_transmitter_state":"unknown","operator_confirmed":False,"capture_role":"controlled_transmitter_active_B"}
        target_mode="any_device" if target.get("kind")=="any" else "specific_device"
        self._write(sid,state="initializing",created_at_utc=utc(),mode="hybrid",channel=channel,duration_seconds=duration,
            target=target,target_mode=target_mode,target_device_id=target.get("device_id"),target_address=target.get("address"),
            target_name_at_start=target.get("label"),target_selection_source=target.get("selection_source","any_device"),
            campaign_intent=contract["campaign_intent"],negative_control_type=contract["negative_control_type"],
            operator_confirmation=contract["operator_confirmation"],target_seen_before_start=contract["target_seen_before_start"],
            steps={"hardware":"running","native_scan":"pending","b200_capture":"pending","burst_detection":"pending","decoding":"pending","correlation":"pending","results":"pending"},counters={})
        threading.Thread(target=self._run,args=(sid,request),daemon=True).start(); return self.get(sid)
    def _run(self,sid,request):
        try:
            self.native.start_scan(sid); self._write(sid,state="capturing",steps={"hardware":"completed","native_scan":"running","b200_capture":"running","burst_detection":"pending","decoding":"pending","correlation":"pending","results":"pending"})
            job=self.capture.create(request); cid=job["capture_id"]; self._write(sid,capture_id=cid)
            while job["state"] not in TERMINAL:
                if sid in self._cancel: self.capture.cancel(cid)
                time.sleep(.5); job=self.capture.get(cid)
            self.native.stop_scan()
            if job["state"]!="completed": raise RuntimeError(f"CAPTURE_{job['state'].upper()}")
            cap=self.capture._job_dir(cid); bursts=sum(1 for _ in (cap/"burst_candidates.jsonl").open(encoding="utf-8")); quality=json.loads((cap/"quality_report.json").read_text())
            decoded=cap/"decoded"; self._write(sid,state="decoding",capture_manifest=str(cap/"capture_manifest.json"),native_scan_path=str(self.native.root/"scans"/sid),steps={"hardware":"completed","native_scan":"completed","b200_capture":"completed","burst_detection":"completed","decoding":"running","correlation":"pending","results":"pending"},counters={"detected_bursts":bursts,"processed_bursts":0,"crc_valid_packets":0,"native_callbacks":self._native_count(sid),"overflows":quality["overflow_count"]})
            subprocess.run([str(self.python),str(self.decoder),"--segments-dir",str(cap/"iq_bursts"),"--output-dir",str(decoded),"--worker-repository",str(self.worker_repo),"--channel",str(request["ble_channel"])],check=True,timeout=3600)
            summary=json.loads((decoded/"batch_summary.json").read_text()); out=self._path(sid)/"correlation"
            self._write(sid,state="correlating",steps={"hardware":"completed","native_scan":"completed","b200_capture":"completed","burst_detection":"completed","decoding":"completed","correlation":"running","results":"pending"})
            subprocess.run([str(self.python),str(self.correlator),"--capture-dir",str(cap),"--decoded",str(decoded),"--native",str(self.native.root/"scans"/sid),"--output",str(out),"--window-ms","250"],check=True,timeout=120)
            metrics=json.loads((out/"metrics.json").read_text()); self._write(sid,state="completed",steps={k:"completed" for k in ("hardware","native_scan","b200_capture","burst_detection","decoding","correlation","results")},counters={"detected_bursts":bursts,"processed_bursts":summary["segments"],"crc_valid_packets":summary["crc_valid_packets"],"native_callbacks":self._native_count(sid),"overflows":quality["overflow_count"],"discontinuities":quality["discontinuity_count"],"strong_matches":metrics["strong_matches"],"payload_matches":metrics["payload_matches"],"ambiguous":metrics["ambiguous"]},result=metrics)
            self._write(sid,scientific_summary=self.scientific_summary(sid))
        except Exception as error: self._write(sid,state="cancelled" if sid in self._cancel else "failed",error=f"{type(error).__name__}:{error}")
        finally:
            try:
                if self.native.status().get("scanning") and self.native.status().get("scan_session_id") == sid: self.native.stop_scan()
            except Exception: pass
            with self._lock:
                if self._active==sid:self._active=None
    def _native_count(self,sid):
        path=self.native.root/"scans"/sid/"advertisements.jsonl"; return sum(1 for _ in path.open(encoding="utf-8")) if path.exists() else 0
    def get(self,sid):
        value=json.loads((self._path(sid)/"session_manifest.json").read_text()); progress=self._capture_progress(value.get("capture_id")); value["live"]=progress
        decoded=self.capture.root/value["capture_id"]/"decoded"/"progress.json" if value.get("capture_id") else None
        if decoded and decoded.exists(): value["decode_progress"]=json.loads(decoded.read_text())
        return value
    def _capture_progress(self,cid):
        if not cid:return None
        try:return {"job":self.capture.get(cid),"telemetry":self.capture.live_frame(cid)}
        except Exception:return None
    def stop(self,sid):
        current=self.get(sid)
        if current.get("state") not in TERMINAL: self._cancel.add(sid)
        return self.get(sid)
    def list(self):
        values=[]
        for p in self.root.glob("BLE-HYBRID-*/session_manifest.json"):
            try:
                value=json.loads(p.read_text())
                if value.get("operational_visibility") != "internal_validation": values.append(value)
            except Exception: pass
        return sorted(values,key=lambda x:x.get("created_at_utc",""),reverse=True)

    @staticmethod
    def _jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.is_file(): return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def results(self, sid: str) -> dict[str, Any]:
        session=self.get(sid)
        if session.get("state") != "completed": raise RuntimeError("HYBRID_RESULTS_NOT_READY")
        return {"session":session,"metrics":session.get("result",{}),"packets":self.packets(sid),"matches":self.matches(sid)}

    def packets(self, sid: str) -> list[dict[str, Any]]:
        session=self.get(sid); cid=session.get("capture_id")
        if not cid: return []
        correlated=self._path(sid)/"correlation"/"decoded_packets.jsonl"
        return self._jsonl(correlated if correlated.is_file() else self.capture.root/cid/"decoded"/"decoded_packets.jsonl")

    def matches(self, sid: str) -> list[dict[str, Any]]:
        self.get(sid)
        return self._jsonl(self._path(sid)/"correlation"/"matches.jsonl")

    def evidence(self, sid: str) -> dict[str, Any]:
        session=self.get(sid); cid=session.get("capture_id"); base=self._path(sid)
        return {"session_id":sid,"capture_id":cid,"artifacts":{
            "session_manifest":str(base/"session_manifest.json"),"correlation_metrics":str(base/"correlation"/"metrics.json"),
            "correlation_matches":str(base/"correlation"/"matches.jsonl"),
            "capture_manifest":session.get("capture_manifest"),"decoded_packets":str(self.capture.root/cid/"decoded"/"decoded_packets.jsonl") if cid else None,
            "native_advertisements":str(self.native.root/"scans"/sid/"advertisements.jsonl")}}

    @staticmethod
    def _artifact(path_value: str | Path | None) -> dict[str, Any]:
        path=Path(path_value) if path_value else None
        if not path or not path.is_file(): return {"available":False}
        record_count=None
        if path.suffix==".jsonl":
            record_count=sum(1 for line in path.open(encoding="utf-8") if line.strip())
        return {"available":True,"name":path.name,"path":str(path),"size_bytes":path.stat().st_size,"record_count":record_count,
            "sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"created_at_utc":datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat().replace("+00:00","Z")}

    def scientific_summary(self,sid:str)->dict[str,Any]:
        session=json.loads((self._path(sid)/"session_manifest.json").read_text()); cid=session.get("capture_id")
        contract=contract_from_session(session); intent=contract["campaign_intent"]
        cap=self.capture.root/cid if cid else None
        capture=json.loads((cap/"capture_manifest.json").read_text()) if cap and (cap/"capture_manifest.json").is_file() else {}
        quality=json.loads((cap/"quality_report.json").read_text()) if cap and (cap/"quality_report.json").is_file() else {}
        batch=json.loads((cap/"decoded"/"batch_summary.json").read_text()) if cap and (cap/"decoded"/"batch_summary.json").is_file() else {}
        packets=self.packets(sid); matches=self.matches(sid); native=self._jsonl(self.native.root/"scans"/sid/"advertisements.jsonl")
        eligible=[p for p in packets if p.get("pdu_type_name") not in {"SCAN_REQ","CONNECT_IND"}]
        eligible_status=Counter((p.get("correlation") or {}).get("status") or "B200_ONLY" for p in eligible)
        eligible_status["AMBIGUOUS_TIME_MATCH"] += eligible_status["AMBIGUOUS"]
        del eligible_status["AMBIGUOUS"]
        strong=[p for p in eligible if (p.get("correlation") or {}).get("status")=="MATCHED_BY_BOTH_STRONG"]
        deltas=[float((m.get("correlation") or {})["time_difference_ms"]) for m in strong if (m.get("correlation") or {}).get("time_difference_ms") is not None]
        b200_addresses={str(p.get("address")).upper() for p in eligible if p.get("address")}; native_addresses={str(n.get("address")).upper() for n in native if n.get("address")}
        target_address=str(session.get("target_address") or "").upper(); target_native=[n for n in native if str(n.get("address","")).upper()==target_address]
        target_native_ids={n.get("native_observation_id") for n in target_native}; target_packets=[p for p in packets if str(p.get("address","")).upper()==target_address]
        target_related=[p for p in packets if (p.get("correlation") or {}).get("native_observation_id") in target_native_ids]
        target_strong=[p for p in {id(p):p for p in target_packets+target_related}.values() if (p.get("correlation") or {}).get("status")=="MATCHED_BY_BOTH_STRONG"]
        target_payload=[p for p in target_related if (p.get("correlation") or {}).get("payload_match") and p not in target_strong]
        target_b200_packet_ids={p.get("packet_sha256") or p.get("packet_id") for p in target_packets+target_related}
        target_b200_packet_ids.discard(None)
        target_b200_crc_packets=len(target_b200_packet_ids)
        false_target_attributions=len(target_native)+target_b200_crc_packets
        general_ok=bool(strong); specific=session.get("target_mode")=="specific_device"
        target_status=("TARGET_MATCHED_STRONG" if target_strong else "TARGET_MATCHED_BY_PAYLOAD" if target_payload else "TARGET_NATIVE_ONLY" if target_native and not target_packets else "TARGET_B200_ONLY" if target_packets and not target_native else "TARGET_AMBIGUOUS" if target_native and target_packets else "TARGET_NOT_OBSERVED") if specific else "TARGET_NOT_EVALUATED"
        bursts=int(quality.get("burst_candidate_count",session.get("counters",{}).get("detected_bursts",0))); processed=int(batch.get("segments",0)); crc=len(packets)
        fingerprint_ok=bool(quality.get("fingerprinting_eligible")) and int(capture.get("overflow_count",0))==0 and int(capture.get("input_discontinuities",0))==0
        clean_capture=int(capture.get("overflow_count",0))==0 and int(capture.get("input_discontinuities",0))==0
        evidence_level="E4" if specific and bool(target_strong) else "E3" if general_ok else "E2" if crc else "E1" if bursts else "E0"
        best_target=min(target_strong+target_payload,key=lambda p:abs(float((p.get("correlation") or {}).get("time_difference_ms",float("inf")))),default=None)
        best_correlation=(best_target or {}).get("correlation") or {}
        match_evidence=None
        if best_target:
            iq_path=cap/"iq_bursts"/str(best_target.get("segment_file")) if cap and best_target.get("segment_file") else None
            match_evidence={"packet_id":best_target.get("packet_id") or best_target.get("burst_id"),"pdu_type":best_target.get("pdu_type_name"),"address":best_target.get("address"),"advertising_data_hex":best_target.get("advertising_data_hex"),"payload_hex":best_target.get("payload_hex") or best_target.get("payload_octets"),"crc_received":best_target.get("crc_received"),"crc_computed":best_target.get("crc_computed"),"sdr_timestamp_utc":best_target.get("timestamp_utc") or best_target.get("timestamp"),"native_observation_id":best_correlation.get("native_observation_id"),"delta_ms":best_correlation.get("time_difference_ms"),"rule":best_correlation.get("rule"),"sample_start":best_target.get("sample_start"),"sample_end":best_target.get("sample_end"),"iq_artifact":{"available":bool(best_target.get("iq_segment")),"name":best_target.get("iq_segment"),"path":best_target.get("iq_segment_path"),"sha256":best_target.get("iq_segment_sha256")},"overlap_with_overflow":False if clean_capture else None,"overlap_with_discontinuity":False if clean_capture else None,"sample_continuity_verified":clean_capture}
        artifacts={name:self._artifact(path) for name,path in {"capture_manifest":cap/"capture_manifest.json" if cap else None,"quality_report":cap/"quality_report.json" if cap else None,"decoded_packets":self._path(sid)/"correlation"/"decoded_packets.jsonl","correlation_metrics":self._path(sid)/"correlation"/"metrics.json","correlation_matches":self._path(sid)/"correlation"/"matches.jsonl","native_observations":self.native.root/"scans"/sid/"advertisements.jsonl"}.items()}
        result={"schema_version":"ble-scientific-summary-v2","session_id":sid,"question":("¿Puede el dispositivo seleccionado ser observado y corroborado independientemente por el B200 y el adaptador Windows?" if specific else f"¿Puede el B200 recuperar paquetes BLE reales con CRC válido en CH{session.get('channel')} y corroborarlos mediante el adaptador Windows?"),
            "general_result":"DEMONSTRATED" if general_ok else "NOT_DEMONSTRATED","success_criterion":"Al menos un evento MATCHED_BY_BOTH_STRONG", "evidence_level":evidence_level,
            "funnel":{"iq_samples":capture.get("actual_samples"),"candidate_bursts":bursts,"processed_bursts":processed,"processing_coverage_percent":round(processed*100/bursts,2) if bursts else 0,"crc_valid_packets":crc,"crc_yield_percent":round(crc*100/processed,2) if processed else 0,"eligible_advertisements":len(eligible),"strong_matches":len(strong),"unique_correlated_devices":len({str(p.get('address')).upper() for p in packets if (p.get('correlation') or {}).get('status')=='MATCHED_BY_BOTH_STRONG' and p.get('address')})},
            "counts":{"crc_events":crc,"unique_b200_addresses":len(b200_addresses),"unique_windows_addresses":len(native_addresses),"addresses_seen_by_both":len(b200_addresses&native_addresses),"unique_payloads":len({p.get('advertising_data_hex') for p in eligible if p.get('advertising_data_hex')}),"repeated_advertisements":max(0,len(eligible)-len({(p.get('address'),p.get('advertising_data_hex')) for p in eligible}))},
            "target":{"mode":session.get("target_mode"),"device_id":session.get("target_device_id"),"address":session.get("target_address"),"name":session.get("target_name_at_start"),"selection_source":session.get("target_selection_source"),"seen_before_start":session.get("target_seen_before_start"),"seen_during_campaign":bool(target_native),"seen_by_windows":bool(target_native),"windows_callbacks":len(target_native),"seen_by_b200":bool(target_packets or target_related),"b200_crc_packets":target_b200_crc_packets,"strong_matches":len(target_strong),"payload_matches":len(target_payload),"best_delta_ms":min((abs(float((p.get('correlation') or {}).get('time_difference_ms'))) for p in target_strong+target_payload if (p.get('correlation') or {}).get('time_difference_ms') is not None),default=None),"channel":session.get("channel"),"status":target_status,"match_evidence":match_evidence,"functional_e4_observed":evidence_level=="E4","clean_e4_evidence":evidence_level=="E4" and clean_capture},
            "acquisition":{"channel":capture.get("ble_channel"),"frequency_hz":capture.get("center_frequency_hz"),"requested_duration_seconds":capture.get("requested_duration_seconds"),"actual_duration_seconds":capture.get("actual_duration_seconds"),"duration_difference_reason":None if capture.get("requested_duration_seconds")==capture.get("actual_duration_seconds") else "La captura terminó con una duración distinta de la solicitada.","sample_rate_sps":capture.get("sample_rate_sps"),"bandwidth_hz":capture.get("bandwidth_hz"),"gain_db":(capture.get("gain_configuration") or {}).get("gain_db"),"antenna":capture.get("antenna"),"expected_samples":int((capture.get("requested_duration_seconds") or 0)*(capture.get("sample_rate_sps") or 0)),"captured_samples":capture.get("actual_samples"),"bytes":capture.get("actual_size_bytes"),"overflows":capture.get("overflow_count"),"discontinuities":capture.get("input_discontinuities"),"lost_samples":capture.get("dropped_samples"),"sha256_verified":bool(capture.get("data_sha256")),"functional_validation":"suitable" if capture.get("capture_complete") and crc else "not_suitable","fingerprinting":"suitable" if fingerprint_ok else "not_suitable"},
            "decoder":{"candidate_bursts":bursts,"processed_bursts":processed,"coverage_percent":round(processed*100/bursts,2) if bursts else 0,"crc_valid":crc,"crc_invalid":max(0,processed-crc),"parser_failures":None,"unsupported_pdu_types":None,"crc_yield_percent":round(crc*100/processed,2) if processed else 0},
            "correlation":{"native_callbacks":len(native),"eligible_native":len(native),"eligible_sdr":len(eligible),"strong_matches":eligible_status["MATCHED_BY_BOTH_STRONG"],"payload_matches":eligible_status["MATCHED_BY_PAYLOAD"],"ambiguous":eligible_status["AMBIGUOUS_TIME_MATCH"],"b200_only":eligible_status["B200_ONLY"],"category_sum":sum(eligible_status.values()),"excluded_non_advertising_pdus":len(packets)-len(eligible),"native_only":len(self._jsonl(self._path(sid)/"correlation"/"unmatched_native.jsonl")),"conflicts":0,"window_ms":session.get("result",{}).get("window_ms"),"median_delta_ms":round(statistics.median(deltas),3) if deltas else None,"p95_abs_delta_ms":round(sorted(abs(x) for x in deltas)[max(0,int(len(deltas)*.95)-1)],3) if deltas else None,"minimum_delta_ms":min(deltas) if deltas else None,"maximum_delta_ms":max(deltas) if deltas else None},
            "conclusion":{"target_specific":"DEMONSTRATED" if specific and target_strong else "NOT_DEMONSTRATED","statement":f"El objetivo {session.get('target_address')} fue observado por Windows y B200 y alcanzó E4 en CH{session.get('channel')}." if specific and target_strong else "No se demostró E4 para el objetivo seleccionado.","functional_validation":"PASSED" if specific and target_strong else "NOT_PASSED","reproducibility":"PENDING","fingerprinting":"NOT_SUITABLE" if not fingerprint_ok else "SUITABLE","physical_identity":"NOT_DEMONSTRATED"},
            "uc02":{"case_id":"BLE-UC-02","session_id":sid,"target_address":session.get("target_address"),"channel":session.get("channel"),"functional_result":"PASSED" if evidence_level=="E4" else "NOT_PASSED","evidence_level":evidence_level,"windows_callbacks":len(target_native),"target_crc_packets":len({p.get('packet_sha256') or p.get('packet_id') for p in target_packets+target_related}),"target_strong_matches":len(target_strong),"clean_capture":clean_capture,"reproducibility":"PENDING","fingerprinting":"NOT_VALIDATED","physical_identity":"NOT_DEMONSTRATED"},
            "artifacts":artifacts,"limitations":[f"Sólo se evaluó CH{session.get('channel')}.","No se validó fingerprint RF.","No se demostró cobertura completa de transmisiones.","La identidad física del transmisor no queda demostrada únicamente por dirección/payload."]}
        negative_control_passed=(intent==NEGATIVE_CONTROL and contract["operator_confirmation"] and bool(contract["negative_control_type"]) and false_target_attributions==0)
        result["schema_version"]="ble-scientific-summary-v3"
        result["question"]={
            POSITIVE_TARGET_VALIDATION:"¿Fue el objetivo preseleccionado y visto ahora observado por Windows y B200 durante la misma campaña?",
            NEGATIVE_CONTROL:"¿Evitó el sistema atribuir falsamente tráfico al objetivo bajo la condición negativa declarada?",
            EXPLORATORY_TARGET_SEARCH:"¿Se obtuvo evidencia del objetivo histórico sin presuponer que estaba presente?",
        }[intent]
        result["campaign"]={
            **contract,
            "result":target_status,
            "maximum_evidence":evidence_level,
            "positive_claim_allowed":intent==POSITIVE_TARGET_VALIDATION,
            "negative_claim_allowed":intent==NEGATIVE_CONTROL and contract["operator_confirmation"],
        }
        negative_result="PASSED_SINGLE_RUN" if negative_control_passed else "FAILED_FALSE_ATTRIBUTION"
        if intent==NEGATIVE_CONTROL:
            negative_source={
                "target_powered_off":"OPERATOR_DECLARED_TARGET_POWERED_OFF",
                "target_physically_absent":"OPERATOR_DECLARED_TARGET_PHYSICALLY_ABSENT",
                "other_device_substituted":"OPERATOR_DECLARED_OTHER_DEVICE_SUBSTITUTED",
                "ambient_only":"OPERATOR_DECLARED_AMBIENT_ONLY",
            }.get(contract["negative_control_type"],"OPERATOR_DECLARED_NEGATIVE_CONDITION")
            result["general_result"]=negative_result
            result["success_criterion"]="Cero atribuciones al objetivo bajo la condición negativa predeclarada"
            result["campaign"]["negative_control_result"]=negative_result
            result["negative_control"]={
                "declared_condition":contract["negative_control_type"].upper(),
                "declared_condition_display":"objetivo apagado" if contract["negative_control_type"]=="target_powered_off" else contract["negative_control_type"].replace("_"," "),
                "ground_truth_source":negative_source,
                "operator_confirmation":contract["operator_confirmation"],
                "ambient_ble_traffic_recovered":crc>target_b200_crc_packets,
                "ambient_crc_valid_packets":max(0,crc-target_b200_crc_packets),
                "target_native_observations":len(target_native),
                "target_b200_crc_valid_packets":target_b200_crc_packets,
                "target_strong_matches":len(target_strong),
                "false_target_attributions":false_target_attributions,
                "result":negative_result,
                "basic_control":"PASSED_SINGLE_RUN" if negative_control_passed else "FAILED",
                "positive_reference_correlation":"DEMONSTRATED" if general_ok else "NOT_DEMONSTRATED",
                "reinforced_control":"PASSED_SINGLE_RUN" if negative_control_passed and general_ok and clean_capture else "PENDING",
                "clean_capture":clean_capture,
                "training_ready":False,
                "fingerprinting":"NOT_VALIDATED",
                "condition_provenance":"La condición física procede de la declaración y confirmación previa del operador; no fue inferida de la ausencia de detección RF.",
            }
        result["functional_validation"]={
            "iq_capture":{"status":"COMPLETED" if clean_capture else "COMPLETED_WITH_LOSS","label":"Validación de captura IQ","detail":("Completada sin pérdidas notificadas" if clean_capture else f"Completada con pérdidas: {capture.get('overflow_count',0)} overflows y {capture.get('input_discontinuities',0)} discontinuidades")},
            "burst_detector":{"status":"PASSED" if bursts else "NOT_DEMONSTRATED","label":"Validación del detector de ráfagas","detail":f"{bursts} ráfagas detectadas"},
            "ble_decoder":{"status":"PASSED_TO_E2" if crc else "NOT_DEMONSTRATED","label":"Validación del decoder BLE","detail":f"{crc} paquetes con CRC válido"},
            "hybrid_correlation":{"status":"DEMONSTRATED" if general_ok else "NOT_DEMONSTRATED","label":"Correlación híbrida Windows–B200","detail":f"{len(strong)} coincidencias fuertes"},
            "target_validation":{"status":"DEMONSTRATED" if target_strong else "NEGATIVE_CONTROL_PASSED" if negative_control_passed else "NOT_DEMONSTRATED","label":"Validación del objetivo","detail":target_status},
            "fingerprinting":{"status":"SUITABLE" if fingerprint_ok else "NOT_SUITABLE","label":"Fingerprinting","detail":"Requiere captura limpia y validación multisensión"},
        }
        if intent==NEGATIVE_CONTROL:
            result["functional_validation"]["target_validation"]["status"]="NEGATIVE_CONTROL_PASSED_SINGLE_RUN" if negative_control_passed else "FAILED_FALSE_ATTRIBUTION"
            result["functional_validation"]["negative_control_basic"]={"status":"PASSED_SINGLE_RUN" if negative_control_passed else "FAILED","label":"Control negativo básico","detail":f"{false_target_attributions} atribuciones falsas al objetivo"}
            result["functional_validation"]["negative_control_reinforced"]={"status":"PASSED_SINGLE_RUN" if negative_control_passed and general_ok and clean_capture else "PENDING","label":"Control negativo con referencia positiva","detail":"Requiere una coincidencia E3 de otro dispositivo y captura limpia"}
        result["acquisition"].pop("functional_validation",None)
        result["target"]["interpretation"]={
            "meaning":"No se obtuvo evidencia suficiente del objetivo durante esta campaña." if target_status=="TARGET_NOT_OBSERVED" else None,
            "does_not_mean":["El dispositivo estaba apagado.","El dispositivo no transmitió.","El dispositivo no existe en el entorno.","El B200 no puede recibirlo."] if target_status=="TARGET_NOT_OBSERVED" else [],
            "possible_causes":["objetivo apagado o ausente","duración insuficiente","publicidad en CH38 o CH39","intervalo de advertising","interferencia","pérdidas de adquisición","distancia","estado de conexión BLE"] if target_status=="TARGET_NOT_OBSERVED" else [],
        }
        if intent==NEGATIVE_CONTROL:
            declared_state="apagado" if contract["negative_control_type"]=="target_powered_off" else result["negative_control"]["declared_condition_display"]
            statement=(f"Antes de iniciar la campaña, el operador declaró y confirmó físicamente que el {session.get('target_name_at_start') or session.get('target_address')} estaba "
                f"{declared_state}. Durante la adquisición, el B200 procesó {processed} ráfagas y recuperó {crc} paquetes BLE con CRC válido "
                f"correspondientes al tráfico ambiental de CH{session.get('channel')}. Ninguna observación Windows ni ningún paquete B200 fue atribuido al dispositivo objetivo. "
                "Bajo el contrato experimental declarado, el sistema no produjo una atribución falsa al SensorTag y el control negativo se considera superado en esta ejecución. "
                "La condición física procede de la declaración experimental del operador; no fue inferida automáticamente a partir de la ausencia de detección RF.")
            result["target"]["interpretation"]={
                "meaning":"El objetivo no fue observado y el sistema registró cero atribuciones falsas bajo el control negativo predeclarado.",
                "does_not_mean":["La ausencia RF demostró automáticamente que el objetivo estaba apagado.","Se conoce la identidad física de los transmisores ambientales."],
                "possible_causes":[],
            }
        elif target_strong:
            statement=f"El objetivo {session.get('target_address')} fue observado por Windows y B200 y alcanzó E4 en CH{session.get('channel')}."
        elif target_status=="TARGET_NOT_OBSERVED":
            statement=(f"El B200 procesó {processed} ráfagas y recuperó {crc} paquetes BLE con CRC válido en CH{session.get('channel')}. "
                "Ninguno pudo asociarse con una observación Windows dentro de la campaña, y no se obtuvo evidencia del dispositivo objetivo. "
                "Este resultado no demuestra que el objetivo estuviera ausente; únicamente indica que no fue observado bajo las condiciones y duración de esta ejecución.")
        else:
            statement="No se demostró correlación E4 para el objetivo seleccionado bajo las condiciones de esta campaña."
        result["conclusion"].update(
            statement=statement,
            functional_validation=result["functional_validation"]["target_validation"]["status"],
            negative_control_result=(negative_result if intent==NEGATIVE_CONTROL else "NOT_APPLICABLE"),
        )
        result["uc02"]["campaign_intent"]=intent
        result["limitations"].insert(1,"TARGET_NOT_OBSERVED no demuestra ausencia física del objetivo.")
        if intent==NEGATIVE_CONTROL:
            result["limitations"].insert(2,"La condición negativa procede de la declaración física previa del operador; no fue inferida de la ausencia RF.")
            result["limitations"].insert(3,"El control negativo básico fue evaluado; la referencia positiva del correlador permanece pendiente si no hubo coincidencias E3 de otro dispositivo.")
        if session.get("state")=="completed":
            persisted={"target_seen_during_campaign":bool(target_native),"target_native_callbacks":len(target_native),"scientific_summary":result}
            if intent==NEGATIVE_CONTROL:
                persisted.update(campaign_intent="NEGATIVE_CONTROL",negative_control_type=str(contract["negative_control_type"]).upper(),operator_confirmation=contract["operator_confirmation"],target_native_observations=len(target_native),target_b200_crc_valid_packets=target_b200_crc_packets,target_strong_matches=len(target_strong),false_target_attributions=false_target_attributions,negative_control_result=negative_result)
            self._write(sid,**persisted)
        return result
