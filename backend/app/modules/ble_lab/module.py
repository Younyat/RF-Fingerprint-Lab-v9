import os, sys
from pathlib import Path
from fastapi import APIRouter
from app.infrastructure.ble.ble_job_manager import BleJobManager
from app.infrastructure.ble.ble_repository import BleRepository
from app.infrastructure.ble.ble_worker_adapter import BleWorkerAdapter, WorkerConfig
from app.infrastructure.ble.ble_gate2a2_job_manager import BleGate2a2JobManager, BleGate2a2WorkerAdapter, Gate2a2WorkerConfig
from app.modules.ble_lab.routes import build_ble_router
from app.modules.ble_lab.gate2a2_routes import build_ble_gate2a2_router
from app.infrastructure.ble.capture.ble_capture_routes import build_ble_capture_router
from app.infrastructure.ble.capture.ble_capture_job_manager import BleCaptureJobManager
from app.infrastructure.ble.capture.ble_iq_capture_service import BleIqCaptureService, CaptureWorkerConfig
from app.infrastructure.ble.capture.ble_sdr_device_service import BleSdrDeviceService, SdrProbeConfig
from app.modules.types import BackendModuleDefinition
from app.config.settings import settings

def env_bool(name,default=False): return os.environ.get(name,str(default)).lower() in {"1","true","yes","on"}

# Four independent BLE feature flags -- none of them reused for more than one
# capability. BLE_ANALYZER_V1 controls only the frozen Gate 1B replay pipeline
# (unchanged). BLE_IQ_OFFLINE_EXPERIMENTAL_ENABLED controls only the new,
# separate Gate 2A.2 offline-IQ-file analysis flow below. SDR capture and
# combined capture+decode remains unavailable. Real IQ capture is a separate
# experimental capability, off by default, backed by the SoapySDR worker.
BLE_CAPTURE_AND_DECODE_ENABLED = False

def _build(context):
    root=settings.storage.storage_root
    backend=settings.storage.backend_root
    config=WorkerConfig(Path(os.environ.get("BLE_WORKER_REPOSITORY",r"C:\Users\Usuario\ble-worker-gate1b-frozen")),Path(os.environ.get("BLE_WORKER_PYTHON",sys.executable)),Path(os.environ.get("BLE_WORKER_ENTRY_POINT",backend/"tools"/"ble_gate1b_replay_worker.py")),float(os.environ.get("BLE_WORKER_TIMEOUT_SECONDS","60")))
    gate1b_router = build_ble_router(BleJobManager(BleRepository(root/"ble"/"jobs"),BleWorkerAdapter(config),env_bool("BLE_ANALYZER_V1")))

    gate2a2_config = Gate2a2WorkerConfig(
        Path(os.environ.get("BLE_GATE2A2_REPOSITORY", r"C:\Users\Usuario\ble-worker-lab")),
        Path(os.environ.get("BLE_GATE2A2_WORKER_PYTHON", sys.executable)),
        Path(os.environ.get("BLE_GATE2A2_WORKER_ENTRY_POINT", backend/"tools"/"ble_gate2a2_offline_worker.py")),
        float(os.environ.get("BLE_GATE2A2_WORKER_TIMEOUT_SECONDS", "120")),
    )
    gate2a2_manager = BleGate2a2JobManager(
        BleRepository(root/"ble"/"gate2a2_jobs"),
        BleGate2a2WorkerAdapter(gate2a2_config),
        env_bool("BLE_IQ_OFFLINE_EXPERIMENTAL_ENABLED"),
    )
    gate2a2_router = build_ble_gate2a2_router(gate2a2_manager)

    runtime_root_value = os.environ.get("BLE_SDR_RUNTIME_ROOT", r"C:\Users\Usuario\radioconda")
    runtime_root = Path(runtime_root_value) if runtime_root_value else None
    capture_python = Path(os.environ.get("BLE_SDR_PYTHON_PATH", os.environ.get("RADIOCONDA_PYTHON", str(runtime_root / "python.exe") if runtime_root else sys.executable)))
    capture_tool = Path(os.environ.get("BLE_CAPTURE_SDR_TOOL", backend / "tools" / "ble_sdr_capture_worker.py"))
    device_service = BleSdrDeviceService(SdrProbeConfig(capture_python, capture_tool, runtime_root))
    capture_service = BleIqCaptureService(CaptureWorkerConfig(capture_python, capture_tool, runtime_root))
    capture_manager = BleCaptureJobManager(
        root / "ble" / "iq_captures", device_service, capture_service,
        env_bool("BLE_IQ_CAPTURE_EXPERIMENTAL_ENABLED"),
    )
    capture_router = build_ble_capture_router(capture_manager, gate2a2_manager)

    combined = APIRouter()
    combined.include_router(gate1b_router)
    combined.include_router(gate2a2_router)
    combined.include_router(capture_router)
    return combined

ble_lab_module=BackendModuleDefinition("ble-lab","BLE Lab",True,85,"Experimental BLE platform integration.",_build)
