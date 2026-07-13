import hashlib, json
from pathlib import Path
import pytest
from pydantic import ValidationError
from app.infrastructure.ble.ble_contracts import BleJobRequest, WORKER_COMMIT
from app.infrastructure.ble.ble_artifact_validator import BleArtifactValidator
from app.infrastructure.ble.ble_errors import ArtifactHashMismatch, InvalidCrcPacketPublished
from app.infrastructure.ble.ble_repository import BleRepository
from app.infrastructure.ble.ble_job_manager import BleJobManager

def request(mode="validated_bitstream_replay"):
    return {"input_mode":mode,"source":{"type":"gate1b_fixture","fixture_id":"x","source_commit":WORKER_COMMIT}}

def make_artifacts(root:Path,jid="BLE-JOB-000001",valid=True):
    packets=[{"packet_id":"p1","crc_valid":valid}]
    contents={"candidate_packets.jsonl":"","confirmed_packets.jsonl":json.dumps(packets[0])+"\n","parsed_packets.jsonl":json.dumps({"packet_id":"p1"})+"\n","advertisements.jsonl":json.dumps({"packet_id":"p1"})+"\n"}
    files=[]
    for name,data in contents.items():
        (root/name).write_text(data,encoding="utf-8"); raw=(root/name).read_bytes(); files.append({"path":name,"sha256":hashlib.sha256(raw).hexdigest(),"size_bytes":len(raw)})
    manifest={"contract_version":"ble-job-v1","job_id":jid,"worker_commit":WORKER_COMMIT,"scientific_status":"BLE_P0_INCOMPLETE","counts":{"confirmed_packets":1},"files":files}
    (root/"artifacts_manifest.json").write_text(json.dumps(manifest),encoding="utf-8")

def test_contract_rejects_wrong_worker_commit():
    body=request(); body["expected_worker_commit"]="wrong"
    with pytest.raises(ValidationError): BleJobRequest.model_validate(body)

def test_validator_accepts_crc_valid_artifacts(tmp_path):
    make_artifacts(tmp_path); assert BleArtifactValidator().validate(tmp_path,"BLE-JOB-000001")["counts"]["confirmed_packets"]==1

def test_validator_rejects_invalid_crc_publication(tmp_path):
    make_artifacts(tmp_path,valid=False)
    with pytest.raises(InvalidCrcPacketPublished): BleArtifactValidator().validate(tmp_path,"BLE-JOB-000001")

def test_validator_rejects_hash_mismatch(tmp_path):
    make_artifacts(tmp_path); (tmp_path/"confirmed_packets.jsonl").write_text("{}\n")
    with pytest.raises(ArtifactHashMismatch): BleArtifactValidator().validate(tmp_path,"BLE-JOB-000001")

def test_disabled_manager_does_not_start_worker(tmp_path):
    class Never:
        def run(self,*args): raise AssertionError("worker started")
    manager=BleJobManager(BleRepository(tmp_path),Never(),False)
    with pytest.raises(PermissionError): manager.create(request())
