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

Intermediate gate interpretation immediately after B200-only qualification:

```text
ACQUISITION_QUALIFICATION = PASSED_3_CONSECUTIVE
HYBRID_CONCURRENCY_QUALIFICATION = UNLOCKED_NEXT_ONLY
S001-POS = BLOCKED
S001-NEG = BLOCKED
DATASET = BLOCKED
TRAINING = BLOCKED
```

At that intermediate point only the hybrid concurrency qualification was
unlocked. The current state after hybrid qualification is documented below.

## Hybrid concurrency qualification result

After the B200-only qualification passed, three Windows-BLE-plus-B200
qualification captures were executed. These runs test only whether the Windows
BLE scanner and the USRP B200 acquisition path can run concurrently for the
same 10-second qualification profile without introducing B200 sample loss.

They do not verify SensorTag identity, E4 ground truth, CRC validity,
Windows-B200 correlation, dataset eligibility, or model readiness.

Frozen acceptance threshold:

```text
minimum_rf_concurrency_overlap_seconds = 9.0
minimum_rf_concurrency_overlap_fraction = 0.90
```

The original dashboard value `concurrency_overlap_seconds = 17.00` was a
legacy job-interval overlap and included non-RF work such as setup, closing,
hashing or manifest handling. It is not a valid RF overlap metric because a
10-second acquisition cannot have more than 10 seconds of RF concurrency.

The corrected metric separates:

```text
b200_job_started_at
b200_job_finished_at
b200_rf_started_at
b200_rf_finished_at
windows_scan_started_at
windows_scan_finished_at
```

For future runs, `b200_rf_started_at` and `b200_rf_finished_at` are emitted by
the SDR worker around the sample reception interval. For the three existing
hybrid runs, the previous worker did not record the exact first-sample
timestamp. The RF overlap is therefore reconstructed from sample count and the
recorded scan envelope: Windows scanning started before the recorded B200 job
interval and finished after it, so the 10-second RF interval is fully covered
even though the exact first-sample timestamp was not present in the old
artifacts.

Corrected invariants:

```text
b200_rf_duration_seconds = actual_samples / sample_rate_sps = 10.0
0 <= rf_concurrency_overlap_seconds <= 10.0
0 <= rf_concurrency_overlap_fraction <= 1.0
```

All three hybrid runs pass the corrected RF-overlap gate:

| Capture | Scan session | Samples | File size | Losses | Overlap | Windows callbacks / unique |
|---|---|---:|---:|---|---:|---:|
| `BLE-IQ-HYBQUAL-H1-6d97ec1435eb` (`HCQ1`) | `BLE-HYBRID-QUAL-H1-6d97ec1435eb` | 40,000,000 | 320,000,000 | 0 overflow / 0 discontinuity | 10.00 s / 1.00 | 743 / 57 |
| `BLE-IQ-HYBQUAL-H2-f77ffff0ceb5` (`HCQ2`) | `BLE-HYBRID-QUAL-H2-f77ffff0ceb5` | 40,000,000 | 320,000,000 | 0 overflow / 0 discontinuity | 10.00 s / 1.00 | 687 / 55 |
| `BLE-IQ-HYBQUAL-H3-e86f90fa5ab6` (`HCQ3`) | `BLE-HYBRID-QUAL-H3-e86f90fa5ab6` | 40,000,000 | 320,000,000 | 0 overflow / 0 discontinuity | 10.00 s / 1.00 | 628 / 55 |

`HCQ1`, `HCQ2`, and `HCQ3` are aliases for the qualification runs only. The
old artifact identifiers are preserved. Future technical hybrid qualification
runs must use `HCQ*` naming because `H1`--`H3` are reserved for confirmatory
scientific hypotheses in the paper.

Windows callback count and unique observations are diagnostics of scanner
activity only. They are not target identity evidence, are not E4 evidence, and
must not be used to unlock a negative control.

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

This profile qualifies only the 10-second engineering qualification profile:

```text
QPROFILE-Z1B2-2402000000-4000000-2000000-cf32_le-RX2-G20-10S
```

The 120-second confirmatory campaign described in the paper is a different
experimental profile. It requires a new `qualification_profile_id` and a full
new acquisition plus hybrid concurrency requalification before it can be used
for scientific campaign captures.

## Estado cientifico y tecnico actual

El objetivo final del modulo no es obtener una accuracy alta ni entrenar un
clasificador aislado. El objetivo es construir una cadena BLE-RFFI trazable
que permita evaluar, dentro de un alcance declarado, si una emision BLE
capturada por el USRP B200 es compatible con la unidad fisica enrolada o con
la poblacion alternativa evaluada.

La cadena prevista es:

```text
unidad fisica registrada
-> protocolo congelado
-> receptor cualificado
-> concurrencia Windows BLE-B200 cualificada
-> ground truth valido
-> capturas positivas aceptadas
-> controles negativos aceptados
-> dataset trazable
-> splits sin fuga
-> entrenamiento
-> calibracion y umbral congelados
-> validacion independiente
-> decision con posibilidad de abstencion
-> trazabilidad hasta el I/Q original
-> despliegue controlado en Live Monitor
```

El modelo final debe usar solo informacion derivada del I/Q del B200. Windows
BLE se usa para observacion logica, ground truth, asociacion temporal y
etiquetado. No puede ser entrada del modelo: direccion BLE, `local_name`,
GATT, payload, manufacturer data ni identidad reportada por Windows.

Estado actual:

```text
ACQUISITION_DIAGNOSTIC = COMPLETED
ACQUISITION_QUALIFICATION = PASSED_3_CONSECUTIVE
HYBRID_CONCURRENCY_QUALIFICATION = PASSED_3_CONSECUTIVE
qualification_profile_matches_campaign = true

qualification_profile_id =
QPROFILE-Z1B2-2402000000-4000000-2000000-cf32_le-RX2-G20-10S

receiver_serial = E3R04Z1B2
usb_mode = USB_3
center_frequency_hz = 2402000000
sample_rate_sps = 4000000
analog_bandwidth_hz = 2000000
cpu_format = cf32
file_format = cf32_le
antenna = RX2
gain_db = 20
duration_seconds = 10
disk_persistence_enabled = true

Etapa actual = PREPARATION_FOR_POSITIVE_PILOT
CURRENT_STAGE = PREPARATION_FOR_POSITIVE_PILOT
NEXT_OPERATOR_ACTION = PREPARE_AND_EXECUTE_S001_POS
NEXT_HARDWARE_ACTION = POSITIVE_PILOT_ONLY
Siguiente ejecucion de hardware = C001 / S001-POS
execution_purpose = POSITIVE_PILOT
S001-POS = UNLOCKED_NEXT_ONLY
S001-NEG = BLOCKED
DATASET = BLOCKED
TRAINING = BLOCKED
LIVE_MODEL = BLOCKED
Campana de 120 s = NOT_QUALIFIED
ROOT_CAUSE_PRIOR_LOSSES = NOT_FULLY_ISOLATED
```

Se ha demostrado solo para el perfil anterior que el B200 puede adquirir 10 s
de I/Q por USB 3, persistir `cf32_le` con 40,000,000 muestras y 320,000,000
bytes, cerrar sin overflows, discontinuidades, short reads, write errors ni
queue overruns, verificar hashes, completar manifiestos y funcionar
concurrentemente con Windows BLE con `rf_concurrency_overlap_seconds = 10.0`
y `rf_concurrency_overlap_fraction = 1.0`.

Estas cualificaciones no demuestran identidad del SensorTag, ground truth E4,
fingerprinting valido, separacion target-background, dataset valido, modelo
entrenable, rendimiento temporal, generalizacion, capturas estables de 120 s
ni comparacion entre unidades del mismo modelo.

### Objetivo de la siguiente etapa

La positiva piloto `C001 / S001-POS` debe demostrar conjuntamente:

- la unidad fisica correcta fue seleccionada;
- el operador confirmo la preparacion fisica;
- Windows BLE observo el objetivo;
- el preflight seguia vigente al iniciar la captura;
- el B200 realizo una adquisicion limpia;
- el decoder obtuvo paquetes CRC validos;
- la asociacion Windows-B200 produjo evidencia suficiente;
- la identidad del objetivo no quedo ambigua;
- los artefactos quedaron integros;
- la sesion puede considerarse elegible para dataset.

La positiva separa observacion minima E4 de aceptacion cientifica para
dataset:

```text
E4_MINIMAL_OBSERVED =
unique_target_crc_packets_with_strong_association >= 1

E4_ACCEPTED_FOR_DATASET =
unique_strong_only_target_crc_packets >= K_campaign
y todos los demas gates de identidad, calidad e integridad aprobados

minimum_unique_target_packets_for_e4_observation = 1
minimum_unique_target_packets_for_dataset_acceptance = 3
quality_gate_version = ble-rffi-positive-pilot-gate-v2
```

Tres paquetes unicos CRC validos con asociacion fuerte no conflictiva
constituyen un minimo de redundancia para esta prueba piloto de 10 s. Este
umbral es un criterio de ingenieria del piloto, no una estimacion estadistica
de suficiencia general. No se reutiliza automaticamente para capturas de
120 s, campanas same-model, paper definitivo, otras tasas de advertising,
otras duraciones ni otros canales.

Antes de iniciar hardware para `S001-POS`, el backend congela y registra el
contrato exacto de ejecucion. Esta congelacion ocurre antes de crear la sesion
activa y antes de arrancar Windows BLE o el B200. El manifiesto debe contener:

```text
source_repository_commit
source_working_tree_status
source_working_tree_dirty
source_working_tree_diff_sha256
protocol_manifest
protocol_manifest_sha256
protocol_hash
protocol_frozen_at_utc
execution_freeze
quality_gate_version = ble-rffi-positive-pilot-gate-v2
qualification_profile_id =
QPROFILE-Z1B2-2402000000-4000000-2000000-cf32_le-RX2-G20-10S
```

Si el arbol de trabajo no esta limpio, no se oculta: se registra
`source_working_tree_status = DIRTY_RECORDED` y se guarda el hash del diff
tracked. Esto no sustituye a un commit limpio para publicacion definitiva,
pero evita que una ejecucion piloto quede sin trazabilidad tecnica.

Para `execution_purpose = POSITIVE_PILOT`, el backend rechaza cambios criticos
con `REQUALIFICATION_REQUIRED` si no coinciden canal 37, 10 s, ganancia 20 dB,
`quality_gate_version` o el `qualification_profile_id` cualificado. No se debe
corregir manualmente un manifiesto despues de observar resultados.

La interfaz de esta etapa debe funcionar como un asistente numerado para un
operador sin conocimientos de BLE, SDR, RFFI, ground truth o procesamiento
I/Q. Cada paso muestra:

```text
1. que esta comprobando la plataforma;
2. que debe hacer fisicamente el usuario;
3. que resultado se espera;
4. que significa un fallo;
5. cual es la unica accion disponible.
```

El asistente indica explicitamente cuando no debe encenderse el SensorTag,
cuando debe colocarse, cuando debe encenderse, cuando debe esperar el preflight
Windows BLE, cuando se inicia la captura de 10 s y cuando la plataforma esta
procesando. Las fases futuras (`S001-NEG`, dataset, entrenamiento y live model)
permanecen bloqueadas y explican por que. Despues de cualquier captura el flujo
se detiene, muestra un resumen humano y conserva los detalles tecnicos
expandibles; ninguna transicion cientifica ocurre automaticamente.

No debe usarse el numero bruto de correlaciones fuertes como numero de
paquetes. Un paquete con una asociacion fuerte y otra asociacion competidora
incompatible no se considera strong-only para el gate cientifico. El resumen
debe distinguir:

```text
windows_target_observations
detected_bursts
decoded_packets
total_crc_valid_packets
unique_crc_valid_packets
target_crc_valid_packets
environmental_crc_valid_packets
unattributed_crc_valid_packets
target_strong_correlation_edges
target_ambiguous_correlation_edges
unique_target_crc_packets_with_strong_association
unique_strong_only_target_crc_packets
unique_target_crc_packets_with_ambiguous_association
unique_target_crc_packets_with_conflicting_association
target_association_conflict_count
```

Estados esperados:

```text
Un solo paquete fuerte:
maximum_observed_evidence_level = E4
association_evidence_status = MINIMAL_OBSERVATION
ground_truth_status = INSUFFICIENT_FOR_ACCEPTED_E4
dataset_eligibility_status = NOT_ELIGIBLE
reason_code = INSUFFICIENT_UNIQUE_TARGET_PACKETS

Tres o mas paquetes strong-only y todos los gates aprobados:
maximum_observed_evidence_level = E4
association_evidence_status = ACCEPTED
ground_truth_status = PASSED_E4
dataset_eligibility_status = ELIGIBLE

Caso ambiguo:
maximum_observed_evidence_level = E4
association_evidence_status = AMBIGUOUS
ground_truth_status = INSUFFICIENT_FOR_ACCEPTED_E4
dataset_eligibility_status = NOT_ELIGIBLE
reason_code = TARGET_ASSOCIATION_AMBIGUOUS
```

La identidad reportada por Windows es ground truth auxiliar, no entrada del
modelo. Una positiva fallida nunca se convierte en negativa. Solo una
positiva aceptada y elegible desbloquea `S001-NEG = UNLOCKED_NEXT_ONLY`;
dataset y entrenamiento siguen bloqueados.

### Intento S001-POS fallido por continuidad RF

El intento `BLE-HYBRID-20260724T101703Z-7493e2` / `BLE-IQ-16cde3ef4a33`
congelo correctamente el protocolo positivo piloto:

```text
freeze_validation_status = PASSED
execution_purpose = POSITIVE_PILOT
condition_id = C001
session_id = S001-POS
physical_unit_id = CC2650-UNIT-01
quality_gate_version = ble-rffi-positive-pilot-gate-v2
qualification_profile_id =
QPROFILE-Z1B2-2402000000-4000000-2000000-cf32_le-RX2-G20-10S
```

El archivo I/Q alcanzo el tamano esperado, pero la adquisicion no es
cientificamente valida:

```text
actual_samples = 40000000
actual_file_size_bytes = 320000000
hash_status = VERIFIED
metadata_status = COMPLETE
manifest_status = COMPLETE
overflow_count = 1
discontinuity_count = 1
failure_reason_codes =
  ACQUISITION_OVERFLOW
  ACQUISITION_DISCONTINUITY
```

El primer evento fue `host_receive_overrun` en
`sample_index_start = 1070667`, aproximadamente `0.268 s` despues del inicio
RF a 4 MS/s. Los contadores del escritor no apoyan una atribucion al disco en
ese intento:

```text
writer_queue_overrun_count = 0
writer_error = null
maximum_write_latency_ms ~= 2.5
writer_queue_high_watermark_bytes = 1600000
writer_queue_capacity_bytes = 67108864
```

Por tanto, el resultado se conserva como intento historico fallido y no
elegible. No desbloquea negativa, dataset ni entrenamiento.

Durante la revision se detecto una incongruencia de propagacion: el protocolo
congelado declaraba `frontend_preview_enabled = false`, pero la peticion real
al capturador heredaba el valor por defecto `frontend_preview_enabled = true`
y `ui_polling_mode = normal`. El orquestador debe pasar siempre estos campos
desde la metadata congelada hacia el worker de captura. Para S001-POS, la
peticion efectiva debe mantener:

```text
frontend_preview_enabled = false
ui_polling_mode = minimal
online_decoder_enabled = false
online_correlation_enabled = false
```

El intento positivo piloto no es una cualificacion tecnica. Aunque sea
fallido y no elegible, su clasificacion documental debe ser:

```text
execution_purpose = POSITIVE_PILOT
scientific_campaign_member = true
dataset_eligible = false
qualification_only = false
scientific_corpus_membership = positive_pilot_pending_gate
```

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
