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
powershell -ExecutionPolicy Bypass -File .\scripts\run_dev.ps1 -UseRealSdr 1 -RadioCondaPythonPath "C:\Users\Usuario\radioconda\python.exe"
```

## Main UI Flow

1. Click `Connect USB`.
2. Click `Start`.
3. Tune frequency using `Center MHz`, `Span MHz`, `Start MHz`, or `Stop MHz`.
4. Use `Spectrum Left` and `Spectrum Right` to move across the spectrum without typing a new frequency.
5. Click the trace to create a marker.
6. Use `Peak` to mark the strongest visible signal.
7. Create M1 and M2 around the signal of interest.
8. Open `Demodulation`, select the mode, and click `Apply Demodulation`.

## Demodulation Workflow

The frontend sends the first two markers as the selected RF band. The backend captures that real band from the USRP-B200.

- `AM`, `FM`, and `WFM` results include an audio player and WAV download button.
- `ASK`, `FSK`, `PSK`, and `OOK` results expose IQ/metadata capture output for digital analysis.
- If fewer than two markers exist, the demodulation button stays disabled because the RF band is not defined.

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
