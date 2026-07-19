import json
from pathlib import Path

from app.infrastructure.ble.dataset_studio_manager import BleDatasetStudioManager

def put(path:Path,value): path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(value)+"\n",encoding="utf-8")
def lines(path:Path,values): path.parent.mkdir(parents=True,exist_ok=True); path.write_text("".join(json.dumps(x)+"\n" for x in values),encoding="utf-8")

def test_dataset_protocol_examples_quarantine_split_and_datasheet(tmp_path):
    hybrid,captures,definitions=tmp_path/"hybrid",tmp_path/"captures",tmp_path/"defs"
    definitions.mkdir(); put(definitions/"evidence_level_definitions.json",{"schema_version":"1.0.0"})
    sid,cid="SESSION-1","CAPTURE-1"; put(hybrid/sid/"session_manifest.json",{"state":"completed","capture_id":cid,"channel":37,"target_address":"AA:BB","target_device_id":"dev-1"})
    put(captures/cid/"capture_manifest.json",{"actual_duration_seconds":1,"data_sha256":"abc"}); put(captures/cid/"quality_report.json",{"overflow_count":1,"discontinuity_count":0})
    lines(captures/cid/"burst_candidates.jsonl",[{"burst_id":"b1","sample_start":10,"sample_count":20,"iq_segment_sha256":"iq1"},{"burst_id":"b2","sample_start":40,"sample_count":10,"iq_segment_sha256":"iq2"}])
    lines(hybrid/sid/"correlation"/"decoded_packets.jsonl",[{"burst_id":"b1","sample_start":10,"sample_end":30,"channel_index":37,"address":"AA:BB","crc_valid":True,"pdu_type_name":"ADV_IND","iq_segment_sha256":"iq1","packet_sha256":"p1","correlation":{"status":"MATCHED_BY_BOTH_STRONG","native_observation_id":"n1","address_match":True,"payload_match":True,"time_difference_ms":2}}])
    manager=BleDatasetStudioManager(tmp_path/"datasets",hybrid,captures,definitions)
    manager.create({"dataset_id":"TEST-DS","version":"1.0.0","intended_task":"logical_device_identification","devices":[{"address":"AA:BB","physical_unit_id":"UNIT-1"}],"channels":[37],"days":[1],"sessions_per_condition":1})
    manager.freeze("TEST-DS","1.0.0"); result=manager.ingest("TEST-DS","1.0.0",{"hybrid_session_id":sid})
    assert len(result["examples"])==2
    assert {x["evidence_level"] for x in result["examples"]}=={"E1","E4"}
    assert all(x["inclusion_state"]=="QUARANTINED_SESSION_LOSS" for x in result["examples"])
    assert result["quality"]["metrics"]["crc_yield_percent"]==50
    split=manager.split("TEST-DS","1.0.0",{"policy":"session"}); assert split["leakage_check"]=="PASSED"
    root=tmp_path/"datasets"/"TEST-DS"/"1.0.0"
    assert (root/"dataset_datasheet.md").is_file() and (root/"checksums.sha256").is_file()
    assert manager.export("TEST-DS","1.0.0","e4").is_file()

def test_published_content_requires_new_version(tmp_path):
    definitions=tmp_path/"defs"; definitions.mkdir()
    manager=BleDatasetStudioManager(tmp_path/"datasets",tmp_path/"hybrid",tmp_path/"captures",definitions)
    manager.create({"dataset_id":"VERSIONED","version":"1.0.0"}); manager.freeze("VERSIONED","1.0.0")
    derived=manager.new_version("VERSIONED","1.0.0","1.1.0")
    assert derived["manifest"]["version"]=="1.1.0" and derived["protocol"]["frozen"] is False

def test_exploratory_e2_session_produces_expected_distribution_without_target_negatives(tmp_path):
    hybrid,captures,definitions=tmp_path/"hybrid",tmp_path/"captures",tmp_path/"defs"
    definitions.mkdir(); put(definitions/"evidence_level_definitions.json",{"schema_version":"1.0.0"})
    sid,cid="BLE-HYBRID-EXPLORATORY","BLE-IQ-LOSS"
    put(hybrid/sid/"session_manifest.json",{
        "state":"completed","capture_id":cid,"channel":37,"target_mode":"specific_device",
        "target_address":"BC:6A:29:AB:DE:13","target_device_id":"sensor-tag",
        "target_selection_source":"native_registry_history","target_seen_before_start":False,
    })
    put(captures/cid/"capture_manifest.json",{"actual_duration_seconds":3,"data_sha256":"abc"})
    put(captures/cid/"quality_report.json",{"overflow_count":3,"discontinuity_count":3})
    lines(captures/cid/"burst_candidates.jsonl",[
        {"burst_id":f"b{i}","sample_start":i*100,"sample_count":80,"iq_segment_sha256":f"iq{i}"}
        for i in range(100)
    ])
    lines(hybrid/sid/"correlation"/"decoded_packets.jsonl",[
        {"burst_id":f"b{i}","sample_start":i*100,"sample_end":i*100+80,"channel_index":37,
         "address":"11:22:33:44:55:66","crc_valid":True,
         "pdu_type_name":"ADV_IND" if i<29 else "SCAN_REQ","packet_sha256":f"p{i}",
         "correlation":{"status":"B200_ONLY"}}
        for i in range(33)
    ])
    manager=BleDatasetStudioManager(tmp_path/"datasets",hybrid,captures,definitions)
    manager.create({"dataset_id":"E2-EXPLORATORY","version":"1.0.0","devices":[{"address":"BC:6A:29:AB:DE:13","physical_unit_id":"UNIT-1"}],"channels":[37]})
    manager.freeze("E2-EXPLORATORY","1.0.0")
    result=manager.ingest("E2-EXPLORATORY","1.0.0",{"hybrid_session_id":sid})
    examples=result["examples"]
    levels=result["quality"]["metrics"]["evidence_levels"]
    assert len(examples)==100 and levels=={"E2":33,"E1":67}
    assert result["quality"]["metrics"]["evidence_levels_cumulative"]=={"E1":100,"E2":33,"E3":0,"E4":0}
    assert all(item["inclusion_state"]=="QUARANTINED_SESSION_LOSS" for item in examples)
    assert all(item["campaign_intent"]=="exploratory_target_search" for item in examples)
    assert all(item["target_relation"]=="UNKNOWN" for item in examples)
    assert sum(item["correlation_state"]=="B200_ONLY" and item["pdu_type"]=="ADV_IND" for item in examples)==29
    assert not any(item["inclusion_state"]=="INCLUDED_NEGATIVE" for item in examples)


def test_declared_negative_control_preserves_evidence_and_contract_relation_in_quarantine(tmp_path):
    hybrid,captures,definitions=tmp_path/"hybrid",tmp_path/"captures",tmp_path/"defs"
    definitions.mkdir(); put(definitions/"evidence_level_definitions.json",{"schema_version":"1.0.0"})
    sid,cid="BLE-HYBRID-NEGATIVE","BLE-IQ-NEGATIVE-LOSS"
    put(hybrid/sid/"session_manifest.json",{
        "state":"completed","capture_id":cid,"channel":37,"target_mode":"specific_device",
        "target_address":"B0:B4:48:C0:36:06","target_device_id":"cc2650",
        "campaign_intent":"NEGATIVE_CONTROL","negative_control_type":"TARGET_POWERED_OFF",
        "operator_confirmation":True,"negative_control_result":"PASSED_SINGLE_RUN",
        "false_target_attributions":0,
    })
    put(captures/cid/"capture_manifest.json",{"actual_duration_seconds":3,"data_sha256":"negative-hash"})
    put(captures/cid/"quality_report.json",{"overflow_count":1,"discontinuity_count":1})
    lines(captures/cid/"burst_candidates.jsonl",[
        {"burst_id":f"b{i}","sample_start":i*100,"sample_count":80,"iq_segment_sha256":f"iq{i}"}
        for i in range(75)
    ])
    lines(hybrid/sid/"correlation"/"decoded_packets.jsonl",[
        {"burst_id":f"b{i}","sample_start":i*100,"sample_end":i*100+80,"channel_index":37,
         "address":"11:22:33:44:55:66","crc_valid":True,"pdu_type_name":"ADV_NONCONN_IND",
         "packet_sha256":f"p{i}","correlation":{"status":"B200_ONLY"}}
        for i in range(30)
    ])
    manager=BleDatasetStudioManager(tmp_path/"datasets",hybrid,captures,definitions)
    manager.create({"dataset_id":"NEGATIVE-DS","version":"1.0.0","devices":[{"address":"B0:B4:48:C0:36:06","physical_unit_id":"CC2650-UNIT-01"}],"channels":[37]})
    manager.freeze("NEGATIVE-DS","1.0.0")
    result=manager.ingest("NEGATIVE-DS","1.0.0",{"hybrid_session_id":sid})
    examples=result["examples"]
    assert len(examples)==75
    assert result["quality"]["metrics"]["evidence_levels"]=={"E2":30,"E1":45}
    assert all(item["target_relation"]=="NEGATIVE_BY_EXPERIMENTAL_CONTRACT" for item in examples)
    assert all(item["negative_ground_truth_source"]=="OPERATOR_DECLARED_TARGET_POWERED_OFF" for item in examples)
    assert all(item["target_address"]=="B0:B4:48:C0:36:06" for item in examples)
    assert all(item["inclusion_state"]=="QUARANTINED_SESSION_LOSS" for item in examples)
    assert all("ambient_device_identity" not in item for item in examples)
    assert result["quality"]["metrics"]["contract_negative_examples"]==75
    assert result["quality"]["metrics"]["quarantined_contract_negative_examples"]==75
    assert result["quality"]["scientific_status"]["declared_negative_control"]=="PASSED_SINGLE_RUN"
    assert result["quality"]["scientific_status"]["false_target_attributions_in_negative_controls"]==0
    datasheet=(tmp_path/"datasets"/"NEGATIVE-DS"/"1.0.0"/"dataset_datasheet.md").read_text(encoding="utf-8")
    assert "NEGATIVE_BY_EXPERIMENTAL_CONTRACT" in datasheet
    assert "no identifica físicamente al transmisor ambiental" in datasheet
