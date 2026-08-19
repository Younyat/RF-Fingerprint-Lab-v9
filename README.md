# RF-Fingerprint-Lab

**Software-defined radio research platform for RF acquisition, BLE
physical-layer device-identification research, signal analysis, and
experimental live inference.**

RF-Fingerprint-Lab combines a real **USRP B200** SDR acquisition path with a
browser-based research environment (**FastAPI** backend, **React/TypeScript**
frontend) built around one central research problem: given a known set of
enrolled BLE devices, which of them is most compatible with a later,
questioned RF emission?

![Live Monitor spectrum](readme_img/live_monitor.png)

---

## Start here: the practical problem

We have a limited set of physical BLE devices, previously **enrolled** —
recorded and characterized ahead of time under controlled conditions. Later,
a new RF emission appears. The practical question this project investigates
is:

**Which enrolled physical device is most compatible with this RF emission?**

**Context.** Known physical BLE devices can be recorded beforehand, under
controlled conditions.

**Problem.** A BLE advertising address is *logical* information — a value
the device's firmware reports. It is not, by itself, physical proof of
which radio actually generated the waveform: an attacker only needs to copy
that value into a different transmitter.

**Approach.** The USRP B200 preserves the actual RF waveform as raw I/Q
samples. Controlled reference examples are built from known, enrolled
devices; models are trained on those references; a later, questioned
emission is compared against the frozen enrolled set — never decided from
the advertised address alone.

```text
known devices -> enrollment -> B200 RF -> dataset -> training -> frozen model -> new emission -> comparison / inconclusive
```

## Why train a model?

Two different moments use the RF evidence differently, and the distinction
matters for the whole rest of this document.

**Enrollment** — building the reference:

```text
known device -> Windows/native BLE (independent logical observation)
             -> B200 captures real RF I/Q
             -> association / admission
             -> reference example
```

**Questioned-source comparison** — using the reference later:

```text
new RF emission -> B200
                 -> frozen preprocessing / frozen model
                 -> comparison against enrolled devices
                 -> result, or inconclusive
```

Windows/native BLE helps **build and check** the enrolled references during
enrollment. It is **not** supplied to the RF classifier as the answer during
later source comparison. If the native Windows stack had to identify every
future emission in advance, the RF-fingerprint classifier would add little
value on top of it — the entire point of BLE-RFFI Studio is a comparison
method that works from radio evidence alone, once enrollment is done.

## How the BLE-RFFI pipeline works

1. Capture RF I/Q (USRP B200, frozen acquisition profile).
2. Detect candidate bursts.
3. Recover BLE packets and verify CRC.
4. Associate packet evidence with an enrolled physical device, under a
   calibrated, **fail-closed** policy.
5. Create traceable examples tied to their exact source I/Q and sample
   range.
6. Build capture-disjoint scientific partitions (TRAIN / VALIDATION /
   protected FUTURE TEST).
7. Train -> validate -> freeze -> protected future evaluation / source
   comparison.

> **CRC-valid packet ≠ physical-source identity.** A correctly decoded
> packet proves the bits were received correctly. It does not, by itself,
> prove which enrolled physical device sent them — that is exactly what
> steps 4 and 7 exist to establish, separately and explicitly, never
> assumed from decode success alone.

---

## Four questions that keep a high score honest

A classifier can score well on held-out data for reasons that have nothing
to do with recognizing real RF hardware characteristics. These four checks
each test one specific, easy alternative explanation.

### RQ1 — Acquisition dependence

**Does it still work on a new recording?**

```text
related capture -> independent capture -> protected future period
```

Tests whether apparent performance depended on incidental context shared
between TRAIN and TEST captures (the same recording session, nearby-in-time
conditions), rather than on the device's real RF characteristics.

### RQ2 — Signal representation

**If every branch receives exactly the same admitted RF evidence, does how
we represent it change the result?**

```text
same admitted RF -> engineered features | raw I/Q | STFT time-frequency | coarse morphology
```

The same examples, the same partitions, four different representations —
see [Implemented benchmark](#implemented-ble-rffi-benchmark) below for the
four real branches this compares.

### RQ3 — Radio-state intervention

**Does turning the transmitter off and back on change the fingerprint more
than simply leaving it running?**

```text
PRE -> RESET -> POST
PRE -> CONTINUOUS/CONTROL -> POST
```

Separates a reset-associated displacement in the fingerprint from ordinary
PRE/POST drift that would happen anyway. `receiver_epoch` (identity +
qualified acquisition profile + session boundary) protects this pairing:
a PRE/POST pair is invalidated whenever the receiver's qualified state
changed between the two captures.

> **Limitation, stated explicitly.** For historical data with no logged
> restart/reconnect event, the session boundary uses a >1 hour acquisition
> gap as a documented proxy. This is **not** direct physical evidence that
> the B200 was actually restarted — see
> [`docs/ble/SCIENTIFIC_STATUS.md`](docs/ble/SCIENTIFIC_STATUS.md) §16.4.

### RQ4 — Packet-content dependence

**Is the model learning RF characteristics, or exploiting easy-to-copy BLE
packet content?**

```text
FULL_BURST | ADVA_EXCLUDED | PRE_PDU
```

`ADVA_EXCLUDED` genuinely **removes** the AdvA (advertiser address) sample
range from the analytical region — it is spliced out, never replaced with a
fixed zero block, so no artificial, trivially learnable pattern is
introduced in its place. `PRE_PDU` is:

```text
Preamble + Access Address | STOP
```

— stopping before the PDU header, so no packet payload content is present
at all in that variant.

---

## Implemented BLE-RFFI benchmark

RQ2's four real, executable signal-analysis branches — the only ones
BLE-RFFI Studio trains:

| Representation | Model(s) |
|---|---|
| Engineered RF descriptors | Logistic Regression / SVM-RBF / Random Forest |
| Raw I/Q | CNN1D |
| Time-frequency (STFT) | CNN2D |
| Coarse time-frequency morphology | Frozen morphological baseline (nearest-centroid, no iterative training) |

No other signal-analysis branch is implemented, exposed, or planned for
BLE-RFFI Studio. Ideas beyond this table (edge transformers, metric learning,
quantized inference, and similar) are tracked separately, explicitly not
mixed with the table above, in
[`docs/research/TECHNIQUE_ROADMAP.md`](docs/research/TECHNIQUE_ROADMAP.md).

### Scientific preprocessing

Two profiles matter for BLE-RFFI Studio's real scientific scope:

- **`paper-eq6-7-v1`** — the primary preprocessing: a frozen BLE reference
  waveform `q[n]`, phase unwrapping over a frozen fitting interval
  (`preamble + access address`), a joint least-squares estimate of an
  affine phase/frequency offset, and per-burst provenance persisted with
  every prediction.
- **`offset-retaining-v1`** — the matching sensitivity-analysis profile,
  identical pipeline, offset deliberately not compensated.

An older, simpler correction (`cfo-compensated-v1`) still exists for
historical/ablation utility. It is explicitly labeled **heuristic/legacy**
and must not be read as an implementation of the paper's compensation —
full derivation and the exact distinction:
[`docs/ble/PREPROCESSING.md`](docs/ble/PREPROCESSING.md).

---

## Current scientific status

**Implemented** = exists in code, wired into the real pipeline, has tests.
**Experimentally validated** = additionally exercised by the required real
campaign, with real evidence meeting its stated scientific criteria. The
second never follows automatically from the first anywhere in this project.

Three explicit status categories, used consistently across this README, the
dashboard, and [`docs/ble/SCIENTIFIC_STATUS.md`](docs/ble/SCIENTIFIC_STATUS.md):
**DEVELOPMENT EVIDENCE** (`AVAILABLE`) — real, current, non-confirmatory
evidence from today's short captures, safe to cite as DEVELOPMENT; **DEFINITIVE
/ PROTECTED FUTURE** (`NOT_YET_AVAILABLE`) — the frozen-protocol, 120 s/12-window
campaign and its one-time protected evaluation, fail-closed, not executed;
**RQ3 / RQ4 / CH38-39 / near-live** (`PENDING` or `NOT_AVAILABLE`) — real
mechanism exists, real campaign data does not yet.

| Capability | Implemented | Real evidence / validation |
|---|---:|---|
| Real B200 I/Q capture | Yes | Yes |
| BLE packet recovery / CRC | Yes | Yes |
| Dataset + capture-disjoint leakage protection | Yes | Yes |
| TRAIN / VALIDATION / protected TEST mechanism | Yes | Mechanism tested; DEFINITIVE campaign `NOT_YET_AVAILABLE` |
| `paper-eq6-7-v1` preprocessing (Eq. 6-7) | Yes | Unit/integration tested; no definitive real bundle yet |
| RQ1 acquisition-dependence measurement | Yes | **DEVELOPMENT EVIDENCE `AVAILABLE`** — real closed-set `delta_dependence = +0.324` (see below) |
| Four RQ2 model branches | Yes | **DEVELOPMENT EVIDENCE `AVAILABLE`** — real closed-set benchmark, `engineered_rf` selected PRIMARY (see below) |
| Decision-window aggregation (10 s) | Yes | **DEVELOPMENT EVIDENCE `AVAILABLE`** — real TRAIN=34/VALIDATION=12/TEST=12 windows, 4/4 TX (see [`PAPER_EVIDENCE_MAP.md`](docs/ble/PAPER_EVIDENCE_MAP.md)); DEFINITIVE campaign `NOT_YET_AVAILABLE` |
| Abstention / coverage / risk-coverage | Yes | **DEVELOPMENT / EXPLORATORY** — real but small-sample (12 windows/domain); DEFINITIVE campaign `NOT_YET_AVAILABLE` |
| PRE/POST RESET-CONTROL framework (RQ3) | Yes | `PENDING` — sample size frozen (80 pairs); 0 real pairs captured yet |
| FULL_BURST / ADVA_EXCLUDED / PRE_PDU (RQ4) | Yes | `NOT_AVAILABLE` — **0/4 enrolled units eligible**, real evidence recorded per unit (see below) |
| CH38/CH39, near-live inference | Yes | `NOT_AVAILABLE` — no real CH38/39 campaign data; no real near-live-prediction collection wired yet |
| Strong native <-> SDR association | Mechanism yes | **No — 0 STRONG, no accepted calibration policy** (fail-closed, real negative result) |
| Protected future scientific result | Mechanism yes | **`NOT_YET_AVAILABLE`** — not executed, fail-closed |

A passing test suite is evidence the code does what its own tests assert —
it is never treated as scientific validation anywhere in this project.

**Association, stated plainly**: the association mechanism is implemented
and **fail-closed**
(`ScientificResultsRepository.find_frozen_association_policy()` currently
returns `None`). No calibration run has yet produced a policy that
satisfies the scientific acceptance criteria, and the real corpus currently
contains **0 STRONG** associations. Consequently: `CRC-valid packet ≠
physical-source identity`, and `native context ≠ STRONG association`. This
is a real, current negative result, not a criterion that was loosened to
get a pass.

Full current-state detail, every real number behind the table above, and
the complete evidence-to-decision trace live in
[`docs/ble/SCIENTIFIC_STATUS.md`](docs/ble/SCIENTIFIC_STATUS.md).

### DEVELOPMENT evidence vs. PROTECTED FUTURE

**DEVELOPMENT evidence** (`AVAILABLE` — real, current, non-confirmatory):
- RQ1 `EXAMPLE_RECORD` diagnostic — capture-dependent / capture-disjoint / held-out TEST (see the table below)
- RQ2 `VALIDATION` — four representations (see below)
- 10-second decision-window check (`06_statistics/coverage_analysis_report.json`,
  `paper_exports/development_decision_window_summary.csv`):
  - `TRAIN=34`, `VALIDATION=12`, `TEST=12` real windows — **all 4/4 classes represented in every partition**
  - `VALIDATION`: `BA=0.750`, `accuracy=0.833`
  - `TEST`: `BA=0.875`, `accuracy=0.917`

**PROTECTED FUTURE**: `NOT_YET_AVAILABLE` — not executed, fail-closed. That real
10-second-window DEVELOPMENT evidence exists above does **not** mean the
definitive 120-second campaign has been run — the two stay structurally
separate everywhere in this repository (dashboard, `paper_export.py`,
`docs/ble/SCIENTIFIC_STATUS.md`); never conflated.

### Real closed-set benchmark result (2026-08-16)

First real, definitive run of the 4-unit closed-set comparison (`CC2541SensorTag`,
`CC2650-UNIT-01`, `keyfobdemo 01`, `keyfobdemo 02` — V2-admitted, session-disjoint,
leakage check `PASSED`, 9,891 real examples across 79 real B200 captures, Shelly excluded
as a class, no background pooled in as a fifth class):

Evaluation unit for every row below is `EXAMPLE_RECORD` (burst-level) — a
separate, real 10-second decision-window evaluation exists too (see
[the window-level scoping fix and DEVELOPMENT decision-window table](docs/ble/PAPER_EVIDENCE_MAP.md)),
never conflated with this one.

| Evaluation domain (RQ1) | Balanced accuracy | 95% CI | n |
|---|---:|---:|---:|
| Capture-dependent (same capture, intentionally leakage-optimistic diagnostic) | 0.958 | [0.938, 0.977] | 1,790 |
| Capture-disjoint (VALIDATION) | 0.634 | [0.544, 0.884] | 2,203 |
| Held-out TEST (PRIMARY branch, not protected FUTURE) | 0.767 | — | 2,464 |

`delta_dependence = capture-dependent − capture-disjoint = +0.324`, 95% CI `[0.077, 0.414]`
(paired cluster bootstrap, session-clustered) — a real, on-hardware measurement of exactly
the optimism RQ1 is designed to detect: a single-recording evaluation would have overstated
closed-set discrimination by roughly 32 balanced-accuracy points relative to genuinely
disjoint captures. The capture-dependent diagnostic gets its own real bootstrap CI too
(it is intentionally leakage-optimistic by design, not a confirmatory estimator -- but its
own resampling uncertainty is still a real, reportable quantity, never omitted just because
the point estimate itself is optimistic).

**Coherence-audit correction (2026-08-19)**: capture-disjoint VALIDATION was previously
reported as 0.749 -- that was raw accuracy, not balanced accuracy, due to a real bug in
`evaluate_rq1_acquisition_dependence()` (`window_report.accuracy`/`capture_report.accuracy`
instead of `.balanced_accuracy`). Corrected value (0.634) now matches RQ2's `engineered_rf`
PRIMARY branch VALIDATION balanced accuracy exactly, verified by hashing the two real
example_id sets (identical, 2,203 examples, same training run, same predictions). No
retraining, no new capture, no criteria/threshold change -- the fix only corrects which
already-computed real field gets read.

![RQ1 closed-set acquisition dependence](readme_img/evidence_rq1_domains.png)

RQ2 branch comparison (VALIDATION, same admitted groups):

| Branch | Balanced accuracy | Macro-F1 |
|---|---:|---:|
| coarse_morphology | 0.277 | 0.128 |
| **engineered_rf (PRIMARY)** | **0.634** | **0.586** |
| raw_iq | 0.248 | 0.226 |
| stft | 0.537 | 0.498 |

`engineered_rf` (best of Logistic Regression / SVM-RBF / Random Forest, selected on
VALIDATION only) was selected PRIMARY in this run and independently in all 4 per-unit
auxiliary runs below — a real, repeated finding, not a single cherry-picked outcome.

![RQ2 closed-set branch comparison](readme_img/evidence_rq2_branches.png)

Confusion matrices, capture-disjoint VALIDATION vs. held-out TEST (PRIMARY branch) —
CC2650-UNIT-01 is perfectly separated (recall 1.0) in both:

![Confusion matrix, VALIDATION capture-disjoint](readme_img/evidence_confusion_validation.png)
![Confusion matrix, TEST](readme_img/evidence_confusion_test.png)

Per-unit TEST precision/recall/F1 (PRIMARY branch), reported individually because the
aggregate balanced-accuracy number hides real, large per-source spread on this naturally
imbalanced split (TEST alone ranges from 166 to 1,857 examples per unit):

| Unit | Recall (TEST) |
|---|---:|
| CC2650-UNIT-01 | 1.000 |
| keyfobdemo 01 | 0.837 |
| CC2541SensorTag | 0.699 |
| keyfobdemo 02 | 0.530 |

![Per-unit precision/recall/F1](readme_img/evidence_per_unit_metrics.png)

**Risk-coverage curve** (TEST, PRIMARY branch) — the exact selective-prediction curve
(El-Yaniv & Wiener, 2010) the manuscript's abstention mechanism is built on, one point per
achievable confidence threshold on the real closed-set TEST split:

![Risk-coverage curve](readme_img/evidence_risk_coverage.png)

**Seed variability** — the PRIMARY branch re-trained under the platform's two other frozen
seeds (`137`, `2024`, VALIDATION-only), a real reproducibility check:

![Seed variability](readme_img/evidence_seed_variability.png)

**Computational cost** — real inference latency and serialized model size per RQ2 branch,
supporting the manuscript's stated computational-cost comparison (`engineered_rf`, a
Random Forest here, is real evidence that the lowest-macro-F1 branch is not automatically
the cheapest one either — heavier than both CNN branches in this run):

![Computational cost by branch](readme_img/evidence_computational_cost.png)

4 auxiliary per-unit TARGET_VS_BACKGROUND detectors (not the closed-set result above)
were also run — real per-unit `delta_dependence` ranges from -0.042 to +0.018, all
substantially smaller than the closed-set effect above (target-vs-background is an
easier task with more redundant evidence per window; the multiclass task is where
acquisition dependence actually shows up):

![Per-unit auxiliary RQ1](readme_img/evidence_per_unit_auxiliary_rq1.png)

**RQ3** — sample size frozen (`rq3_sample_size` scientist decision,
`PROSPECTIVE_BALANCED_WITHIN_DEVICE_CROSSOVER`): 10 RESET + 10 CONTROL pairs per unit,
80 pairs / 160 captures total across the 4 units. 0 real pairs captured yet — unchanged
from the row above; no nominal statistical power is declared, since no real RQ3 variance
estimate exists yet.

**RQ4** — real eligibility check completed for every enrolled unit:
`RQ4 = DATA_NOT_AVAILABLE: CONTROLLED_VARIANT_NOT_AVAILABLE` (0/4 eligible; no enrolled
unit has documented, independently-verified control over its own packet content — full
per-unit reasons in [`docs/ble/SCIENTIFIC_STATUS.md`](docs/ble/SCIENTIFIC_STATUS.md)).

**Confusion matrix, normalized by true class** (TEST, PRIMARY branch) — same real counts
as above, row-normalized to a per-class percentage with `n` kept as secondary per-cell
information, the canonical view for the manuscript:

![Confusion matrix, normalized by true class](readme_img/evidence_confusion_normalized.png)

**Campaign timeline** — every study phase, qualification through protected FUTURE and
confirmatory analysis, colored by its real, current `execution_state` (never hand-drawn —
rendered once by the paper-export pipeline and reused verbatim below):

![Campaign timeline](readme_img/evidence_campaign_timeline.png)

**Forensic evidence lineage** — source I/Q → burst → PDU → admitted example → dataset →
split → preprocessing → model → RQ1/RQ2 decision, traced with real IDs/hashes from the
closed-set PRIMARY branch, not a dashboard screenshot:

![Forensic evidence lineage](readme_img/evidence_forensic_lineage.png)

All figures above are generated straight from the platform's own real, persisted evidence
by [`docs/ble/generate_evidence_figures.py`](docs/ble/generate_evidence_figures.py) —
never hand-drawn, never from a spreadsheet copy. Re-run it after any new real RQ1/RQ2/RQ3
result to regenerate every PNG in this section from current state. The last 3 figures
(normalized confusion matrix, campaign timeline, forensic lineage) are not re-plotted by
that script — it calls the platform's own paper-export pipeline
(`ScientificResultsRepository.run_paper_export()` → `paper_export.py` →
`figures/paper_figures.py`, the same renderer the manuscript's PDF/SVG exports use) and
copies the PNG variant it already wrote, so there is exactly one real computation behind
each of those three, never two independent plots. The same real data, with the same
plotting functions, is also available as a runnable, GitHub-renderable notebook:
[`docs/ble/evidence_figures.ipynb`](docs/ble/evidence_figures.ipynb) (regenerate via
[`docs/ble/build_evidence_notebook.py`](docs/ble/build_evidence_notebook.py) after running
the figure script).

**Regenerating these figures — two equivalent paths, same real code:**

1. **From the platform itself** — BLE Scientific Results Studio → **Evidence Dashboard** tab
   → **"Generar imagenes nuevas (README + notebook)"** button. Calls
   `POST /api/ble-scientific-results/evidence-dashboard/regenerate-figures`, which loads and
   runs the exact same `generate_evidence_figures.py` / `build_evidence_notebook.py` `main()`
   functions listed above (never a second implementation) and reports back which files were
   written.
2. **From a terminal**, manually, running the same two scripts directly (commands above).

Either path only writes real PNG/`.ipynb` files into the repo working tree — neither commits
nor pushes anything; review the diff and `git add / commit / push` yourself afterward.

These same results, plus the per-unit auxiliary runs, RQ3's live campaign progress, and
RQ4's per-unit eligibility, are also readable live (not a snapshot) from the platform
itself: BLE Scientific Results Studio → **Evidence Dashboard** tab, `GET
/api/ble-scientific-results/evidence-dashboard`.

---

## Quick start

```powershell
uhd_find_devices
uhd_usrp_probe
```

Then, from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_unified.ps1
```

Core operator path once both processes are running:

```text
Live Monitor -> Capture Lab -> BLE-RFFI Studio -> Dataset Builder -> Training / Evaluation -> Experimental inference
```

Manual setup, environment variables, and every other operator view are
documented in [Documentation](#documentation) below — this section
intentionally stops at "how to start."

---

## Platform views

BLE-RFFI Studio (above) is the platform's primary research workflow. The
same backend also hosts the general SDR/RF workspace it is built on.

### Live Monitor -- `/spectrum`

Real-time RF workspace: SDR connection and stream controls, frequency,
span, sample-rate, gain, antenna, markers, and visualization.

![Live Monitor spectrum](readme_img/live_monitor.png)

<details>
<summary>Waterfall, RF Intelligence overlay, Spectrum Tools, legacy view</summary>

![Live Monitor with waterfall](readme_img/live_monitor_waterfall.png)
![Live Monitor with RF Intelligence overlay](readme_img/live_monitor_rf_intelligence_overlay.png)
![Spectrum Tools](readme_img/live_monitor_spectrum_tools.png)
![Animated Spectrum Tools demonstration](readme_img/live_monitor_spectrum_tools.gif)
![Legacy Live Monitor waterfall](readme_img/live_monitor_waterfall_legacy.png)

Spectrum Tools definitions and validation checks:
[`frontend/src/features/spectrum-tools/VALIDATION.md`](frontend/src/features/spectrum-tools/VALIDATION.md).

</details>

### Capture Lab -- `/capture`

Controlled acquisition of real complex I/Q: immediate capture, or triggered
burst capture with a bounded pre-trigger buffer. Every capture preserves
raw I/Q, acquisition configuration, timing, labels/split, quality metadata,
and a SHA-256 checksum.

![Capture Lab](readme_img/capture_lab.png)

<details>
<summary>Earlier Capture Lab signal-analysis interface</summary>

![Capture Lab signal analysis](readme_img/capture_lab_signal_analysis.png)

</details>

### Dataset Builder -- `/dataset-builder`

The governance gate between acquisition and model use: offline QC, label
and review-state management, experimental split control, and
duplicate/overlap safeguards before anything can enter training or
validation.

![Dataset Builder](readme_img/dataset_builder.png)

### BLE-RFFI Studio -- `/ble-rffi-studio`

The workflow this document is built around (see above) — capture,
evidence, dataset, split, training, decision windows, and experimental
live inference, over real USRP B200 acquisitions. No dedicated UI
screenshot is included in this README yet; the module's own scope,
findings, and real evidence are documented in
[`backend/app/modules/ble_rffi_studio/README.md`](backend/app/modules/ble_rffi_studio/README.md)
and [`docs/ble/SCIENTIFIC_STATUS.md`](docs/ble/SCIENTIFIC_STATUS.md).

### BLE Scientific Results Studio -- `/ble-scientific-results`

Turns BLE-RFFI Studio's captures into the formal scientific record behind
the four questions above: strict association semantics (a resolved
`physical_unit_id` context alone is never treated as a
`TARGET_ASSOCIATED_PACKET` -- that requires a real, frozen-policy match), an
eligibility/diagnostics split, protocol-deviation classification, and real
time-based decision windows. Its **Guided Validation** tab is a real, wired
capture-first wizard for non-experts (Live Timing Diagnostic, Reinforced
Target-Absence Control) -- real runs so far are consistent with the 0 STRONG
associations already stated above. Its **Evidence Dashboard** tab is a live,
refreshable, in-platform view of the real closed-set/per-unit RQ1-RQ2
results, RQ3 sample-size decision and campaign progress, and RQ4 per-unit
eligibility summarized under "Real closed-set benchmark result" above --
reads the same persisted artifacts live, never a snapshot, and now also shows
bootstrap CI error bars on `BA_capture`, a raw/normalized confusion-matrix
toggle, real decision-window/capture counts per domain, the PRIMARY
selection-domain badge, and a `CURRENT TEST EVIDENCE` label on risk-coverage
(the confirmatory `DEFINITIVE` variant stays pending until the protected
FUTURE campaign runs). Its **Supporting Tables** tab adds the composition
tables the figures above summarize -- per-transmitter capture composition,
per-partition windows/captures/sessions for any real split, label provenance
(STRONG vs. declared-isolation association), and receiver-epoch composition.
Its **Scientific Completeness** tab renders ONE real, live status per paper
element (AVAILABLE / PENDING_REAL_ACQUISITION / BLOCKED / NOT_ELIGIBLE /
PROTECTED, with the real missing evidence) -- the in-platform mirror of
[`PENDING_TO_CLOSE.md`](PENDING_TO_CLOSE.md). No dedicated UI screenshot yet;
detail: [`docs/ble/SCIENTIFIC_STATUS.md`](docs/ble/SCIENTIFIC_STATUS.md).

### RF Intelligence -- `/rf-intelligence`

Real-time RF object detection and cautious rule/profile-based protocol
hypotheses. Energy in a frequency region is never treated as proof that a
protocol has been decoded.

![RF Intelligence](readme_img/rf_intelligence.png)

### Demodulation -- `/demodulation` and Live Demodulation -- `/live-demodulation`

Marker-selected or stored-acquisition demodulation (analog, digital, BLE,
IEEE 802.15.4, OOK/FSK, and experimental protocol pipelines), plus
continuous AM/FM/NFM/WFM audio recovery from the live stream. A signal is
never reported as successfully decoded merely because RF energy was
observed.

![Demodulation](readme_img/demodulation.png)

<details>
<summary>Live Demodulation</summary>

![Live Demodulation](readme_img/live_demodulation.png)

</details>

### Other views

Mission Control (`/`, operational dashboard), Spectrum Tools, RF Experiment
Lab (`/rf-experiment-lab`, the general-technique registry — E0/E1/E3/E5
implemented, see
[`docs/research/TECHNIQUE_ROADMAP.md`](docs/research/TECHNIQUE_ROADMAP.md)
for what is not), E6 Oracle-Style Lab (`/e6-oracle-style-lab`, a separate,
non-BLE classical-ML lab), RF Signal Understanding, Training/Retraining/
Validation/Inference/Models, Waterfall, Recordings, KiwiSDR Map, and
Settings are all real, working views of the same backend — module-by-module
detail: [`backend/README.md`](backend/README.md).

---

## Architecture and evidence lineage

```text
RF-Fingerprint-Lab
|
+-- frontend/    React / TypeScript / Vite -- operator views, spectrum visualization
+-- backend/     FastAPI -- SDR control, acquisition, dataset governance,
|                demodulation, RF fingerprinting, BLE-RFFI Studio, ML workflows
+-- backend/tools/  GNU Radio / UHD workers
+-- docs/        scientific and technical documentation
+-- readme_img/  README figures
+-- start_unified.ps1
```

The **backend owns hardware-facing and scientific processing state**; the
frontend provides the operator workflow and visualization layer.

Every BLE-RFFI prediction traces back to its original I/Q:

```text
original I/Q -> sample range -> packet/burst -> example -> dataset -> split
             -> preprocessing -> model bundle -> decision -> inference manifest
```

Metadata migrations (corrections to already-persisted records — never to
I/Q itself) are recorded in an append-only migration ledger
(`migration_id`, timestamps, old/new value, reason, tool). Entries
reconstructed after the fact, for changes made before the ledger existed,
are explicitly flagged `RETROACTIVE_RECONSTRUCTION`, and their historical
timestamps are each artifact's real on-disk modification time — a
documented proxy, not the exact original edit instant. Full mechanism and
real counts: [`docs/ble/SCIENTIFIC_STATUS.md`](docs/ble/SCIENTIFIC_STATUS.md)
§16.10.

## Testing

```powershell
cd backend
python -m pytest app/tests/unit -q
```

```powershell
cd frontend
npm run build
```

Hardware-facing changes should additionally be tested against the actual
SDR path (device discovery, connect/stream, acquisition controls, capture,
dataset routing) — a passing unit-test suite alone is not evidence that a
hardware-dependent workflow has been validated over real RF input.

---

## Scientific scope and contribution

RF fingerprinting itself is established prior art, as are raw-I/Q CNN
fingerprinting, STFT/CNN2D fingerprinting, classical engineered-feature
classifiers, BLE-specific RF fingerprinting, and channel/power-cycle
sensitivity studies of RF fingerprints. RF-Fingerprint-Lab does not claim
novelty for any of those individual techniques.

The more defensible contribution is the **controlled integration**, in one
real BLE source-comparison pipeline over genuine USRP B200 acquisitions, of
explicit acquisition-dependence measurement (RQ1), a protected single-use
future evaluation (TRAIN -> VALIDATION -> FREEZE -> FUTURE TEST), radio-state
intervention (RQ3), BLE packet-content controls (RQ4), and end-to-end
evidence lineage — together, with real code and real tests, rather than any
one of them treated as a solved side detail.

Terms this project deliberately avoids as unqualified claims: *first*,
*receiver-invariant*, *channel-invariant*, *validated forensic
attribution*, *validated real-time identification*. Full positioning and
what is and is not claimed:
[`docs/research/CONTRIBUTION.md`](docs/research/CONTRIBUTION.md).

RF-Fingerprint-Lab is an **active research platform**. The authoritative
state of any capability is its module documentation, artifacts, tests, and
scientific-status records — never inferred only from the existence of a
user-interface control.

## Documentation

- [`PENDING_TO_CLOSE.md`](PENDING_TO_CLOSE.md) -- everything real that is
  still needed to fully close the platform and the paper: the confirmatory
  readiness gate (16 real scientist decisions), the RQ3 physical campaign,
  protected FUTURE evaluation, S1/S2, and the remaining paper-text updates,
  with a suggested order of operations. Start here for "what's left."
- [`docs/ble/SCIENTIFIC_STATUS.md`](docs/ble/SCIENTIFIC_STATUS.md) --
  current BLE scientific evidence, full capability status, and the complete
  evidence-to-decision trace (start here for technical depth).
- [`docs/ble/PREPROCESSING.md`](docs/ble/PREPROCESSING.md) -- the paper's
  Eq.(6)-(7) preprocessing, full derivation and per-burst provenance.
- [`docs/research/TECHNIQUE_ROADMAP.md`](docs/research/TECHNIQUE_ROADMAP.md)
  -- not-yet-implemented technique ideas, kept out of the executable
  benchmark above.
- [`docs/research/CONTRIBUTION.md`](docs/research/CONTRIBUTION.md) --
  scientific contribution and prior-art positioning.
- [`backend/app/modules/ble_rffi_studio/README.md`](backend/app/modules/ble_rffi_studio/README.md)
  -- BLE-RFFI Studio module documentation: engineering obstacles, real
  findings, and implementation detail.
- [`docs/ble/PILOT_V1_LEGACY.md`](docs/ble/PILOT_V1_LEGACY.md) -- the
  superseded BLE Dataset Studio Pilot v1 baseline.
- [Backend documentation](backend/README.md) / [Backend setup](backend/README_SETUP.md)
  -- architecture, APIs, workers, hardware integration.
- [Frontend documentation](frontend/README.md)

## Citation

For academic use or publication, record the software revision, hardware
configuration, dataset version, acquisition conditions, and the relevant
validation state (per the distinction above) alongside any reported result.
A root-level `CITATION.cff` and explicit software license are recommended
for a citable release.
