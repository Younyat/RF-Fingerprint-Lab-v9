from __future__ import annotations

from typing import Any


class DecisionFusionPipeline:
    method = "waterfall_visual_mlp_bispectral_fusion"

    def fuse(
        self,
        region: dict[str, Any] | None,
        visual: dict[str, Any] | None,
        mlp: dict[str, Any] | None,
        spectral_features: dict[str, Any] | None,
        bispectral_features: dict[str, Any] | None,
        legacy_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not region:
            return {
                "final_label": "unknown",
                "final_confidence": 0.0,
                "decision_status": "unknown",
                "method": self.method,
                "agreement": None,
                "evidence": {},
                "limitations": self._limitations(),
            }
        visual_label = (visual or {}).get("label", "unknown")
        mlp_label = (mlp or {}).get("label", "unknown")
        visual_conf = float((visual or {}).get("confidence", 0.0))
        mlp_conf = float((mlp or {}).get("confidence", 0.0))
        snr_db = float((spectral_features or {}).get("snr_db", 0.0))
        phase_coupling = float((bispectral_features or {}).get("phase_coupling_score", 0.0))
        nonlinear_ratio = float((bispectral_features or {}).get("nonlinear_energy_ratio", 0.0))

        if visual_label == mlp_label and visual_label != "unknown":
            label = visual_label
            confidence = min(0.97, (visual_conf * 0.55) + (mlp_conf * 0.35) + 0.1)
            status = "accepted"
        elif visual_label == "unknown" and mlp_label == "unknown":
            label = "unknown"
            confidence = max(visual_conf, mlp_conf) * 0.5
            status = "unknown"
        else:
            label = "ambiguous"
            confidence = max(visual_conf, mlp_conf) * 0.65
            status = "ambiguous"

        if snr_db < 6.0:
            confidence *= 0.72
            if phase_coupling > 0.55 and nonlinear_ratio > 0.35:
                confidence = min(confidence + 0.08, 0.88)
        elif snr_db > 15.0:
            confidence = min(confidence + 0.04, 0.98)

        legacy_agreement = self._legacy_agreement(label, legacy_result)
        evidence = {
            "region_detection": region,
            "visual_classification": visual or {},
            "mlp_membership": mlp or {},
            "spectral_features": spectral_features or {},
            "bispectral_features": bispectral_features or {},
        }
        if phase_coupling > 0.55 and nonlinear_ratio > 0.35:
            evidence["transmitter_specific_fingerprint_evidence"] = {
                "status": "possible",
                "reason": "Strong bispectral phase coupling and nonlinear energy were observed.",
            }
        return {
            "final_label": label,
            "final_confidence": float(max(0.0, min(confidence, 1.0))),
            "decision_status": status,
            "method": self.method,
            "agreement": legacy_agreement,
            "evidence": evidence,
            "limitations": self._limitations(),
        }

    def _legacy_agreement(self, label: str, legacy_result: dict[str, Any] | None) -> str | None:
        if not legacy_result or label in {"unknown", "ambiguous"}:
            return None
        legacy_text = f"{legacy_result.get('label', '')} {legacy_result.get('family', '')}".lower()
        if "ook" in label and ("ook" in legacy_text or "remote" in legacy_text or "ism" in legacy_text):
            return "compatible"
        if "fsk" in label and ("fsk" in legacy_text or "remote" in legacy_text or "ism" in legacy_text):
            return "compatible"
        if "ofdm" in label and any(term in legacy_text for term in ["wifi", "ofdm", "lte"]):
            return "compatible"
        return "different"

    def _limitations(self) -> list[str]:
        return [
            "The result is a signal-type hypothesis, not protocol-level decoding.",
            "The transmitter identity requires a trained device-level fingerprint model.",
        ]
