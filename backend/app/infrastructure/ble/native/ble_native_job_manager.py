from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from ..parsers import BleParserRegistry
from ..parsers.vendor_profiles import (
    KNOWN_SERVICE_NAMES,
    TI_HUMIDITY_CONFIG,
    TI_HUMIDITY_DATA,
    TI_HUMIDITY_PERIOD,
    TI_IR_TEMPERATURE_CONFIG,
    TI_IR_TEMPERATURE_DATA,
    TI_IR_TEMPERATURE_PERIOD,
)
from .ble_device_registry import BleDeviceRegistry


class BleNativeJobManager:
    def __init__(self, root: Path) -> None:
        self.root = root; root.mkdir(parents=True, exist_ok=True)
        self.registry = BleDeviceRegistry(root / "device_registry.json")
        self.parsers = BleParserRegistry()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="ble-native-winrt")
        self._thread.start()
        self._scanner = None; self._clients: dict[str, Any] = {}; self._scanning = False
        self._last_error: str | None = None

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop); self._loop.run_forever()

    def _submit(self, coroutine, timeout: float = 30):
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result(timeout=timeout)

    async def _adapter_status(self) -> dict[str, Any]:
        try:
            from bleak.backends.winrt.util import assert_mta
            await assert_mta()
            from winrt.windows.devices.bluetooth import BluetoothAdapter
            adapter = await BluetoothAdapter.get_default_async()
            if adapter is None: raise RuntimeError("NO_DEFAULT_BLUETOOTH_ADAPTER")
            return {"available": True, "adapter_type": "native_ble", "backend": "winrt", "scan_supported": True, "gatt_supported": True}
        except Exception as error:
            self._last_error = f"{type(error).__name__}:{error}"
            return {"available": False, "adapter_type": "native_ble", "backend": "winrt", "scan_supported": False, "gatt_supported": False, "reason_code": "NO_NATIVE_BLE_ADAPTER", "message": "A conventional BLE adapter is required for device scanning and GATT access.", "diagnostic": self._last_error}

    def status(self) -> dict[str, Any]:
        try: result = self._submit(self._adapter_status(), 10)
        except Exception as error: result = {"available": False, "adapter_type": "native_ble", "backend": "winrt", "scan_supported": False, "gatt_supported": False, "reason_code": "NO_NATIVE_BLE_ADAPTER", "message": "A conventional BLE adapter is required for device scanning and GATT access.", "diagnostic": f"{type(error).__name__}:{error}"}
        return {**result, "scanning": self._scanning, "device_count": len(self.registry.list()), "last_error": self._last_error}

    async def _start_scan(self) -> None:
        from bleak import BleakScanner
        if self._scanning: return
        def callback(device, advertisement):
            manufacturer = {f"0x{int(key):04X}": bytes(value).hex() for key, value in (advertisement.manufacturer_data or {}).items()}
            services = {str(key).lower(): bytes(value).hex() for key, value in (advertisement.service_data or {}).items()}
            self.registry.observe(device, advertisement, self.parsers.classify_advertisement(manufacturer, services))
        self._scanner = BleakScanner(detection_callback=callback)
        await self._scanner.start(); self._scanning = True; self._last_error = None

    def start_scan(self) -> dict[str, Any]:
        try: self._submit(self._start_scan(), 15)
        except Exception as error:
            self._last_error = f"{type(error).__name__}:{error}"; raise RuntimeError("NATIVE_BLE_SCAN_FAILED") from error
        return {"state": "scanning", "started": True}

    async def _stop_scan(self) -> None:
        if self._scanner is not None: await self._scanner.stop()
        self._scanner = None; self._scanning = False

    def stop_scan(self) -> dict[str, Any]:
        self._submit(self._stop_scan(), 15); return {"state": "idle", "stopped": True, "device_count": len(self.registry.list())}

    def devices(self) -> list[dict[str, Any]]: return self.registry.list()
    def device(self, device_id: str) -> dict[str, Any]: return self.registry.get(device_id)

    async def _connect(self, device_id: str) -> dict[str, Any]:
        from bleak import BleakClient, BleakScanner
        # Most BLE USB adapters only support one active native GATT
        # connection at a time -- connecting to a second device while a
        # first is still held open fails at the WinRT/Bleak level. Drop any
        # other connected device first so "Connect" always succeeds from a
        # clean slate rather than requiring the user to disconnect manually.
        for other_id, other_client in list(self._clients.items()):
            if other_id != device_id and other_client.is_connected:
                await self._disconnect(other_id)
        record = self.registry.get(device_id)
        client = self._clients.get(device_id)
        if client is None or not client.is_connected:
            # Connecting a bare BleakClient(address) is flaky on the WinRT
            # backend -- Windows' own BLE device cache entry for an address
            # can lag behind what a passive scan already sees, so the first
            # attempt sometimes raises BleakDeviceNotFoundError for a device
            # that is genuinely in range and advertising right now. Retry a
            # couple of times before falling back to an explicit fresh
            # discovery (which is slower but resolves a stale cache).
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    client = BleakClient(record["address"])
                    await asyncio.wait_for(client.connect(), timeout=12.0)
                    last_error = None
                    break
                except Exception as error:  # noqa: BLE001 - deliberately broad, this is a hardware-flakiness retry
                    last_error = error
                    await asyncio.sleep(0.75)
            if last_error is not None:
                discovered = await BleakScanner.find_device_by_address(record["address"], timeout=10.0)
                if discovered is None:
                    raise RuntimeError(f"BLE_DEVICE_NOT_DISCOVERABLE:{record['address']}") from last_error
                client = BleakClient(discovered)
                await asyncio.wait_for(client.connect(), timeout=12.0)
        self._clients[device_id] = client
        services = self._serialize_services(client.services)
        updates: dict[str, Any] = {"connection": "connected", "data_mode": self._classify_services(services), "gatt_services": services}

        # Phase 2 detection: the connected device's OWN discovered GATT
        # services/characteristics are the only thing that can enable a
        # vendor profile's measurements -- phase 1 (advertising fingerprint,
        # applied earlier by the caller/registry.observe) is a hint only and
        # is deliberately not sufficient by itself (some real SensorTag units
        # advertise with empty manufacturer_data/service_data/service_uuids).
        service_uuids = {item["service_uuid"] for item in services}
        characteristic_uuids = {char["uuid"] for item in services for char in item["characteristics"]}
        profile = self.parsers.detect_connected_vendor_profile(service_uuids, characteristic_uuids)
        previous_environmental = record.get("environmental_sensor") or {}
        previous_ir = record.get("ir_temperature_sensor") or {}
        if profile:
            updates["profile_id"] = profile["profile_id"]
            updates["profile_label"] = profile["profile_label"]
            updates["profile_detection_source"] = profile["profile_detection_source"]
            updates["environmental_sensor"] = {
                **previous_environmental, "available": profile["environmental_available"], "active": False,
                "status": "available" if profile["environmental_available"] else "unavailable",
                "data_uuid": TI_HUMIDITY_DATA, "config_uuid": TI_HUMIDITY_CONFIG, "period_uuid": TI_HUMIDITY_PERIOD,
            }
            updates["ir_temperature_sensor"] = {
                **previous_ir, "available": profile["ir_temperature_available"], "active": False,
                "status": "available" if profile["ir_temperature_available"] else "unavailable",
                "data_uuid": TI_IR_TEMPERATURE_DATA, "config_uuid": TI_IR_TEMPERATURE_CONFIG, "period_uuid": TI_IR_TEMPERATURE_PERIOD,
            }
        self.registry.update(device_id, **updates)
        return self.registry.get(device_id)

    def connect(self, device_id: str) -> dict[str, Any]: return self._submit(self._connect(device_id), 75)

    @staticmethod
    def _mark_stale(sensor: dict[str, Any] | None) -> dict[str, Any] | None:
        if not sensor:
            return sensor
        reading = sensor.get("last_reading")
        return {**sensor, "active": False, "status": "disconnected", "last_reading": {**reading, "stale": True} if reading else None}

    async def _disconnect(self, device_id: str) -> None:
        client = self._clients.pop(device_id, None)
        if client and client.is_connected: await client.disconnect()
        record = self.registry.get(device_id)
        # A lost/closed connection must never keep showing the last reading
        # as current -- preserve it for history, but mark it stale.
        self.registry.update(
            device_id, connection="disconnected",
            environmental_sensor=self._mark_stale(record.get("environmental_sensor")),
            ir_temperature_sensor=self._mark_stale(record.get("ir_temperature_sensor")),
        )

    def disconnect(self, device_id: str) -> dict[str, Any]: self._submit(self._disconnect(device_id), 20); return self.registry.get(device_id)

    def services(self, device_id: str) -> list[dict[str, Any]]:
        record = self.registry.get(device_id)
        if record.get("connection") != "connected": self.connect(device_id); record = self.registry.get(device_id)
        return record.get("gatt_services", [])

    @staticmethod
    def _serialize_services(services) -> list[dict[str, Any]]:
        return [{"service_uuid": service.uuid.lower(), "description": service.description, "known_name": KNOWN_SERVICE_NAMES.get(service.uuid.lower()), "characteristics": [{"uuid": char.uuid.lower(), "description": char.description, "properties": list(char.properties), "descriptors": [{"handle": desc.handle, "uuid": desc.uuid.lower(), "description": desc.description} for desc in char.descriptors]} for char in service.characteristics]} for service in services]

    def _classify_services(self, services: list[dict[str, Any]]) -> str:
        properties = {prop for service in services for char in service["characteristics"] for prop in char["properties"]}
        return "GATT_NOTIFY" if properties & {"notify", "indicate"} else "GATT_READ" if "read" in properties else "UNKNOWN_FORMAT"

    def _characteristic(self, device_id: str, characteristic_uuid: str) -> dict[str, Any]:
        for service in self.registry.get(device_id).get("gatt_services", []):
            for characteristic in service["characteristics"]:
                if characteristic["uuid"].lower() == characteristic_uuid.lower(): return characteristic
        raise KeyError(characteristic_uuid)

    async def _read(self, device_id: str, characteristic_uuid: str) -> dict[str, Any]:
        if device_id not in self._clients or not self._clients[device_id].is_connected: await self._connect(device_id)
        characteristic = self._characteristic(device_id, characteristic_uuid)
        if "read" not in characteristic["properties"]: raise PermissionError("CHARACTERISTIC_NOT_READABLE")
        raw = bytes(await self._clients[device_id].read_gatt_char(characteristic_uuid))
        measurement = self.parsers.parse_gatt(device_id, characteristic_uuid, raw, "gatt_read")
        if measurement: self.registry.add_measurement(device_id, measurement)
        return {"device_id": device_id, "characteristic_uuid": characteristic_uuid.lower(), "raw_hex": raw.hex(), "measurement": measurement, "parser_supported": measurement is not None}

    def read(self, device_id: str, characteristic_uuid: str) -> dict[str, Any]: return self._submit(self._read(device_id, characteristic_uuid), 30)

    async def _subscribe(self, device_id: str, characteristic_uuid: str) -> dict[str, Any]:
        if device_id not in self._clients or not self._clients[device_id].is_connected: await self._connect(device_id)
        characteristic = self._characteristic(device_id, characteristic_uuid)
        if not ({"notify", "indicate"} & set(characteristic["properties"])): raise PermissionError("CHARACTERISTIC_NOT_NOTIFIABLE")
        def callback(_, data: bytearray):
            measurement = self.parsers.parse_gatt(device_id, characteristic_uuid, bytes(data), "gatt_notify")
            if measurement: self.registry.add_measurement(device_id, measurement)
        await self._clients[device_id].start_notify(characteristic_uuid, callback)
        self.registry.update(device_id, connection="receiving_notifications", data_mode="GATT_NOTIFY")
        return {"subscribed": True, "characteristic_uuid": characteristic_uuid.lower(), "parser": self.parsers.describe(characteristic_uuid)}

    def subscribe(self, device_id: str, characteristic_uuid: str) -> dict[str, Any]: return self._submit(self._subscribe(device_id, characteristic_uuid), 30)

    async def _unsubscribe(self, device_id: str, characteristic_uuid: str) -> None:
        await self._clients[device_id].stop_notify(characteristic_uuid)
        self.registry.update(device_id, connection="connected")

    def unsubscribe(self, device_id: str, characteristic_uuid: str) -> dict[str, Any]: self._submit(self._unsubscribe(device_id, characteristic_uuid), 20); return {"subscribed": False, "characteristic_uuid": characteristic_uuid.lower()}

    # ── TI CC2650 SensorTag: humidity/ambient temperature service (AA20) ────
    # Sequence per TI's SensorTag user guide: subscribe AA21, write the
    # sampling period to AA23, then write 0x01 to AA22 to enable the sensor.
    # Stopping is the mirror image: write 0x00 to AA22 (best-effort -- the
    # notification is always torn down even if this write fails), then stop
    # the AA21 subscription.
    def _update_environmental_reading(self, device_id: str, measurements: list[dict[str, Any]]) -> None:
        if not measurements: return
        by_type = {item["measurement_type"]: item for item in measurements}
        sensor = self.registry.get(device_id).get("environmental_sensor") or {}
        reading = {
            "temperature_c": by_type.get("temperature", {}).get("value"),
            "relative_humidity_percent": by_type.get("relative_humidity", {}).get("value"),
            "observed_at_utc": measurements[0]["observed_at_utc"],
            "source_raw_hex": measurements[0]["source_raw_hex"],
            "stale": False,
        }
        self.registry.update(device_id, environmental_sensor={**sensor, "active": True, "status": "active", "last_reading": reading})

    async def _start_environmental(self, device_id: str, period_hex: bytes = b"\x64", first_notification_timeout: float = 5.0) -> dict[str, Any]:
        if device_id not in self._clients or not self._clients[device_id].is_connected: await self._connect(device_id)
        record = self.registry.get(device_id)
        sensor = record.get("environmental_sensor") or {}
        if not sensor.get("available"): raise PermissionError("TI_ENVIRONMENTAL_SENSOR_NOT_AVAILABLE")
        if sensor.get("active"): return record  # already running -- idempotent, not a second subscription
        client = self._clients[device_id]
        first_notification = asyncio.Event()

        def callback(_, data: bytearray):
            measurements = self.parsers.parse_ti_humidity_notification(device_id, bytes(data))
            for measurement in measurements: self.registry.add_measurement(device_id, measurement)
            self._update_environmental_reading(device_id, measurements)
            first_notification.set()

        # Set "starting" BEFORE subscribing, not after writing period/config --
        # a fast device (or, as in tests, a mock) can deliver its first
        # notification before those two writes even return, and updating the
        # registry afterward with this pre-subscribe snapshot would clobber
        # the reading the callback already stored.
        self.registry.update(device_id, environmental_sensor={**sensor, "active": True, "status": "starting"})
        await client.start_notify(TI_HUMIDITY_DATA, callback)
        await client.write_gatt_char(TI_HUMIDITY_PERIOD, period_hex, response=True)
        await client.write_gatt_char(TI_HUMIDITY_CONFIG, b"\x01", response=True)
        try:
            await asyncio.wait_for(first_notification.wait(), timeout=first_notification_timeout)
        except asyncio.TimeoutError:
            current = self.registry.get(device_id).get("environmental_sensor") or {}
            self.registry.update(device_id, environmental_sensor={**current, "status": "starting_no_data_yet"})
        return self.registry.get(device_id)

    def start_environmental_measurements(self, device_id: str) -> dict[str, Any]:
        return self._submit(self._start_environmental(device_id), 30)

    async def _stop_environmental(self, device_id: str) -> dict[str, Any]:
        record = self.registry.get(device_id)
        sensor = record.get("environmental_sensor") or {}
        client = self._clients.get(device_id)
        if client and client.is_connected:
            try:
                await client.write_gatt_char(TI_HUMIDITY_CONFIG, b"\x00", response=True)
            finally:
                await client.stop_notify(TI_HUMIDITY_DATA)
        reading = sensor.get("last_reading")
        self.registry.update(device_id, environmental_sensor={**sensor, "active": False, "status": "disabled", "last_reading": {**reading, "stale": True} if reading else None})
        return self.registry.get(device_id)

    def stop_environmental_measurements(self, device_id: str) -> dict[str, Any]:
        return self._submit(self._stop_environmental(device_id), 20)

    # ── TI CC2650 SensorTag: IR temperature service (AA00) ──────────────────
    def _update_ir_reading(self, device_id: str, measurements: list[dict[str, Any]]) -> None:
        if not measurements: return
        by_type = {item["measurement_type"]: item for item in measurements}
        sensor = self.registry.get(device_id).get("ir_temperature_sensor") or {}
        reading = {
            "object_temperature_c": by_type.get("object_temperature", {}).get("value"),
            "ambient_temperature_c": by_type.get("ambient_temperature", {}).get("value"),
            "observed_at_utc": measurements[0]["observed_at_utc"],
            "source_raw_hex": measurements[0]["source_raw_hex"],
            "stale": False,
        }
        self.registry.update(device_id, ir_temperature_sensor={**sensor, "active": True, "status": "active", "last_reading": reading})

    async def _start_ir_temperature(self, device_id: str, period_hex: bytes = b"\x64", first_notification_timeout: float = 5.0) -> dict[str, Any]:
        if device_id not in self._clients or not self._clients[device_id].is_connected: await self._connect(device_id)
        record = self.registry.get(device_id)
        sensor = record.get("ir_temperature_sensor") or {}
        if not sensor.get("available"): raise PermissionError("TI_IR_TEMPERATURE_SENSOR_NOT_AVAILABLE")
        if sensor.get("active"): return record
        client = self._clients[device_id]
        first_notification = asyncio.Event()

        def callback(_, data: bytearray):
            measurements = self.parsers.parse_ti_ir_temperature_notification(device_id, bytes(data))
            for measurement in measurements: self.registry.add_measurement(device_id, measurement)
            self._update_ir_reading(device_id, measurements)
            first_notification.set()

        # See _start_environmental for why this update happens before
        # subscribing rather than after the period/config writes.
        self.registry.update(device_id, ir_temperature_sensor={**sensor, "active": True, "status": "starting"})
        await client.start_notify(TI_IR_TEMPERATURE_DATA, callback)
        await client.write_gatt_char(TI_IR_TEMPERATURE_PERIOD, period_hex, response=True)
        await client.write_gatt_char(TI_IR_TEMPERATURE_CONFIG, b"\x01", response=True)
        try:
            await asyncio.wait_for(first_notification.wait(), timeout=first_notification_timeout)
        except asyncio.TimeoutError:
            current = self.registry.get(device_id).get("ir_temperature_sensor") or {}
            self.registry.update(device_id, ir_temperature_sensor={**current, "status": "starting_no_data_yet"})
        return self.registry.get(device_id)

    def start_ir_temperature_measurements(self, device_id: str) -> dict[str, Any]:
        return self._submit(self._start_ir_temperature(device_id), 30)

    async def _stop_ir_temperature(self, device_id: str) -> dict[str, Any]:
        record = self.registry.get(device_id)
        sensor = record.get("ir_temperature_sensor") or {}
        client = self._clients.get(device_id)
        if client and client.is_connected:
            try:
                await client.write_gatt_char(TI_IR_TEMPERATURE_CONFIG, b"\x00", response=True)
            finally:
                await client.stop_notify(TI_IR_TEMPERATURE_DATA)
        reading = sensor.get("last_reading")
        self.registry.update(device_id, ir_temperature_sensor={**sensor, "active": False, "status": "disabled", "last_reading": {**reading, "stale": True} if reading else None})
        return self.registry.get(device_id)

    def stop_ir_temperature_measurements(self, device_id: str) -> dict[str, Any]:
        return self._submit(self._stop_ir_temperature(device_id), 20)

    def inventory(self) -> dict[str, Any]:
        return {"schema_version": "1.0", "source": "native_ble_winrt", "devices": [{**item, "vendor": "unknown", "model": "unknown", "values_in_advertising": item.get("data_mode") == "ADVERTISEMENT_VALUE", "gatt_required": item.get("data_mode") in {"GATT_READ", "GATT_NOTIFY"}, "next_action": "inspect_gatt_characteristics" if not item.get("parser_available") else "validate_parser_against_reference"} for item in self.registry.list()]}
