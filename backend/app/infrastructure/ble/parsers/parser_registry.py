from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from .vendor_profiles import (
    PROFILE_ID as TI_PROFILE_ID,
    TI_HUMIDITY_DATA,
    TI_IR_TEMPERATURE_DATA,
    matches_ti_sensortag_environment_profile,
    matches_ti_sensortag_ir_profile,
    parse_ti_cc2650_humidity,
    parse_ti_cc2650_ir_temperature,
)

TI_HUMIDITY_PARSER_ID = "ti-cc2650-hdc1000-v1"
TI_IR_PARSER_ID = "ti-cc2650-tmp007-v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class BleParserRegistry:
    """Strict registry: unmatched payloads never become measurements."""

    STANDARD_GATT: dict[str, dict[str, Any]] = {
        "00002a19-0000-1000-8000-00805f9b34fb": {
            "parser_id": "bluetooth-sig-battery-level-v1", "measurement_type": "battery",
            "unit": "%", "length": 1, "signed": False, "scale": 1.0,
        },
        "00002a6e-0000-1000-8000-00805f9b34fb": {
            "parser_id": "bluetooth-sig-temperature-v1", "measurement_type": "temperature",
            "unit": "degC", "length": 2, "signed": True, "scale": 0.01,
        },
        "00002a6f-0000-1000-8000-00805f9b34fb": {
            "parser_id": "bluetooth-sig-humidity-v1", "measurement_type": "humidity",
            "unit": "%", "length": 2, "signed": False, "scale": 0.01,
        },
    }

    def __init__(self) -> None:
        self._vendor_parsers: list[Callable[..., dict[str, Any] | None]] = []

    def describe(self, characteristic_uuid: str) -> dict[str, Any] | None:
        profile = self.STANDARD_GATT.get(characteristic_uuid.lower())
        return None if profile is None else {**profile, "parser_version": "1.0", "source_type": "gatt", "characteristic_uuid": characteristic_uuid.lower(), "endianness": "little", "minimum_payload_length": profile["length"], "supported_measurements": [profile["measurement_type"]]}

    def parse_gatt(self, device_id: str, characteristic_uuid: str, raw: bytes, acquisition_mode: str) -> dict[str, Any] | None:
        profile = self.STANDARD_GATT.get(characteristic_uuid.lower())
        if profile is None or len(raw) != profile["length"]:
            return None
        integer = int.from_bytes(raw, "little", signed=profile["signed"])
        return {
            "measurement_id": "ble-measurement-" + uuid.uuid4().hex[:16],
            "device_id": device_id,
            "measurement_type": profile["measurement_type"],
            "value": integer * profile["scale"],
            "unit": profile["unit"],
            "observed_at_utc": utc_now(),
            "acquisition_mode": acquisition_mode,
            "source_uuid": characteristic_uuid.lower(),
            "source_raw_hex": raw.hex(),
            "parser_id": profile["parser_id"],
            "parser_version": "1.0",
            "conversion": {"endianness": "little", "signed": profile["signed"], "scale": profile["scale"], "offset": 0},
            "quality": {"parsed": True, "crc_available": False},
        }

    def classify_advertisement(self, manufacturer_data: dict[str, str], service_data: dict[str, str]) -> dict[str, Any]:
        # Vendor formats require an explicit registered parser. Raw bytes are
        # intentionally returned without guessing offsets or engineering units.
        # In particular: manufacturer_data["0x000D"] (TI's company ID) is never
        # interpreted as a measurement here -- it is only ever a phase-1 hint,
        # handled separately by matches_ti_sensortag_advertising_fingerprint().
        return {"data_mode": "UNKNOWN_FORMAT" if manufacturer_data or service_data else "GATT_READ", "parser_available": False, "measurements": []}

    def detect_connected_vendor_profile(self, service_uuids: set[str] | list[str], characteristic_uuids: set[str] | list[str]) -> dict[str, Any] | None:
        """Phase 2 -- only ever called with the device's own discovered GATT
        services/characteristics after connecting. Returns None (no vendor
        profile) unless at least one sub-profile's full UUID set matches."""
        has_environmental = matches_ti_sensortag_environment_profile(service_uuids, characteristic_uuids)
        has_ir = matches_ti_sensortag_ir_profile(service_uuids, characteristic_uuids)
        if not has_environmental and not has_ir:
            return None
        return {
            "profile_id": TI_PROFILE_ID,
            "profile_label": "TI SensorTag-compatible",
            "profile_detection_source": "gatt_fingerprint",
            "environmental_available": has_environmental,
            "ir_temperature_available": has_ir,
        }

    def parse_ti_humidity_notification(self, device_id: str, raw: bytes) -> list[dict[str, Any]]:
        try:
            parsed = parse_ti_cc2650_humidity(raw)
        except ValueError:
            return []
        base = {
            "parser_id": TI_HUMIDITY_PARSER_ID, "parser_version": "1.0", "device_id": device_id,
            "source_uuid": TI_HUMIDITY_DATA, "source_raw_hex": raw.hex(), "observed_at_utc": utc_now(),
            "acquisition_mode": "gatt_notify", "quality": {"parsed": True, "crc_available": False},
        }
        return [
            {**base, "measurement_id": "ble-measurement-" + uuid.uuid4().hex[:16], "measurement_type": "temperature",
             "value": round(parsed.temperature_c, 2), "unit": "degC",
             "conversion": {"endianness": "little", "signed": False, "scale": 165.0 / 65536.0, "offset": -40.0}},
            {**base, "measurement_id": "ble-measurement-" + uuid.uuid4().hex[:16], "measurement_type": "relative_humidity",
             "value": round(parsed.relative_humidity_percent, 2), "unit": "%RH",
             "conversion": {"endianness": "little", "signed": False, "scale": 100.0 / 65536.0, "offset": 0.0}},
        ]

    def parse_ti_ir_temperature_notification(self, device_id: str, raw: bytes) -> list[dict[str, Any]]:
        try:
            parsed = parse_ti_cc2650_ir_temperature(raw)
        except ValueError:
            return []
        base = {
            "parser_id": TI_IR_PARSER_ID, "parser_version": "1.0", "device_id": device_id,
            "source_uuid": TI_IR_TEMPERATURE_DATA, "source_raw_hex": raw.hex(), "observed_at_utc": utc_now(),
            "acquisition_mode": "gatt_notify", "quality": {"parsed": True, "crc_available": False},
        }
        return [
            {**base, "measurement_id": "ble-measurement-" + uuid.uuid4().hex[:16], "measurement_type": "object_temperature",
             "value": round(parsed.object_temperature_c, 3), "unit": "degC",
             "conversion": {"endianness": "little", "signed": False, "scale": 0.03125, "offset": 0.0}},
            {**base, "measurement_id": "ble-measurement-" + uuid.uuid4().hex[:16], "measurement_type": "ambient_temperature",
             "value": round(parsed.ambient_temperature_c, 3), "unit": "degC",
             "conversion": {"endianness": "little", "signed": False, "scale": 0.03125, "offset": 0.0}},
        ]
