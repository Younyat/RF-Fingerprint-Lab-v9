# BLE-RFFI Studio module technical README

Audience: programmers maintaining the BLE-RFFI End-to-End Studio (the
independent module that turns already-captured/replayed B200 IQ into
CaptureRecord -> Evidence -> Dataset -> Training -> Evaluation -> Export ->
Inference).

This README is part of the project audit trail. Any meaningful change to this
module must update this file in the same work item: what changed, why it
changed, what scientific/UX assumption it protects, and how it was verified.

## Module scope

This module never re-captures or re-decodes IQ itself. It reads the
already-validated legacy B200 capture tree (`ble/capture` module) and the
already-replayed/decoded packets (`ble/packet_analysis` module), then owns
everything downstream of that:

- `contracts/` -- pydantic schemas for every artifact (`CaptureRecord`,
  `ExampleRecord`/`ExampleAnnotation`, `DatasetManifest`, `SplitManifest`,
  `TrainingRun`, `ModelBundleManifest`, `DatasetQualityReport`). One
  vocabulary, versioned via `*_SCHEMA_VERSION` constants.
- `acquisition/capture_stage.py` -- builds a `CaptureRecord` from a legacy
  capture directory.
- `registry/` -- Physical Device Registry: `PhysicalUnitRecord` +
  `AddressBinding`, the only place an operator-declared identity is turned
  into a binding a BLE radio address can resolve to.
- `evidence/evidence_stage.py` -- turns one replayed capture into
  `ExampleRecord`/`ExampleAnnotation` pairs (association/quality/eligibility
  separated, never auto-promoted to `ELIGIBLE`).
- `dataset/`, `quality/`, `training/`, `evaluation/`, `export/`, `inference/`
  -- Fase 2-5: dataset freezing, quality gate, VALIDATION-only model
  selection + single TEST evaluation, bundle export with
  `data_origin`/`operational_use` gating, offline inference.
- `campaign/campaign_orchestrator.py` -- orchestrates a REAL capture campaign
  session end to end (hybrid B200+native-scan session -> CaptureStage ->
  resumable offline replay -> EvidenceStage), reusing the `ble_lab` module's
  hybrid/capture managers as pure mechanism.
- `api/` -- `StudioRepository` (all read/write logic), `StudioJobManager`
  (background jobs: evidence build, training, prepare-and-train, campaign
  session), `studio_routes.py` (FastAPI routes).
- `demo/synthetic_demo_seeder.py` -- SYNTHETIC_TEST_ONLY fixture generator.
  No UI entry point in Guided mode (see below); kept only as a backend
  regression fixture (`test_data_origin_gating.py`) and reachable from
  Advanced mode.
- `scientific_basis/` -- technique/preprocessing/model evidence registry (see
  its own README).

It does not perform BLE demodulation, RF acquisition, or native Windows BLE
scanning -- those remain the `ble/capture`, `ble/packet_analysis` and
`ble_lab` modules' responsibility.

## Guided Mode: capture purpose contract

The Guided UI's very first question is **"¿Que quieres capturar ahora?"** --
never a device picker forced up front, since an environment/background
capture may not need one at all. This is a real contract on `CaptureRecord`
(`contracts/capture.py`), not just frontend state:

```text
CapturePurpose = "TARGET_DEVICE" | "BACKGROUND_ENVIRONMENT"
TargetState    = "POWERED_ON" | "OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED"
DatasetRole    = "POSITIVE_CANDIDATE" | "NEGATIVE_CANDIDATE"
```

- `capture_purpose` / `target_state` / `dataset_role` are derived together,
  never set independently of each other (`CampaignOrchestrator.run_session`
  and `StudioRepository._capture_type_and_decision` are the two places that
  do this derivation -- keep them in sync if this mapping ever changes).
- `target_reference_id` is documentary only: which physical unit this
  capture's declared purpose is about (the unit selected for TARGET_DEVICE,
  or the unit the operator says was off/removed for BACKGROUND_ENVIRONMENT).
  It is **never** treated as ground truth for labeling on its own.
- `CampaignOrchestrator.run_session` validates: `TARGET_DEVICE` requires a
  `physical_unit_id`; `BACKGROUND_ENVIRONMENT` requires
  `operator_confirmed_target_absent=True` (raises otherwise) and always
  forces `isolation_declared=False`, regardless of what the caller passed --
  physical isolation ("only this unit was transmitting nearby") asserts the
  opposite of what a background capture is for, so a stale/incorrect
  frontend request can never smuggle a positive label onto it.
- **The system never infers `POWERED_OFF` from the absence of a signal.**
  That state comes exclusively from the operator's explicit confirmation at
  capture time. `EvidenceStage._build_example` enforces this at the evidence
  layer: if a `BACKGROUND_ENVIRONMENT` capture's `target_reference_id` is
  set and an example's resolved `physical_unit_id` happens to match it (via
  the normal, unreliable address-binding lookup), that is treated as a real,
  honestly-surfaced **contradiction** -- `association_status="CONFLICT"`,
  `physical_unit_id=None` -- never silently trusted as a positive example.
  This reuses the existing `CONFLICT`/quarantine bucket
  (`MULTIPLE_NATIVE_CALLBACKS` uses the same status for a different reason;
  `EvidenceStage._build_annotation`'s `is_background_contradiction` check
  distinguishes the two for the annotation's `decision_reason` text).

`StudioRepository._capture_type_and_decision(capture_id)` computes, fresh
from the capture + its examples (never stored/duplicated on the capture
itself):

- `capture_type_label` -- human text for the Guided UI's captures list:
  `"Dispositivo encendido"` / `"Entorno -- dispositivo apagado"` /
  `"Entorno general"` / `"Sin clasificar"` (legacy/pre-this-feature capture,
  `capture_purpose is None`) / `"Sintetica de pruebas"`.
- `capture_decision` -- `ELIGIBLE_AS_POSITIVE` / `ELIGIBLE_AS_BACKGROUND` /
  `QUARANTINED` / `REJECTED` / `NOT_ANALYZED_YET`. "Eligible so far" here
  means the same includable set `DatasetBuilder.select_examples()` itself
  uses (quality `PASSED`, `dataset_eligibility` in
  `{PENDING_REVIEW, ELIGIBLE}`) -- Evidence Stage never itself promotes an
  example all the way to `ELIGIBLE` (that is the Fase 2 Dataset
  Builder/Analyzer gate's call, made per-dataset, not per-capture).

Both are exposed on every row from `StudioRepository.list_legacy_captures()`
(`GET /legacy-captures`), alongside the pre-existing `device_label`/
`device_source` (which answer *which device*, a different question from
*what was this capture for*).

## Frontend contract point

`frontend/src/presentation/views/ble-rffi-studio/BleRffiStudioGuided.tsx` is
the only consumer of this contract today:

- Step 1: the two-button gate (`chooseCapturePurpose`).
- Step 2: conditional device selection + the isolation checkbox
  (TARGET_DEVICE) or the operator-absence-confirmation checkbox
  (BACKGROUND_ENVIRONMENT) -- never both. Unregistered devices detected by
  the native scan are shown in a collapsed `<details>` dropdown (opened on
  click, not by default) with filters by name, MAC substring, minimum RSSI
  (dBm) and max age since last seen (`filteredUnregisteredActiveDevices`) --
  a real scan in a populated area returns many far-away devices, and the
  operator needs to narrow that down rather than scroll past all of them.
  The RSSI floor defaults to -127 dBm (the practical floor of the scale, so
  nothing is excluded until the operator opts in) -- a first version
  defaulted to -100 dBm and silently hid real far-away devices the operator
  used to see, since BLE RSSI commonly goes below -100 for those.
- Step 3: launches a real campaign session (`launchCampaignSession`, forwards
  `capture_purpose`/`operator_confirmed_target_absent`) or reuses existing
  legacy captures (`useRealCaptures`) -- the latter always **rebuilds** the
  `CaptureRecord` and re-runs the evidence job rather than reusing a
  previously-built one, so a stale declaration from an earlier session
  reusing the same legacy `capture_id` can never linger. Per-session results
  (Tipo / Estado declarado / Paquetes / Elegibles / Calidad / Decision) and
  device-vs-environment progress counters are shown here.
- Captures list: "Tipo de captura" column +
  `[Todas][Dispositivo][Entorno][Sin analizar]` filters
  (`matchesCaptureFilter`).
- Technical IDs/contracts/internal states stay in Advanced mode; nothing
  above should ever require the operator to know a `capture_purpose` string
  literal exists.

Covered by `frontend/tests/e2e/ble-rffi-studio.spec.ts` -- in particular the
three mandatory tests named `Prueba 1/2/3`: a `BACKGROUND_ENVIRONMENT`
capture is never linked as positive for the declared-absent unit, a
`TARGET_DEVICE` capture's decision is a real computed verdict (never a
fabricated default), and capture type/declaration/decision survive a full
page reload (because they live on the backend's `CaptureRecord`, never only
in React state).

## Data origin / operational use gating (unchanged by the above)

Independent of `capture_purpose`, every `CaptureRecord`/`DatasetManifest`/
`TrainingRun`/`ModelBundleManifest` still carries `data_origin` (`REAL_B200`
vs `SYNTHETIC_TEST_ONLY`). A bundle trained on any synthetic data is capped at
`SYNTHETIC_PIPELINE_VERIFIED` and can never reach `EVALUATED` or
`APPROVED_FOR_LIVE_PILOT` (`export/bundle_builder.py`,
`test_data_origin_gating.py`). This gate and `capture_purpose` are
orthogonal: a capture can be `REAL_B200` + `BACKGROUND_ENVIRONMENT`, for
example, and both facts are enforced independently.

## Verification

- Backend: `backend/.venv-validation/Scripts/python.exe -m pytest
  app/tests/unit/ble_rffi_studio/` (178 tests as of this contract's
  introduction).
- Frontend: `npx tsc --noEmit -p .` and
  `npx playwright test tests/e2e/ble-rffi-studio.spec.ts` (7 tests, including
  `Prueba 1/2/3`) with the real backend running (`radioconda` python, no
  `--reload` -- restart it after any backend code change in this module,
  since a stale process silently ignores new contract fields instead of
  erroring).
