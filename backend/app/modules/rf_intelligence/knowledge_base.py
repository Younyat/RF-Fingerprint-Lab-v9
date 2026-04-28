from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=1)
def load_band_profiles() -> dict[str, dict[str, Any]]:
    path = Path(__file__).with_name("band_profiles.json")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)
