# Spectrum Lab

Spectrum Lab is a browser-based RF laboratory for live spectrum monitoring,
marker-driven I/Q capture, dataset curation, and reproducible RF machine
learning experiments.

The current hardware path targets an Ettus Research USRP-B200 through
UHD/GNU Radio in a RadioConda Python environment. The application is split into
a FastAPI backend and a React/TypeScript frontend.

## What This Project Does

Spectrum Lab is designed to support the full RF workflow from observation to
training data:

- Observe live RF spectrum and waterfall data from a real SDR.
- Place markers on signals of interest and use them as capture boundaries.
- Capture raw I/Q as `.cfile` or `.iq` with JSON metadata.
- Capture short transient signals with triggered capture and pre-trigger
  buffering.
- Review captures in Dataset Builder with offline QC over the saved I/Q file.
- Repair missing class metadata from RF band profiles, then confirm labels when
  the operator has ground-truth knowledge.
- Route accepted captures into fingerprinting, RF Signal Understanding, or RF
  Experiment Lab workflows.
- Train and compare experimental RF models using reproducible dataset gates and
  split policies.

It is not a generic mock dashboard. The live SDR path opens real UHD/GNU Radio
workers, reads real samples, and stores real dataset artifacts.

## Recent Changes

- **OOK 433 / 315 / 868 MHz remote control pipeline** - New IoT demodulation
  pipeline (`ook_433_remote`) for ISM-band remote controls using EV1527/SC1527
  and PT2262/SC2262 protocols. The pipeline estimates the chip period T from a
  histogram of HIGH-pulse widths, segments frames by sync gaps, decodes PWM
  bits, and matches the 20-bit address + 4-bit button field of EV1527 or the
  12-tri-state encoding of PT2262. Repeat-frame analysis reports consistency,
  inter-frame gap and estimated transmit period. Live SDR path is supported
  through the `ook` worker with full IoT post-processing in the controller.

- **BLE SYNC correlation filter** - The BLE burst decoder now computes a 40-bit
  SYNC score (8-bit preamble `0xAA` + 32-bit Access Address `0x8E89BED6`) per
  burst across all symbol-phase candidates. Bursts with a maximum SYNC score
  below 28/40 are discarded before CRC checking. Non-BLE 2.4 GHz interference
  typically scores ≤ 24; real BLE bursts score 32 or higher. This eliminates
  false-positive BLE candidates from Zigbee, WiFi CH1 leakage and ISM noise.

- **Zigbee pipeline** - New IoT demodulation pipeline (`zigbee`) supporting
  IEEE 802.15.4 O-QPSK at 2.4 GHz. Recovers chip sequences, correlates against
  the 32-chip PN spreading code, reconstructs nibbles and bytes, parses the MAC
  frame (FCS, frame type, sequence number, addressing), and reports PAN IDs and
  device addresses. Note: Zigbee CH26 (2480 MHz) and BLE CH39 (2480 MHz) share
  the same center frequency; capture context and burst structure distinguish them.

- **Demodulation result persistence fix** - Live IoT pipeline results stored
  under `{id}/demodulation_report.json` were not reloaded after page refresh.
  The result loader now reads both the flat `*.json` pattern (script-level
  metadata) and the nested `*/demodulation_report.json` pattern (enriched IoT
  report), with the enriched report winning when both exist for the same ID.

- **Audio demodulation display** - FM, WFM, and AM results in the Demodulation
  tab now show audio-relevant fields: demodulation mode, center frequency,
  bandwidth, sample rate, signal duration, audio presence and sample rate, gain,
  and antenna. Packet-oriented fields (protocol, packets decoded, CRC valid,
  channel) are shown only for digital and IoT demodulation results.

- **Collapsible sidebars** - The left navigation sidebar and the right status
  panel in the Spectrum view each have a circular collapse/expand button that
  remains visible even when the panel is fully hidden. Both panels animate to
  `w-0` when collapsed so the spectrum display uses the full screen width.

- **MLOps WinError 123 fix** - Training no longer crashes when the dataset
  directory contains subdirectories with colons in their names. The export
  cleanup uses `cmd /c rd /s /q` as a fallback on Windows when `shutil.rmtree`
  fails.

## Architecture

```text
frontend/                 React, TypeScript, Vite, Tailwind
backend/                  FastAPI application and RF/ML services
backend/tools/            GNU Radio/UHD helper workers
backend/app/modules/      Domain modules: fingerprinting, RF intelligence,
                          RF Signal Understanding, RF Experiment Lab, MLOps
backend/app/infrastructure/persistence/storage/
                          Local captures, metadata, temporary files, datasets,
                          model artifacts and experiment results
scripts/run_dev.ps1       Windows development launcher
start_unified.ps1         Project-level launcher wrapper
```

The backend owns hardware access, capture workers, QC, dataset registries, model
training, inference and persistence. The frontend owns the operator workflow:
spectrum view, markers, Capture Lab, Dataset Builder, model views and experiment
screens.

## Hardware And Runtime

Primary development target:

| Component | Value |
|---|---|
| SDR | Ettus Research USRP-B200 |
| Driver/runtime | UHD + GNU Radio |
| SDR Python | RadioConda Python |
| Default antenna | `RX2` |
| Default center | `89.4 MHz` |
| Default sample rate | `2 MS/s` |
| Default gain | `20 dB` |

Before running the app, UHD must be able to discover and probe the device:

```powershell
& "C:\Users\Usuario\radioconda\Library\bin\uhd_find_devices.exe"
& "C:\Users\Usuario\radioconda\Library\bin\uhd_usrp_probe.exe"
```

For network USRPs, pass `UHD_DEVICE_ARGS=addr=<ip>`. For multiple USB devices,
use `UHD_DEVICE_ARGS=serial=<serial>`.

## Quick Start On Windows

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_unified.ps1
```

With an explicit RadioConda path:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_unified.ps1 `
  -RadioCondaPythonPath "C:\Users\Usuario\radioconda\python.exe"
```

With a remote training host configured for the UI:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_unified.ps1 `
  -RemoteUser "<ssh-user>" `
  -RemoteHost "<training-host>"
```

The launcher starts:

- backend API on `http://127.0.0.1:8000`
- frontend dev server through Vite
- frontend environment values for polling intervals, remote host metadata and
  RadioConda Python propagation
- persisted runtime settings from
  `backend/app/infrastructure/persistence/storage/config/runtime_settings.json`
  when that file exists

## Manual Development

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

The full `backend/requirements.txt` includes GNU Radio and UHD packages. On
Windows, the project normally uses RadioConda for SDR workers and a separate
backend virtual environment for FastAPI dependencies.

## Operator Workflow

1. Connect and probe the USRP.
2. Start the application with `start_unified.ps1`.
3. Open Live Spectrum.
4. Tune center frequency, span, sample rate, gain and antenna.
5. Place Marker 1 and Marker 2 around the signal band.
6. Use Capture Lab to record the marked band.
7. Choose manual capture for fixed-duration recordings or triggered capture for
   burst signals.
8. Open Dataset Builder.
9. Run `Recompute QC`.
10. Fill missing fields from the band profile when needed.
11. Confirm the label as strong only when the operator has verified the signal
    class or transmitter identity.
12. Accept, reject or keep the capture for review.
13. Use accepted captures for training, validation, RF Signal Understanding or RF
    Experiment Lab.

## Capture Modes

### Manual Capture

Manual capture records immediately for the requested duration. It is appropriate
for continuous signals, stable test transmitters, long packets, or controlled
captures where the signal is already active.

### Triggered Capture

Triggered capture streams continuously and saves an event only when the trigger
detects a burst. It maintains a circular pre-trigger buffer, so the beginning of
the burst is preserved. This mode is better for LoRa, OOK, FSK, remote keys,
BLE-like bursts and other packet signals.

Available trigger strategies:

| Strategy | Use |
|---|---|
| Adaptive Energy | General burst detection based on rolling noise floor and energy rise |
| Smart Burst | Adds persistence and saturation rejection for cleaner burst events |

Each valid event writes an I/Q file and a JSON metadata file.

## Demodulator

The Demodulator tab is split into two workflows:

| Mode | Input | Main use | Persistence |
|---|---|---|---|
| Live Demodulation | Current SDR stream and marker-selected band | Fast inspection of what is on air now | Optional IQ and result storage |
| Dataset Demodulation | Stored `.cfile`, `.iq`, `.bin`, `.dat` or SigMF capture | Reproducible post-capture analysis | Results are linked to the source dataset/sample |

Both workflows use the same demodulation pipeline registry. The difference is
the source adapter: live mode derives metadata from SDR settings and markers,
while dataset mode derives metadata from the stored capture and Dataset Builder
record. Critical metadata such as sample rate, center frequency, datatype and
source file must be present before a dataset demodulation is executed.

Each demodulation result is written under the local demodulation storage area
and is visible from the UI. The result viewer opens decoded artifacts directly
instead of requiring the operator to inspect files manually. Depending on the
pipeline, outputs can include:

- `demodulation_report.json`
- `decoded_packets.json`
- `decoded_frames.json` or `decoded_frames.csv`
- `bitstream.bin` or `recovered_bitstream.bin`
- recovered media such as `.wav` or `.ts`
- `logs.txt`

The UI must distinguish RF activity, protocol compatibility, synchronization,
bitstream recovery, frame reconstruction, CRC validation and payload extraction.
Energy in a channel is not reported as a successful demodulation.

The result display adapts to the demodulation type:

- **Analog audio** (AM, FM, WFM): shows center frequency, bandwidth, sample
  rate, signal duration, audio presence, audio sample rate, gain and antenna.
- **Digital / IoT**: shows protocol, pipeline, packet count, CRC status, channel
  index and a link to the decoded artifacts.

Demodulation results survive page refresh. The loader reads both flat
script-level metadata files and enriched nested `{id}/demodulation_report.json`
files; the enriched report takes precedence when both exist.

### IoT and Protocol Pipelines

| Pipeline ID | Band | Protocol | Description |
|---|---|---|---|
| `ook_433_remote` | 315 / 433 / 868 MHz | EV1527, PT2262 | Remote control chip period estimation, PWM decode, address/button extraction |
| `ook_ask_iot_sensor` | 315 / 433 / 868 MHz | Generic OOK/ASK | Generic ISM-band OOK sensor decode |
| `zigbee` | 2.4 GHz CH11–CH26 | IEEE 802.15.4 | O-QPSK chip correlation, MAC frame parse, PAN/address decode |
| `ble_advertising` | 2.402 / 2.426 / 2.480 GHz | BLE CH37–39 | GFSK discriminator, Access Address search, CRC-24 validation, AdvData TLV decode |
| `wifi_80211` | 2.4 / 5 GHz | IEEE 802.11 | Frame detection and header parse |
| `lora` | 433 / 868 / 915 MHz | LoRa/LoRaWAN | Chirp spread-spectrum decode |

## BLE Advertising Demodulation

The Demodulation tab includes a **BLE advertising channel test** that captures
channels 37 (2402 MHz), 38 (2426 MHz), and 39 (2480 MHz) sequentially and
attempts to decode advertising packets from each.

The BLE implementation is intentionally conservative. It can report RF activity,
burst candidates, recovered bitstream, Access Address matches and reconstructed
packet candidates. It does not mark a capture as demodulated unless CRC-24
validates on at least one packet. A result such as:

```text
Access Address: true
Packets: 8
CRC valid: 0
Final status: ble_candidate_not_decoded
```

means the signal is compatible with BLE advertising and candidate PDUs were
found, but no packet has been proven valid. In that state, addresses, PDU types
and payload hex are debugging candidates, not trusted decoded content.

The demodulation pipeline:

1. Capture IQ from the USRP at the target channel center frequency.
2. Run the GFSK frequency discriminator (instantaneous phase delta).
3. Apply a moving-average low-pass filter over one symbol period.
4. Downsample to one sample per symbol (1 Mbit/s BLE symbol rate).
5. Search for the 40-bit sync word (8-bit preamble `0xAA` + 32-bit
   Access Address `0x8E89BED6`) using NumPy correlation. Both polarities are
   tested.
6. De-whiten the PDU bits using a 7-bit LFSR (polynomial x^7+x^4+1) initialised
   with the BLE channel index.
7. Validate CRC-24 (polynomial x^24+x^10+x^9+x^6+x^4+x^3+x+1, init `0x555555`).
8. Decode the PDU header (type, TxAdd, length), advertiser MAC address, and
   AdvData TLV records (flags, local name, TX power, manufacturer-specific data).

The current decoder also performs burst-local symbol phase trials and small
bit-phase adjustments around Access Address offsets. This improves diagnostics
on live captures where each burst starts at a different sample phase. Candidate
fields remain untrusted until CRC passes.

Before CRC checking, each burst is scored against a 40-bit SYNC template
(preamble `0xAA` + Access Address `0x8E89BED6`) across all tested symbol phases.
Bursts where the best SYNC score across all phases is below 28/40 are rejected
without further processing. Real BLE advertising bursts score 32 or higher;
non-BLE 2.4 GHz sources (Zigbee, WiFi CH1 leakage, ISM wideband noise) score
24 or lower. This filter eliminates false-positive BLE candidates that otherwise
pass the energy and burst-detection stage.

Results are shown per channel in the test table and saved as
`decoded_packets.json` in the demodulation output directory.

Each BLE run writes these artifacts:

| Artifact | Purpose |
|---|---|
| `filtered_iq.cfile` | IQ used by the BLE analysis stage |
| `burst_candidates.json` | Detected burst windows and durations |
| `recovered_bitstream.bin` | Packed hard-bit stream recovered from GFSK discrimination |
| `access_address_search.json` | Correlation diagnostics for `0x8E89BED6` |
| `decoded_packets.json` | Candidate or CRC-valid decoded packets |
| `demodulation_report.json` | Run summary, status, metrics and warnings |
| `logs.txt` | Human-readable pipeline trace |

Valid BLE demodulation requires all of the following:

- `access_address_detected = true`
- `packets_decoded >= 1`
- `packets_crc_valid >= 1`
- `final_status = decoded_with_valid_crc`

**Limitations**: The pipeline requires a direct LOS signal with sufficient SNR.
The current backend uses a lightweight Python/NumPy GFSK discriminator and
symbol sampling path. It can reach Access Address and candidate PDU diagnostics
on strong captures, but CRC-valid packet recovery may still require a stronger
BLE physical layer implementation with real clock recovery
(Gardner/Mueller-Muller or GNU Radio `gr-ble`). It will not recover packets from
heavily faded or interfered channels, or from non-advertising BLE channels
(data channels use a different access address and hop sequence that this
pipeline does not implement).

## Dataset Builder And QC

Dataset Builder is the gate between raw acquisition and training data. It tracks
four independent states:

| Field | Meaning |
|---|---|
| `capture_quality` | Technical quality of the I/Q file: `valid`, `warning`, `doubtful` or `invalid` |
| `label_status` | Label evidence: `unlabeled`, `weak_label` or `strong_label` |
| `review_status` | Human review state: `needs_review`, `accepted`, `rejected` or `manual_override` |
| `training_readiness` | Training eligibility: `not_ready`, `candidate`, `ready_for_training` or `debug_only` |

`Recompute QC` analyzes the stored I/Q file, not the live preview. It recomputes
SNR, occupied bandwidth, peak offset, clipping, silence, burst activity,
duration, edge margin and profile-specific flags.

For marker-driven burst captures, the intended operator rule is simple:

- if the useful signal is inside the marked band,
- SNR is sufficient,
- clipping and sample drops are absent,
- the burst has usable duration,
- metadata is complete,
- and the label is confirmed when training requires ground truth,

then the capture can become `valid` and `ready_for_training`. Peak offset inside
the marked band is retained as a warning when relevant, but it is not by itself a
reason to reject a good marker-band burst capture.

## Labels And Band Profiles

The RF band profile knowledge base is stored in:

```text
backend/app/modules/rf_intelligence/band_profiles.json
```

Dataset Builder can use it to fill missing technical fields such as:

- `transmitter_label`
- `transmitter_class`
- `signal_type`
- `modulation_class`
- `protocol_family`
- `band_label`
- `profile_key`

These generated labels start as weak technical labels. They become strong labels
only after operator confirmation. Strong labels are required for strict
scientific training.

## RF Experiment Lab

RF Experiment Lab provides reproducible experimental workflows on top of curated
captures. It is separate from day-to-day live monitoring and capture.

Implemented experiment families:

| ID | Input | Purpose |
|---|---|---|
| E0 | Metadata and manifest checks | Dataset validation and traceability |
| E5 | Spectral features | Explainable baseline for signal or transmitter classification |
| E1 | Raw I/Q windows | 1D CNN-style raw I/Q fingerprinting experiments |
| E3 | Spectrogram/waterfall images | 2D time-frequency learning experiments |

Strict experiment runs use `scientific_strict` by default. Eligible captures must
be:

```text
label_status == strong_label
review_status == accepted
training_readiness == ready_for_training
capture_quality == valid
```

For exploratory runs, use `training_draft`. For plumbing tests only, use
`all_debug`.

## Runtime Settings

The `Settings` tab exposes the operational parameters that the application uses
for SDR startup, spectrum defaults, waterfall behavior, recording defaults,
demodulation defaults, frontend polling, RF Intelligence and Dataset Builder QC.

Settings are served by:

```text
GET  /api/runtime-settings
POST /api/runtime-settings
```

Saved values are written to:

```text
backend/app/infrastructure/persistence/storage/config/runtime_settings.json
```

The launcher reads this file on startup and exports the values into the backend
and frontend environments before starting the services. Most settings therefore
take effect after pressing `Save` in the UI and restarting the application.

Each setting includes:

- the affected tab or workflow,
- a short description,
- what changes when the value is modified,
- the active value and default value,
- the source of the value: `saved`, `env` or `default`,
- whether a restart is required,
- the allowed range when one exists,
- and the kind of limit.

Limit kinds:

| Kind | Meaning |
|---|---|
| `hardware` | Bounded by the SDR, host USB path, antenna path or UHD device support |
| `software` | Bounded by application performance, UI behavior or worker implementation |
| `scientific_policy` | Bounded by dataset quality policy, not by the radio hardware |

Software and scientific-policy limits are shown in red in the Settings tab.
Changing them can make the application more permissive, but it can also admit
bad data, hide weak signals, increase false detections or overload the host.

Operational examples:

| Setting | Typical reason to change |
|---|---|
| `UHD_DEVICE_ARGS` | Select a specific USRP with `serial=<serial>` or a network USRP with `addr=<ip>` |
| `DEFAULT_ANTENNA` | Use the correct receive input, for example `RX2` |
| `DEFAULT_CENTER_FREQUENCY_HZ` | Start the spectrum view on a known band |
| `DEFAULT_SAMPLE_RATE_HZ` / `DEFAULT_SPAN_HZ` | Capture a wider or narrower band by default |
| `DEFAULT_GAIN_DB` | Start with a safer gain for the current RF environment |
| `REAL_SDR_CONNECT_TIMEOUT` | Allow slow UHD initialization before declaring failure |
| `VITE_SPECTRUM_POLL_INTERVAL_MS` | Trade UI responsiveness against API/browser load |
| `QC_MIN_VALID_SNR_DB` | Tighten or relax the minimum SNR required for valid training captures |
| `QC_MAX_VALID_CLIPPING_PCT` | Control how much clipping is acceptable before QC rejects a capture |
| `RF_INTELLIGENCE_MIN_SNR_DB` | Tune weak-signal detection sensitivity |

Runtime settings do not bypass real hardware limits. If a USRP, USB controller,
driver, antenna path or host cannot support a requested value, UHD may still
reject it or streaming may become unstable. The UI documents configured limits;
the radio and host remain the final authority.

## Important Environment Variables

Most values in this table can now be edited from the `Settings` tab and saved to
`runtime_settings.json`. Direct environment variables are still useful for
automation, one-off launches or CI.

| Variable | Purpose |
|---|---|
| `RADIOCONDA_PYTHON` | Python executable used for GNU Radio/UHD tools |
| `UHD_DEVICE_ARGS` | UHD device selector such as `serial=...` or `addr=...` |
| `DEFAULT_CENTER_FREQUENCY_HZ` | Backend startup center frequency |
| `DEFAULT_SAMPLE_RATE_HZ` | Backend startup sample rate |
| `DEFAULT_SPAN_HZ` | Backend startup spectrum span |
| `DEFAULT_GAIN_DB` | Backend startup gain |
| `DEFAULT_ANTENNA` | Backend startup antenna |
| `DEFAULT_RBW_HZ` | Backend startup resolution bandwidth |
| `DEFAULT_VBW_HZ` | Backend startup video bandwidth |
| `DEFAULT_REFERENCE_LEVEL_DB` | Spectrum display reference level |
| `DEFAULT_NOISE_FLOOR_OFFSET_DB` | Display and RF Intelligence noise-floor offset |
| `DEFAULT_WATERFALL_HISTORY_SIZE` | Waterfall history rows retained in the UI |
| `DEFAULT_RECORDING_DURATION_SECONDS` | Default recording duration |
| `DEFAULT_FM_DEVIATION_HZ` | Default FM demodulation deviation |
| `DEFAULT_AUDIO_SAMPLE_RATE_HZ` | Default demodulated audio sample rate |
| `RF_MIN_CENTER_FREQUENCY_HZ` | Lowest center frequency accepted by safety checks |
| `RF_MAX_CENTER_FREQUENCY_HZ` | Highest center frequency accepted by safety checks |
| `RF_MIN_SAMPLE_RATE_HZ` | Lowest sample rate accepted by safety checks |
| `RF_MAX_SAMPLE_RATE_HZ` | Highest sample rate accepted by safety checks |
| `RF_MAX_SPAN_HZ` | Largest span accepted by safety checks |
| `RF_MIN_GAIN_DB` | Lowest manual gain accepted by safety checks |
| `RF_MAX_GAIN_DB` | Highest manual gain accepted by safety checks |
| `REAL_SDR_CONNECT_TIMEOUT` | Timeout for SDR connection checks |
| `REAL_SDR_FPS` | Live spectrum worker frame rate |
| `REAL_SDR_MAX_FFT_SIZE` | Maximum FFT size accepted by the live SDR worker |
| `VITE_APP_SYNC_INTERVAL_MS` | Frontend background sync interval |
| `VITE_SPECTRUM_POLL_INTERVAL_MS` | Frontend spectrum polling interval |
| `VITE_WATERFALL_POLL_INTERVAL_MS` | Frontend waterfall polling interval |
| `VITE_RADIOCONDA_PYTHON` | Frontend copy of the SDR Python path injected by the launcher |
| `QC_MIN_VALID_SNR_DB` | Minimum SNR for a valid Dataset Builder capture |
| `QC_MAX_VALID_CLIPPING_PCT` | Maximum clipping percentage for a valid capture |
| `QC_MAX_SILENCE_PCT` | Maximum silence percentage before QC warnings |
| `RF_INTELLIGENCE_THRESHOLD_OFFSET_DB` | Detection threshold above the estimated noise floor |
| `RF_INTELLIGENCE_MIN_SNR_DB` | Minimum SNR for RF Intelligence candidates |

## Model Formats And Export

Spectrum Lab trains and saves three kinds of model artifacts:

| Artifact | Extension | Contents | Training path |
|---|---|---|---|
| PyTorch checkpoint | `.pt` | `model_state_dict`, `device_to_label`, `window_size`, `stride`, `embedding_dim` | E1 CNN 1D, E3 CNN 2D, operational fingerprinting (`best_model.pt`) |
| scikit-learn model | `.pkl` | `{"model_name", "model", "feature_names"}` | E5 Logistic Regression, Random Forest, SVM RBF, KNN |
| NumPy softmax | `.npz` | Weight matrix `W`, bias `b`, label array, feature mean/scale | RF Signal Understanding `numpy_softmax_regression` |

Each training run also writes:

```text
training_config.json        hyperparameters and dataset fingerprint
label_schema.json           int → class name mapping
normalization_params.json   canonical mean and RMS normalization used during preprocessing
split_strategy.txt          group-disjoint split method applied
dataset_manifest_path.txt   path to the RFExperimentDatasetV1 manifest used
```

### Export Options

PyTorch `.pt` checkpoints can be exported to:

- **ONNX** via `torch.onnx.export` — for cross-platform runtime inference (ONNX Runtime, TensorRT, mobile).
- **TorchScript** via `torch.jit.trace` — for embedded or C++ deployment.
- **SafeTensors** via `safetensors.torch.save_file` — for safe weight sharing without arbitrary code execution.

scikit-learn `.pkl` models can be exported to:

- **ONNX** via `skl2onnx.convert_sklearn` — for interoperability with ONNX Runtime.

NumPy `.npz` models are plain arrays and can be loaded and exported without any ML framework.

Export is not automated in the current UI. Use the result package path shown in the Models tab to locate the checkpoint and apply the export command externally.

## Troubleshooting

### Settings tab returns 404 for `/api/runtime-settings`

This means the frontend is newer than the backend process that is currently
running. Stop backend and frontend, then relaunch from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_unified.ps1
```

After restart, `GET /api/runtime-settings` should return the runtime settings
catalog. If it still returns 404, verify that the backend was started from this
repository checkout and not from an older copy.

### UHD does not find the USRP

Run:

```powershell
& "C:\Users\Usuario\radioconda\Library\bin\uhd_find_devices.exe"
& "C:\Users\Usuario\radioconda\Library\bin\uhd_usrp_probe.exe"
```

If discovery fails, check USB cable, USB 3.0 port, power, Windows driver, and
whether another process has the device open. For network devices, verify host IP
configuration and use `UHD_DEVICE_ARGS=addr=<ip>`.

### Capture is good but training readiness is not ready

Check Dataset Builder:

- `capture_quality` must be `valid` for strict training.
- `label_status` must be `strong_label`.
- `review_status` must be `accepted`.
- metadata must not have required missing fields.

For burst captures inside the marker band, offset warnings are informational.
They should not block readiness when the capture is otherwise good.

### E1, E3 or E5 refuses to train

The default eligibility policy is strict. Use Dataset Builder to promote
reviewed captures, or choose `training_draft` for exploratory work. Also verify
that the selected label field has at least two classes in the training split.

### The backend venv is broken

If `backend/venv/Scripts/python.exe` points to a missing WindowsApps Python
launcher, recreate the virtual environment with a real Python 3.10+ executable.

## Testing

Backend unit tests:

```powershell
cd backend
python -m pytest app/tests/unit -q
```

Frontend build:

```powershell
cd frontend
npm run build
```

## Documentation

Detailed subsystem documentation lives in:

- `backend/README.md`
- `backend/README_SETUP.md`
- `frontend/README.md`

The root README is intentionally kept as the project-level operating guide.
