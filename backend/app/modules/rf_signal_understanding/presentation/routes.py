from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.modules.rf_signal_understanding.application.signal_understanding_service import RFSignalUnderstandingService
from app.modules.rf_signal_understanding.domain.schemas import AnalyzeCaptureRequest, CompareWithRFIntelligenceRequest, TrainingRequest, ValidationRequest


def build_rf_signal_understanding_router(service: RFSignalUnderstandingService, spectrum_controller=None) -> APIRouter:
    router = APIRouter(prefix="/rf-signal-understanding", tags=["rf-signal-understanding"])

    @router.get("/live")
    async def live():
        if spectrum_controller is None:
            raise HTTPException(status_code=503, detail="Live spectrum controller is not available")
        raw_frame = spectrum_controller.get_spectrum(None)
        return service.analyze_live_frame(raw_frame)

    @router.post("/compare-live-with-rf-intelligence")
    async def compare_live_with_rf_intelligence():
        if spectrum_controller is None:
            raise HTTPException(status_code=503, detail="Live spectrum controller is not available")
        raw_frame = spectrum_controller.get_spectrum(None)
        return service.compare_live_with_rf_intelligence(raw_frame)

    @router.post("/analyze")
    async def analyze(request: AnalyzeCaptureRequest):
        try:
            return service.analyze_capture(request)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/results/{analysis_id}")
    async def get_result(analysis_id: str):
        try:
            return service.get_result(analysis_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/compare-with-rf-intelligence")
    async def compare_with_rf_intelligence(request: CompareWithRFIntelligenceRequest):
        try:
            return service.compare_with_rf_intelligence(request)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/train-region-detector")
    async def train_region_detector(request: TrainingRequest):
        return service.train_region_detector(request)

    @router.post("/train-classifier")
    async def train_classifier(request: TrainingRequest):
        return service.train_classifier(request)

    @router.post("/validate")
    async def validate(request: ValidationRequest):
        return service.validate(request)

    @router.get("/models")
    async def models():
        return service.models()

    @router.get("/references")
    async def references():
        return service.references()

    return router
