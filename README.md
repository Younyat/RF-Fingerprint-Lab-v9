# SpectraEase - RF Spectrum Analyzer

SpectraEase is a web-based RF spectrum analyzer for real SDR hardware. The current development target is an **Ettus Research USRP-B200** connected over USB and accessed through **UHD/GNU Radio** using the RadioConda Python environment.

The application is built with a FastAPI backend and a React/TypeScript frontend. It visualizes live RF spectrum data captured from the device, exposes analyzer-style controls, and supports real capture workflows.

## Current Hardware Path

- Device: **USRP-B200 from Ettus Research**
- Driver/runtime path: **UHD + GNU Radio**
- Python runtime for SDR tools: **RadioConda**
- Default antenna: `RX2`
- Default center frequency: `89.4 MHz`
- Default sample rate/span: `2 MS/s`
- Default gain: `20 dB`


## Features

- Live RF spectrum from the connected USRP-B200
- Analyzer controls for center frequency, start/stop, span, RBW, VBW, reference level, gain, detector mode, and averaging
- Spectrum pan controls to move the tuned window left or right without typing a new frequency
- Marker creation on the trace with frequency and interpolated signal level
- Marker delta readout between the first two markers
- Marker-band demodulation using M1 and M2 as RF limits
- AM/FM/WFM demodulation with WAV audio playback and export from the dashboard
- ASK/FSK/PSK/OOK marker-band IQ capture with metadata export for digital analysis
- Modulated signal analysis tab for marker-limited IQ dataset capture
- Guided `Capture Lab` safety checks for bandwidth, duration, and invalid frequency windows before launching IQ acquisition
- Persistent transparent execution overlay for SDR operations and ML jobs (training, retraining, validation, prediction) that stays visible while navigating between tabs without blocking the interface
- Live marker-band QC preview with peak, noise floor, SNR, and peak frequency before recording
- Automatic RadioConda Python propagation to `Validation` and `Inference` so `python_exe` appears prefilled by default
- Persistent `.cfile` and `.iq` capture libraries for replay workflows and AI model training datasets
- Automatic local peak markers
- Marker dragging directly on the spectrum canvas
- Peak marker detection
- Trace statistics: mean, maximum, minimum, and standard deviation
- CSV export for trace points
- PNG export for the current spectrum canvas
- Mouse-wheel zoom on spectrum span
- Crosshair cursor readout with frequency and level
- Trace modes: Clear/Write, Average, Max Hold, Min Hold, and Video Average
- Detector modes: Sample, RMS, Average, Peak, Max Hold, Min Hold, and Video
- Display controls for reference level, dB/div, offset, and color scheme
- Basic SCPI-style REST command endpoint for external control
- Device status panel showing connection state, driver, sample rate, gain, center, span, start, and stop
- Recording/session screens for capture management
- FastAPI REST API with OpenAPI docs
- React/Vite frontend with canvas-based spectrum rendering

## What The Platform Offers

SpectraEase combines RF acquisition, dataset curation, and RF fingerprinting workflows in one browser-based laboratory interface. It is designed for operators who need to move from live spectrum observation to reproducible machine-learning experiments without changing tools.

Main capabilities:

- Live RF monitoring with analyzer-style controls, markers, measurements, and spectrum/waterfall visualization.
- Marker-driven RF capture for focused IQ acquisition around signals of interest.
- Capture Lab workflows for generating train, validation, and prediction datasets with metadata and quality checks.
- Dataset Builder for reviewing captures, assigning splits, and keeping the fingerprinting registry consistent.
- Remote model training and retraining with persistent job tracking across navigation.
- Validation workflows for evaluating trained models against curated validation captures.
- Prediction/inference workflows that produce structured reports with confidence, profile distances, vote stability, and traceability.
- Model registry for inspecting current and historical RF fingerprinting artifacts.
- Non-blocking transparent execution messaging for long-running operations, so users can keep using the application while jobs continue.
- Unified backend API for SDR control, capture management, demodulation, fingerprinting, MLOps, and model reporting.

The execution overlay is intentionally global: if a training, retraining, validation, or prediction job is running, the message remains visible when moving from one page to another, survives refresh through the stored job id, and disappears automatically only when the backend reports that the job has finished. The same transparent non-blocking pattern is used for capture, SDR operations, and MLOps executions so long-running work never traps the operator on one tab.


## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | FastAPI, Python |
| Frontend | React 18, TypeScript, Vite |
| SDR | UHD, GNU Radio, RadioConda |
| Device | Ettus Research USRP-B200 |
| Storage | JSON/file-based project storage |

## Run On Windows

Use PowerShell from the project root:

```powershell
cd C:\path\to\spectrum-lab

$env:DEFAULT_CENTER_FREQUENCY_HZ="89400000"
$env:DEFAULT_SAMPLE_RATE_HZ="2000000"
$env:DEFAULT_GAIN_DB="20"
$env:DEFAULT_ANTENNA="RX2"
$env:UHD_DEVICE_ARGS=""

powershell -ExecutionPolicy Bypass -File .\scripts\run_dev.ps1 -UseRealSdr 1 -RadioCondaPythonPath "<radioconda-python-path>"
```

Arranque unificado recomendado para la plataforma fusionada:

```powershell
cd C:\path\to\spectrum-lab
powershell -ExecutionPolicy Bypass -File .\start_unified.ps1
```

Si quieres pasar explícitamente el usuario y la IP del entrenamiento remoto, usa:

```powershell
cd C:\path\to\spectrum-lab
powershell -ExecutionPolicy Bypass -File .\start_unified.ps1 -RemoteUser "<ssh-user>" -RemoteHost "<training-host>"
```

Esos valores quedan además precargados en la pestaña `Training`.
El mismo arranque propaga también `RadioCondaPythonPath` al frontend para que `Validation` e `Inference` muestren `python_exe` ya detectado por defecto.
Si quieres precargar también la activación del entorno remoto clásico, usa `-RemoteVenvActivate "<remote-venv-activate-path>"` al arrancar con `run_dev.ps1`.

Ese comando levanta en una sola orden:

- backend FastAPI unificado,
- frontend Vite,
- monitor SDR en vivo,
- Capture Lab,
- Dataset Builder,
- Training,
- Retraining,
- Validation,
- Inference,
- Models.

Polling frontend-backend por defecto:

- `App sync` (`/api/device/status`, `/api/recordings/`, `/api/sessions/`, `/api/presets/`): `5000 ms`
- `Spectrum`: `100 ms`
- `Waterfall`: `100 ms`

Puedes sobrescribirlos al arrancar sin tocar código:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_dev.ps1 `
  -UseRealSdr 1 `
  -RadioCondaPythonPath "<radioconda-python-path>" `
  -AppSyncIntervalMs 10000 `
  -SpectrumPollIntervalMs 250 `
  -WaterfallPollIntervalMs 400
```

En Linux/macOS con `run_dev.sh`:

```bash
APP_SYNC_INTERVAL_MS=10000 SPECTRUM_POLL_INTERVAL_MS=250 WATERFALL_POLL_INTERVAL_MS=400 bash scripts/run_dev.sh
```

Then open:

- Frontend: `http://localhost:5173`
- Backend API: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`

## Basic Workflow

1. Connect the USRP-B200 over USB.
2. Start the app with `run_dev.ps1` and `-UseRealSdr 1`.
3. Open the frontend.
4. Click `Connect USB`.
5. Click `Start`.
6. Tune center/span or start/stop from the controls.
7. Use `Spectrum Left` and `Spectrum Right` to move across the band.
8. Click the spectrum to add markers with frequency and signal level.
9. Open `Demodulation` to demodulate or capture the RF band between M1 and M2.
10. Open `Capture Lab` to capture IQ for `train`, `val`, or `predict`.
11. Use `Dataset Builder` to accept, reject, or mark the imported capture as doubtful before using it in ML workflows.
12. Continue in `Training`, `Validation`, or `Inference` according to the split assigned during capture.

## Application Screenshots

### Live Spectrum View

The main spectrum view shows the live RF trace from the USRP-B200 with analyzer controls, marker placement, cursor readout, and export options.

![Live RF spectrum view with analyzer controls and markers](readme_img/spectrum_pic.png)

### Spectrum And Waterfall View

The combined view splits the analyzer horizontally so the live spectrum trace and the waterfall history share the same center frequency and span.

![Combined spectrum and waterfall display using the same RF frequency window](readme_img/spectrum_waterfall.png)

## Marker-Band Demodulation

The `Demodulation` tab uses the first two spectrum markers as the selected RF band:

1. Create M1 and M2 on the spectrum trace.
2. Open `Demodulation`.
3. Select `AM`, `FM`, `WFM`, `ASK`, `FSK`, `PSK`, or `OOK`.
4. Set the capture duration.
5. Click `Apply Demodulation`.

For `AM`, `FM`, and `WFM`, the backend captures real IQ from the USRP-B200, demodulates it, generates a WAV file, and exposes it for playback/download in the dashboard.

For `ASK`, `FSK`, `PSK`, and `OOK`, the backend captures the marker-limited IQ plus metadata for later digital analysis/export. These modes do not currently generate dashboard audio.

Example FM workflow using a broadcast channel around `98.4 MHz` in Spain:

![FM demodulation workflow with generated audio output](readme_img/demodulation.png)

## Capture Lab IQ Acquisition

`Capture Lab` is the dataset-style IQ acquisition screen. It is not an audio demodulation screen. It supports two frequency-definition workflows:

- `Markers M1-M2`: capture exactly the band delimited by the first two spectrum markers
- `Custom Frequencies`: define `center + bandwidth` or `start + stop`, with the other pair recalculated automatically

Before recording, the operator also gets a live band-quality preview for the active window:

- peak level
- noise floor
- live SNR
- peak frequency

For each acquisition it creates:

- `.cfile` or `.iq`: raw complex64 IQ samples, selected by the user
- `.json`: metadata with center, start/stop, bandwidth, sample rate, gain, antenna, format, SHA256, label, modulation hint, and replay parameters

The same screen also lets the user declare the purpose of the capture from the beginning:

- `train`
- `val`
- `predict`

Generated files are stored under:

```text
backend/app/infrastructure/persistence/storage/recordings/modulated_signal_captures/
backend/app/infrastructure/persistence/storage/recordings/modulated_signal_iq_captures/
```

The UI always lists the files found in both directories and provides separate downloads for the RF data file and metadata.

If `Auto-import to fingerprinting` is enabled, the capture is also imported into the fingerprinting registry, where the backend computes quality-control metrics from the generated IQ file:

- estimated SNR
- occupied bandwidth
- peak frequency and offset
- burst start and end
- silence percentage
- clipping percentage

Those QC metrics are computed from the saved IQ file itself, not only from the live preview. This is why a capture that looked plausible live can still be rejected later if the stored burst is mostly silence, strongly off-center, or too weak once analyzed offline.

Example marker-band capture configured to generate `.cfile` or `.iq` datasets for replay, offline analysis, or AI model training:

![Marker-band cfile and IQ dataset generation workflow](readme_img/cfile_iqfile_generator_from_marker_BW.png)

## Capture Lab Guardrails And User Guidance

`Capture Lab` is intentionally conservative. It is designed for reproducible scientific acquisition, not for unlimited wideband dumping.

Current protective behaviors:

- It validates that the requested frequency window is coherent before starting capture.
- It blocks invalid `start/stop` combinations.
- It blocks invalid `center/bandwidth` combinations.
- It validates capture duration before starting the worker process.
- It warns in the UI when the requested bandwidth is too large for the controlled dataset workflow.
- It disables the capture button while the request is outside the safe operating window.
- It shows a global transparent activity overlay while connecting the SDR or recording IQ, without blocking navigation across tabs.

Current practical capture limit in `Capture Lab`:

- Maximum guided bandwidth for this workflow: about `10 MHz`

This limit exists so the tool does not silently push the USRP-B200 workflow into unstable or excessively heavy captures that often end in timeout, oversized IQ files, or unreliable scientific conditions.

## Understanding Common Messages

These messages are expected when the tool is protecting the workflow:

- `Create at least two markers first. M1 and M2 define the capture band.`
  Meaning: `Markers M1-M2` mode is selected but the spectrum does not yet contain two markers.

- `Enter a valid frequency window. Start must be lower than stop and both must be positive.`
  Meaning: the custom frequency definition is mathematically invalid.

- `Capture Lab supports up to 10.0 MHz of bandwidth in this workflow. Reduce the requested window.`
  Meaning: the requested capture is too wide for the safe guided acquisition path. Narrow the band or use a different workflow.

- `Duration must be between 0 and 120 seconds.`
  Meaning: the capture duration is outside the allowed range.

- `Connecting to SDR`
  Meaning: the SDR initialization is still in progress. UHD/GNU Radio can take a few seconds. The overlay is informative and does not lock the rest of the UI.

- `Capturing TRAIN/VAL/PREDICT dataset segment`
  Meaning: IQ acquisition is running and the hardware is being used exclusively for that operation.

- `Prediction Job: running`
  Meaning: `Inference` launched an asynchronous backend job and the UI is following its `job_id` until completion.

- `No report generated yet. If the job is still running, wait for completion. If it failed, inspect stderr above.`
  Meaning: the prediction report JSON does not exist yet or the job has not finished.

- `Python por defecto detectado: <radioconda-python-path>`
  Meaning: the frontend received the RadioConda runtime path from the launcher. In normal use you can keep this value as-is or leave the field empty and let the backend default apply.

- `UHD did not find the USRP-B200. Check the USB connection and make sure no other GNU Radio/UHD process is using the device.`
  Meaning: the radio is not reachable or another process already owns it.

- `timed out after 45.0 seconds`
  Meaning: the requested acquisition was too heavy or the worker did not finish in the expected time. Typical causes are excessive bandwidth, excessive sample rate, heavy host load, or UHD device contention.

Recommended operator reaction when an error appears:

1. Read whether the message is about frequency definition, bandwidth, duration, USB/UHD access, or timeout.
2. If it is a validation message, correct the parameters in `Capture Lab` before retrying.
3. If it is a hardware message, verify the USRP-B200 connection and ensure no other SDR process is running.
4. If it is a timeout, reduce bandwidth first, then reduce duration, and retry with a narrower and more controlled capture.

## Frontend Flow And Why Each Tab Exists

- `Mission Control`: explains the recommended end-to-end workflow and separates monitoring, acquisition, curation, and ML tasks.
- `Live Monitor`: used to tune, inspect the band, place markers, and verify the signal visually before capture.
- `Capture Lab`: controlled dataset acquisition. This is where the operator records `.cfile`/`.iq` and sets the purpose as `train`, `val`, or `predict`.
- `Dataset Builder`: dataset curation, not acquisition. It is used to inspect QC, accept/reject captures, and keep the registry scientifically consistent.
- `Training`: exports the current `train` registry into the internal `backend/app/infrastructure/persistence/storage/mlops/data/rf_dataset` dataset and then launches the remote training job.
- `Retraining`: rebuilds that internal training dataset and reruns training over the updated `train` registry.
- `Validation`: exports the current `val` registry into the internal `backend/app/infrastructure/persistence/storage/mlops/data/rf_dataset_val` dataset and evaluates only that curated split. The RadioConda Python appears prefilled by default.
- `Inference`: runs asynchronous prediction jobs on `predict` captures, polls the job automatically, and shows `stdout`, `stderr`, and the final report.
- `Models`: summarizes current model artifacts and readiness state.

## Training, Retraining, And Validation Prechecks

Before launching the internal RF fingerprinting pipeline, the unified dashboard now performs explicit prechecks and dataset export.

Training and retraining:

- rebuild `rf_dataset` automatically from the fingerprinting registry
- export only captures with `dataset_split = train` and `quality_review.status = valid`
- require at least `2` unique transmitters
- require exactly `1` `center_frequency_hz`
- require exactly `1` `sample_rate_hz`

Validation:

- rebuild `rf_dataset_val` automatically from the fingerprinting registry
- export only captures with `dataset_split = val` and `quality_review.status = valid`
- require at least `1` valid exported record with a real IQ file
- require exactly `1` `center_frequency_hz`
- require exactly `1` `sample_rate_hz`
- require a complete model directory with `best_model.pt`, `enrollment_profiles.json`, and `dataset_manifest.json`

Recommended value for `remote_venv_activate`:

- `<remote-venv-activate-path>`

That field is optional. If left empty, the remote launcher tries to create a fallback virtual environment on the remote host.

All ML lifecycle scripts now live directly inside:

```text
backend/app/infrastructure/scripts/
```

No second repository is required anymore for training, retraining, validation, or prediction.

Typical messages now shown by the UI:

- `Training requires at least 2 unique transmitters with dataset_split=train and quality_review.status=valid. Found 1: remote_001.`
- `Validation requires at least 1 capture with dataset_split=val and quality_review.status=valid.`
- `Validation center_frequency_hz does not match the trained model.`
- `python_exe not found: ...`

## Important Environment Variables

| Variable | Purpose |
|----------|---------|
| `DEFAULT_CENTER_FREQUENCY_HZ` | Initial tuned center frequency |
| `DEFAULT_SAMPLE_RATE_HZ` | Initial sample rate and spectrum span |
| `DEFAULT_GAIN_DB` | Initial RF gain |
| `DEFAULT_ANTENNA` | UHD antenna name, currently `RX2` |
| `UHD_DEVICE_ARGS` | Optional UHD device arguments |
| `RADIOCONDA_PYTHON` | Python executable with GNU Radio/UHD installed |
| `VITE_RADIOCONDA_PYTHON` | Frontend runtime copy of the RadioConda Python path, injected by `run_dev.ps1` |
| `REAL_SDR_FPS` | Spectrum worker frame rate, default `10` |
| `REAL_SDR_MAX_FFT_SIZE` | Maximum FFT size used to approach requested RBW, default `65536` |

The frontend can change the active analyzer settings at runtime. These variables only define startup defaults.

RBW is implemented by selecting an FFT size from the active sample rate and requested RBW. If the requested RBW would require more than `REAL_SDR_MAX_FFT_SIZE`, the backend uses the closest practical FFT size and reports the effective RBW in each spectrum frame. VBW is implemented as frame-to-frame video smoothing, so it is only meaningful at values near or below the live frame rate.

## SCPI-Style Control

Basic SCPI-style commands can be sent through:

```text
POST /api/spectrum/scpi
```

Supported examples:

```text
SENS:FREQ:CENT 89.4MHz
SENS:FREQ:SPAN 2MHz
DISP:TRAC:Y:RLEV 0dBm
DISP:TRAC:Y:SCAL:PDIV 10dB
```

## RF Safety Guardrails

The backend validates hardware-facing parameters before opening or retuning the USRP-B200:

| Limit | Default |
|-------|---------|
| Center frequency | `70 MHz` to `6 GHz` |
| Sample rate / span | `200 kS/s` to `61.44 MS/s` |
| Gain | `0 dB` to `60 dB` |
| RBW | `1 Hz` to `1 MHz` |
| VBW | `1 Hz` to `1 MHz` |

The default sample-rate ceiling follows the USRP-B200/B210 USB 3.0 host sample-rate specification for single-channel use. Practical sustained rates near `61.44 MS/s` depend on USB 3.0 controller quality, host load, channel count, and DSP load; B210 2x2 operation is lower. These limits can be overridden with `RF_MIN_CENTER_FREQUENCY_HZ`, `RF_MAX_CENTER_FREQUENCY_HZ`, `RF_MIN_SAMPLE_RATE_HZ`, `RF_MAX_SAMPLE_RATE_HZ`, `RF_MAX_SPAN_HZ`, `RF_MIN_GAIN_DB`, and `RF_MAX_GAIN_DB`.

Software limits do not protect the RF input from excessive external power. Use appropriate antennas, attenuators, and RF front-end protection when connecting unknown signals.

## Project Structure

```text
spectrum-lab/
  backend/
    app/
      config/
      domain/
      application/
      infrastructure/
        scripts/
    tools/
      capture_and_demodulate_fm.py
      spectrum_stream_worker.py
      wfm_receiver_qt.py
  frontend/
    src/
      app/
      domain/
      presentation/
      shared/
  scripts/
    run_dev.ps1
    run_dev.sh
    init_project.sh
```
