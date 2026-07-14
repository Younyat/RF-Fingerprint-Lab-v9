from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

SIGMF_VERSION = "1.2.6"
MANIFEST_VERSION = "1.0"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def validate_sigmf(metadata: dict[str, Any]) -> None:
    global_meta = metadata.get("global")
    captures = metadata.get("captures")
    if not isinstance(global_meta, dict) or not isinstance(captures, list) or len(captures) != 1:
        raise ValueError("INVALID_SIGMF_STRUCTURE")
    required_global = {"core:version", "core:datatype", "core:sample_rate", "core:hw", "core:recorder"}
    if not required_global.issubset(global_meta):
        raise ValueError("INVALID_SIGMF_GLOBAL")
    if global_meta["core:datatype"] not in {"ci8", "ci16_le", "cf32_le"}:
        raise ValueError("UNSUPPORTED_SIGMF_DATATYPE")
    if not {"core:sample_start", "core:frequency", "core:datetime"}.issubset(captures[0]):
        raise ValueError("INVALID_SIGMF_CAPTURE")
