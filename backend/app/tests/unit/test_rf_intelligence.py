from app.modules.rf_intelligence.schemas import RFIntelligenceSettings, SpectrumFrameInput
from app.modules.rf_intelligence.service import RFIntelligenceService


def test_rf_intelligence_detects_fm_broadcast_candidate():
    frequencies = [98_000_000 + index * 20_000 for index in range(101)]
    levels = [-92.0] * len(frequencies)
    for index, frequency in enumerate(frequencies):
        if 98_420_000 <= frequency <= 98_580_000:
            levels[index] = -50.0

    service = RFIntelligenceService()
    scene = service.analyze_frame(
        SpectrumFrameInput(
            timestamp_utc="2026-04-28T10:00:00Z",
            center_frequency_hz=99_000_000,
            span_hz=2_000_000,
            frequencies_hz=frequencies,
            levels_db=levels,
        ),
        RFIntelligenceSettings(threshold_offset_db=10.0, min_snr_db=8.0),
    )

    assert scene.summary["total_detections"] == 1
    detection = scene.detections[0]
    assert detection.candidate_family == "broadcast_fm"
    assert detection.label == "WFM broadcast candidate"
    assert detection.snr_db > 30
    assert detection.evidence.frequency_band_match is True
    assert detection.evidence.bandwidth_match is True


def test_rf_intelligence_returns_empty_scene_for_noise_only():
    frequencies = [433_000_000 + index * 10_000 for index in range(100)]
    levels = [-88.0, -89.0, -87.5, -88.5] * 25

    service = RFIntelligenceService()
    scene = service.analyze_frame(
        SpectrumFrameInput(
            center_frequency_hz=433_500_000,
            span_hz=1_000_000,
            frequencies_hz=frequencies,
            levels_db=levels,
        )
    )

    assert scene.detections == []
    assert scene.noise_floor_db is not None
