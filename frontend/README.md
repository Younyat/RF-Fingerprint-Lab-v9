# SpectraEase Frontend

React/TypeScript frontend for SpectraEase, a real SDR spectrum analyzer currently used with an **Ettus Research USRP-B200**.

The frontend controls the FastAPI backend and displays live RF spectrum frames captured from the real device through UHD/GNU Radio. It does not rely on mock spectrum data in the active application flow.

## Features

- Live spectrum canvas
- Device connect/disconnect and start/stop controls
- Center/span tuning
- Start/stop frequency tuning
- Spectrum pan buttons: `Spectrum Left` and `Spectrum Right`
- Configurable pan step in MHz
- RBW, VBW, reference level, noise offset, detector mode, averaging, and gain controls
- dB/div scale control
- Trace mode selector: Clear/Write, Average, Max Hold, Min Hold, Video Average
- Color scheme selector
- Marker placement by clicking the trace
- Marker dragging on the trace
- Marker table with frequency and signal level
- Delta readout between M1 and M2
- Demodulation tab driven by the M1/M2 marker band
- AM/FM/WFM audio playback from demodulated real captures
- WAV export for analog demodulation results
- ASK/FSK/PSK/OOK marker-band capture controls
- `Capture Lab` for controlled `train` / `val` / `predict` IQ acquisition, intelligent RF pre/post-capture guidance, download, and safe deletion
- `Dataset Builder` for capture review and QC-driven acceptance/rejection
- `Training`, `Retraining`, `Validation`, `Inference`, and `Models` tabs for the unified RF fingerprinting flow
- RF canonicalization-aware validation that allows different original SDR center frequencies when canonical preprocessing is compatible
- Persistent transparent global operation overlay for capture, training, retraining, validation, and prediction jobs
- Persistent `.cfile` and `.iq` metadata capture list with separate downloads
- Live marker-band QC preview with peak, noise floor, SNR, and peak frequency
- Non-blocking global operation overlay for SDR connect and capture operations
- Peak marker button
- Auto peaks button
- Trace statistics panel
- Crosshair cursor readout
- Mouse-wheel zoom
- CSV export
- PNG export
- Device status panel
- Recording/session screens

## Tech Stack

- React 18
- TypeScript
- Vite
- Tailwind CSS
- Zustand
- Axios
- Lucide React

## Development

Install dependencies:

```bash
cd frontend
npm install
```

Run the frontend:

```bash
npm run dev
```

The frontend runs at:

```text
http://localhost:5173
```

The backend must be running at:

```text
http://localhost:8000
```

## Recommended Full App Startup

From the project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_dev.ps1 -UseRealSdr 1 -RadioCondaPythonPath "C:\path\to\radioconda\python.exe"
```


## Modular Tab Architecture

The frontend tabs are physically separated into one folder per module and composed through a small registry instead of being hardcoded separately in the router and sidebar. The module area lives in:

```text
frontend/src/app/modules/
  capture-lab/module.tsx
  dataset-builder/module.tsx
  training/module.tsx
  validation/module.tsx
  ...
  labModules.tsx
  types.ts
```

Each `module.tsx` declares:

- stable `id`
- display `name`
- primary `path`
- optional `aliases`
- sidebar `icon`
- React `element`
- `enabled` flag
- `showInNavigation` flag
- ordering metadata
- short functional description

`AppRouter` consumes `moduleRoutes` from `labModules.tsx`. `AppLayout` consumes `navigationModules` and `findModuleByPath`. This means a tab can be added, disabled, hidden from navigation, or removed from the active UI by changing that module's own `module.tsx`, without editing the router and sidebar separately.

Disabling a module should be done by setting `enabled: false` in its own folder. Hiding a module while keeping its route active should be done by setting `showInNavigation: false`. Existing aliases such as `/guided-capture` and `/modulated-analysis` are preserved under the Capture Lab module for compatibility.

## Main UI Flow

1. Click `Connect USB`.
2. Click `Start`.
3. Tune frequency using `Center MHz`, `Span MHz`, `Start MHz`, or `Stop MHz`.
4. Use `Spectrum Left` and `Spectrum Right` to move across the spectrum without typing a new frequency.
5. Click the trace to create a marker.
6. Use `Peak` to mark the strongest visible signal.
7. Create M1 and M2 around the signal of interest.
8. Open `Demodulation`, select the mode, and click `Apply Demodulation`.
9. Open `Capture Lab` to record the selected band as `.cfile` or `.iq` and assign it to `train`, `val`, or `predict`.
10. Use `Dataset Builder` to review QC and mark the imported record as `valid`, `doubtful`, or `rejected`.
11. Continue in `Training`, `Validation`, or `Inference` depending on the assigned split.

## UI Screens

<table>
  <tr>
    <td width="50%">
      <img src="../readme_img/spectrum_waterfall_v5.png" alt="Spectrum and waterfall workspace" width="100%">
      <br>
      <strong>Live Monitor</strong>
      <br>
      Spectrum, waterfall, analyzer controls, marker workflow, and device state in the primary operator view.
    </td>
    <td width="50%">
      <img src="../readme_img/spectrum_waterfall_active_rf_intelligence_v5.png" alt="RF Intelligence overlay in live monitor" width="100%">
      <br>
      <strong>RF Overlay</strong>
      <br>
      Live RF Intelligence detections rendered directly on top of the spectrum and waterfall workspace.
    </td>
  </tr>
  <tr>
    <td width="50%">
      <img src="../readme_img/demodulation.png" alt="Demodulation workflow" width="100%">
      <br>
      <strong>Demodulation</strong>
      <br>
      Marker-band AM/FM/WFM demodulation with generated audio playback and export.
    </td>
    <td width="50%">
      <img src="../readme_img/capture_lab.png" alt="Capture Lab workflow" width="100%">
      <br>
      <strong>Capture Lab</strong>
      <br>
      Dataset-oriented IQ acquisition with marker/custom windows, metadata, labels, and split selection.
    </td>
  </tr>
  <tr>
    <td width="50%">
      <img src="../readme_img/dataset_analyser.png" alt="Dataset Builder review workflow" width="100%">
      <br>
      <strong>Dataset Builder</strong>
      <br>
      QC-driven review, split assignment, and acceptance status before ML workflows.
    </td>
    <td width="50%">
      <img src="../readme_img/rf_intelligence_v5.png" alt="RF Intelligence console" width="100%">
      <br>
      <strong>RF Intelligence</strong>
      <br>
      Explainable detected RF objects with bandwidth, confidence, SNR, candidate family, and evidence notes.
    </td>
  </tr>
</table>

## Demodulation Workflow

The frontend sends the first two markers as the selected RF band. The backend captures that real band from the USRP-B200.

- `AM`, `FM`, and `WFM` results include an audio player and WAV download button.
- `ASK`, `FSK`, `PSK`, and `OOK` results expose IQ/metadata capture output for digital analysis.
- If fewer than two markers exist, the demodulation button stays disabled because the RF band is not defined.

## Capture Lab Workflow

`Capture Lab` is the acquisition screen for dataset generation. It can use:

- `Markers M1-M2`
- `Custom Frequencies` with synchronized `center + bandwidth` and `start + stop`

It creates dataset-style captures with:

- raw `.cfile` or `.iq` complex64 IQ samples, selected by the user
- `.json` metadata with frequency, bandwidth, sample rate, gain, antenna, label, modulation hint, SHA256, and replay parameters
- persistent listing of all generated files found on disk
- download buttons for the selected RF data file and metadata

It also shows a live QC preview for the selected capture band:

- peak level
- noise floor
- live SNR
- peak frequency

If auto-import is enabled, the capture is sent to the fingerprinting registry so later tabs can detect it by split.

## RF Fingerprinting Workflow In The UI

The ML tabs operate on curated registry captures rather than directly on arbitrary files. The expected flow is:

1. Capture raw `.cfile` or `.iq` in `Capture Lab`.
2. Import the capture into the fingerprinting registry.
3. Review QC in `Dataset Builder` and mark records as `valid`, `doubtful`, or `rejected`.
4. Assign each valid capture to `train`, `val`, or `predict`.
5. Launch `Training` or `Retraining`; the backend exports canonical I/Q automatically.
6. Launch `Validation`; selected validation captures are canonicalized with the trained model profile and checked for session leakage.
7. Use `Inference` for asynchronous prediction on `predict` captures.
8. Inspect `Models` for current model card, provenance, validation evidence, retraining history, and artifact readiness.

The UI no longer treats different original SDR `center_frequency_hz` values as an automatic validation blocker. It surfaces them as context while the backend enforces the scientifically relevant constraints: canonical preprocessing profile, canonical sample rate, canonical bandwidth, segment length, and train/validation session separation.

## Validation And Inference Python Default

When the frontend is started through `run_dev.ps1`, `python_exe` in `Validation` and `Inference` is prefilled from the same RadioConda path used by the backend launcher. In normal use the operator does not need to type that path manually.

## Inference Behavior

`Inference` launches prediction as an asynchronous job. The frontend now:

- follows the returned `job_id`
- polls job status automatically
- shows `stdout`
- shows `stderr`
- shows the final prediction report when the JSON is generated

## Safety Feedback

The backend enforces safety limits before applying settings to the USRP-B200. If a value is outside the configured range, the request fails with `400 Bad Request` and the UI shows the backend error instead of applying the setting.

## Project Structure

```text
src/
  app/
    router/
    services/
    store/
  domain/
    models/
    valueObjects/
  presentation/
    controllers/
    hooks/
    views/
  shared/
    constants/
    types/
    utils/
```

## Notes

- The frontend expects real SDR data from the backend.
- If the backend returns `real_sdr_error`, the UI should show the device/backend error instead of fake data.
- If changes are not visible while Vite is running, hard-refresh with `Ctrl+F5` or restart the dev script.
