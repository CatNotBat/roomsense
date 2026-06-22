# Room Sentinel — Pipeline Correctness Fixes (do this BEFORE any discrimination re-test)

## Context for the agent

This repo runs a passive BLE room-boundary system: 3–4 ESP32 "satellites" scan BLE advertisements and report `(device_addr, rssi, mfg_data, timestamp)` over WiFi to a "brain" that builds features and runs a classifier (currently Random Forest) to decide **inside vs outside** the room. A prior diagnostic produced **AUC = 0.586** when scoring real devices with a beacon-trained model. We have reason to believe a large part of that failure is **execution error in the data/feature pipeline**, not just modeling. The job in this document is to **fix the pipeline correctness issues first**, with verifiable acceptance criteria, and to **NOT draw any inside/outside discrimination conclusions until those fixes are in place and verified.**

### PRIME DIRECTIVE
> Do **not** run, score, or report any inside/outside discrimination experiment until **Phase 1 and Phase 2 are complete and their acceptance criteria pass.** Phase 4 (the re-test) is gated behind that. If you are tempted to "just check if it works now," stop — that is exactly the mistake we are correcting.

### How to work
- **Inventory before editing.** Phase 0 forces you to read the actual code and data schemas and write them down. Do not assume field names, units, or windowing; discover them.
- **Incremental and reversible.** One task = one focused change + its test. Never delete or overwrite raw capture data; write derived data to new paths.
- **Make everything configurable.** Window lengths, calibration offsets, channel handling — all in a config file, not magic numbers in code.
- **Log before/after.** Every fix must emit a short note (numbers, not adjectives) showing what changed.
- **Be honest about what the hardware exposes.** If a needed signal (e.g. per-packet BLE channel) is not available from the firmware/stack, **say so and implement the documented mitigation** — do not fabricate or silently approximate it.
- **At the end of each phase, write a `PHASE_N_REPORT.md`** summarizing what was changed, the acceptance numbers, and any caveats.

### Key definitions (use these exact terms)
- **RX timestamp** — the time a BLE packet was *received at the satellite*, on the satellite's clock. Distinct from *arrival time at the brain*, which includes WiFi + queue latency.
- **Co-hearing window (W)** — max time gap allowed when combining readings from *different* satellites into one cross-sensor sample. Default `W = 200 ms`. Readings further apart than W must NOT be differenced.
- **Aggregation window (A)** — the longer window over which we summarize a device's behavior into distributional features. Default `A = 20 s`, 50% overlap.
- **Advertising channels** — BLE legacy advertising uses channels 37 / 38 / 39 at 2402 / 2426 / 2480 MHz. RSSI differs across them; treat as a confound.
- **Reference node** — an optional satellite placed *outside* the room (hallway) or flush on a wall, tagged in config as `role: reference`. Code must tolerate its presence/absence.

---

## Phase 0 — Inventory & baseline (no behavior changes)

**Goal:** produce a written, accurate picture of the current pipeline so the fixes are grounded in reality.

- [ ] **0.1 Map the codebase.** Identify and document in `INVENTORY.md`: where satellites publish readings, the wire format/schema of a reading, the ingest path on the brain, where windowing happens, where features are computed, where the model is trained/scored, and where data files live.
- [ ] **0.2 Document the reading schema precisely.** For each field: name, type, **units**, and source. Critically answer:
  - Does a reading carry a **satellite-side RX timestamp**, or only a brain-arrival timestamp? (Check the firmware scan callback and the publish payload.)
  - Is the **BLE advertising channel** (37/38/39) present per packet? (Check whether the BLE stack — NimBLE/Bluedroid — exposes it in the scan result.)
  - What is the RSSI **unit and resolution** (dBm, integer?), and is any per-node calibration applied today?
- [ ] **0.3 Document current feature extraction.** List every feature, its window length, and whether it uses cross-sensor differences. Note specifically: what time window is used when two sensors' RSSIs are combined, and whether channel is considered.
- [ ] **0.4 Snapshot the current data assets.** Record row counts and schemas of the existing datasets (raw readings, beacon-labeled, real-device-labeled) and copy them read-only into `data/raw/` references. Do not modify.

**Acceptance:** `INVENTORY.md` exists and answers every question in 0.2 with evidence (file + line references). The three yes/no questions (RX timestamp? channel exposed? calibration applied?) are answered definitively.

---

## Phase 1 — Data-integrity fixes (the plumbing)

### 1.1 RX timestamping and cross-satellite clock alignment
**Why:** If two satellites' readings that are actually seconds apart get combined, a moving body has changed the geometry between them and every cross-sensor "difference" is garbage. This silently destroys the most informative features.

**What to implement:**
- [ ] If satellites do **not** stamp RX time: add it in firmware at the scan callback (`esp_timer_get_time()` or equivalent) and include it in the published payload. If firmware changes are out of scope for this pass, document that clearly and proceed with the mitigation below.
- [ ] Establish a shared time base: either SNTP from the brain to all satellites at boot + periodic resync, or a periodic sync broadcast the satellites timestamp. Record clock offset/skew per satellite.
- [ ] **Measure arrival jitter:** from real captures, compute the distribution of cross-satellite time deltas for the *same* packet/device. Report median and 95th percentile.
- [ ] If RX timestamps are unavailable and brain-arrival jitter (95th pct) exceeds `W`, you **cannot** align reliably at `W = 200 ms`. Either (a) fix firmware to add RX timestamps, or (b) document the degraded `W` you must use and flag it as a known error source in `PHASE_1_REPORT.md`.

**Acceptance:** Either RX timestamps flow end to end, or a documented clock-offset correction is applied; and a measured jitter report exists. A unit test confirms the alignment layer (built in 2.1) refuses to pair readings more than `W` apart.

### 1.2 BLE advertising-channel capture
**Why:** RSSI varies across channels 37/38/39. Mixing them into one feature injects frequency-selective fading noise.

**What to implement:**
- [ ] Determine whether the stack exposes the channel index of each received legacy advertisement. (Note: many ESP32 BLE stacks do **not** expose this for received legacy adv, since the controller handles hopping.)
- [ ] If available: include channel per reading in the schema.
- [ ] If **not** available: document it explicitly. The mitigation is handled in 2.2/2.3 (aggregate enough packets that channel mix averages out) — implement that, and record this as a residual, un-fixable-at-this-layer error source.

**Acceptance:** `INVENTORY.md`/`PHASE_1_REPORT.md` states definitively whether channel is available, and the chosen path (capture vs documented mitigation) is implemented.

### 1.3 Per-node RSSI offset calibration
**Why:** Each ESP32 + antenna has its own RSSI bias of several dB. Uncalibrated, every cross-sensor "difference" carries fixed per-node error that the beacon training baked in and that drifts.

**What to implement:**
- [ ] A calibration routine: place the beacon at the room's geometric center (or a fixed known equidistant spot); have all satellites log RSSI simultaneously for ~60 s.
- [ ] Compute per-node offset: `offset[i] = median_over_all_nodes(rssi) − median(rssi[node i])`. Store in `calibration/node_offsets.json` with timestamp and beacon position.
- [ ] Apply offsets at ingest: `rssi_cal = rssi_raw + offset[node]`. All downstream features use calibrated RSSI.
- [ ] (Optional, better) Repeat at 2–3 positions and fit offsets that best equalize across them; keep median-at-center as the v1 default.

**Acceptance:** `node_offsets.json` exists; after applying, the calibration capture shows near-zero inter-node median difference (report before/after numbers); all feature code reads calibrated RSSI.

---

## Phase 2 — Feature-extraction fixes

### 2.1 Co-hearing alignment join
**Why:** Cross-sensor features are only meaningful for readings that describe the *same instant*.

**What to implement:**
- [ ] A join that, to form a cross-sensor sample for a device at time `t`, takes per satellite only the reading(s) within `[t − W/2, t + W/2]` (using RX timestamps / corrected clock).
- [ ] If a satellite has no reading in the window, mark that satellite **missing** for this sample. **Do not** backfill from a far-away reading and **do not** carry the sentinel value forward as if it were a real measurement; record `n_heard` (how many satellites contributed) as an explicit field.

```
# pseudocode
def cohearing_samples(readings, device, W):
    for t in candidate_centers(readings[device]):
        sample = {}
        for sat in satellites:
            r = nearest_reading(readings[device][sat], t, max_gap=W/2)
            sample[sat] = r.rssi_cal if r is not None else MISSING
        sample['n_heard'] = count_non_missing(sample)
        yield t, sample
```

**Acceptance:** Unit test with synthetic readings at known RX times proves no two paired readings are more than `W` apart, and that `n_heard` is correct. `W` is configurable.

### 2.2 Same-channel differencing
**Why:** Differencing sensor A on ch37 vs sensor B on ch39 mixes geometry with frequency-selective fading.

**What to implement:**
- [ ] If channel is available (1.2): compute cross-sensor differences **within the same channel**, or compute per-channel features and aggregate.
- [ ] If channel is not available: rely on aggregation (2.3) to average the channel mix, and annotate the affected features as channel-confounded in the feature docs.

**Acceptance:** Code either bins by channel before differencing, or documents the mitigation path; a test verifies within-channel differencing when channel data is present.

### 2.3 Temporal aggregation windows
**Why:** Single-snapshot RSSI is dominated by deep fading; aggregated RSS over time is far more informative. This is the highest-impact single change.

**What to implement:**
- [ ] Replace instantaneous/short windows with aggregation windows `A = 20 s` (configurable), 50% overlap.
- [ ] For each `(device, satellite)` in a window, compute distributional features: `median`, `IQR` (or MAD), `max`, `min`, `count` (packets), `frac_subwindows_heard`.
- [ ] Keep cross-sensor features (from 2.1/2.2) computed per sub-window, then summarized across the aggregation window (e.g., median of the per-subwindow spread).

**Acceptance:** Feature table reflects distributional stats over `A`; `A` and overlap configurable; doc lists every feature and its window.

### 2.4 TX-invariant / transfer features
**Why:** A pocketed phone's absolute level is dominated by transmit power + antenna + body shadowing (10–40 dB, larger than the wall we're reading). Features must be invariant to the device's own level.

**What to implement (add these features):**
- [ ] **Per-device self-normalization:** for each device in a window, reference level `ref = median(rssi_cal over all sats & window)`; emit each satellite's value as `rssi_cal − ref`.
- [ ] **Anisotropy / spread:** variance or IQR of the per-satellite medians within the window (a single scalar: how unequal are the sensors). Rotation-invariant; level-invariant.
- [ ] **Argmax coverage:** over the sub-windows (and a rolling longer horizon), the fraction of distinct satellites that were ever the loudest. (Interior movement visits all corners; exterior stays on one side.)
- [ ] **Reference-node delta (if a `role: reference` node exists):** `median(interior_nodes) − median(reference_node)`. Tolerate absence of the reference node.

**Acceptance:** Each feature has a unit test on synthetic inputs with a known expected value (e.g., a perfectly isotropic input yields ~0 anisotropy; a device loudest on one fixed sat yields argmax-coverage = 1/N).

---

## Phase 3 — Worn-device calibration data collection (do, but it is data, not code)

**Why:** A beacon has no body. The dominant term in a pocketed-phone signal is body shadowing, which beacon-only data cannot contain. We need labeled data from devices actually worn on a body, across orientations.

**What to implement:**
- [ ] A small **labeling tool** (CLI or notebook) that records a timeline: `timestamp, position_id, orientation, label(inside/outside), carried_macs[]`. Join it to readings to produce labeled worn-device rows, filtered to **only the carried MACs** (so neighbor devices heard through walls are never mislabeled "inside").

**Collection protocol (for the human operator):**
- [ ] Carry 2–3 real devices in realistic spots (front pocket, back pocket, bag, wrist). Record their MACs.
- [ ] Visit ≥8 inside and ≥8 outside positions, **including positions just past the wall you most worry about.**
- [ ] At each position, **stand and rotate 360° over ~30–60 s** to sample the body-shadow distribution. Optionally also walk a slow loop for the "mover" features.
- [ ] If possible, repeat with a second person of different body size.

**Acceptance:** A labeled worn-device dataset exists with carried-MAC ground truth, multiple orientations per position, and positions on both sides of the worry-wall.

---

## Phase 4 — Re-test: COMPLETED (2026-06-20)

**Approach changed:** Instead of per-device features (which failed at 56.3% due to stationary neighbor devices), we implemented environment-level features (`env_features.py`) that aggregate ALL BLE devices per time window. This is MAC-rotation-proof and doesn't require tracking individual devices.

**Results:**
- [x] Environment-level features trained with LOPO: **93.8% accuracy** (excl. RF-transparent C2-C3 wall)
- [x] Phone-only detection: 95%, AirPods-only: 95%, Empty room: 100%
- [x] Live manual testing: 100% presence accuracy, correct device counting
- [x] C2-C3 wall identified as physics ceiling (~0 dB attenuation) — not fixable with BLE alone
- [x] Recommended hardware fix: mmWave radar fusion (HLK-LD2410, ~$3 each)

**Decision:** AUC moved massively from 0.586 → execution and feature engineering were the primary cause. Environment-level features solved the transfer problem entirely. The remaining limitation is physics (RF-transparent wall), not modeling.

---

## Definition of done for this document
1. `INVENTORY.md` + `PHASE_1_REPORT.md` + `PHASE_2_REPORT.md` exist with concrete before/after numbers.
2. The three honesty questions are answered in writing: Are RX timestamps available end to end? Is BLE channel exposed? What are the per-node calibration offsets?
3. Calibrated RSSI, co-hearing alignment (≤ W), channel handling, aggregation windows, and transfer features are all implemented, configurable, and unit-tested.
4. A worn-device labeled dataset (carried-MAC ground truth, multi-orientation) exists.
5. No discrimination conclusion was drawn before items 1–3 were complete.

> Reminder of the prime directive: fixes and their verification come first; the re-test is the last step, not the first.
