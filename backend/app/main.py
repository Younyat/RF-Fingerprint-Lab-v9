from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import settings
from app.infrastructure.di.container import ApplicationContainer
from app.infrastructure.web.api.routes.demodulation_routes import build_demodulation_router
from app.infrastructure.web.api.routes.device_routes import build_device_router
from app.infrastructure.web.api.routes.marker_routes import build_marker_router
from app.infrastructure.web.api.routes.modulated_signal_routes import build_modulated_signal_router
from app.infrastructure.web.api.routes.preset_routes import build_preset_router
from app.infrastructure.web.api.routes.recording_routes import build_recording_router
from app.infrastructure.web.api.routes.session_routes import build_session_router
from app.infrastructure.web.api.routes.spectrum_routes import build_spectrum_router
from app.infrastructure.web.api.routes.waterfall_routes import build_waterfall_router
from app.modules.fingerprinting import FingerprintingService, build_fingerprinting_router
from app.modules.mlops import MlOpsService, build_mlops_router
from app.modules.kiwisdr.module import build_kiwisdr_module
from app.modules.kiwisdr.presentation.routes import build_kiwi_session_router, build_receiver_router


logging.basicConfig(
    level=getattr(logging, settings.logging.level.upper(), logging.INFO),
    format=settings.logging.format,
)

container = ApplicationContainer.build()
kiwisdr_module = build_kiwisdr_module(settings.storage.storage_root)
fingerprinting_service = FingerprintingService(settings.storage.fingerprinting_dir)
mlops_service = MlOpsService(
    settings.storage.mlops_dir,
    settings.storage.mlops_scripts_dir,
    settings.storage.backend_requirements_path,
    radioconda_python=os.environ.get("RADIOCONDA_PYTHON", r"C:\Users\Usuario\radioconda\python.exe"),
)

app = FastAPI(
    title=settings.app.app_name,
    version=settings.app.app_version,
    debug=settings.app.debug,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(build_device_router(container.device_controller), prefix=settings.api.base_path)
app.include_router(build_spectrum_router(container.spectrum_controller), prefix=settings.api.base_path)
app.include_router(build_waterfall_router(container.spectrum_controller), prefix=settings.api.base_path)
app.include_router(build_marker_router(container.marker_controller), prefix=settings.api.base_path)
app.include_router(build_recording_router(container.recording_controller), prefix=settings.api.base_path)
app.include_router(build_demodulation_router(container.demodulation_controller), prefix=settings.api.base_path)
app.include_router(build_modulated_signal_router(container.modulated_signal_controller), prefix=settings.api.base_path)
app.include_router(
    build_fingerprinting_router(fingerprinting_service, container.modulated_signal_controller),
    prefix=settings.api.base_path,
)
app.include_router(build_mlops_router(mlops_service), prefix=settings.api.base_path)
app.include_router(build_receiver_router(kiwisdr_module.receiver_controller), prefix=settings.api.base_path)
app.include_router(build_kiwi_session_router(kiwisdr_module.session_controller), prefix=settings.api.base_path)
app.include_router(build_preset_router(container.preset_controller), prefix=settings.api.base_path)
app.include_router(
    build_session_router(
        create_session_use_case=container.create_session_use_case,
        get_active_device_state=container.device_manager.get_device_state,
    ),
    prefix=settings.api.base_path,
)


@app.on_event("startup")
def start_kiwisdr_catalog_refresh() -> None:
    kiwisdr_module.start_background_refresh()


@app.get("/")
def root() -> dict:
    return {
        "app_name": settings.app.app_name,
        "version": settings.app.app_version,
        "status": "ok",
    }
