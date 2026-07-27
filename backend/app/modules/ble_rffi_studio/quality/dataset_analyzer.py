"""Real, computed dataset quality checks -- nothing here is a hardcoded
"PASSED" literal. exact_duplicates and sample_overlap are blocking gates;
near_duplicates is always DIAGNOSTIC_CHECK (design correction #12) and can
never by itself produce NOT_ACCEPTED_FOR_TRAINING.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..contracts import (
    DatasetManifest,
    DatasetQualityReport,
    ExactDuplicatesResult,
    ExampleRecord,
    NearDuplicateResult,
    SampleOverlapResult,
)

DEFAULT_NEAR_DUPLICATE_THRESHOLD = 0.98
DEFAULT_MAX_GROUP_SIZE = 300


class DatasetAnalyzer:
    def check_exact_duplicates(self, examples: list[ExampleRecord]) -> ExactDuplicatesResult:
        groups: dict[tuple[str, int, int], list[str]] = {}
        for example in examples:
            key = (example.source_iq_sha256, example.iq_start_sample, example.iq_end_sample)
            groups.setdefault(key, []).append(example.example_id)
        duplicate_groups = [sorted(ids) for ids in groups.values() if len(ids) > 1]
        return ExactDuplicatesResult(status="FAILED" if duplicate_groups else "PASSED", duplicate_groups=duplicate_groups)

    def check_sample_overlap(self, examples: list[ExampleRecord]) -> SampleOverlapResult:
        by_source: dict[str, list[ExampleRecord]] = {}
        for example in examples:
            by_source.setdefault(example.source_iq_sha256, []).append(example)

        overlapping_pairs: list[list[str]] = []
        for group in by_source.values():
            ordered = sorted(group, key=lambda e: e.iq_start_sample)
            for i in range(len(ordered)):
                a = ordered[i]
                for j in range(i + 1, len(ordered)):
                    b = ordered[j]
                    if b.iq_start_sample >= a.iq_end_sample:
                        break  # sorted by start -- no later item can overlap `a` either
                    if a.iq_start_sample == b.iq_start_sample and a.iq_end_sample == b.iq_end_sample:
                        continue  # exact duplicate, already reported by check_exact_duplicates
                    overlapping_pairs.append(sorted([a.example_id, b.example_id]))
        return SampleOverlapResult(status="FAILED" if overlapping_pairs else "PASSED", overlapping_pairs=overlapping_pairs)

    def check_near_duplicates(
        self,
        examples: list[ExampleRecord],
        capture_iq_paths: dict[str, Path] | None = None,
        similarity_threshold: float = DEFAULT_NEAR_DUPLICATE_THRESHOLD,
        max_group_size: int = DEFAULT_MAX_GROUP_SIZE,
    ) -> NearDuplicateResult:
        """Real, but deliberately narrow: normalized complex cross-correlation
        magnitude between raw I/Q windows, compared only within the same
        capture (bounding the O(n^2) cost). This is exactly the honest scope
        of a DIAGNOSTIC_CHECK -- it has not been validated for phase/time
        invariance or false-positive rate, so it never blocks freezing."""
        if not capture_iq_paths:
            return NearDuplicateResult(status="NOT_EXECUTED", note="No IQ file paths supplied; near-duplicate diagnostic requires reading raw samples.")

        by_capture: dict[str, list[ExampleRecord]] = {}
        for example in examples:
            by_capture.setdefault(example.capture_id, []).append(example)

        flagged: list[list[str]] = []
        skipped_captures: list[str] = []
        for capture_id, group in by_capture.items():
            path = capture_iq_paths.get(capture_id)
            if path is None or not Path(path).is_file():
                continue
            if len(group) > max_group_size:
                skipped_captures.append(capture_id)
                continue
            data = np.memmap(path, dtype=np.complex64, mode="r")
            windows: dict[str, np.ndarray] = {}
            for example in group:
                start, end = example.iq_start_sample, min(example.iq_end_sample, data.shape[0])
                if start >= end:
                    continue
                windows[example.example_id] = np.asarray(data[start:end])
            ids = list(windows.keys())
            for i in range(len(ids)):
                a = windows[ids[i]]
                for j in range(i + 1, len(ids)):
                    b = windows[ids[j]]
                    n = min(len(a), len(b))
                    if n == 0:
                        continue
                    a_t, b_t = a[:n], b[:n]
                    denom = float(np.linalg.norm(a_t) * np.linalg.norm(b_t))
                    if denom == 0.0:
                        continue
                    similarity = abs(np.vdot(a_t, b_t)) / denom
                    if similarity >= similarity_threshold:
                        flagged.append(sorted([ids[i], ids[j]]))

        note = "Diagnostic only -- never blocks dataset freezing. Compares normalized complex cross-correlation magnitude within the same capture only; not validated for phase/time invariance or false-positive rate."
        if skipped_captures:
            note += f" Skipped {len(skipped_captures)} capture(s) exceeding max_group_size={max_group_size}: {skipped_captures}."
        return NearDuplicateResult(
            status="DIAGNOSTIC_CHECK", similarity_metric="normalized_complex_cross_correlation_magnitude",
            similarity_threshold=similarity_threshold, flagged_pairs=flagged, note=note,
        )

    def build_gate(
        self,
        dataset: DatasetManifest,
        exact_duplicates: ExactDuplicatesResult,
        sample_overlap: SampleOverlapResult,
        near_duplicates: NearDuplicateResult,
        created_at: str,
    ) -> DatasetQualityReport:
        reasons: list[str] = []
        if not dataset.example_ids:
            return DatasetQualityReport(
                dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version,
                exact_duplicates=exact_duplicates, sample_overlap=sample_overlap, near_duplicates=near_duplicates,
                gate_decision="NOT_ACCEPTED_FOR_TRAINING", gate_reasons=["Dataset has zero examples."], created_at=created_at,
            )

        if exact_duplicates.status == "FAILED":
            reasons.append(f"{len(exact_duplicates.duplicate_groups)} exact-duplicate group(s) found.")
        if sample_overlap.status == "FAILED":
            reasons.append(f"{len(sample_overlap.overlapping_pairs)} overlapping (non-identical) sample-range pair(s) found.")

        if exact_duplicates.status == "FAILED" or sample_overlap.status == "FAILED":
            gate_decision: Any = "NOT_ACCEPTED_FOR_TRAINING"
        elif near_duplicates.status == "DIAGNOSTIC_CHECK" and near_duplicates.flagged_pairs:
            gate_decision = "ACCEPTED_WITH_LIMITATIONS"
            reasons.append(f"{len(near_duplicates.flagged_pairs)} near-duplicate pair(s) flagged as a non-blocking diagnostic; review before drawing strong conclusions.")
        else:
            gate_decision = "ACCEPTED_FOR_TRAINING"

        return DatasetQualityReport(
            dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version,
            exact_duplicates=exact_duplicates, sample_overlap=sample_overlap, near_duplicates=near_duplicates,
            gate_decision=gate_decision, gate_reasons=reasons, created_at=created_at,
        )
