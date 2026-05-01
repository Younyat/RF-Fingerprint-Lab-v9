# RF Experiment Lab validation notes

The FastAPI backend is documented to run from `backend\venv\Scripts\python.exe`, with `RADIOCONDA_PYTHON` used for GNU Radio/UHD subprocesses. In this workspace, `backend\venv\Scripts\python.exe` currently points at a missing WindowsApps Python 3.12 executable and cannot start.

Runtime validation for the RF Experiment Lab integration should therefore use:

```powershell
$env:PYTHONPATH="backend"
$env:RADIOCONDA_PYTHON="C:\Users\Usuario\radioconda\python.exe"
& "C:\Users\Usuario\radioconda\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Validated interpreter:

```text
C:\Users\Usuario\radioconda\python.exe
```

This interpreter has the required backend dependencies used by the RF Experiment Lab validation layer (`pydantic`, `numpy`, `scipy`). Optional experiment dependencies such as `h5py`, `torch` or `sklearn` are treated as optional and reported through `GET /api/rf-experiment-lab/health`.

`pytest` is not installed in the current RadioConda interpreter, so the RF Experiment Lab integration test is also executable with the standard library:

```powershell
$env:PYTHONPATH="backend"
& "C:\Users\Usuario\radioconda\python.exe" -m unittest backend.app.tests.integration.test_rf_experiment_lab -v
```

The RF Experiment Lab is an optional backend module. It must not modify capture, live spectrum, waterfall, markers, Capture Lab, Dataset Builder, RF Intelligence, or RF Signal Understanding behavior.
