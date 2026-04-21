from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel


class MarkerBandIqCaptureBody(BaseModel):
    start_frequency_hz: float
    stop_frequency_hz: float
    duration_seconds: float = 5.0
    label: str = ""
    modulation_hint: str = "unknown"
    notes: str = ""
    file_format: str = "cfile"


def build_modulated_signal_router(controller) -> APIRouter:
    router = APIRouter(prefix="/modulated-signals", tags=["modulated-signals"])

    @router.post("/captures")
    async def capture_marker_band_iq(body: MarkerBandIqCaptureBody):
        try:
            return controller.capture_marker_band(
                start_frequency_hz=body.start_frequency_hz,
                stop_frequency_hz=body.stop_frequency_hz,
                duration_seconds=body.duration_seconds,
                label=body.label,
                modulation_hint=body.modulation_hint,
                notes=body.notes,
                file_format=body.file_format,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/captures")
    async def list_captures():
        return {"captures": controller.list_captures()}

    @router.get("/captures/{capture_id}")
    async def get_capture(capture_id: str):
        try:
            return controller.get_capture(capture_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/captures/{capture_id}/iq")
    async def download_iq(capture_id: str):
        try:
            path = controller.get_iq_file(capture_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path, media_type="application/octet-stream", filename=path.name)

    @router.get("/captures/{capture_id}/metadata")
    async def download_metadata(capture_id: str):
        try:
            path = controller.get_metadata_file(capture_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path, media_type="application/json", filename=path.name)

    return router
