from __future__ import annotations

from app.config.settings import settings
from app.modules.types import BackendModuleDefinition

from .api import ScientificResultsJobManager, ScientificResultsRepository, build_ble_scientific_results_router


def _build(context):
    root = settings.storage.storage_root
    repository = ScientificResultsRepository(
        root / "scientific_reports" / "ble", ble_rffi_studio_root=root / "ble_rffi_studio",
    )
    job_manager = ScientificResultsJobManager(repository, root / "scientific_reports" / "ble" / "jobs")
    return build_ble_scientific_results_router(repository, job_manager)


ble_scientific_results_module = BackendModuleDefinition(
    "ble-scientific-results", "BLE Scientific Results Studio", True, 87,
    "Deterministic orchestrator for BLE paper evidence: frozen analysis contracts, scientific preflight, "
    "and (in later phases) RQ1-4/S1-S2 statistics, figures, tables and LaTeX export. Read-only over "
    "ble_rffi_studio's own manifests and artifacts -- never modifies them.",
    _build,
)
