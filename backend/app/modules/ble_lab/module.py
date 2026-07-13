import os, sys
from pathlib import Path
from app.infrastructure.ble.ble_job_manager import BleJobManager
from app.infrastructure.ble.ble_repository import BleRepository
from app.infrastructure.ble.ble_worker_adapter import BleWorkerAdapter, WorkerConfig
from app.modules.ble_lab.routes import build_ble_router
from app.modules.types import BackendModuleDefinition
from app.config.settings import settings

def env_bool(name,default=False): return os.environ.get(name,str(default)).lower() in {"1","true","yes","on"}
def _build(context):
    root=settings.storage.storage_root
    backend=settings.storage.backend_root
    config=WorkerConfig(Path(os.environ.get("BLE_WORKER_REPOSITORY",r"C:\Users\Usuario\ble-worker-gate1b-frozen")),Path(os.environ.get("BLE_WORKER_PYTHON",sys.executable)),Path(os.environ.get("BLE_WORKER_ENTRY_POINT",backend/"tools"/"ble_gate1b_replay_worker.py")),float(os.environ.get("BLE_WORKER_TIMEOUT_SECONDS","60")))
    return build_ble_router(BleJobManager(BleRepository(root/"ble"/"jobs"),BleWorkerAdapter(config),env_bool("BLE_ANALYZER_V1")))
ble_lab_module=BackendModuleDefinition("ble-lab","BLE Lab",True,85,"Experimental BLE platform integration.",_build)
