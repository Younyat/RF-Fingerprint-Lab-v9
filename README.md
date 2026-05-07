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
