from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
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
        self._scan_session_id: str | None = None
        self._scan_session_dir: Path | None = None
        self._scan_file_lock = threading.Lock()
        self._gatt_semaphore = None
        self.gatt_policy = {"max_concurrent_gatt_connections": 1, "max_retries_per_device": 3,
                            "connection_timeout_s": 12.0, "service_discovery_timeout_s": 15.0,
                            "read_timeout_s": 10.0, "notification_timeout_s": 5.0, "retry_backoff_s": 0.75}

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
        return {**result, "scanning": self._scanning, "device_count": len(self.registry.list()), "last_error": self._last_error,
                "native_gate_status": "NATIVE-1_IMPLEMENTED_PENDING_RUNTIME_VALIDATION", "gatt_policy": self.gatt_policy}

    async def _start_scan(self, session_id: str | None = None) -> None:
        from bleak import BleakScanner
        if self._scanning: return
        self._scan_session_id = session_id or ("ble-scan-" + uuid.uuid4().hex)
        if any(token in self._scan_session_id for token in ("/", "\\", "..")): raise ValueError("INVALID_SCAN_SESSION_ID")
        self._scan_session_dir = self.root / "scans" / self._scan_session_id
        self._scan_session_dir.mkdir(parents=True, exist_ok=True)
        started_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        (self._scan_session_dir / "scan_manifest.json").write_text(json.dumps({"schema_version":"ble-native-scan-v1",
            "scan_session_id":self._scan_session_id,"started_at_utc":started_utc,"started_monotonic_ns":time.monotonic_ns(),
            "backend_version":"ble-native-v1","bleak_version":"0.22.3","deduplication":False}, indent=2)+"\n", encoding="utf-8")
        def callback(device, advertisement):
            manufacturer = {f"0x{int(key):04X}": bytes(value).hex() for key, value in (advertisement.manufacturer_data or {}).items()}
            services = {str(key).lower(): bytes(value).hex() for key, value in (advertisement.service_data or {}).items()}
            self.registry.observe(device, advertisement, self.parsers.classify_advertisement(manufacturer, services), self._scan_session_id)
            observation = {"schema_version":"ble-native-observation-v1","native_observation_id":"native-"+uuid.uuid4().hex,
                "scan_session_id":self._scan_session_id,"timestamp_callback_utc":datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "timestamp_callback_monotonic_ns":time.monotonic_ns(),"address":str(device.address),"address_type":"unknown",
                "local_name":advertisement.local_name or getattr(device,"name",None),"rssi_dbm":getattr(advertisement,"rssi",None),
                "tx_power_dbm":advertisement.tx_power,"connectable":getattr(advertisement,"connectable",None),
                "manufacturer_data":manufacturer,"service_data":services,"service_uuids":[str(x).lower() for x in (advertisement.service_uuids or [])]}
            line=json.dumps(observation,sort_keys=True)+"\n"
            with self._scan_file_lock:
                with (self._scan_session_dir / "advertisements.jsonl").open("a",encoding="utf-8",newline="\n") as handle:
                    handle.write(line); handle.flush(); os.fsync(handle.fileno())
        self._scanner = BleakScanner(detection_callback=callback)
        await self._scanner.start(); self._scanning = True; self._last_error = None

    def start_scan(self, session_id: str | None = None) -> dict[str, Any]:
        try: self._submit(self._start_scan(session_id), 15)
        except Exception as error:
            self._last_error = f"{type(error).__name__}:{error}"; raise RuntimeError("NATIVE_BLE_SCAN_FAILED") from error
        return {"state": "scanning", "started": True, "scan_session_id": self._scan_session_id}

    async def _stop_scan(self) -> None:
        if self._scanner is not None: await self._scanner.stop()
        if self._scan_session_dir:
            devices=[item for item in self.registry.list() if item.get("scan_session_id")==self._scan_session_id]
            (self._scan_session_dir/"devices.json").write_text(json.dumps({"schema_version":"ble-native-devices-v1","devices":devices},indent=2)+"\n",encoding="utf-8")
        self._scanner = None; self._scanning = False

    def stop_scan(self) -> dict[str, Any]:
        self._submit(self._stop_scan(), 15); return {"state": "idle", "stopped": True, "device_count": len(self.registry.list())}

    def devices(self) -> list[dict[str, Any]]: return self.registry.list()
    def device(self, device_id: str) -> dict[str, Any]: return self.registry.get(device_id)
    def diagnostics(self, device_id: str) -> list[dict[str, Any]]: return self.registry.get(device_id).get("gatt_diagnostics", [])

    @staticmethod
    def _error_status(error: Exception) -> str:
        value = f"{type(error).__name__}:{error}".lower()
        if "timeout" in value: return "CONNECTION_TIMEOUT"
        if "access" in value or "denied" in value: return "ACCESS_DENIED"
        if "pair" in value: return "PAIRING_REQUIRED"
        if "not discoverable" in value or "not found" in value: return "DEVICE_OBJECT_UNRESOLVED"
        if "unreachable" in value: return "CONNECTION_UNREACHABLE"
        return "GATT_DISCOVERY_FAILED"

    def _diagnostic(self, device_id: str, operation: str, attempt: int, started: float,
                    *, status: str, error: Exception | None = None, cache_mode: str = "cached") -> None:
        finished = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.registry.add_diagnostic(device_id, {
            "attempt_id": "gatt-attempt-" + uuid.uuid4().hex,
            "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "started_at": finished, "finished_at": finished,
            "started_monotonic_ns": int(started * 1_000_000_000), "finished_monotonic_ns": time.monotonic_ns(),
            "scan_session_id": self.registry.get(device_id).get("scan_session_id"),
            "bleak_version": "0.22.3", "backend_version": "ble-native-v1",
            "operation": operation, "attempt": attempt,
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
            "cache_mode": cache_mode, "status": status,
            "exception_class": type(error).__name__ if error else None,
            "exception_message": str(error) if error else None,
            "winrt_code": getattr(error, "winerror", None) if error else None,
            "gatt_communication_status": getattr(error, "status", None) if error else None,
            "protocol_error": getattr(error, "protocol_error", None) if error else None,
        })

    def diagnostic_report(self, device_id: str) -> dict[str, Any]:
        record = self.registry.get(device_id)
        attempts = []
        for item in record.get("gatt_diagnostics", []):
            status = str(item.get("status", ""))
            attempts.append({
                "attempt_id": item.get("attempt_id"), "operation": item.get("operation"),
                "started_at": item.get("started_at") or item.get("timestamp_utc"),
                "finished_at": item.get("finished_at") or item.get("timestamp_utc"),
                "started_monotonic_ns": item.get("started_monotonic_ns"),
                "finished_monotonic_ns": item.get("finished_monotonic_ns"),
                "duration_ms": item.get("duration_ms"), "queue_duration_ms": item.get("queue_duration_ms"),
                "cache_mode": item.get("cache_mode", "not_applicable"),
                "result": "success" if status in {"CONNECTED", "SERVICES_DISCOVERED", "MEASUREMENT_AVAILABLE"} else ("timeout" if "TIMEOUT" in status else "failure"),
                "failure_classification": None if status in {"CONNECTED", "SERVICES_DISCOVERED", "MEASUREMENT_AVAILABLE"} else status,
                "gatt_communication_status": item.get("gatt_communication_status"),
                "protocol_error": item.get("protocol_error"),
                "exception_type": item.get("exception_class"), "exception_message": item.get("exception_message"),
                "winrt_error_code": item.get("winrt_code"), "scan_session_id": item.get("scan_session_id"),
                "bleak_version": item.get("bleak_version"), "backend_version": item.get("backend_version"),
            })
        return {
            "schema_version": "ble-gatt-diagnostics-v1", "device_id": device_id,
            "advertising_state": "ADVERTISEMENT_SEEN" if record.get("advertising_seen") else "NOT_SEEN",
            "connection_state": "CONNECTED" if record.get("connection_established") else (record.get("native_status") if record.get("connection_attempted") else "NOT_ATTEMPTED"),
            "gatt_discovery_state": "GATT_DISCOVERED" if record.get("gatt_discovery_succeeded") else ("GATT_DISCOVERY_FAILED" if record.get("gatt_discovery_attempted") else "NOT_ATTEMPTED"),
            "profile_state": "PROFILE_CLASSIFIED" if record.get("profile_recognized") else "NOT_EVALUATED",
            "parser_state": "SUPPORTED" if record.get("sensor_parser_supported") else ("PARSER_UNSUPPORTED" if record.get("profile_recognized") else "NOT_EVALUATED"),
            "measurement_state": "MEASUREMENT_AVAILABLE" if record.get("measurement_available") else "UNAVAILABLE",
            "attempts": attempts,
        }

    async def _connect(self, device_id: str) -> dict[str, Any]:
        if self._gatt_semaphore is None: self._gatt_semaphore = asyncio.Semaphore(self.gatt_policy["max_concurrent_gatt_connections"])
        queued = time.monotonic()
        async with self._gatt_semaphore:
            queue_duration_ms = round((time.monotonic() - queued) * 1000, 3)
            if queue_duration_ms > 1:
                self.registry.add_diagnostic(device_id, {"attempt_id": "gatt-attempt-" + uuid.uuid4().hex,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "operation": "queue_wait",
                    "attempt": 0, "duration_ms": 0, "queue_duration_ms": queue_duration_ms, "cache_mode": "not_applicable",
                    "status": "QUEUED", "exception_class": None, "exception_message": None, "winrt_code": None,
                    "gatt_communication_status": None, "protocol_error": None})
            return await self._connect_serialized(device_id)

    async def _connect_serialized(self, device_id: str) -> dict[str, Any]:
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
        self.registry.update(device_id, connection_attempted=True, native_state="CONNECT_REQUESTED", native_status="ADVERTISEMENT_ONLY")
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
                started = time.monotonic()
                try:
                    client = BleakClient(record["address"])
                    await asyncio.wait_for(client.connect(), timeout=12.0)
                    self._diagnostic(device_id, "connect", attempt + 1, started, status="CONNECTED")
                    last_error = None
                    break
                except Exception as error:  # noqa: BLE001 - deliberately broad, this is a hardware-flakiness retry
                    last_error = error
                    status = self._error_status(error)
                    self._diagnostic(device_id, "connect", attempt + 1, started, status=status, error=error)
                    self.registry.update(device_id, connection="failed", connection_established=False, native_status=status)
                    await asyncio.sleep(0.75)
            if last_error is not None:
                discovered = await BleakScanner.find_device_by_address(record["address"], timeout=10.0)
                if discovered is None:
                    self.registry.update(device_id, windows_device_resolved=False, native_status="DEVICE_OBJECT_UNRESOLVED")
                    raise RuntimeError(f"BLE_DEVICE_NOT_DISCOVERABLE:{record['address']}") from last_error
                self.registry.update(device_id, windows_device_resolved=True, native_state="CACHE_RESOLVED")
                client = BleakClient(discovered)
                await asyncio.wait_for(client.connect(), timeout=12.0)
        self._clients[device_id] = client
        services = self._serialize_services(client.services)
        updates: dict[str, Any] = {"connection": "connected", "connection_established": True, "gatt_discovery_attempted": True, "gatt_discovery_succeeded": True, "native_state": "CHARACTERISTICS_DISCOVERED", "native_status": "NO_SENSOR_SERVICES", "data_mode": self._classify_services(services), "gatt_services": services, "notification_supported": any("notify" in char["properties"] or "indicate" in char["properties"] for service in services for char in service["characteristics"])}

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
            updates["profile_recognized"] = True
            updates["native_state"] = "PROFILE_CLASSIFIED"
            updates["native_status"] = "PROFILE_CLASSIFIED"
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
            connection_established=False, native_status="ADVERTISEMENT_ONLY",
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
