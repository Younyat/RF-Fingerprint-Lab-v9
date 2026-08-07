# RF-Fingerprint-Lab

**Software-defined radio research platform for RF acquisition, signal
analysis, dataset construction, physical-layer device fingerprinting,
demodulation, model evaluation, and experimental live inference.**

RF-Fingerprint-Lab integrates real software-defined radio acquisition with
signal-processing and machine-learning workflows in a browser-based
laboratory environment.

The primary hardware path uses an **Ettus Research USRP B200** through **UHD
and GNU Radio**. The application combines a **FastAPI backend** with a
**React/TypeScript frontend** and provides a common workflow from RF
observation to controlled I/Q acquisition, dataset curation, model
development, validation, and inference.

> **Real RF data by default.**
> Hardware-facing acquisition, live spectrum visualization, waterfall
> analysis, triggered I/Q capture, BLE decoding, and dataset artifacts
> operate on samples acquired from SDR hardware. Synthetic or test-only
> evidence is explicitly distinguished from real acquisitions.

![Live Monitor spectrum](readme_img/live_monitor.png)

---

## Terminology

Every code, acronym, and status label used anywhere below is defined here
first, before its first use elsewhere in this document.

**Core acronyms**: SDR = Software-Defined Radio (the USRP B200 in this
project). IQ = In-phase/Quadrature, the raw complex baseband samples the SDR
outputs. CFO = Carrier Frequency Offset, a hardware-level RF-fingerprint
feature. PDU = (BLE) Protocol Data Unit, one decoded packet. CRC = Cyclic
Redundancy Check, the packet-integrity check a decode must pass to be
CRC-valid. GFSK = Gaussian Frequency-Shift Keying, BLE's physical-layer
modulation. TVB = `TARGET_VS_BACKGROUND`, one of BLE-RFFI Studio's scientific
tasks, used as a dataset-naming suffix (e.g. `SHELLY-PLUG-01-AUTO-TVB`).

**RF Experiment Lab technique codes (`/rf-experiment-lab`)**: each code below
names one specific, literature-referenced RF-fingerprinting technique this
module can implement and compare -- not a generic experiment number. Source
of record: `backend/app/modules/rf_experiment_lab/experiment_registry.py`.

| Code | Technique | Real implementation status |
|---|---|---|
| E0 | Morphological heuristic waterfall-region detector (no training) | Implemented |
| S1 | PSD/energy detection | Not implemented |
| S2 | SCD/CSP cyclostationary alpha-profile classification | Not implemented |
| S4 | Unknown dynamic RF classification | Not implemented |
| E1 | Raw-IQ CNN fingerprinting (1D CNN / ResNet1D) | Implemented (1D-CNN baseline) |
| E2 | Edge IQ Transformer (lightweight CNN1D / transformer encoder) | Not implemented |
| E3 | Spectrogram/waterfall CNN (CNN2D / ResNet18 / VGG11) | Implemented (simple 2D-CNN, optional torchvision backbones) |
| E5 | PSD/MFCC/LFCC classical ML (SVM / random forest / KNN) | Partially implemented (basic PSD only) |
| E8 | Bispectrum and cyclostationary statistics (SVM / MLP / RF) | Not implemented |
| E9 | Metric-learning open-set fingerprinting (siamese / triplet / prototypical / ArcFace-like) | Not implemented |
| E10 | Quantized edge inference (TFLite / quantized CNN / transformer) | Not implemented |

There is no code named **E4** in this registry -- E3 is followed directly by
E5. An unrelated, unconnected use of "E4" (a different, older numbering)
exists only in the legacy BLE Dataset Studio Pilot v1 record -- see
[`docs/ble/PILOT_V1_LEGACY.md`](docs/ble/PILOT_V1_LEGACY.md). The two must
never be conflated.

**E6 Oracle-Style Lab** (`/e6-oracle-style-lab`) is a separate module, not
part of the E0-E10 registry above: a classical (non-CNN) RF fingerprinting
lab over external, non-BLE reference datasets, with 8 classical algorithms
(HistGradientBoosting, random forest, extra trees, MLP, SVM-RBF, SVM-linear,
KNN, logistic regression).

**BLE-RFFI Studio** and **Guided BLE Scientific Validation** (both described
in full below) use **no E/S code at all** -- they are independent modules
with their own vocabulary (`capture_purpose`, `association_status`,
`ScientificTask`, etc.), never numbered like RF Experiment Lab's techniques.

---

## Overview

RF-Fingerprint-Lab is organized around five complementary research
functions:

1. **RF observation and acquisition** -- real-time spectrum monitoring,
   waterfall visualization, markers, spectrum statistics, immediate capture,
   and triggered capture with pre-trigger buffering.
2. **Signal analysis and demodulation** -- RF activity analysis,
   signal-family hypotheses, analog demodulation, digital/IoT decoding
   pipelines, and protocol-specific evidence.
3. **Dataset engineering** -- capture metadata, quality control, labeling,
   session-aware splitting, checksums, and controlled dataset construction.
4. **RF fingerprinting experimentation** -- classical machine learning, raw
   I/Q models, spectrogram-based models, validation, model registry, and
   inference.
5. **BLE physical-layer identification research** -- a dedicated BLE-RFFI
   workflow spanning B200 acquisition, packet evidence, dataset generation,
   model training, and experimental live-spectrum identification.

The platform is intended as a **research and experimentation environment**.
Capability status and scientific limitations are reported explicitly;
implementation of a feature does not by itself imply population-level
generalization, receiver invariance, forensic attribution, or deployment
readiness.

## Core workflow

```text
USRP B200
    |
    v
Live RF Observation
    |
    +-- Spectrum / Waterfall / Spectrum Tools
    +-- RF Intelligence
    +-- Marker-selected signal region
                 |
                 v
             Capture Lab
                 |
          Real complex I/Q
                 |
                 v
          Dataset Builder
          /      |       \
         v       v        v
   Training   Validation  Inference
        |        |         |
        +--------+---------+
                 |
                 v
          Model Registry
```

For BLE-specific physical-layer experiments:

```text
USRP B200
    |
    v
Real BLE I/Q
    |
    v
Burst Detection
    |
    v
BLE Synchronization / GFSK Recovery
    |
    v
Dewhitening -> PDU -> CRC
    |
    v
Evidence Construction
    |
    v
Quality-Gated Dataset
    |
    v
Session-Disjoint Split
    |
    v
Model Training / Evaluation
    |
    v
Experimental Live-Spectrum Inference
```

## Main capabilities

| Area | Capability |
|---|---|
| SDR acquisition | UHD/GNU Radio acquisition from USRP B200/B210-class receivers |
| Spectrum analysis | FFT/PSD visualization, waterfall, markers, peak inspection, pan, zoom, freeze, export |
| Spectrum statistics | Max Hold, Min Hold, averaging, RMS, EWMA, percentiles, trace history, persistence, occupancy |
| I/Q capture | Immediate and triggered acquisition with circular pre-trigger buffering |
| Capture provenance | Metadata, acquisition configuration, timing information, labels, splits, and SHA-256 checksums |
| RF analysis | Signal-region detection and evidence-based RF hypotheses |
| Demodulation | Analog, digital, BLE, IEEE 802.15.4, OOK/FSK and experimental protocol pipelines |
| Dataset governance | Offline QC, labeling, review states, experimental split control, duplicate/leakage safeguards |
| Machine learning | Classical ML, raw-IQ CNN, spectrogram CNN, training, validation, model registry, inference |
| RF research | E0-E10/S1/S2/S4 experiment workflows (see [Terminology](#terminology)) and the independent E6 classical-ML workflow |
| BLE-RFFI | Real B200 BLE acquisition -> evidence -> dataset -> training -> experimental live inference |
| Remote SDR | KiwiSDR receiver discovery and inspection |

---

## Quick start

### Requirements

Recommended development environment:

- Windows 10/11
- Ettus Research USRP B200/B210 or compatible UHD receiver
- UHD
- GNU Radio
- RadioConda Python environment
- Python environment for the FastAPI backend
- Node.js and npm

Verify the USRP before starting the application:

```powershell
& "C:\Users\Usuario\radioconda\Library\bin\uhd_find_devices.exe"
& "C:\Users\Usuario\radioconda\Library\bin\uhd_usrp_probe.exe"
```

### Unified launcher

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_unified.ps1
```

To specify the RadioConda Python executable explicitly:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_unified.ps1 `
  -RadioCondaPythonPath "C:\Users\Usuario\radioconda\python.exe"
```

The launcher starts the backend and frontend while preserving the separation
between the application Python environment and the RadioConda GNU
Radio/UHD runtime.

> Machine-specific remote usernames, IP addresses, development paths, and
> laboratory credentials should not be documented as canonical project
> defaults in this README. Keep them in local configuration or dedicated
> deployment documentation.

### Manual development

**Backend**

```powershell
cd backend
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.dev-windows.txt
$env:RADIOCONDA_PYTHON="C:\path\to\radioconda\python.exe"
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend**

```powershell
cd frontend
npm install
npm run dev
```

## Recommended workflow

```text
Mission Control
      |
      v
Live Monitor -> Mark signal band -> Capture Lab
                                      |
                                      v
                               Dataset Builder
                                 /    |    \
                                v     v     v
                           Training Validation Inference
                                |       |       |
                                +-------+-------+
                                        v
                                      Models
```

1. Connect the USRP and start the live stream.
2. Tune the center frequency, span, sample rate, gain, and antenna.
3. Inspect the signal with Live Monitor, Waterfall, Spectrum Tools, and RF
   Intelligence overlays.
4. Place M1 and M2 around the signal of interest.
5. Open Capture Lab and select immediate or triggered capture.
6. Review the saved I/Q and metadata in Dataset Builder.
7. Recompute QC, confirm the label, and accept, reject, or mark the capture
   as doubtful.
8. Route accepted captures to training, validation, inference, demodulation,
   RF Signal Understanding, or RF Experiment Lab.

---

## Platform

### Mission Control -- `/`

Mission Control is the top-level operational dashboard. It summarizes
acquisition, dataset readiness, training state, validation evidence,
inference, and model availability, so an operator can identify the next
blocked or incomplete stage in the workflow.

### Live Monitor -- `/spectrum`

Live Monitor is the primary real-time RF workspace: SDR connection and
stream controls together with frequency, span, sample-rate, gain, antenna,
RBW, VBW, detector, averaging, reference-level, marker, and visualization
controls.

![Live Monitor spectrum](readme_img/live_monitor.png)

The spectrum can be combined with recent spectral history:

![Live Monitor with waterfall](readme_img/live_monitor_waterfall.png)

RF Intelligence can be overlaid without replacing or modifying the
underlying spectrum data:

![Live Monitor with RF Intelligence overlay](readme_img/live_monitor_rf_intelligence_overlay.png)

<details>
<summary>Legacy Live Monitor / waterfall reference</summary>

![Legacy Live Monitor waterfall](readme_img/live_monitor_waterfall_legacy.png)

</details>

### Spectrum Tools

Spectrum Tools extends Live Monitor with independent statistical and
temporal representations of the same incoming spectrum frames. It is always
available from the upper-right corner and opens over the canvas without
reducing the spectrum workspace. Several tools can run simultaneously
because every processor receives the same original Live frame rather than
the output of another technique.

![Spectrum Tools with Max Hold, Min Hold, averages, RMS, EWMA and statistical layers](readme_img/live_monitor_spectrum_tools.png)

![Animated Spectrum Tools demonstration](readme_img/live_monitor_spectrum_tools.gif)

| Technique | Purpose | Main limitation |
|---|---|---|
| Live Trace | Current FFT/PSD observation | Represents the current frame only |
| Max Hold | Retains the highest observed value per frequency bin | Does not preserve event time or duration |
| Min Hold | Tracks lowest observed values | Outliers persist until reset |
| Power Average | Stable mean-power estimate | Smooths short events |
| RMS Power | Effective accumulated power | Can resemble averaged PSD for some inputs |
| EWMA | Time-weighted spectral smoothing | Large constants reduce responsiveness |
| Percentiles | P50/P90/P95/P99 distributions | Requires an observation window |
| Trace History | Visualizes previous spectrum frames | Can become visually dense |
| Density / Persistence | Shows repeated spectral states | Represents observed frames, not regulatory occupancy |
| Spectrum Mask | Visual threshold comparison | Currently a visualization function |
| Observed-frame Occupancy | Fraction of observations above threshold | Depends on threshold and observation conditions |
| Gated Spectrum | Spectrum over a selected temporal interval | Requires appropriately synchronized I/Q |
| Zero Span | Power evolution at a selected frequency | Requires continuous timed samples |

Visual representations and analytical inputs remain separate. Enabling a
display technique does not silently replace the signal used by another
analysis module. Detailed formulas and validation checks are maintained in
[`frontend/src/features/spectrum-tools/VALIDATION.md`](frontend/src/features/spectrum-tools/VALIDATION.md).

### Capture Lab -- `/capture`

Capture Lab performs controlled acquisition of **real complex I/Q samples**.
Acquisition limits can be derived from markers, the live peak, the visible
spectrum window, or explicitly configured frequencies.

![Capture Lab](readme_img/capture_lab.png)

Two acquisition modes are available:

- **Immediate capture** -- records a specified RF interval for a fixed
  duration.
- **Triggered burst capture** -- continuously monitors the source and
  preserves the event together with samples from a bounded pre-trigger
  buffer.

Each capture can preserve: raw complex I/Q; acquisition frequency and
bandwidth; sample rate; gain and antenna; timing information;
trigger/pre-trigger metadata; labels and experimental split; quality
metadata; SHA-256 checksum.

<details>
<summary>Earlier Capture Lab signal-analysis interface</summary>

![Capture Lab signal analysis](readme_img/capture_lab_signal_analysis.png)

</details>

### Dataset Builder -- `/dataset-builder`

Dataset Builder is the governance gate between acquisition and model use. It
does not capture RF -- it reviews saved I/Q, recomputes offline QC, manages
labels and experimental splits, and prevents doubtful or invalid samples
from silently entering training or validation.

![Dataset Builder](readme_img/dataset_builder.png)

| Property | Example states |
|---|---|
| Capture quality | `valid`, `warning`, `doubtful`, `invalid` |
| Label status | `unlabeled`, `weak_label`, `strong_label` |
| Review status | `needs_review`, `accepted`, `doubtful`, `rejected` |
| Split | `train`, `val`, `predict` |

QC includes SNR, clipping, silence/near-zero content, occupied bandwidth,
frequency offset, sample count, file consistency, and burst suitability.

### RF Intelligence -- `/rf-intelligence`

RF Intelligence performs real-time RF object detection and cautious
rule/profile-based protocol hypotheses: estimated noise floor, detection
threshold, minimum SNR, detected objects, temporal behavior, confidence, and
the evidence supporting each hypothesis.

![RF Intelligence](readme_img/rf_intelligence.png)

Energy in a frequency region is not treated as proof that a protocol has
been decoded. Hypotheses remain explicitly distinct from packet- or
frame-level confirmation.

### RF Experiment Lab -- `/rf-experiment-lab`

RF Experiment Lab provides reproducible research workflows over curated RF
datasets: strict dataset splits, dry-run validation, representation
extraction, metrics, exports, and benchmark reports, for every technique
code defined in [Terminology](#terminology) above. Codes marked "not
implemented" there are registered but deliberately not presented as
available functionality. The view records configuration, dataset manifest,
label schema, preprocessing, split policy, artifacts, metrics, and
scientific traceability.

### E6 Oracle-Style Lab -- `/e6-oracle-style-lab`

E6 (defined in [Terminology](#terminology)) supports local dataset creation,
SigMF and reference-dataset import, feature extraction, training,
benchmarking, pre-trained model import, registry management, and file/live
prediction, over its 8 classical algorithms. It is intentionally separate
from the E0-E10/S1/S2/S4 workflows and from BLE-RFFI Studio.

### RF Signal Understanding -- `/rf-signal-understanding`

RF Signal Understanding analyzes I/Q-derived waterfall representations,
detects time-frequency regions, extracts spectral evidence, and produces
cautious signal-family hypotheses. The view can compare newer
region/feature pipelines with legacy analysis results.

### Training -- `/training`

Training launches controlled RF fingerprinting jobs from canonicalized
captures assigned to the training registry: dataset readiness,
hyperparameters, remote execution status, logs, metrics, and generated
model artifacts. Strict mode requires accepted, strongly labelled,
technically valid captures.

### Retraining -- `/retraining`

Retraining updates an existing model using the current curated training
registry, preserving lineage between the source model, dataset fingerprint,
configuration, new metrics, and replacement candidate.

### Validation -- `/validation`

Validation evaluates selected models against canonicalized validation
captures kept separate from training groups: leakage, label compatibility,
artifact readiness, per-class results, aggregate metrics, and
external-validation evidence.

### Inference -- `/inference`

Inference runs asynchronous predictions on captures assigned to the
prediction split: resolves the selected capture and model, validates
required metadata, tracks job state, and presents ranked predictions and
confidence evidence.

### Models -- `/models`

Models is the registry and model-card view: model identity, task,
algorithm, dataset lineage, label schema, validation evidence, artifact
paths, readiness, and whether a model is enabled for live use.

### Waterfall -- `/waterfall`

Waterfall visualizes spectral power over time -- useful for bursts,
frequency hopping, drift, intermittent interference, and temporal
occupancy. The standalone view complements the split waterfall available in
Live Monitor.

### Recordings -- `/recordings`

Recordings provides a library of recording sessions and saved artifacts, to
locate, inspect, and manage I/Q or audio recordings independently of the
curated Dataset Builder registry.

### KiwiSDR Map -- `/kiwisdr`

KiwiSDR Map discovers and catalogs remote KiwiSDR receivers, displays them
on a map, exposes receiver filters, and supports selecting a remote
receiver for inspection. This module is separate from the local UHD/USRP
hardware path.

### Settings -- `/settings`

Settings exposes persisted application, analyzer, hardware, polling,
capture, QC, and RF Intelligence parameters. Each setting documents its
active value, default, source, allowed range, affected workflow, restart
requirement, and whether the limit is imposed by hardware, software, or
scientific policy.

### Demodulation -- `/demodulation`

The Demodulation workspace processes a marker-selected live band or a
stored acquisition through analog, digital, or IoT pipelines.

![Demodulation](readme_img/demodulation.png)

```text
RF activity -> synchronization -> symbol/bit recovery -> frame
reconstruction -> integrity check -> decoded payload
```

A signal is not reported as successfully decoded merely because RF energy
was observed.

| Pipeline | Status | Primary output |
|---|---|---|
| `wfm_broadcast` | Basic implementation | WFM audio |
| `nfm` | Basic implementation | NFM audio |
| `am` | Basic implementation | AM audio |
| `ble_advertising` | Experimental decoding path | BLE packet candidates / CRC evidence |
| `wifi_80211` | Experimental scaffold | 802.11 activity/frame evidence |
| `generic_gfsk_iot` | Physical-layer estimator | GFSK bitstream candidate |
| `ook_ask_iot_sensor` | Physical-layer estimator | OOK/ASK bitstream candidate |
| `generic_fsk_iot` | Physical-layer estimator | FSK bitstream candidate |
| `zigbee_ieee802154` | Implemented | IEEE 802.15.4 frames and FCS evidence |
| `ieee802154_oqpsk` | Experimental scaffold | O-QPSK candidates |
| `adsb_1090` | Experimental scaffold | ADS-B candidates |
| `lora_css` | Experimental scaffold | LoRa candidates |
| `ook_433_remote` | Implemented | EV1527/PT2262 evidence |

Persisted outputs depend on the decoder and can include packet/frame JSON,
CSV reports, bitstreams, burst candidates, logs, audio, and other
protocol-specific artifacts.

### Live Demodulation -- `/live-demodulation`

Live Demodulation provides continuous AM, FM, NFM, and WFM audio recovery
from the active SDR stream, with tuning, bandwidth and gain controls, Web
Audio playback, stream status, level monitoring, and optional persistence.

![Live Demodulation](readme_img/live_demodulation.png)

---

## BLE-RFFI Studio

**Route:** `/ble-rffi-studio`

BLE-RFFI Studio is a dedicated, independent research workflow (it does not
modify or replace RF Experiment Lab, E6, or Models) for investigating
identification of physical BLE transmitters from their radio-frequency
characteristics: capture -> evidence -> dataset -> split -> training ->
export -> live inference, all against real USRP B200 acquisitions, never
synthetic data for anything operational.

Current real state of this module (all counts below are real, on-disk
artifacts, not targets or plans):

- **146** registered captures, decoded through a real BLE packet decoder
  (Gate 2A.2) and resolved against an address-binding registry, never
  guessed.
- **8** frozen, quality-gated, single-device datasets.
- **27** trained and `APPROVED_FOR_LIVE_PILOT` models, covering **5** real
  physical devices (`CC2541SensorTag`, `CC2650-UNIT-01`, `SHELLY-PLUG-01`,
  `keyfobdemo 01`, `keyfobdemo 02`), 5 model architectures each -- every
  architecture is always trained and exported, never only the
  best-scoring one, so the real comparison between them stays visible.

### Research objective

Protocol-level identifiers such as addresses, names, and advertised fields
describe logical BLE identity and can be changed or imitated: an attacker
only needs to copy those values into their own transmitter. RF fingerprinting
investigates a different, complementary source of information -- hardware
imperfections of the actual analog transmitter (carrier frequency offset, IQ
imbalance, transient shape) that are not controlled by firmware and are far
harder to replicate.

RF-Fingerprint-Lab therefore treats BLE physical-layer identification as an
**experimental research problem**, not as a solved identity or anti-spoofing
mechanism. Every claim in this section is stated with its real evidence and
its real limitations. No BLE-RFFI result should be interpreted automatically
as forensic attribution, population-level identification,
receiver-independent performance, or channel-independent generalization. See
also Guided BLE Scientific Validation below, which investigates the opposite
direction -- whether identity can be corroborated *independently* of the
trained classifier, purely from timing -- and reports a real, current
negative result for that specific approach.

### Evidence chain

BLE-RFFI Studio keeps acquisition, decoding, labeling, and classification as
distinct stages.

1. **Acquisition**: real B200 I/Q, registered with its own `capture_purpose`
   (`TARGET_DEVICE_ON`, `BACKGROUND_TARGET_OFF`, `BACKGROUND_GENERAL`, or
   `UNKNOWN_DEVICE_COLLECTION`) -- never a generic, ambiguous "background"
   bucket.
2. **Evidence**: every decoded packet is resolved to a registered physical
   device through address bindings, never trusted blindly -- a declared
   "device off" capture that still shows the device's real address is
   flagged as a contradiction, not silently counted as negative evidence.
3. **Dataset**: a frozen, hashed selection of evidence examples, gated on
   quality (duplicate/overlap checks) before it can be used at all.
4. **Split**: session-disjoint TRAIN/VALIDATION/TEST partitions, with an
   explicit minimum-evidence rule per scientific task -- a task reports
   `NOT_FEASIBLE` with a real reason rather than training on an
   under-evidenced split.
5. **Training and evaluation**: 5 candidate model architectures per run
   (logistic regression, SVM-RBF, random forest, 1D CNN, 2D CNN); a
   VALIDATION-only composite score picks a recommended one (single,
   guaranteed TEST evaluation, no multiple-comparison leakage), while every
   other candidate can still be exported with its own real, separately-run
   TEST evaluation.
6. **Experimental live inference**: eligible models score real, decoded BLE
   bursts from the same live B200 stream Live Monitor already uses, never a
   second SDR session. This path is described as **live-spectrum
   inference** or **online experimental inference** -- end-to-end latency,
   throughput, and dropped-window behavior have not been characterized, so
   "real-time" is never claimed for this reason.

### Live Monitor integration

Panel in the top-right corner of the spectrum:

- A single-model **health check**: an automated 15s-baseline /
  15s-device-on comparison that verifies a model actually discriminates the
  real device from the real environment, instead of trusting a good TEST
  score blindly.
- **Simultaneous multi-device watching**: several already-trained,
  single-device models run in parallel against the *same* decoded burst
  (one decode, N classifications -- never a separate capture per model, no
  bottleneck). Each watched device gets its own compact status badge
  (`PRESENTE`/`AUSENTE`) and a small on-spectrum band at its real training
  frequency.
- A **Training Service** panel lets an operator pick any already-frozen,
  already-labeled dataset plus exactly which model architectures to train,
  with an internally-generated run name and both automatic and explicit
  export buttons.

### Current scientific scope

Real evidence covers **5 physical devices** (a heterogeneous population,
not identical units), **1 receiver** (USRP B200, serial `E3R04Z1B2`), **1
BLE channel per device's training set**, across **146 real+synthetic
capture sessions** (2026-07-28 to 2026-08-03), all at a single physical
location. Accordingly, the existing results do **not** establish
population-level generalization, receiver invariance, channel invariance,
location invariance, robustness against deliberate waveform imitation, or
forensic source attribution -- no such claim is made anywhere in this
project.

**The single most important label-quality caveat**: `association_status`
(the independently-corroborated, address + native-Windows-timestamp match)
is `STRONG` on exactly 72 examples across the entire 47,051-example corpus
-- and all 72 come from one `SYNTHETIC_TEST_ONLY` capture used for demo
seeding. **Among real (`REAL_B200`) evidence, `STRONG` association occurs
zero times.** Every one of the corpus's 7,599 real `CONFIRMED` label
decisions instead relies on `PHYSICAL_ISOLATION_DECLARED` -- the operator's
declaration that only one device was transmitting nearby, explicitly
documented in code as weaker ground truth with no independent cross-check.
This does not block training (per-device `physical_unit_id` resolution is a
separate, address-binding-registry mechanism both paths feed), but it means
no claim of address-and-timestamp-corroborated ground truth can currently
be made for any real device in this project.

The full per-capability status table, the complete acquisition-chain trace,
every real execution on disk (favorable and unfavorable alike), and the
exact reproduction sequence live in
[`docs/ble/SCIENTIFIC_STATUS.md`](docs/ble/SCIENTIFIC_STATUS.md).

### Independent BLE association validation (Guided BLE Scientific Validation)

A third, independent verification path (`BLE Scientific Results Studio ->
Guided Validation`), read-only over BLE-RFFI Studio's own manifests and
artifacts. It asks a narrower, more skeptical question than the trained
classifier above: **could device identity be corroborated without trusting
the operator's declared label at all**, purely by cross-referencing the
SDR's decoded packet timestamps against an *independent* observation
source -- the host's native Windows Bluetooth adapter, scanning in parallel
with the same B200 capture. A packet only counts as a strong,
source-corroborated association if both sources report the same
advertising address within a 250 ms window.

Real result, reproduced against the full corpus (138 real captures, 5
devices): **zero strong associations**, for every device, including ones
the trained classifier already identifies successfully from RF fingerprint
alone. For `SHELLY-PLUG-01` specifically, the SDR correctly decodes 52
packets carrying the device's real, registered address -- proving capture
and decode are not the problem -- yet all 52 fail independent
corroboration: 40 because the native-adapter and SDR timestamps never
agree within the accepted window even under a widened search
(`ASSOCIATION_TIME_DELTA_ABOVE_THRESHOLD`), 10 because a native event
exists nearby in time but reports a different address
(`ASSOCIATION_ADDRESS_MISMATCH`), 2 because multiple native events compete
for the same window (`ASSOCIATION_MULTIPLE_NATIVE_CALLBACKS`).

This is read as a real, unresolved clock-domain calibration gap between the
native Windows Bluetooth stack and the B200/host capture pipeline -- no
field calibration of that offset has been performed -- not as evidence
that association is impossible or that the underlying RF-fingerprint
classifier is wrong. The two mechanisms answer different questions: the
classifier learns from labels the operator already controls
experimentally; this module tries to generate that same label
independently, and currently cannot. Closing this gap is a stated open
item, not a claimed result.

### Device Scrubbing

An **always-on device** (e.g. `SHELLY-PLUG-01`, a mains smart plug with no
accessible off switch) structurally never produces a real "device absent"
example. **Device scrubbing** -- surgically removing that device's own
decoded-packet windows from real IQ captures and replacing each with a real
quiet segment copied from elsewhere in the *same* recording, never a
synthetic/averaged fill -- was designed, implemented, and verified live:
after scrubbing and capturing 8 real background sessions,
`SHELLY-PLUG-01`'s best model reached TEST macro-F1 = 1.0 and was confirmed
live, correctly reporting `IDENTIFIED` against real traffic.

Scrubbed data remains distinguishable from directly-acquired target-absent
evidence in every record -- the method generates usable negative examples,
it does not manufacture an independent physical observation of the device
being absent.

### Other real, investigated findings

Documented in full in [`backend/README.md`](backend/README.md) and the
module's own
[`backend/app/modules/ble_rffi_studio/README.md`](backend/app/modules/ble_rffi_studio/README.md):

- A real cross-device dataset-contamination bug was found (one device's
  packets leaking into another device's "single-device" training set when
  both were physically nearby) and fixed at the dataset-building layer.
- A real hardware artifact (LO leakage, a direct-conversion USRP
  B200/AD9361 characteristic) was investigated, root-caused, and mitigated
  via LO-offset tuning.
- A pre-existing multi-class "which of N devices is this" task was found to
  structurally exclude any "no device" example from its own training split
  -- documented rather than silently worked around, which is why
  simultaneous multi-device watching (above) exists as the practical
  solution instead of a single combined classifier.

### Engineering obstacles encountered

Documented here (rather than only in code comments) so the real difficulty
of running this pipeline against physical hardware is visible, and so the
same problems are not silently rediscovered:

- **RF acquisition overflow**: a real, measured ~46% single-attempt failure
  rate for continuous USB3 B200 streaming in this environment, even with no
  other USB load -- the host cannot always keep up with sample delivery.
  Absorbed with automatic, bounded retry (`_MAX_CAPTURE_ATTEMPTS`), never
  silently retried without limit and never reported as a clean capture when
  it was not.
- **USB3 vs. USB2**: an earlier capture/analysis pass run over USB2 was
  identified as unreliable and redone entirely over USB3 once the
  difference was traced.
- **A non-atomic hardware-session race**: the capture manager's background
  thread writes its terminal state and clears its own "session active" flag
  as two separate steps. An immediate retry right after a session ends can
  observe the stale "still active" state and be rejected even though the
  device is free -- absorbed with a short backoff-retry, not a longer
  timeout that would slow every normal capture down.
- **LO leakage**: a real hardware artifact of the B200/AD9361's
  direct-conversion architecture (local-oscillator energy leaking into the
  received band near DC) was investigated, root-caused, and mitigated via
  LO-offset tuning rather than post-hoc filtering.
- **Always-on IoT devices structurally break "device absent" sampling**: a
  mains-powered device with no accessible off switch can never produce a
  real negative example -- see Device Scrubbing above.
- **Windows `MAX_PATH` (260 characters)**: deeply nested run-artifact paths
  (timestamped run ID + timestamped action ID + filename) silently failed
  to write, surfacing as a bare `[Errno 2] No such file or directory` with
  no indication of the real cause. Fixed with the `\\?\` extended-length
  path prefix at the file-write layer.
- **Protocol-freeze drift**: the positive-pilot protocol required several
  corrective passes (channel/duration/gain drift from the frozen
  specification, a stale protocol revision hash, a capture-request freeze
  under specific timing) before it reproduced identically on every run --
  each caught by the freeze/hash check refusing to proceed rather than
  silently accepting a drifted run.
- **Physical device population, not device count**: the original device
  inventory assumption (five identical `CC2650` units) was corrected to
  what is physically true -- five heterogeneous BLE transmitters of
  different models. This matters scientifically: population homogeneity
  directly affects what generalization claim, if any, the results can
  support.

**Model-training obstacles**:

- Only five architectures are implemented and compared side by side every
  run -- logistic regression, SVM-RBF, random forest, 1D CNN, 2D CNN. CNN
  training refuses to run below 15 real examples per class rather than
  training on an under-evidenced split and reporting a misleadingly
  confident score.
- **Live inference is structurally narrower than offline inference**: the
  live spectrum stream only ever exposes FFT/PSD data, never raw IQ, so any
  task requiring raw IQ (e.g. E1) or a spectrogram (E3) is rejected for the
  live path by construction, not by a missing feature -- the same model
  class can be offline-trainable and live-inference-ineligible at once.
- A model is only considered live-ready above a fixed
  `READINESS_MIN_MACRO_F1 = 0.50` gate on its held-out TEST score.
- No latency, throughput, or dropped-window measurement code exists for the
  live inference path -- stated explicitly rather than assumed, which is
  why "real-time" is avoided project-wide in favor of "online experimental
  inference" or "live-spectrum inference."

BLE-RFFI Studio implements a real, end-to-end capture-to-inference pipeline
against genuine USRP B200 acquisitions, with per-device classification
scores traceable to raw IQ; it does not currently constitute a deployed
industrial identification system, and no output of this pipeline should be
read as forensic attribution without an explicit population definition, a
stated set of alternative-source propositions, and an independent
validation study.

---

## Architecture

```text
RF-Fingerprint-Lab
|
+-- frontend/
|   +-- React
|   +-- TypeScript
|   +-- Vite
|   +-- operator-facing views
|   +-- spectrum visualization / Spectrum Tools
|
+-- backend/
|   +-- FastAPI
|   +-- SDR control
|   +-- acquisition
|   +-- persistence
|   +-- dataset governance
|   +-- demodulation
|   +-- RF fingerprinting
|   +-- BLE-RFFI Studio
|   +-- ML workflows
|   +-- validation / model registry
|
+-- backend/tools/
|   +-- GNU Radio / UHD workers
|
+-- docs/
|   +-- scientific and technical documentation
|
+-- readme_img/
|   +-- README figures and demonstrations
|
+-- start_unified.ps1
```

The **backend owns hardware-facing and scientific processing state**. The
frontend provides the operator workflow and visualization layer. This
separation avoids making the browser responsible for SDR acquisition or
authoritative experiment state.

## Hardware and runtime

| Component | Current primary path |
|---|---|
| SDR | Ettus Research USRP B200 |
| SDR API | UHD |
| DSP runtime | GNU Radio |
| SDR Python environment | RadioConda |
| Default receive antenna | `RX2` |
| Backend | FastAPI / Python |
| Frontend | React / TypeScript / Vite |

Acquisition parameters such as center frequency, sample rate, bandwidth,
gain, antenna, FFT size, and polling interval are runtime configuration
values rather than scientific constants.

| Variable | Purpose |
|---|---|
| `RADIOCONDA_PYTHON` | Python executable used by GNU Radio/UHD workers |
| `UHD_DEVICE_ARGS` | UHD device selector |
| `DEFAULT_CENTER_FREQUENCY_HZ` | Initial analyzer center frequency |
| `DEFAULT_SAMPLE_RATE_HZ` | Initial sample rate |
| `DEFAULT_SPAN_HZ` | Initial span |
| `DEFAULT_GAIN_DB` | Initial receiver gain |
| `DEFAULT_ANTENNA` | Initial receive antenna |
| `REAL_SDR_FPS` | Live spectrum target frame rate |
| `REAL_SDR_MAX_FFT_SIZE` | Maximum accepted FFT size |
| `VITE_SPECTRUM_POLL_INTERVAL_MS` | Frontend spectrum polling interval |
| `VITE_WATERFALL_POLL_INTERVAL_MS` | Frontend waterfall polling interval |
| `QC_MIN_VALID_SNR_DB` | Dataset QC threshold |
| `RF_INTELLIGENCE_MIN_SNR_DB` | RF Intelligence candidate threshold |

Persisted runtime settings are stored under
`backend/app/infrastructure/persistence/storage/config/runtime_settings.json`.

## Testing

**Backend**

```powershell
cd backend
python -m pytest app/tests/unit -q
```

**Frontend**

```powershell
cd frontend
npm run build
```

Hardware-facing changes should additionally be tested against the actual
SDR path, including:

1. UHD device discovery and probe.
2. Connect/disconnect.
3. Stream start/stop.
4. Frequency, sample-rate, span, gain, antenna, RBW and VBW controls.
5. Live spectrum and waterfall.
6. Markers and Spectrum Tools.
7. Immediate capture.
8. Triggered capture and pre-trigger preservation.
9. Dataset QC and split routing.
10. Any demodulation, training, validation, BLE-RFFI, or inference path
    affected by the change.

A passing frontend build or unit-test suite alone is not evidence that a
hardware-dependent workflow has been validated over real RF input.

## Scientific reporting principles

RF-Fingerprint-Lab follows several project-level rules intended to keep
experimental and operational claims distinguishable:

- Real, synthetic, derived, and test-only data remain distinguishable.
- RF activity is not automatically called protocol decoding.
- A CRC-valid packet is distinguished from an RF burst candidate.
- Logical device identification is distinguished from physical RF
  fingerprinting.
- Dataset labels retain their provenance.
- Training, validation, and test groups do not silently share related
  sessions.
- Unsupported experimental conditions fail or report `NOT_FEASIBLE` rather
  than silently weaken a scientific requirement.
- Negative or unfavorable validation results remain part of the documented
  project state.
- Implementation status is not equivalent to scientific validation.
- A successful experiment over a bounded device set is not automatically
  generalized to unseen devices, receivers, channels, locations, or
  acquisition conditions.

For the current BLE evidence boundary and validation state, see
[`docs/ble/SCIENTIFIC_STATUS.md`](docs/ble/SCIENTIFIC_STATUS.md).

## Troubleshooting

### UHD reports `No devices found`

Verify the receiver independently:

```powershell
uhd_find_devices
uhd_usrp_probe
```

Then check: USB enumeration; USB 3.x connectivity; whether another
application owns the SDR; UHD/RadioConda compatibility; `UHD_DEVICE_ARGS`
when more than one device is available.

### The Settings API returns 404

Confirm the backend process actually mounts the Settings router for the
running `app.main:app` entry point, and that the frontend's configured API
base URL matches the backend's real host/port.

### Frontend and backend appear inconsistent

Stop both processes and restart them from the same repository revision
using `start_unified.ps1`.

### A capture cannot enter training

Inspect Dataset Builder and verify acquisition quality, required metadata,
label status, review status, selected split, and dataset-specific
scientific gates.

### E1, E3, or E5 refuses to train

Check dataset readiness, number of target classes, class presence in each
required split, session/group leakage, representation compatibility, label
field, and minimum evidence requirements. A failed scientific gate should
normally be investigated rather than bypassed.

### Spectrum Tools obscures the Live trace

Toggle off unused overlays -- Trace History and Density/Persistence in
particular render dense layers that can visually dominate a thin Live
trace at some display scales; this is a rendering-order effect, not a data
issue.

## Documentation

Detailed implementation and scientific documentation is intentionally
separated from this root overview:

- [Backend documentation](backend/README.md) -- backend architecture, APIs,
  workers, and hardware integration.
- [Backend setup](backend/README_SETUP.md)
- [Frontend documentation](frontend/README.md)
- [`frontend/src/features/spectrum-tools/VALIDATION.md`](frontend/src/features/spectrum-tools/VALIDATION.md)
  -- Spectrum Tools definitions and scientific checks.
- [BLE-RFFI Studio module documentation](backend/app/modules/ble_rffi_studio/README.md)
- [`docs/ble/SCIENTIFIC_STATUS.md`](docs/ble/SCIENTIFIC_STATUS.md) -- current
  BLE scientific evidence, capability status, limitations, and reproduction
  information.
- [`docs/ble/PILOT_V1_LEGACY.md`](docs/ble/PILOT_V1_LEGACY.md) -- the
  superseded BLE Dataset Studio Pilot v1 baseline, including an honest,
  disk-verified note on which of its cited artifacts no longer exist.

Historical or superseded experiments are maintained under `docs/` rather
than placed before the active project description in this README.

## Project status

RF-Fingerprint-Lab is an **active research platform**. Several workflows
operate end-to-end against real SDR data, while other modules remain
experimental, partially implemented, or scientifically under validation.
The authoritative state of a capability should therefore be determined from
its corresponding module documentation, artifacts, tests, and
scientific-status records rather than inferred only from the existence of a
user-interface control.

## Citation and research release

For academic use or publication, the repository should maintain
machine-readable citation metadata through a root-level `CITATION.cff` and
an explicit software license. When experimental results from
RF-Fingerprint-Lab are reported, the software revision, hardware
configuration, dataset version, acquisition conditions, and relevant
validation state should be recorded alongside the result.
