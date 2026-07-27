"""Fase 2 addition: the Dataset Analyzer's output. Never a hardcoded verdict
-- every field here is the result of an actual computed check over a
concrete DatasetManifest, and a FAILED/blocked check always carries the
specific example_ids or keys involved, never just a string like "PASSED"."""
from __future__ import annotations

from typing import Literal

from .common import StudioContract

QUALITY_REPORT_SCHEMA_VERSION = "ble-rffi-studio-quality-report-v1"

CheckStatus = Literal["PASSED", "FAILED", "NOT_EXECUTED"]
GateDecision = Literal["ACCEPTED_FOR_TRAINING", "ACCEPTED_WITH_LIMITATIONS", "NOT_ACCEPTED_FOR_TRAINING"]


class ExactDuplicatesResult(StudioContract):
    status: CheckStatus
    duplicate_groups: list[list[str]] = []  # groups of example_id sharing identical (source_iq_sha256, start, end)


class SampleOverlapResult(StudioContract):
    status: CheckStatus
    overlapping_pairs: list[list[str]] = []  # [example_id_a, example_id_b] with overlapping (not identical) ranges


class NearDuplicateResult(StudioContract):
    """DIAGNOSTIC_CHECK only -- per design correction #12, never a blocking
    gate until metric/threshold/phase-and-time invariance/false-positive-rate
    are validated. Always NOT_EXECUTED or a non-blocking informational status;
    this contract structurally has no FAILED state to prevent it from being
    mistaken for a gate."""

    status: Literal["DIAGNOSTIC_CHECK", "NOT_EXECUTED"]
    similarity_metric: str = ""
    similarity_threshold: float | None = None
    flagged_pairs: list[list[str]] = []
    note: str = ""


class DatasetQualityReport(StudioContract):
    schema_version: Literal["ble-rffi-studio-quality-report-v1"] = QUALITY_REPORT_SCHEMA_VERSION
    dataset_id: str
    dataset_version: str

    exact_duplicates: ExactDuplicatesResult
    sample_overlap: SampleOverlapResult
    near_duplicates: NearDuplicateResult

    gate_decision: GateDecision
    gate_reasons: list[str] = []
    created_at: str
