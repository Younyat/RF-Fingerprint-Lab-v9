# BLE-RFFI Studio: preprocessing specification

Full derivation and code references for the two scientific preprocessing
profiles the root README only summarizes. Source: `backend/app/modules/ble_rffi_studio/preprocessing/`.

## `paper-eq6-7-v1` — paper-compliant affine phase/frequency compensation

**Status: IMPLEMENTED AND TESTED. Not yet exercised by a definitive real
model bundle/campaign** — no bundle trained under this profile has been
produced by a real campaign run yet; see the root README's Current
scientific status table.

Implementation: `preprocessing/paper_compliant_cfo.py`.

1. **`q[n]`** — a frozen BLE reference: the ideal GFSK-modulated
   preamble + access-address waveform (LE 1M PHY, Gaussian pulse BT=0.5,
   modulation index h=0.5), built once from fixed, known bits. The
   advertising-channel access address is fixed at `0x8E89BED6` for every real
   advertising packet (Bluetooth Core Spec Vol 6 Part B 1.4.1); the preamble
   byte (`0xAA`/`0x55`) is deterministically implied by the access address's
   first-transmitted bit (Vol 6 Part B 2.1.2). `q[n]` is therefore the same
   waveform for every burst at a given sample rate — never fit to the
   observed signal.
2. **`z_b[n] = x_b[n] · q*[n]`** — the observed burst multiplied by the
   conjugated reference, evaluated only over the frozen index set below.
3. **`ψ_b[n] = unwrap(angle(z_b[n]))`** — the unwrapped phase of `z_b`.
4. **`I_b`** — the frozen fitting interval: the burst's own `PRE_PDU` sample
   range (`packet_content/field_mapping.py`'s `PRE_PDU_BITS = 40`,
   preamble + access address) — the only span of a real advertising burst
   whose bit content is known and fixed, so it is the only span a known
   reference can be correlated against.
5. **Joint least-squares estimation** of `(φ_b0, f_b)` such that
   `ψ_b[n] ≈ φ_b0 + 2π·f_b·n/Fs` over `I_b`, via `np.linalg.lstsq` — a real
   joint regression, not a mean-slope or single-sample approximation.
6. **Affine compensation**, applied to the *whole* burst window (not just
   `I_b`):
   `x̃_b[n] = x_b[n] · exp(-j(φ_b0 + 2π·f_b·n/Fs))`.

**Per-burst provenance** (persisted, never discarded): `profile_id`,
`reference_waveform_version`, `reference_waveform_hash` (SHA-256 of `q[n]`),
`index_set` (`I_b`, as absolute sample bounds), `phi_b0`, `f_b_hz`,
`sample_rate_sps`, `compensation_status` (`APPLIED` or
`SKIPPED_WINDOW_SHORTER_THAN_I_B`, never a fabricated value for a window too
short to fit). Training writes one row per example to
`training_runs/<run>/preprocessing_provenance.jsonl`; offline inference
attaches the same structure to each scored decision. TRAIN and inference
call the exact same function
(`apply_base_preprocessing_with_provenance`) — never two implementations.

## `offset-retaining-v1` — sensitivity-analysis counterpart

Identity preprocessing (no step enabled) under its own, intentionally
distinct `profile_id`, run through the same pipeline except the
compensation step — the deliberate "what if we don't correct the offset"
comparison against `paper-eq6-7-v1`, never conflated with the older,
unrelated `base-v1` default.

## `cfo-compensated-v1` — heuristic/legacy compensation, not Eq.(6)-(7)

An older, simpler correction (mean phase-step CFO over the whole window +
first-sample phase zeroing) kept only for historical/ablation utility. It
has **no** reference waveform, **no** frozen index set, **no** joint
regression, and **no** per-burst persisted parameters. It must never be
described as an implementation of Eq.(6)-(7) — see
`scientific_basis/preprocessing_evidence.json`'s own justification note for
this profile, which states the distinction explicitly.

## Justification gate

No preprocessing step that alters the signal runs unless
`scientific_basis/preprocessing_evidence.json` records a real
`justified_by_technique_id` for it, checked in code
(`BasePreprocessingProfile.validate_justifications`) — a step cannot be
silently enabled without an on-file justification, and a fabricated
citation is explicitly forbidden by the same file's own policy note.
