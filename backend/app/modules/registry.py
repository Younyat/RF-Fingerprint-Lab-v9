from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI

from app.modules.capture_lab.module import capture_lab_module
from app.modules.demodulation.module import demodulation_module
from app.modules.device.module import device_module
from app.modules.fingerprinting.api_module import fingerprinting_module
from app.modules.kiwisdr.api_module import kiwi_receivers_module, kiwi_sessions_module
from app.modules.markers.module import markers_module
from app.modules.mlops.api_module import mlops_module
from app.modules.presets.module import presets_module
from app.modules.recordings.module import recordings_module
from app.modules.sessions.module import sessions_module
from app.modules.spectrum.module import spectrum_module
from app.modules.types import BackendModuleDefinition
from app.modules.waterfall.module import waterfall_module


@dataclass(frozen=True)
class BackendModuleContext:
    container: Any
    kiwisdr_module: Any
    fingerprinting_service: Any
    mlops_service: Any


backend_modules: list[BackendModuleDefinition] = [
    device_module,
    spectrum_module,
    waterfall_module,
    markers_module,
    recordings_module,
    demodulation_module,
    capture_lab_module,
    fingerprinting_module,
    mlops_module,
    kiwi_receivers_module,
    kiwi_sessions_module,
    presets_module,
    sessions_module,
]


def active_backend_modules() -> list[BackendModuleDefinition]:
    return sorted((module for module in backend_modules if module.enabled), key=lambda module: module.order)


def register_backend_modules(app: FastAPI, context: BackendModuleContext, api_prefix: str) -> None:
    for module in active_backend_modules():
        app.include_router(module.build_router(context), prefix=api_prefix)
