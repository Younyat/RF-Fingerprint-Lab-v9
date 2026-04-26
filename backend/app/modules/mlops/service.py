from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _JobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._latest_by_type: dict[str, str] = {}

    def start_job(self, command: list[str], cwd: str | None, metadata: dict[str, Any]) -> dict[str, Any]:
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                bufsize=0,
            )
        except OSError as exc:
            executable = command[0] if command else "<empty>"
            raise ValueError(
                f"Failed to start job process. executable={executable} cwd={cwd or '<none>'} error={exc}"
            ) from exc
        job_id = str(uuid.uuid4())
        job = {
            "job_id": job_id,
            "command": command,
            "cwd": cwd,
            "metadata": metadata,
            "process": process,
            "started_at_utc": _utc_now(),
            "ended_at_utc": None,
            "returncode": None,
            "stdout_lines": deque(maxlen=4000),
            "stderr_lines": deque(maxlen=4000),
        }
        with self._lock:
            self._jobs[job_id] = job
            self._latest_by_type[str(metadata.get("job_type", ""))] = job_id
        self._start_reader(job_id, "stdout")
        self._start_reader(job_id, "stderr")
        return {
            "job_id": job_id,
            "status": "running",
            "started_at_utc": job["started_at_utc"],
            "command": command,
            "cwd": cwd,
        }

    def _start_reader(self, job_id: str, stream_name: str) -> None:
        threading.Thread(target=self._reader_loop, args=(job_id, stream_name), daemon=True).start()

    def _reader_loop(self, job_id: str, stream_name: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            stream = getattr(job["process"], stream_name)
        if stream is None:
            return
        lines_key = f"{stream_name}_lines"
        try:
            for raw_line in iter(stream.readline, b""):
                if not raw_line:
                    break
                try:
                    line = raw_line.decode("utf-8")
                except UnicodeDecodeError:
                    line = raw_line.decode("cp1252", errors="replace")
                with self._lock:
                    job = self._jobs.get(job_id)
                    if job is None:
                        break
                    job[lines_key].append(line.rstrip("\n"))
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def get_status(self, job_type: str, job_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            selected_id = job_id or self._latest_by_type.get(job_type)
            if selected_id is None or selected_id not in self._jobs:
                return {"status": "not_found", "job_id": selected_id}
            job = self._jobs[selected_id]
            returncode = job["process"].poll()
            if returncode is not None and job["returncode"] is None:
                job["returncode"] = returncode
                job["ended_at_utc"] = _utc_now()
            status = "running"
            if job["returncode"] is not None:
                status = "completed" if job["returncode"] == 0 else "failed"
            return {
                "status": status,
                "job_id": selected_id,
                "started_at_utc": job["started_at_utc"],
                "ended_at_utc": job["ended_at_utc"],
                "returncode": job["returncode"],
                "command": job["command"],
                "cwd": job["cwd"],
                "metadata": job["metadata"],
                "stdout": "\n".join(job["stdout_lines"]),
                "stderr": "\n".join(job["stderr_lines"]),
            }


class MlOpsService:
    def __init__(self, storage_root: Path, scripts_dir: Path, requirements_path: Path, radioconda_python: str) -> None:
        self._storage_root = storage_root
        self._storage_root.mkdir(parents=True, exist_ok=True)
        self._job_manager = _JobManager()
        self._fingerprinting_root = self._storage_root.parent / "fingerprinting"
        self._fingerprinting_captures_dir = self._fingerprinting_root / "captures"
        self._scripts_dir = scripts_dir
        self._requirements_path = requirements_path
        self._mlops_reports_root = self._storage_root
        self._mlops_data_root = self._storage_root / "data"
        self._default_python = self._resolve_python_executable(radioconda_python)
        self._powershell_exe = self._resolve_powershell_executable()

        self._train_dataset_dir = self._mlops_data_root / "rf_dataset"
        self._val_dataset_dir = self._mlops_data_root / "rf_dataset_val"
        self._predict_dataset_dir = self._mlops_data_root / "rf_dataset_predict"
        self._model_output_dir = self._mlops_data_root / "remote_trained_model"
        self._validation_output_dir = self._mlops_data_root / "validation"
        self._inference_output_dir = self._mlops_data_root / "inference"

        for path in (
            self._mlops_data_root,
            self._train_dataset_dir,
            self._val_dataset_dir,
            self._predict_dataset_dir,
            self._model_output_dir,
            self._validation_output_dir,
            self._inference_output_dir,
            self._mlops_reports_root / "models",
            self._mlops_reports_root / "validation_reports",
        ):
            path.mkdir(parents=True, exist_ok=True)

    def training_dashboard(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        model_dir = self._resolve_path(payload.get("local_output_dir"), self._model_output_dir)
        best_model_path = model_dir / "best_model.pt"
        history_path = model_dir / "training_history.json"
        manifest_path = model_dir / "dataset_manifest.json"
        profiles_path = model_dir / "enrollment_profiles.json"
        label_map_path = model_dir / "label_map.json"
        train_config_path = model_dir / "train_config.json"
        version_index_path = model_dir / "versions" / "index.json"
        versions_dir = model_dir / "versions"

        history = self._load_json(history_path) or []
        manifest = self._load_json(manifest_path) or {}
        profiles = self._load_json(profiles_path) or {}
        label_map = self._load_json(label_map_path) or {}
        train_config = self._load_json(train_config_path) or {}
        retraining_snapshots = self._load_retraining_snapshots(version_index_path, versions_dir)
        records = manifest.get("records", []) if isinstance(manifest, dict) else []
        reports = self.list_validation_reports()

        return {
            "model_dir": str(model_dir),
            "current_model": {
                "path": str(best_model_path),
                "exists": best_model_path.exists(),
                "size_bytes": self._safe_size(best_model_path),
                "modified_at_utc": self._safe_mtime(best_model_path),
                "train_config": train_config if isinstance(train_config, dict) else {},
                "dataset_manifest": manifest if isinstance(manifest, dict) else {},
                "label_map": label_map if isinstance(label_map, dict) else {},
                "file_inventory": self._collect_file_inventory(model_dir),
            },
            "dataset": self._dataset_summary(records if isinstance(records, list) else []),
            "training": {
                **self._history_summary(history if isinstance(history, list) else []),
                "config": train_config if isinstance(train_config, dict) else {},
                "profiles_count": len(profiles) if isinstance(profiles, dict) else 0,
                "labeled_devices": len(label_map.get("device_to_label", {})) if isinstance(label_map, dict) else 0,
                "latest_history": history[-20:] if isinstance(history, list) else [],
            },
            "retraining": {
                "snapshot_count": len(retraining_snapshots),
                "snapshots": retraining_snapshots,
            },
            "prediction_readiness": {
                "has_model_file": best_model_path.exists(),
                "has_profiles": profiles_path.exists(),
                "has_manifest": manifest_path.exists(),
                "has_history": history_path.exists(),
                "has_validation": len(reports) > 0,
                "latest_validation": reports[-1] if reports else None,
            },
            "validation_reports": reports,
            "filesystem": {
                "model_dir_exists": model_dir.exists(),
                "model_dir_size_bytes": self._safe_tree_size(model_dir),
                "train_dataset_dir": str(self._train_dataset_dir),
                "train_dataset_size_bytes": self._safe_tree_size(self._train_dataset_dir),
                "val_dataset_dir": str(self._val_dataset_dir),
                "val_dataset_size_bytes": self._safe_tree_size(self._val_dataset_dir),
                "predict_dataset_dir": str(self._predict_dataset_dir),
                "predict_dataset_size_bytes": self._safe_tree_size(self._predict_dataset_dir),
            },
        }

    def _load_retraining_snapshots(self, index_path: Path, versions_dir: Path) -> list[dict[str, Any]]:
        """
        Reads retraining lineage from versions/index.json and falls back to the
        versions directory. The fallback matters because a completed retraining
        may create snapshot folders even if the index is stale or unreadable.
        """
        snapshots: list[dict[str, Any]] = []
        index = self._load_json(index_path)
        raw_versions = index.get("versions", []) if isinstance(index, dict) else []
        if isinstance(raw_versions, list):
            for item in raw_versions:
                if isinstance(item, dict):
                    snapshots.append(self._normalize_retraining_snapshot(item))

        known_ids = {str(item.get("version_id") or item.get("version") or "") for item in snapshots}
        if versions_dir.exists():
            for child in sorted(versions_dir.iterdir()):
                if not child.is_dir() or child.name in known_ids:
                    continue
                snapshots.append(
                    self._normalize_retraining_snapshot(
                        {
                            "version_id": child.name,
                            "snapshot_dir": str(child),
                            "reason": child.name.split("-", 1)[1] if "-" in child.name else "snapshot",
                            "model_file": str(child / "best_model.pt"),
                            "created_at_utc": self._safe_mtime(child),
                        }
                    )
                )

        return sorted(snapshots, key=lambda item: str(item.get("created_at_utc") or item.get("version_id") or ""))

    def _normalize_retraining_snapshot(self, item: dict[str, Any]) -> dict[str, Any]:
        version_id = str(item.get("version_id") or item.get("version") or "snapshot").strip()
        snapshot_dir = Path(str(item.get("snapshot_dir") or "")) if item.get("snapshot_dir") else None
        model_file = Path(str(item.get("model_file") or "")) if item.get("model_file") else None
        return {
            **item,
            "version": version_id,
            "version_id": version_id,
            "reason": str(item.get("reason") or "snapshot"),
            "snapshot_dir": str(snapshot_dir) if snapshot_dir else str(item.get("snapshot_dir") or ""),
            "model_file": str(model_file) if model_file else str(item.get("model_file") or ""),
            "model_file_exists": bool(model_file and model_file.exists()),
            "model_file_size_bytes": self._safe_size(model_file) if model_file else 0,
            "snapshot_size_bytes": self._safe_tree_size(snapshot_dir) if snapshot_dir else 0,
            "created_at_utc": str(item.get("created_at_utc") or (self._safe_mtime(snapshot_dir) if snapshot_dir else "") or ""),
        }

    def list_models(self) -> list[dict[str, Any]]:
        models_dir = self._mlops_reports_root / "models"
        items: list[dict[str, Any]] = []
        for path in sorted(models_dir.glob("*.json")):
            data = self._load_json(path)
            if isinstance(data, dict):
                items.append(data)
        return items

    def current_model(self) -> dict[str, Any] | None:
        models_dir = self._mlops_reports_root / "models"
        current = models_dir / "current.txt"
        if not current.exists():
            return None
        version = current.read_text(encoding="utf-8").strip()
        data = self._load_json(models_dir / f"{version}.json")
        return data if isinstance(data, dict) else None

    def model_by_version(self, version: str) -> dict[str, Any] | None:
        data = self._load_json((self._mlops_reports_root / "models") / f"{version}.json")
        return data if isinstance(data, dict) else None

    def start_training(self, payload: dict[str, Any], retrain: bool = False) -> dict[str, Any]:
        remote_user = str(payload.get("remote_user", "")).strip()
        remote_host = str(payload.get("remote_host", "")).strip()
        if not remote_user or not remote_host:
            raise ValueError("Remote training requires both remote_user and remote_host.")

        target_center_frequency_hz = self._parse_optional_float(payload.get("target_center_frequency_hz"))
        center_frequency_tolerance_hz = self._parse_optional_float(payload.get("center_frequency_tolerance_hz")) or 1.0
        dataset_dir = self._resolve_path(payload.get("local_dataset_dir"), self._train_dataset_dir)
        export_summary = self._export_fingerprinting_split(
            dataset_split="train",
            destination_dir=dataset_dir,
            allowed_statuses={"valid"},
            target_center_frequency_hz=target_center_frequency_hz,
            center_frequency_tolerance_hz=center_frequency_tolerance_hz,
        )
        self._validate_training_dataset(export_summary)

        deploy_script = self._scripts_dir / "deploy_remote_train.ps1"
        command = [
            self._powershell_exe,
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(deploy_script),
            "-RemoteUser",
            remote_user,
            "-RemoteHost",
            remote_host,
            "-LocalDatasetDir",
            str(dataset_dir),
            "-LocalTrainScript",
            str(self._scripts_dir / "train_or_resume_rf_fingerprint.py"),
            "-LocalOutputDir",
            str(self._resolve_path(payload.get("local_output_dir"), self._model_output_dir)),
            "-LocalRequirements",
            str(self._requirements_path),
            "-Epochs",
            str(int(payload.get("epochs", 20))),
            "-BatchSize",
            str(int(payload.get("batch_size", 128))),
            "-WindowSize",
            str(int(payload.get("window_size", 1024))),
            "-Stride",
            str(int(payload.get("stride", 1024))),
        ]
        if target_center_frequency_hz is not None:
            command.extend(
                [
                    "-TargetCenterFrequencyHz",
                    str(target_center_frequency_hz),
                    "-CenterFrequencyToleranceHz",
                    str(center_frequency_tolerance_hz),
                ]
            )
        remote_venv = str(payload.get("remote_venv_activate", "")).strip()
        if remote_venv:
            command.extend(["-RemoteVenvActivate", remote_venv])
        return self._job_manager.start_job(
            command=command,
            cwd=str(self._scripts_dir),
            metadata={
                "job_type": "training",
                "mode": "retrain" if retrain else "train",
                "remote_user": remote_user,
                "remote_host": remote_host,
                "dataset_export": export_summary,
                "target_center_frequency_hz": target_center_frequency_hz,
            },
        )

    def training_status(self, job_id: str | None = None) -> dict[str, Any]:
        return self._job_manager.get_status("training", job_id=job_id)

    def run_validation(self, payload: dict[str, Any], async_mode: bool) -> dict[str, Any]:
        model_dir = self._resolve_path(payload.get("model_dir"), self._model_output_dir)
        self._validate_model_dir(model_dir)
        val_root = self._resolve_path(payload.get("val_root"), self._val_dataset_dir)
        selected_capture_ids = {str(item).strip() for item in (payload.get("selected_capture_ids") or []) if str(item).strip()}
        export_summary = self._export_fingerprinting_split(
            dataset_split="val",
            destination_dir=val_root,
            allowed_statuses={"valid"},
            selected_capture_ids=selected_capture_ids or None,
        )
        self._validate_validation_dataset(export_summary, model_dir)
        selected_metadata_paths = self._resolve_validation_selection(
            payload=payload,
            export_summary=export_summary,
        )
        output_json = self._resolve_path(payload.get("output_json"), self._validation_output_dir / "validation_report.json")
        command = [
            self._resolve_python_executable(str(payload.get("python_exe", "")).strip()),
            str(self._scripts_dir / "validate_rf_fingerprint.py"),
            "--val-root",
            str(val_root),
            "--model-dir",
            str(model_dir),
            "--output-json",
            str(output_json),
            "--batch-size",
            str(int(payload.get("batch_size", 256))),
        ]
        for item in selected_metadata_paths:
            command.extend(["--selected-metadata-path", str(item)])
        if async_mode:
            return self._job_manager.start_job(
                command=command,
                cwd=str(self._scripts_dir),
                metadata={
                    "job_type": "validation",
                    "output_json": str(output_json),
                    "dataset_export": export_summary,
                    "selected_metadata_paths": selected_metadata_paths,
                },
            )
        result = subprocess.run(command, cwd=str(self._scripts_dir), capture_output=True, text=True)
        response = {
            "command_result": {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
            "output_json": str(output_json),
            "dataset_export": export_summary,
            "selected_metadata_paths": selected_metadata_paths,
        }
        if result.returncode == 0 and output_json.exists():
            report = self._load_json(output_json)
            if report is not None:
                response["report"] = report
                self._store_validation_report(output_json, report)
        return response

    def validation_status(self, job_id: str | None = None) -> dict[str, Any]:
        status = self._job_manager.get_status("validation", job_id=job_id)
        status = self._attach_report(status)
        if status.get("status") == "completed" and isinstance(status.get("report"), dict):
            output_json = str((status.get("metadata") or {}).get("output_json", "")).strip()
            if output_json:
                self._store_validation_report(Path(output_json), status["report"])
        return status

    def list_validation_reports(self) -> list[dict[str, Any]]:
        reports_dir = self._mlops_reports_root / "validation_reports"
        items: list[dict[str, Any]] = []
        for path in sorted(reports_dir.glob("*.json")):
            data = self._load_json(path)
            if isinstance(data, dict):
                items.append(data)
        return items

    def _store_validation_report(self, source_path: Path, report: dict[str, Any]) -> Path:
        reports_dir = self._mlops_reports_root / "validation_reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        source_digest = str(source_path.resolve()).replace(":", "").replace("\\", "_").replace("/", "_")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = reports_dir / f"validation_{stamp}_{abs(hash(source_digest)) % 1000000:06d}.json"
        if not any(existing.read_text(encoding="utf-8", errors="ignore") == json.dumps(report, indent=2, ensure_ascii=False) for existing in reports_dir.glob("*.json")):
            out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return out_path

    def classify_capture(self, payload: dict[str, Any]) -> dict[str, Any]:
        cfile_path = str(payload.get("cfile_path", ""))
        return {
            "mode": "classify",
            "cfile_path": cfile_path,
            "exists": Path(cfile_path).exists(),
        }

    def verify_capture(self, payload: dict[str, Any]) -> dict[str, Any]:
        cfile_path = str(payload.get("cfile_path", ""))
        return {
            "mode": "verify",
            "cfile_path": cfile_path,
            "exists": Path(cfile_path).exists(),
        }

    def list_prediction_captures(self) -> list[dict[str, Any]]:
        captures: list[dict[str, Any]] = []
        for path in sorted(self._predict_dataset_dir.rglob("*.json")):
            data = self._load_json(path)
            if isinstance(data, dict):
                captures.append(data)
        return captures

    def start_prediction(self, payload: dict[str, Any]) -> dict[str, Any]:
        model_dir = self._resolve_path(payload.get("model_dir"), self._model_output_dir)
        self._validate_model_dir(model_dir)
        output_json = self._resolve_path(payload.get("output_json"), self._inference_output_dir / "prediction_report.json")
        command = [
            self._resolve_python_executable(str(payload.get("python_exe", "")).strip()),
            str(self._scripts_dir / "infer_rf_fingerprint.py"),
            "--cfile-path",
            str(payload.get("cfile_path", "")),
            "--model-dir",
            str(model_dir),
            "--output-json",
            str(output_json),
            "--batch-size",
            str(int(payload.get("batch_size", 256))),
        ]
        metadata_path = str(payload.get("metadata_path", "")).strip()
        if metadata_path:
            command.extend(["--metadata-path", metadata_path])
        return self._job_manager.start_job(
            command=command,
            cwd=str(self._scripts_dir),
            metadata={"job_type": "inference_prediction", "output_json": str(output_json)},
        )

    def prediction_status(self, job_id: str | None = None) -> dict[str, Any]:
        status = self._job_manager.get_status("inference_prediction", job_id=job_id)
        return self._attach_report(status)

    def _attach_report(self, status: dict[str, Any]) -> dict[str, Any]:
        output_json = str((status.get("metadata") or {}).get("output_json", "")).strip()
        if output_json:
            path = Path(output_json)
            if path.exists():
                report = self._load_json(path)
                if report is not None:
                    status["report"] = report
        return status

    def _resolve_path(self, value: str | None, default_path: Path) -> Path:
        if value is None or str(value).strip() == "":
            return default_path
        path = Path(str(value))
        if path.is_absolute():
            return path
        return self._mlops_data_root / path

    def _export_fingerprinting_split(
        self,
        dataset_split: str,
        destination_dir: Path,
        allowed_statuses: set[str],
        target_center_frequency_hz: float | None = None,
        center_frequency_tolerance_hz: float = 1.0,
        selected_capture_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        records = self._load_fingerprinting_captures(dataset_split=dataset_split, allowed_statuses=allowed_statuses)
        if selected_capture_ids:
            records = [record for record in records if str(record.get("capture_id", "")).strip() in selected_capture_ids]
        if target_center_frequency_hz is not None:
            filtered_records: list[dict[str, Any]] = []
            for record in records:
                center_frequency_hz = self._parse_optional_float((record.get("capture_config") or {}).get("center_frequency_hz"))
                if center_frequency_hz is None:
                    continue
                if abs(center_frequency_hz - target_center_frequency_hz) <= center_frequency_tolerance_hz:
                    filtered_records.append(record)
            records = filtered_records
        if destination_dir.exists():
            shutil.rmtree(destination_dir)
        destination_dir.mkdir(parents=True, exist_ok=True)

        exported_records: list[dict[str, Any]] = []
        for record in records:
            exported = self._export_capture_record(record, destination_dir)
            if exported is not None:
                exported_records.append(exported)

        summary = self._dataset_summary(exported_records)
        summary["center_frequencies_hz"] = sorted(
            {round(float(item.get("center_frequency_hz", 0.0) or 0.0), 3) for item in exported_records}
        )
        summary["sample_rates_hz"] = sorted(
            {round(float(item.get("sample_rate_hz", 0.0) or 0.0), 6) for item in exported_records}
        )
        summary.update(
            {
                "dataset_split": dataset_split,
                "export_dir": str(destination_dir),
                "records": len(exported_records),
                "record_paths": [item["metadata_file"] for item in exported_records],
                "exported_records": exported_records,
                "quality_statuses": sorted(allowed_statuses),
                "target_center_frequency_hz": target_center_frequency_hz,
                "center_frequency_tolerance_hz": center_frequency_tolerance_hz,
                "selected_capture_ids": sorted(selected_capture_ids) if selected_capture_ids else [],
            }
        )
        return summary

    def _load_fingerprinting_captures(self, dataset_split: str, allowed_statuses: set[str]) -> list[dict[str, Any]]:
        if not self._fingerprinting_captures_dir.exists():
            return []
        captures: list[dict[str, Any]] = []
        for path in sorted(self._fingerprinting_captures_dir.glob("*.json")):
            data = self._load_json(path)
            if not isinstance(data, dict):
                continue
            if str(data.get("dataset_split", "")).strip().lower() != dataset_split:
                continue
            quality_review = data.get("quality_review") or {}
            status = str(quality_review.get("status", "")).strip().lower()
            if status not in allowed_statuses:
                continue
            captures.append(data)
        return captures

    def _export_capture_record(self, record: dict[str, Any], destination_dir: Path) -> dict[str, Any] | None:
        transmitter = record.get("transmitter") or {}
        scenario = record.get("scenario") or {}
        capture_config = record.get("capture_config") or {}
        artifacts = record.get("artifacts") or {}

        emitter_device_id = str(transmitter.get("transmitter_label") or transmitter.get("transmitter_id") or "").strip()
        session_id = str(record.get("session_id") or "").strip()
        iq_path_text = str(artifacts.get("iq_file") or capture_config.get("output_path") or "").strip()
        if not emitter_device_id or not session_id or not iq_path_text:
            return None
        iq_source = Path(iq_path_text)
        if not iq_source.exists() or not iq_source.is_file():
            return None

        session_dir = destination_dir / emitter_device_id / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        suffix = iq_source.suffix or ".cfile"
        export_stem = f"iq_{emitter_device_id}_{record.get('capture_id', 'capture')}"
        exported_iq = session_dir / f"{export_stem}{suffix}"
        shutil.copy2(iq_source, exported_iq)

        center_frequency_hz = float(capture_config.get("center_frequency_hz", 0.0) or 0.0)
        sample_rate_hz = float(capture_config.get("sample_rate_hz", 0.0) or 0.0)
        bandwidth_hz = float(capture_config.get("effective_bandwidth_hz", sample_rate_hz) or sample_rate_hz)
        gain_settings = capture_config.get("gain_settings") or {}
        metadata = {
            "id": str(record.get("capture_id", "")),
            "generated_at_utc": str(record.get("created_at_utc", _utc_now())),
            "capture_type": "fingerprint_iq",
            "source_device": str(capture_config.get("device_source", "")),
            "receiver_id": str(capture_config.get("sdr_serial") or capture_config.get("sdr_model") or "unknown"),
            "emitter_device_id": emitter_device_id,
            "session_id": session_id,
            "environment_id": str(scenario.get("environment", "")),
            "label": str(transmitter.get("transmitter_class", "")),
            "modulation_hint": str(transmitter.get("family") or "unknown"),
            "notes": str(scenario.get("notes", "")),
            "center_frequency_hz": center_frequency_hz,
            "bandwidth_hz": bandwidth_hz,
            "duration_seconds": float(capture_config.get("capture_duration_s", 0.0) or 0.0),
            "sample_rate_hz": sample_rate_hz,
            "sample_count": int(capture_config.get("sample_count", 0) or 0),
            "gain_db": float(gain_settings.get("composite_gain_db", 0.0) or 0.0),
            "agc_enabled": str(capture_config.get("gain_mode", "manual")).strip().lower() == "auto",
            "antenna": str(capture_config.get("antenna_port", "RX2")),
            "device_addr": str(capture_config.get("sdr_serial", "")),
            "channel_index": int(capture_config.get("channel_count", 1) or 1) - 1,
            "iq_file": str(exported_iq.resolve()),
            "metadata_file": str((session_dir / f"{export_stem}.json").resolve()),
            "iq_format": "complex64_fc32_interleaved",
            "iq_dtype": str(capture_config.get("sample_dtype", "complex64")),
            "byte_order": str(capture_config.get("byte_order", "native")),
            "file_size_bytes": exported_iq.stat().st_size,
            "sha256": str(artifacts.get("sha256", "")),
            "replay_parameters": {
                "center_frequency_hz": center_frequency_hz,
                "sample_rate_hz": sample_rate_hz,
                "gain_db": float(gain_settings.get("composite_gain_db", 0.0) or 0.0),
                "antenna": str(capture_config.get("antenna_port", "RX2")),
                "iq_format": "complex64_fc32_interleaved",
            },
            "ai_dataset_fields": [
                "emitter_device_id",
                "session_id",
                "receiver_id",
                "environment_id",
                "label",
                "modulation_hint",
                "center_frequency_hz",
                "bandwidth_hz",
                "sample_rate_hz",
                "duration_seconds",
                "iq_file",
                "sha256",
            ],
        }
        metadata_path = session_dir / f"{export_stem}.json"
        metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        return {
            "capture_id": str(record.get("capture_id", "")),
            "iq_file": str(exported_iq.resolve()),
            "metadata_file": str(metadata_path.resolve()),
            "source_iq_file": str(iq_source.resolve()),
            "source_metadata_file": str(artifacts.get("metadata_file") or ""),
            "emitter_device_id": emitter_device_id,
            "session_id": session_id,
            "receiver_id": metadata["receiver_id"],
            "environment_id": metadata["environment_id"],
            "sample_rate_hz": sample_rate_hz,
            "center_frequency_hz": center_frequency_hz,
            "duration_seconds": metadata["duration_seconds"],
            "sha256": metadata["sha256"],
            "label": metadata["label"],
            "modulation_hint": metadata["modulation_hint"],
        }

    def _resolve_validation_selection(self, payload: dict[str, Any], export_summary: dict[str, Any]) -> list[str]:
        exported_records = export_summary.get("exported_records") or []
        if not isinstance(exported_records, list):
            exported_records = []

        by_capture_id: dict[str, str] = {}
        by_source_metadata: dict[str, str] = {}
        by_exported_metadata: dict[str, str] = {}
        for item in exported_records:
            if not isinstance(item, dict):
                continue
            exported_metadata = str(item.get("metadata_file", "")).strip()
            if not exported_metadata:
                continue
            capture_id = str(item.get("capture_id", "")).strip()
            if capture_id:
                by_capture_id[capture_id] = exported_metadata
            source_metadata = str(item.get("source_metadata_file", "")).strip()
            if source_metadata:
                by_source_metadata[source_metadata] = exported_metadata
            by_exported_metadata[exported_metadata] = exported_metadata

        requested_paths = payload.get("selected_metadata_paths") or []
        requested_capture_ids = payload.get("selected_capture_ids") or []
        resolved: list[str] = []

        for value in requested_capture_ids:
            selected = by_capture_id.get(str(value).strip())
            if selected and selected not in resolved:
                resolved.append(selected)

        for value in requested_paths:
            text = str(value).strip()
            if not text:
                continue
            selected = by_exported_metadata.get(text) or by_source_metadata.get(text) or by_capture_id.get(text)
            if selected and selected not in resolved:
                resolved.append(selected)

        return resolved

    def _validate_training_dataset(self, dataset_summary: dict[str, Any]) -> None:
        if int(dataset_summary.get("records", 0)) == 0:
            raise ValueError(
                "Training dataset export is empty. Mark at least 2 captures as train, review them as valid, and retry."
            )
        device_ids = list(dataset_summary.get("device_ids", []))
        if len(device_ids) < 2:
            raise ValueError(
                "Training requires at least 2 unique transmitters with dataset_split=train and quality_review.status=valid. "
                f"Found {len(device_ids)}: {', '.join(device_ids) if device_ids else '<none>'}."
            )
        center_frequencies = list(dataset_summary.get("center_frequencies_hz", []))
        if len(center_frequencies) != 1:
            raise ValueError(
                "Training requires exactly 1 center_frequency_hz across exported train captures. "
                f"Found {len(center_frequencies)}: {center_frequencies or ['<none>']}."
            )
        sample_rates = list(dataset_summary.get("sample_rates_hz", []))
        if len(sample_rates) != 1:
            raise ValueError(
                "Training requires exactly 1 sample_rate_hz across exported train captures. "
                f"Found {len(sample_rates)}: {sample_rates or ['<none>']}."
            )

    def _validate_model_dir(self, model_dir: Path) -> None:
        required = [
            model_dir / "best_model.pt",
            model_dir / "enrollment_profiles.json",
            model_dir / "dataset_manifest.json",
        ]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise ValueError(
                "Model directory is incomplete. Missing: " + ", ".join(missing)
            )

    def _validate_validation_dataset(self, dataset_summary: dict[str, Any], model_dir: Path) -> None:
        if int(dataset_summary.get("records", 0)) == 0:
            raise ValueError(
                "Validation requires at least 1 capture with dataset_split=val and quality_review.status=valid."
            )
        center_frequencies = list(dataset_summary.get("center_frequencies_hz", []))
        if len(center_frequencies) != 1:
            raise ValueError(
                "Validation requires exactly 1 center_frequency_hz across exported val captures. "
                f"Found {len(center_frequencies)}: {center_frequencies or ['<none>']}."
            )
        sample_rates = list(dataset_summary.get("sample_rates_hz", []))
        if len(sample_rates) != 1:
            raise ValueError(
                "Validation requires exactly 1 sample_rate_hz across exported val captures. "
                f"Found {len(sample_rates)}: {sample_rates or ['<none>']}."
            )

        train_config = self._load_json(model_dir / "train_config.json")
        if isinstance(train_config, dict):
            model_center = train_config.get("center_frequency_hz")
            model_sample_rate = train_config.get("sample_rate_hz")
            if model_center is not None and round(float(model_center), 3) != center_frequencies[0]:
                raise ValueError(
                    "Validation center_frequency_hz does not match the trained model. "
                    f"Model={round(float(model_center), 3)} Hz, validation={center_frequencies[0]} Hz."
                )
            if model_sample_rate is not None and round(float(model_sample_rate), 6) != sample_rates[0]:
                raise ValueError(
                    "Validation sample_rate_hz does not match the trained model. "
                    f"Model={round(float(model_sample_rate), 6)} sps, validation={sample_rates[0]} sps."
                )

    def _resolve_python_executable(self, requested: str | None) -> str:
        candidate = str(requested or "").strip()
        if candidate:
            path = Path(candidate)
            if path.exists():
                return str(path)
            raise ValueError(f"python_exe not found: {candidate}")
        default_path = Path(str(self._default_python)) if getattr(self, "_default_python", None) else None
        if default_path and default_path.exists():
            return str(default_path)
        return sys.executable

    @staticmethod
    def _parse_optional_float(value: Any) -> float | None:
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            return None
        try:
            parsed = float(text)
        except (TypeError, ValueError):
            return None
        if not np.isfinite(parsed):
            return None
        return parsed

    @staticmethod
    def _resolve_powershell_executable() -> str:
        preferred = Path(r"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe")
        if preferred.exists():
            return str(preferred)
        return "powershell"

    @staticmethod
    def _load_json(path: Path) -> Any:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    @staticmethod
    def _safe_size(path: Path) -> int:
        try:
            return path.stat().st_size if path.exists() else 0
        except OSError:
            return 0

    @staticmethod
    def _safe_mtime(path: Path) -> str | None:
        try:
            if not path.exists():
                return None
            return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            return None

    @staticmethod
    def _safe_tree_size(path: Path) -> int:
        if not path.exists():
            return 0
        total = 0
        try:
            for item in path.rglob("*"):
                if item.is_file():
                    total += item.stat().st_size
        except OSError:
            return total
        return total

    def _collect_file_inventory(self, model_dir: Path) -> list[dict[str, Any]]:
        inventory: list[dict[str, Any]] = []
        if not model_dir.exists():
            return inventory
        for path in sorted(model_dir.glob("*")):
            if not path.is_file():
                continue
            inventory.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "size_bytes": self._safe_size(path),
                    "modified_at_utc": self._safe_mtime(path),
                }
            )
        return inventory

    @staticmethod
    def _dataset_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
        devices = sorted({str(r.get("emitter_device_id", "")).strip() for r in records if r.get("emitter_device_id")})
        sessions = sorted({f"{r.get('emitter_device_id', '')}:{r.get('session_id', '')}" for r in records if r.get("session_id")})
        return {
            "records": len(records),
            "devices": len(devices),
            "sessions": len(sessions),
            "device_ids": devices,
        }

    @staticmethod
    def _history_summary(history: list[dict[str, Any]]) -> dict[str, Any]:
        if not history:
            return {
                "epochs": 0,
                "best_test_acc": 0.0,
                "last_test_acc": 0.0,
                "last_train_acc": 0.0,
                "best_epoch": None,
            }
        best_row = max(history, key=lambda row: float(row.get("test_acc", 0.0)))
        last_row = history[-1]
        return {
            "epochs": len(history),
            "best_test_acc": float(best_row.get("test_acc", 0.0)),
            "last_test_acc": float(last_row.get("test_acc", 0.0)),
            "last_train_acc": float(last_row.get("train_acc", 0.0)),
            "best_epoch": int(best_row.get("epoch", 0)) if best_row.get("epoch") is not None else None,
        }
