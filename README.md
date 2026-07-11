# Spectrum Lab

Spectrum Lab is a browser-based RF laboratory for real-time spectrum monitoring,
controlled I/Q acquisition, dataset curation, demodulation, RF scene analysis,
model training, validation, and inference.

The primary hardware path uses an **Ettus Research USRP-B200** through
**UHD/GNU Radio** in a RadioConda environment. The platform consists of a
FastAPI backend and a React/TypeScript frontend.

> Spectrum Lab uses real SDR samples. The live spectrum, waterfall, captures,
> triggered pre-buffer, demodulation, and dataset artifacts are not mock data.

## Contents

- [Main capabilities](#main-capabilities)
- [Quick start](#quick-start)
- [Recommended workflow](#recommended-workflow)
- [Platform views](#platform-views)
- [Live Monitor and Spectrum Tools](#live-monitor-and-spectrum-tools)
- [Capture and dataset workflow](#capture-and-dataset-workflow)
- [Demodulation capabilities](#demodulation-capabilities)
- [Architecture](#architecture)
- [Hardware and runtime](#hardware-and-runtime)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)

## Main capabilities

- Real-time FFT/PSD spectrum monitoring from a USRP.
- Spectrum and waterfall split view.
- Frequency, span, sample-rate, gain, antenna, RBW, VBW, reference-level,
  detector, trace, averaging, and display controls.
- Interactive markers, marker-band filtering, automatic peaks, pan, zoom,
  freeze, and CSV/PNG export.
- Simultaneous Spectrum Tools traces and statistical layers.
- Manual and triggered I/Q acquisition with pre-trigger buffering.
- Capture metadata, checksums, experimental splits, and quality control.
- RF Intelligence hypotheses with explicit confidence and evidence.
- Waterfall-based RF Signal Understanding.
- Analog, digital, and IoT demodulation workflows.
- Dataset governance for training, validation, and prediction.
- Model training, retraining, external validation, registry, and inference.
- Reproducible E0/E1/E3/E5 experiments and E6 classical-ML workflows.
- KiwiSDR receiver discovery and remote receiver map.
- Persisted runtime settings with hardware and scientific-policy limits.

## Quick start

### Requirements

- Windows 10/11.
- Node.js and npm.
- Python environment for the FastAPI backend.
- RadioConda with GNU Radio and UHD for real SDR workers.
- USRP-B200/B210 or another UHD-compatible receiver.

Confirm that UHD can discover and open the radio:

```powershell
& "C:\Users\Usuario\radioconda\Library\bin\uhd_find_devices.exe"
& "C:\Users\Usuario\radioconda\Library\bin\uhd_usrp_probe.exe"
```

### Unified launcher

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_unified.ps1
```

With an explicit RadioConda interpreter:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_unified.ps1 `
  -RadioCondaPythonPath "C:\Users\Usuario\radioconda\python.exe"
```

The launcher starts the backend on `http://127.0.0.1:8000`, starts Vite, and
propagates the SDR and polling configuration required by the frontend.

### Manual development

Backend:

```powershell
cd backend
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.dev-windows.txt
$env:RADIOCONDA_PYTHON="C:\Users\Usuario\radioconda\python.exe"
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Frontend:

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
7. Recompute QC, confirm the label, and accept, reject, or mark the capture as
   doubtful.
8. Route accepted captures to training, validation, inference, demodulation,
   RF Signal Understanding, or RF Experiment Lab.

## Platform views

The following sections correspond to the routes registered under
`frontend/src/app/modules/`. Every navigation view is documented even when a
dedicated screenshot is not yet available.

### Mission Control — `/`

Mission Control is the top-level operational dashboard. It summarizes
acquisition, dataset readiness, training state, validation evidence, inference,
and model availability. Use it to identify the next blocked or incomplete stage
in the RF fingerprinting workflow.

### Live Monitor — `/spectrum`

Live Monitor is the main real-time analyzer. It provides SDR connection and
streaming controls, spectrum navigation, markers, analyzer settings, optional
waterfall, overlays, freeze, exports, and Spectrum Tools.

![Live Monitor spectrum](readme_img/live_monitor.png)

The split workspace keeps the live spectrum and recent spectral history in the
same view:

![Live Monitor with waterfall](readme_img/live_monitor_waterfall.png)

RF Intelligence can be displayed directly over the live workspace without
changing the underlying spectrum data:

![Live Monitor with RF Intelligence overlay](readme_img/live_monitor_rf_intelligence_overlay.png)

An older split-view reference is retained for comparison:

<details>
<summary>Legacy Live Monitor and waterfall screenshot</summary>

![Legacy Live Monitor waterfall](readme_img/live_monitor_waterfall_legacy.png)

</details>

See [Live Monitor and Spectrum Tools](#live-monitor-and-spectrum-tools) for the
complete technique reference.

Exact formulas and automated scientific checks are recorded in
[Spectrum Tools Critical Validation](frontend/src/features/spectrum-tools/VALIDATION.md).

### Capture Lab — `/capture`

Capture Lab performs controlled real-I/Q acquisition. It can derive capture
limits from M1/M2, the live peak, the visible monitor window, or custom
frequencies. Before capture it reports center, bandwidth, peak, noise floor,
SNR, and scientific suitability.

![Capture Lab](readme_img/capture_lab.png)

Supported capture modes:

- **Immediate**: records the requested duration immediately.
- **Triggered Burst**: waits for an event and preserves samples from the
  circular pre-trigger buffer.

Each capture stores raw complex I/Q and JSON metadata including frequency
limits, sample rate, gain, antenna, format, labels, split, timing, and checksum.

The following screenshot shows the earlier signal-analysis capture interface,
which is now represented by the Capture Lab route and aliases
`/guided-capture` and `/modulated-analysis`:

<details>
<summary>Capture Lab signal-analysis interface</summary>

![Capture Lab signal analysis](readme_img/capture_lab_signal_analysis.png)

</details>

### Dataset Builder — `/dataset-builder`

Dataset Builder is the governance gate between acquisition and model use. It
does not capture RF. It reviews saved I/Q, recomputes offline QC, manages
labels and experimental splits, and prevents doubtful or invalid samples from
silently entering training or validation.

![Dataset Builder](readme_img/dataset_builder.png)

The view separates:

- `capture_quality`: `valid`, `warning`, `doubtful`, or `invalid`.
- `label_status`: `unlabeled`, `weak_label`, or `strong_label`.
- `review_status`: `needs_review`, `accepted`, `doubtful`, or `rejected`.
- `split`: `train`, `val`, or `predict`.

QC includes SNR, clipping, silence/near-zero content, occupied bandwidth,
frequency offset, sample count, file consistency, and burst suitability.

### Training — `/training`

Training launches controlled RF fingerprinting jobs from canonicalized captures
assigned to the training registry. It exposes dataset readiness,
hyperparameters, remote execution status, logs, metrics, and generated model
artifacts. Strict mode requires accepted, strongly labelled, technically valid
captures.

### Retraining — `/retraining`

Retraining updates an existing model using the current curated training
registry. It preserves lineage between the source model, dataset fingerprint,
configuration, new metrics, and replacement candidate.

### RF Intelligence — `/rf-intelligence`

RF Intelligence performs real-time RF object detection and cautious
rule/profile-based protocol hypotheses. It shows the estimated noise floor,
detection threshold, minimum SNR, detected objects, temporal behavior,
confidence, and the evidence supporting each hypothesis.

![RF Intelligence](readme_img/rf_intelligence.png)

The output is intentionally phrased as a hypothesis unless enough evidence is
available. RF energy alone is not treated as a decoded or identified protocol.

### RF Experiment Lab — `/rf-experiment-lab`

RF Experiment Lab provides reproducible research workflows with strict dataset
splits, dry-run validation, representation extraction, metrics, exports, and
benchmark reports.

Implemented experiment families include:

- **E0**: morphological waterfall/spectrogram baseline.
- **E1**: raw-I/Q 1D CNN workflow.
- **E3**: spectrogram/waterfall 2D CNN workflow.
- **E5**: engineered spectral-feature classical ML baseline.

The view records configuration, dataset manifest, label schema, preprocessing,
split policy, artifacts, metrics, and scientific traceability.

### E6 Oracle-Style Lab — `/e6-oracle-style-lab`

E6 is an oracle-style classical RF fingerprinting laboratory. It supports local
dataset creation, SigMF and reference-dataset import, feature extraction,
training, benchmarking, pre-trained model import, registry management, and
file/live prediction.

Available algorithms:

- HistGradientBoosting
- Random Forest
- Extra Trees
- MLP
- SVM RBF
- SVM linear
- KNN
- Logistic Regression

Models are isolated by dataset and algorithm, and long-running jobs report
progress, elapsed time, current stage, metrics, model size, and inference
latency.

### RF Signal Understanding — `/rf-signal-understanding`

RF Signal Understanding analyzes I/Q-derived waterfall representations,
detects time-frequency regions, extracts spectral evidence, and produces
cautious signal-family hypotheses. The view can compare newer region/feature
pipelines with legacy analysis results.

### Validation — `/validation`

Validation evaluates selected models against canonicalized validation captures
that are kept separate from training groups. It checks leakage, label
compatibility, artifact readiness, per-class results, aggregate metrics, and
external-validation evidence.

### Inference — `/inference`

Inference runs asynchronous predictions on captures assigned to the prediction
split. It resolves the selected capture and model, validates required metadata,
tracks job state, and presents ranked predictions and confidence evidence.

### Models — `/models`

Models is the registry and model-card view. It presents model identity, task,
algorithm, dataset lineage, label schema, validation evidence, artifact paths,
readiness, and whether a model is enabled for live use.

### Waterfall — `/waterfall`

Waterfall visualizes spectral power over time. It is useful for bursts,
frequency hopping, drift, intermittent interference, and temporal occupancy.
The standalone view complements the split waterfall available in Live Monitor.

### Recordings — `/recordings`

Recordings provides a library of recording sessions and saved artifacts. It is
used to locate, inspect, and manage I/Q or audio recordings independently of
the curated Dataset Builder registry.

### Demodulation — `/demodulation`

Demodulation processes a marker-selected live band or a stored dataset capture
through analog, digital, or IoT pipelines. Results distinguish RF activity,
synchronization, bit recovery, frame reconstruction, CRC validation, and
successfully decoded payloads.

![Demodulation](readme_img/demodulation.png)

### Live Demodulation — `/live-demodulation`

Live Demodulation provides real-time AM, FM, NFM, and WFM audio recovery from
the current SDR stream. It includes tuning, bandwidth and gain controls, Web
Audio playback, stream status, level monitoring, and optional persistence.

![Live Demodulation](readme_img/live_demodulation.png)

### KiwiSDR Map — `/kiwisdr`

KiwiSDR Map discovers and catalogs remote KiwiSDR receivers, displays them on a
map, exposes receiver filters, and supports selecting a remote receiver for
inspection. This module is separate from the local UHD/USRP hardware path.

### Settings — `/settings`

Settings exposes persisted application, analyzer, hardware, polling, capture,
QC, and RF Intelligence parameters. Each setting documents its active value,
default, source, allowed range, affected workflow, restart requirement, and
whether the limit is imposed by hardware, software, or scientific policy.

## Live Monitor and Spectrum Tools

Spectrum Tools is always available from the upper-right corner of Live Monitor.
The menu opens over the canvas and does not reduce the spectrum workspace.
Several tools can run simultaneously because every processor receives the same
original Live frame rather than the output of another technique.

### Static overview

![Spectrum Tools with Max Hold, Min Hold, averages, RMS, EWMA and statistical layers](readme_img/live_monitor_spectrum_tools.png)

### Animated overview

![Animated Spectrum Tools demonstration](readme_img/live_monitor_spectrum_tools.gif)

### Display controls

- **Live Trace** shows or hides only the original blue trace. Hiding it does not
  stop acquisition, analysis, markers, waterfall, captures, or tool updates.
- The **eye** hides a tool representation while its processor keeps collecting.
- **Reset** clears only that tool's accumulated history.
- **Disable** stops the tool and releases its accumulated state.
- **Reset all histories** keeps tools enabled but clears their buffers.
- **Disable all tools** disables every optional tool but leaves Live running.
- Tooltips appear after approximately 350 ms and explain purpose, use cases,
  limitations, requirements, impact, and parameter direction.

### Technique reference

| Technique | What it shows | Best used for | Important limitation |
|---|---|---|---|
| Live Trace | Current FFT/PSD frame | Immediate spectrum inspection | Hiding it is visual only; acquisition continues |
| Max Hold | Highest observed power per bin | Bursts, hopping, intermittent signals, spurs | Does not preserve occurrence time or duration |
| Min Hold | Lowest observed power per bin | Noise-floor inspection and persistent-channel analysis | A low outlier remains until reset |
| Power Average | Mean power calculated in linear domain | Stable estimates of persistent energy | Smooths short events |
| RMS Power | Effective accumulated power per bin | Energy comparison for varying signals | PSD-only RMS can resemble Power Average |
| EWMA | Timestamp-aware exponential average | Adjustable smoothing with recent-frame emphasis | Large time constants respond slowly |
| Percentiles | P50, P90, P95, and P99 per bin | Typical level versus rare peaks | Needs a sample window and additional processing |
| Trace History | Previous traces with fading opacity | Drift, movement, and intermittent activity | Many traces can make the graph visually dense |
| Density / Persistence | Distribution of observed power levels | Multiple signal states and persistence | Observed-frame density, not a regulatory measurement |
| Spectrum Mask | Configurable upper limit line | Visual emission-limit comparison | Currently visual; it does not trigger IQ capture |
| Observed-frame Occupancy | Time fraction above a threshold | Comparing activity across the span | Not absolute or regulatory occupancy |
| Gated Spectrum | Spectrum inside a precise time gate | A selected part of a burst or pulse | Requires synchronized real IQ; unavailable on PSD-only Live input |
| Zero Span | Power versus time at one selected frequency | Pulses, duty cycle, and temporal modulation | Requires continuous timed IQ and a separate time-axis panel |

### Parameter behavior

| Parameter | Increase it | Decrease it |
|---|---|---|
| EWMA time constant | Smoother, steadier trace with slower response | Faster response with more visible noise |
| Spectrum Mask level | Fewer crossings; only stronger signals exceed the mask | More sensitivity and more noise-related crossings |
| Occupancy threshold | Counts only stronger signals; lower reported occupancy | Includes weaker signals/noise; higher apparent occupancy |

### Freeze and geometry changes

Freeze pauses visual tool updates without deleting accumulated state. Changes
to acquisition geometry—center frequency, span, bin count, or frequency grid—
reset incompatible buffers so values from different grids are never mixed.

### Analysis source and legacy Max Hold

Display and analysis remain separate concepts. Enabling a visual tool does not
automatically change RF Intelligence, RF Signal Understanding, markers, or
prediction input. The existing **Use Peak For Detection** control explicitly
selects the legacy peak trace when required. Permanent and decay Max Hold,
Reset Peaks, marker band-pass, and Freeze behavior remain available.

## Capture and dataset workflow

### Immediate capture

Immediate mode records the selected RF window for a fixed duration. It is best
for continuous signals, controlled transmitters, or cases where the signal is
already active.

### Triggered capture

Triggered mode continuously observes the source and writes an event only after
the configured condition is met. A bounded circular buffer preserves samples
from before the trigger so the beginning of a burst is not lost.

Typical targets include OOK remotes, LoRa, FSK, BLE-like bursts, short packets,
and intermittent emitters.

### Capture artifacts

Each successful acquisition can produce:

- `.cfile` or `.iq` complex-sample file.
- JSON metadata sidecar.
- SHA-256 checksum.
- Capture configuration and RF context.
- Trigger and pre-trigger metadata when applicable.
- Dataset split and label fields.

## Demodulation capabilities

The demodulation registry supports analog audio, digital protocols, and IoT
pipelines. A signal is not reported as decoded merely because energy exists in
the selected band.

| Pipeline | Status | Main output |
|---|---|---|
| `wfm_broadcast` | Basic implementation | Recovered WFM audio and report |
| `nfm` | Basic implementation | Recovered NFM audio and report |
| `am` | Basic implementation | Recovered AM audio and report |
| `ble_advertising` | RF activity and synchronization scaffold | BLE CH37–CH39 packet candidates and CRC evidence |
| `wifi_80211` | RF activity and frame scaffold | 2.4/5 GHz frame candidates and report |
| `generic_gfsk_iot` | Physical bitstream estimator | Bitstream, payload candidate, and report |
| `ook_ask_iot_sensor` | Physical bitstream estimator | Generic OOK/ASK bitstream and payload candidate |
| `generic_fsk_iot` | Physical bitstream estimator | Generic FSK bitstream and payload candidate |
| `zigbee_ieee802154` | Implemented | IEEE 802.15.4 frames, MAC fields, and FCS evidence |
| `ieee802154_oqpsk` | RF activity and synchronization scaffold | O-QPSK packet candidates and report |
| `adsb_1090` | RF activity and synchronization scaffold | ADS-B packet candidates and report |
| `ook_fsk_generic` | Symbol-estimation scaffold | Generic OOK/FSK/GFSK bitstream diagnostics |
| `lora_css` | Experimental scaffold | LoRa payload candidates and report |
| `ook_433_remote` | Implemented | EV1527/PT2262 frames, address/button fields, and bitstream |
| `fsk_remote_decoder` | Candidate decoder | ISM remote bursts, two-tone FSK candidates, and repetition evidence |
| `dvbt` | External chain required | Detection/report only |
| `dvbs_s2` | Experimental; external RF front end required | Detection/report only |

Depending on the pipeline, persisted results can include:

- `demodulation_report.json`
- `decoded_packets.json`
- `decoded_frames.json` or `decoded_frames.csv`
- `recovered_bitstream.bin`
- `burst_candidates.json`
- recovered `.wav` or `.ts` media
- `logs.txt`

## Architecture

```text
frontend/                         React, TypeScript, Vite, Tailwind
  src/app/modules/                Route and navigation module definitions
  src/presentation/views/         Operator-facing views
  src/features/spectrum-tools/    Multi-technique spectrum processing and UI

backend/                          FastAPI application
  app/infrastructure/web/         Controllers and API routes
  app/infrastructure/sdr/         Real spectrum stream and SDR safety
  app/modules/fingerprinting/     Operational RF fingerprinting
  app/modules/rf_intelligence/    RF scene detection and hypotheses
  app/modules/rf_signal_understanding/
  app/modules/rf_experiment_lab/  E0/E1/E3/E5 workflows
  app/modules/e6_oracle_style/    E6 classical-ML workflows
  app/modules/mlops/              Training, validation, registry lifecycle

backend/tools/                    GNU Radio/UHD capture and stream workers
readme_img/                       View-aligned README screenshots
start_unified.ps1                 Unified Windows launcher
```

The backend owns hardware access, capture, pre-trigger buffering, persistence,
QC, demodulation, training, validation, and inference. The frontend owns the
operator workflow and visualization.

## Hardware and runtime

| Component | Default |
|---|---|
| SDR | Ettus Research USRP-B200 |
| Driver/runtime | UHD + GNU Radio |
| SDR Python | RadioConda Python |
| Antenna | `RX2` |
| Center frequency | `89.4 MHz` |
| Sample rate | `2 MS/s` |
| Span | `2 MHz` |
| Gain | `20 dB` |

Important environment variables:

| Variable | Purpose |
|---|---|
| `RADIOCONDA_PYTHON` | Python executable used by GNU Radio/UHD workers |
| `UHD_DEVICE_ARGS` | Device selector such as `serial=...` or `addr=...` |
| `DEFAULT_CENTER_FREQUENCY_HZ` | Initial analyzer center |
| `DEFAULT_SAMPLE_RATE_HZ` | Initial sample rate |
| `DEFAULT_SPAN_HZ` | Initial acquisition span |
| `DEFAULT_GAIN_DB` | Initial receiver gain |
| `DEFAULT_ANTENNA` | Initial receive antenna |
| `REAL_SDR_FPS` | Target live spectrum worker frame rate |
| `REAL_SDR_MAX_FFT_SIZE` | Maximum accepted FFT size |
| `VITE_SPECTRUM_POLL_INTERVAL_MS` | Frontend spectrum polling interval |
| `VITE_WATERFALL_POLL_INTERVAL_MS` | Frontend waterfall polling interval |
| `QC_MIN_VALID_SNR_DB` | Minimum SNR for valid dataset captures |
| `RF_INTELLIGENCE_MIN_SNR_DB` | Minimum SNR for RF Intelligence candidates |

Persisted runtime settings are stored under:

```text
backend/app/infrastructure/persistence/storage/config/runtime_settings.json
```

## Testing

Backend unit tests:

```powershell
cd backend
python -m pytest app/tests/unit -q
```

Frontend production build:

```powershell
cd frontend
npm run build
```

Before accepting hardware-facing changes, also verify:

1. `uhd_find_devices` and `uhd_usrp_probe`.
2. Connect/disconnect and start/stop stream.
3. Frequency, span, sample rate, gain, antenna, RBW, and VBW.
4. Markers, Freeze, waterfall, Spectrum Tools, and overlays.
5. Immediate and triggered capture with pre-trigger data.
6. Dataset Builder QC and split routing.
7. Demodulation, training, validation, and inference paths in scope.

## Troubleshooting

### UHD reports `No devices found`

Run the UHD discovery and probe tools shown in [Quick start](#quick-start). If
the radio is detected intermittently:

- reconnect the USB cable and prefer a USB 3.x port;
- close other applications that may own the USRP;
- wait for Windows device enumeration before pressing Connect;
- configure `UHD_DEVICE_ARGS=serial=<serial>` instead of empty autodetection;
- verify that the UHD version used by RadioConda can probe the device.

### The Settings API returns 404

The frontend and backend processes are from different revisions. Stop both and
restart from the repository root with `start_unified.ps1`.

### A capture cannot enter training

Check Dataset Builder. Strict training normally requires valid technical QC, a
strong label, accepted human review, required metadata, and a training split.

### E1, E3, or E5 refuses to train

Verify dataset readiness, group-disjoint splits, at least two target classes,
compatible representations, and the selected label field. Draft policies are
for exploration and should not replace strict evaluation evidence.

### Spectrum Tools obscures the Live trace

Use the `Live Trace` checkbox or eye control to hide only the original trace.
Acquisition and every processor continue running. Hide individual tools with
their eye controls, or reset/disable only the tool whose history is no longer
needed.

## Additional documentation

- [Backend documentation](backend/README.md)
- [Backend setup](backend/README_SETUP.md)
- [Frontend documentation](frontend/README.md)
