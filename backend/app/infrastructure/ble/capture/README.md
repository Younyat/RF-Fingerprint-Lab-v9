# BLE capture module technical README

Audience: programmers maintaining the BLE-RFFI acquisition path.

This README is part of the project audit trail. Any meaningful change to this
module must update this file in the same work item: what changed, why it
changed, what scientific assumption it protects, and how it was verified.

## Module scope

This module owns the experimental USRP B200 IQ acquisition path used by the
BLE-RFFI stage-one workflow:

- SDR discovery and capability reporting.
- Capture request validation.
- Out-of-process execution of `backend/tools/ble_sdr_capture_worker.py`.
- Capture manifests, quality reports, live telemetry and terminal status.
- Qualification-only captures that prove acquisition stability before any BLE
  campaign capture is allowed.

It does not validate BLE demodulation, target identity, E4 ground truth,
dataset eligibility, or model training. Those remain separate gates.

## Main files

- `ble_capture_job_manager.py`: API-facing job manager, request validation,
  protocol-field augmentation, hash verification and capture listing.
- `ble_iq_capture_service.py`: subprocess boundary and RadioConda runtime
  environment for SoapySDR/UHD.
- `ble_sdr_device_service.py`: SDR probe and B200 device identity handling.
- `ble_capture_routes.py`: FastAPI routes for devices, jobs, live frames and
  metadata.
- `backend/tools/ble_sdr_capture_worker.py`: real acquisition worker. It is
  deliberately outside the FastAPI process.

## Scientific constraints

The platform must not confuse a file with the right size with a scientifically
valid acquisition. A capture is not acceptable for later BLE-RFFI evidence if
any of these conditions fail:

- expected samples equal actual samples;
- expected file size equals actual file size;
- `overflow_count == 0`;
- `input_discontinuities == 0`;
- `short_read_count == 0`;
- `write_error_count == 0`;
- `writer_queue_overrun_count == 0`;
- `hash_status == VERIFIED`;
- `metadata_status == COMPLETE`.

Qualification captures are technical evidence only:

```text
execution_purpose = ACQUISITION_QUALIFICATION
scientific_campaign_member = false
dataset_eligible = false
qualification_only = true
```

They must not count as positives, negatives, campaign conditions, Dataset
Studio material, or training readiness.

## Acquisition and persistence design

The critical acquisition sequence is:

```text
UHD receive
-> preallocated buffer
-> bounded queue
-> dedicated writer
-> file close
-> size verification
-> post-capture hash
-> terminal manifest
```

The UHD receive loop must not wait for:

- disk writes;
- SHA-256 calculation;
- frontend/live JSON serialization;
- large manifest writes;
- BLE decoding;
- correlation;
- dataset/example generation.

Telemetry is allowed only when explicitly enabled. With
`ui_polling_mode = disabled`, the worker must not write `live.json` from the
critical loop.

## Format fields

Each diagnostic or qualification capture records the three distinct format
layers:

```text
cpu_format
otw_format
file_format
bytes_per_cpu_sample
bytes_per_wire_sample
bytes_per_file_sample
conversion_enabled
```

This prevents a clean `ci16_le` run from being misread as proof that only disk
size changed. It may also change USB payload, host copies, memory pressure, or
conversion behavior, depending on the SDR driver path.

Current protocol remains:

```text
protocol_sample_format = cf32_le
protocol_revision = qualification-rev1 / actual campaign revision
```

Do not silently switch the campaign to `ci16_le`. If `ci16_le` is ever adopted,
create a new protocol revision, new preprocessing contract, new qualification
profile, and rerun all qualification gates.

## Writer instrumentation

Terminal manifests and quality reports must include writer and host metrics:

```text
writer_thread_mode
writer_queue_capacity_bytes
writer_queue_high_watermark_bytes
writer_queue_overrun_count
maximum_buffer_occupancy
write_block_size_bytes
write_call_count
mean_write_latency_ms
maximum_write_latency_ms
measured_write_throughput_bytes_s
memory_copy_count_per_block
storage_target
storage_free_bytes
hash_during_capture
manifest_during_capture
fsync_during_capture
cpu_usage_mean
cpu_usage_max
process_cpu_usage_mean
memory_usage_max
```

If a loss occurs, record the most specific supported correlation:

```text
writer_queue_full
write_latency_spike
buffer_exhaustion
host_receive_overrun
unknown
```

Do not invent a root cause when the instrumentation cannot isolate it.

## USB3 diagnostic history

Earlier B200-only qualification attempts under the old path produced correct
file sizes but overflows/discontinuities. After moving the B200 to USB3 and
instrumenting the writer, the controlled diagnostic matrix was repeated.

Valid matrix after disabling live writes in the critical loop:

| Run group | Profile | Result |
|---|---|---|
| B1-B3 | `cf32_le`, no persistence | 40,000,000 samples, zero losses |
| C1-C3 | `cf32_le`, persistence, 320,000,000 bytes | zero losses, hash verified |
| E1-E3 | `ci16_le`, persistence, 160,000,000 bytes | zero losses, hash verified |

Interpretation:

```text
ACQUISITION_DIAGNOSTIC = COMPLETED
CF32_PERSISTENCE_DIAGNOSTIC_PASSED = true
ROOT_CAUSE_PRIOR_LOSSES = NOT_FULLY_ISOLATED
```

The prior losses must not be attributed to one single cause because USB mode,
writer design, instrumentation, and live telemetry behavior changed during the
same stabilization cycle.

## Acquisition qualification result

After the diagnostic matrix, three consecutive B200-only qualification
captures were executed with the scientific profile:

```text
sample_format = cf32_le
sample_rate_sps = 4000000
duration_seconds = 10
center_frequency_hz = 2402000000
bandwidth_hz = 2000000
antenna = RX2
gain_db = 20
usb_mode = USB 3
expected_samples = 40000000
expected_file_size_bytes = 320000000
```

All three passed:

| Capture | Samples | File size | Losses | Hash |
|---|---:|---:|---|---|
| `BLE-IQ-ACQQUAL-Q1-af246b260971` | 40,000,000 | 320,000,000 | 0 overflow / 0 discontinuity | VERIFIED |
| `BLE-IQ-ACQQUAL-Q2-6e85a5ccc574` | 40,000,000 | 320,000,000 | 0 overflow / 0 discontinuity | VERIFIED |
| `BLE-IQ-ACQQUAL-Q3-e3b8f324c709` | 40,000,000 | 320,000,000 | 0 overflow / 0 discontinuity | VERIFIED |

Current gate interpretation:

```text
ACQUISITION_QUALIFICATION = PASSED_3_CONSECUTIVE
HYBRID_CONCURRENCY_QUALIFICATION = UNLOCKED_NEXT_ONLY
S001-POS = BLOCKED
S001-NEG = BLOCKED
DATASET = BLOCKED
TRAINING = BLOCKED
```

Only the next hybrid concurrency qualification is unlocked. Do not jump
directly to SensorTag search, positive capture, negative control, Dataset
Studio, or training.

## Hybrid concurrency qualification result

After the B200-only qualification passed, three Windows-BLE-plus-B200
qualification captures were executed. These runs test only whether the Windows
BLE scanner and the USRP B200 acquisition path can run concurrently for the
same 10-second qualification profile without introducing B200 sample loss.

They do not verify SensorTag identity, E4 ground truth, CRC validity,
Windows-B200 correlation, dataset eligibility, or model readiness.

Frozen acceptance threshold:

```text
minimum_concurrency_overlap_seconds = 9.0
```

All three hybrid runs passed:

| Capture | Scan session | Samples | File size | Losses | Overlap | Windows callbacks / unique |
|---|---|---:|---:|---|---:|---:|
| `BLE-IQ-HYBQUAL-H1-6d97ec1435eb` | `BLE-HYBRID-QUAL-H1-6d97ec1435eb` | 40,000,000 | 320,000,000 | 0 overflow / 0 discontinuity | 17.00 s | 743 / 57 |
| `BLE-IQ-HYBQUAL-H2-f77ffff0ceb5` | `BLE-HYBRID-QUAL-H2-f77ffff0ceb5` | 40,000,000 | 320,000,000 | 0 overflow / 0 discontinuity | 17.00 s | 687 / 55 |
| `BLE-IQ-HYBQUAL-H3-e86f90fa5ab6` | `BLE-HYBRID-QUAL-H3-e86f90fa5ab6` | 40,000,000 | 320,000,000 | 0 overflow / 0 discontinuity | 17.00 s | 628 / 55 |

Current gate interpretation:

```text
HYBRID_CONCURRENCY_QUALIFICATION = PASSED_3_CONSECUTIVE
qualification_profile_matches_campaign = true
S001-POS = UNLOCKED_NEXT_ONLY
S001-NEG = BLOCKED
DATASET = BLOCKED
TRAINING = BLOCKED
```

The negative control remains blocked until a later S001-POS run is accepted
and eligible. These hybrid qualification runs remain `qualification_only`,
`scientific_campaign_member = false`, and `dataset_eligible = false`.

## Verification commands

Compile the worker with the same Python runtime used for SoapySDR/UHD:

```powershell
C:\Users\Usuario\radioconda\python.exe -m py_compile backend/tools/ble_sdr_capture_worker.py
```

Probe the B200 with the RadioConda environment:

```powershell
$runtime='C:\Users\Usuario\radioconda'
$env:PATH=($runtime+'\Library\bin')+';'+($runtime+'\Scripts')+';'+$runtime+';'+(Join-Path $env:SystemRoot 'System32')
$env:SOAPY_SDR_PLUGIN_PATH=$runtime+'\Library\lib\SoapySDR\modules0.8'
& "$runtime\python.exe" backend/tools/ble_sdr_capture_worker.py devices
```

Expected B200 evidence includes serial `E3R04Z1B2` and UHD stderr text
containing `Operating over USB 3`.

## Developer rule for future changes

When modifying this module, update this README with:

- the technical change;
- the scientific reason;
- the gate or status affected;
- the artifact IDs or tests used for verification;
- any limitation or claim boundary that remains.

This prevents future work from relying on memory, chat history, or ambiguous
dashboard state.
