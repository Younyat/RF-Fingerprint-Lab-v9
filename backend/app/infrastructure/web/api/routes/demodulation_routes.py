from __future__ import annotations
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel


class StartDemodulationBody(BaseModel):
    mode: str
    frequency_hz: float | None = None


class MarkerBandDemodulationBody(BaseModel):
    start_frequency_hz: float
    stop_frequency_hz: float
    mode: str
    duration_seconds: float = 5.0


def build_demodulation_router(controller) -> APIRouter:
    router = APIRouter(prefix="/demodulation", tags=["demodulation"])
    
    @router.post("/start")
    async def start_demodulation(body: StartDemodulationBody):
        return controller.start_demodulation(body.mode)
    
    @router.post("/stop")
    async def stop_demodulation():
        return controller.stop_demodulation()
    
    @router.get("/audio/status")
    async def get_audio_status():
        return controller.get_audio_status()

    @router.post("/marker-band")
    async def demodulate_marker_band(body: MarkerBandDemodulationBody):
        try:
            return controller.demodulate_marker_band(
                start_frequency_hz=body.start_frequency_hz,
                stop_frequency_hz=body.stop_frequency_hz,
                mode=body.mode,
                duration_seconds=body.duration_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/results")
    async def list_demodulation_results():
        return {"results": controller.list_results()}

    @router.get("/results/{demodulation_id}")
    async def get_demodulation_result(demodulation_id: str):
        try:
            return controller.get_result(demodulation_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/audio/{demodulation_id}")
    async def get_demodulation_audio(demodulation_id: str):
        try:
            path = controller.get_audio_file(demodulation_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path, media_type="audio/wav", filename=path.name)
    
    return router
