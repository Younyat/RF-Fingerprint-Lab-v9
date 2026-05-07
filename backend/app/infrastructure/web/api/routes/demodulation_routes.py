from __future__ import annotations
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Any


class StartDemodulationBody(BaseModel):
    mode: str
    frequency_hz: float | None = None


class MarkerBandDemodulationBody(BaseModel):
    start_frequency_hz: float
    stop_frequency_hz: float
    mode: str
    duration_seconds: float = 5.0
    apply_bandpass_filter: bool = False
    filter_stopband_attenuation_db: float = 60.0
    filter_transition_width_hz: float | None = None


class DatasetDemodulationBody(BaseModel):
    dataset_id: str | None = None
    sample_id: str
    file_path: str
    file_format: str | None = None
    datatype: str | None = None
    sample_rate_hz: float | None = None
    center_frequency_hz: float | None = None
    signal_type: str | None = None
    bandwidth_hz: float | None = None
    capture_duration: float | None = None
    source_dataset: str | None = None
    device_profile: str | None = None
    pipeline: str | None = None
    manual_signal_type: str | None = None
    options: dict[str, Any] = {}


class BleChannelTestBody(BaseModel):
    duration_seconds: float = 1.0
    sample_rate_hz: float = 8_000_000.0
    bandwidth_hz: float = 2_000_000.0


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
    def demodulate_marker_band(body: MarkerBandDemodulationBody):
        try:
            return controller.demodulate_marker_band(
                start_frequency_hz=body.start_frequency_hz,
                stop_frequency_hz=body.stop_frequency_hz,
                mode=body.mode,
                duration_seconds=body.duration_seconds,
                apply_bandpass_filter=body.apply_bandpass_filter,
                filter_stopband_attenuation_db=body.filter_stopband_attenuation_db,
                filter_transition_width_hz=body.filter_transition_width_hz,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/dataset-capture")
    async def demodulate_dataset_capture(body: DatasetDemodulationBody):
        try:
            return controller.demodulate_dataset_capture(body.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/pipelines")
    async def list_demodulation_pipelines():
        return {"pipelines": controller.list_pipelines()}

    @router.post("/ble-advertising/test-channels")
    def test_ble_advertising_channels(body: BleChannelTestBody):
        try:
            return controller.test_ble_advertising_channels(
                duration_seconds=body.duration_seconds,
                sample_rate_hz=body.sample_rate_hz,
                bandwidth_hz=body.bandwidth_hz,
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

    @router.delete("/results/{demodulation_id}")
    async def delete_demodulation_result(demodulation_id: str):
        try:
            return controller.delete_result(demodulation_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/audio/{demodulation_id}")
    async def get_demodulation_audio(demodulation_id: str):
        try:
            path = controller.get_audio_file(demodulation_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path, media_type="audio/wav", filename=path.name)

    @router.get("/outputs/{demodulation_id}/{filename}")
    async def get_demodulation_output(demodulation_id: str, filename: str):
        try:
            path = controller.get_output_file(demodulation_id, filename)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path, filename=path.name)
    
    return router
