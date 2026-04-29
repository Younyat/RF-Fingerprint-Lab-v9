from __future__ import annotations

from pathlib import Path
from typing import Any


class ModelRegistry:
    def __init__(self, models_dir: Path) -> None:
        self.models_dir = models_dir

    def list_models(self) -> list[dict[str, Any]]:
        model_types = ["region_detector", "waterfall_classifier", "mlp_spectral_classifier", "bispectral_fusion"]
        summaries: list[dict[str, Any]] = []
        for model_type in model_types:
            model_dir = self.models_dir / model_type
            model_dir.mkdir(parents=True, exist_ok=True)
            files = [path for path in model_dir.iterdir() if path.is_file()]
            summaries.append(
                {
                    "model_id": f"{model_type}_v1",
                    "model_type": model_type,
                    "status": "trained" if files else "not_trained",
                    "path": str(model_dir),
                    "trained": bool(files),
                    "metadata": {"files": [path.name for path in files]},
                }
            )
        return summaries
