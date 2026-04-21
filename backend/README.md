# SpectraEase Backend

FastAPI backend for the SpectraEase RF spectrum analyzer.

The current active hardware path uses a real **Ettus Research USRP-B200** through **UHD/GNU Radio**. The backend starts helper tools with the RadioConda Python executable and returns live spectrum frames captured from the device.

## Active Device Flow

- Driver reported by the API: `uhd_gnuradio`
- Device currently used: `USRP-B200 from Ettus Research`
- Capture source: real UHD/GNU Radio samples
- Default antenna: `RX2`
- Default center frequency: `89.4 MHz`
- Default sample rate/span: `2 MS/s`
- Default gain: `20 dB`

The active API does not generate mock spectrum data. If the device cannot be opened or no frame is available, the spectrum endpoint returns a real SDR error or pending state.

## Main Components

- `app/infrastructure/web/controllers/device_controller.py`
  - Connects/disconnects the real SDR flow
  - Starts/stops live spectrum streaming
  - Reports device status

- `app/infrastructure/web/controllers/spectrum_controller.py`
  - Serves live spectrum data
  - Updates center frequency, span, start/stop, RBW, VBW, reference level, detector mode, and averaging

- `app/infrastructure/web/controllers/demodulation_controller.py`
  - Captures the RF band selected by M1 and M2
  - Runs marker-band AM/FM/WFM audio demodulation
  - Stores demodulation metadata and WAV output for dashboard playback/export

- `app/infrastructure/web/controllers/modulated_signal_controller.py`
  - Captures marker-limited `.cfile` or `.iq` files for modulated-signal analysis
  - Persists metadata for replay workflows and AI datasets
  - Lists and serves generated IQ/metadata files from disk

- `app/infrastructure/sdr/real_spectrum_stream.py`
  - Manages the persistent spectrum worker process
  - Restarts the worker when tuning parameters change

- `tools/spectrum_stream_worker.py`
  - Opens the USRP through GNU Radio/UHD
  - Captures IQ samples
  - Produces FFT spectrum frames as JSON

## Run Backend Manually

The recommended development entrypoint is the project script:

```powershell
cd C:\Users\Usuario\Desktop\NICS\Spectum_lab\spectrum-lab

$env:DEFAULT_CENTER_FREQUENCY_HZ="89400000"
$env:DEFAULT_SAMPLE_RATE_HZ="2000000"
$env:DEFAULT_GAIN_DB="20"
$env:DEFAULT_ANTENNA="RX2"
$env:UHD_DEVICE_ARGS=""

powershell -ExecutionPolicy Bypass -File .\scripts\run_dev.ps1 -UseRealSdr 1 -RadioCondaPythonPath "C:\Users\Usuario\radioconda\python.exe"
```

If running only the backend, make sure `RADIOCONDA_PYTHON` points to the Python executable that has GNU Radio and UHD:

```powershell
$env:RADIOCONDA_PYTHON="C:\Users\Usuario\radioconda\python.exe"
cd backend
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Key API Endpoints

- `GET /api/device/status`
- `POST /api/device/connect`
- `POST /api/device/disconnect`
- `POST /api/device/stream/start`
- `POST /api/device/stream/stop`
- `POST /api/device/frequency`
- `POST /api/device/gain`
- `GET /api/spectrum/live`
- `POST /api/spectrum/center-frequency`
- `POST /api/spectrum/span`
- `POST /api/spectrum/start-stop`
- `POST /api/spectrum/rbw`
- `POST /api/spectrum/vbw`
- `POST /api/spectrum/reference-level`
- `POST /api/spectrum/noise-floor-offset`
- `POST /api/spectrum/detector-mode`
- `POST /api/spectrum/averaging`
- `POST /api/spectrum/scpi`
- `POST /api/demodulation/marker-band`
- `GET /api/demodulation/results`
- `GET /api/demodulation/results/{id}`
- `GET /api/demodulation/audio/{id}`
- `POST /api/modulated-signals/captures`
- `GET /api/modulated-signals/captures`
- `GET /api/modulated-signals/captures/{id}`
- `GET /api/modulated-signals/captures/{id}/iq`
- `GET /api/modulated-signals/captures/{id}/metadata`

OpenAPI docs are available at `http://localhost:8000/docs` when the backend is running.

## Marker-Band Demodulation

`POST /api/demodulation/marker-band` captures real IQ from the USRP-B200 between the two frequencies supplied by the frontend, normally M1 and M2.

Example body:

```json
{
  "start_frequency_hz": 89320000,
  "stop_frequency_hz": 89450000,
  "mode": "fm",
  "duration_seconds": 5
}
```

Supported modes:

- `am`, `fm`, `wfm`: capture IQ, generate WAV audio, expose `/api/demodulation/audio/{id}`
- `ask`, `fsk`, `psk`, `ook`: capture IQ and metadata for digital analysis/export

The backend applies the same RF safety checks used by spectrum tuning before opening the USRP-B200.

## Modulated Signal IQ Captures

`POST /api/modulated-signals/captures` captures the RF band between M1 and M2 as raw complex64 IQ plus JSON metadata. The request can choose `file_format` as `cfile` or `iq`.

Example body:

```json
{
  "start_frequency_hz": 89320000,
  "stop_frequency_hz": 89500000,
  "duration_seconds": 5,
  "file_format": "iq",
  "label": "device_01_signal_a",
  "modulation_hint": "fsk",
  "notes": "Capture for offline analysis and AI dataset generation"
}
```

Files are stored in:

```text
backend/app/infrastructure/persistence/storage/recordings/modulated_signal_captures/
backend/app/infrastructure/persistence/storage/recordings/modulated_signal_iq_captures/
```

Each metadata file includes capture identity, selected file format, frequency limits, center frequency, bandwidth, sample rate, gain, antenna, IQ format, sample count, file size, SHA256, label, modulation hint, notes, and replay parameters.

## Runtime Configuration

| Variable | Purpose |
|----------|---------|
| `RADIOCONDA_PYTHON` | Python executable with GNU Radio/UHD |
| `DEFAULT_CENTER_FREQUENCY_HZ` | Startup center frequency |
| `DEFAULT_SAMPLE_RATE_HZ` | Startup sample rate/span |
| `DEFAULT_GAIN_DB` | Startup gain |
| `DEFAULT_ANTENNA` | UHD antenna name |
| `UHD_DEVICE_ARGS` | Optional UHD device selector |
| `REAL_SDR_FPS` | Spectrum worker frame rate |

## RF Safety Guardrails

The backend rejects unsafe or invalid hardware-facing settings before they reach UHD:

| Parameter | Default software range |
|-----------|------------------------|
| Center frequency | `70 MHz` to `6 GHz` |
| Sample rate / span | `200 kS/s` to `10 MS/s` |
| Gain | `0 dB` to `60 dB` |
| RBW | `1 Hz` to `1 MHz` |
| VBW | `1 Hz` to `1 MHz` |

The safety status is also exposed through:

```text
GET /api/spectrum/safety-limits
```

These checks reduce accidental misconfiguration. They do not replace RF input protection; avoid injecting high-power signals directly into the USRP-B200 input.

## SCPI-Style Commands

Basic external-control commands are accepted through `POST /api/spectrum/scpi` with a JSON body:

```json
{ "command": "SENS:FREQ:CENT 89.4MHz" }
```

Supported commands:

- `SENS:FREQ:CENT <value>[Hz|kHz|MHz|GHz]`
- `SENS:FREQ:SPAN <value>[Hz|kHz|MHz|GHz]`
- `DISP:TRAC:Y:RLEV <value>[dB|dBm]`
- `DISP:TRAC:Y:SCAL:PDIV <value>dB`

## Troubleshooting

- Confirm the USRP-B200 is connected over USB.
- Confirm RadioConda can import `gnuradio` and `uhd`.
- Confirm the app was started with `-UseRealSdr 1`.
- Confirm `RADIOCONDA_PYTHON` points to `C:\Users\Usuario\radioconda\python.exe`.
- If `/api/spectrum/live` returns `real_sdr_pending`, wait for the first frame.
- If it returns `real_sdr_error`, check the error field and the backend terminal output.
