# Phase 2 Report — Feature-Extraction Fixes

## 2.1 Co-Hearing Alignment Join

**Status: IMPLEMENTED**

### What changed
- **New:** `src/cohearing.py` — `cohearing_samples(readings, W_ms=200, sensors=SENSORS)`
- For each (device, candidate time center), finds nearest reading per satellite within W/2
- Missing sensors marked `NaN` (distinct from NOT_HEARD=-120 sentinel)
- `n_heard` = count of non-NaN sensors per sample
- Candidate centers thinned by W/4 to avoid redundant samples
- Uses `np.searchsorted` for efficient nearest-neighbor lookup

### Before
- Cross-sensor features paired ALL readings in the same 2s floor-division window
- No max-gap enforcement — readings up to 2s apart could be paired
- Missing sensor filled with -120 dBm (indistinguishable from very weak signal)

### After
- Strict W/2 = 100ms max gap from center (configurable via `ROOMSENSE_COHEARING_W_MS`)
- Missing sensors are NaN, not -120
- n_heard accurately reflects how many sensors contributed

### Config
- `ROOMSENSE_COHEARING_W_MS` = 200 (default)

---

## 2.2 Same-Channel Differencing

**Status: DOCUMENTED (channel not available)**

- Added channel-confound documentation in `features.py` header
- If a future firmware exposes a `channel` column, the aggregation module will compute within-channel features automatically
- Current mitigation: 20s aggregation averages over channel mix

---

## 2.3 Temporal Aggregation Windows

**Status: IMPLEMENTED**

### What changed
- **New:** `src/aggregation.py` — `build_aggregated_table(readings, A=20, overlap=0.5, ...)`
- Replaces 2s snapshot windows with configurable aggregation windows

### Feature set (per sensor per window)

| Feature | Description |
|---------|-------------|
| `rssi_median__{sensor}` | Median RSSI over window |
| `rssi_iqr__{sensor}` | Interquartile range (Q75-Q25) |
| `rssi_mad__{sensor}` | Median absolute deviation |
| `rssi_max__{sensor}` | Maximum RSSI |
| `rssi_min__{sensor}` | Minimum RSSI |
| `pkt_count__{sensor}` | Packet count |
| `frac_heard__{sensor}` | Fraction of 10 sub-windows with ≥1 reading |

### Cross-sensor features

| Feature | Description |
|---------|-------------|
| `n_heard` | Sensors that heard device (co-hearing aligned) |
| `rssi_vec_max` | Strongest sensor median |
| `rssi_spread` | Max-min of heard sensor medians |
| `delta__{a}__{b}` | Pairwise median differences (C(N,2) pairs) |
| `is_loudest__{sensor}` | One-hot for loudest sensor |

### Before vs after

| Property | Before (v2) | After (v3) |
|----------|-------------|------------|
| Window | 2s, no overlap | 20s, 50% overlap |
| Stats per sensor | 9 (median, mean, std, min, max, p25, p75, range, count) | 7 (median, IQR, MAD, max, min, count, frac_heard) |
| Cross-sensor alignment | None (same 2s bin) | Co-hearing W=200ms |
| Channel handling | Mixed | Averaged by 20s aggregation |

### Config
- `ROOMSENSE_AGG_WINDOW_S` = 20 (default)
- `ROOMSENSE_AGG_OVERLAP` = 0.5 (default)

---

## 2.4 TX-Invariant / Transfer Features

**Status: IMPLEMENTED**

### What changed
- **New:** `src/transfer_features.py` — four feature functions
- Integrated into `aggregation.py` per agg window

### New features

| Feature | Description | Invariant to |
|---------|-------------|-------------|
| `rssi_normed__{sensor}` | rssi_median - median(all heard sensors) | TX power, antenna gain |
| `anisotropy` | IQR of per-satellite medians | TX power, rotation |
| `argmax_coverage` | Fraction of sensors ever loudest (from co-hearing sub-samples) | TX power |
| `ref_delta` | median(interior) - median(reference) | TX power (requires reference sensor) |

### Design rationale
- **Self-normalization:** A pocketed phone at -80 dBm and a bare phone at -50 dBm have identical normalized profiles if at the same position
- **Anisotropy:** Inside devices are surrounded by sensors → low anisotropy. Outside devices see one loud side → high anisotropy
- **Argmax coverage:** Moving inside visits all corners → all sensors take turns being loudest. Outside stays on one side → 1/N coverage
- **Reference delta:** Requires a sensor placed outside the room (optional)

### Config
- `ROOMSENSE_REFERENCE_SENSOR` = "" (default, no reference node)

---

## Training Pipeline Changes

- `src/train.py` updated to v3: uses `build_aggregated_table()` by default
- `--legacy` flag falls back to old `build_table()` for comparison
- Can specify custom data file as first argument
- Model bundle now includes `version: "v3"` field

## Live Pipeline Changes

- `src/live_ble.py` detects model version and switches between aggregation and legacy
- Buffer size adapts to model's window size

---

## Test Coverage

| Test File | Tests | Status |
|-----------|-------|--------|
| `tests/test_cohearing.py` | 6 | All pass |
| `tests/test_aggregation.py` | 8 | All pass |
| `tests/test_transfer_features.py` | 12 | All pass |

**Total test suite: 105 tests, all passing (updated 2026-06-20).**

---

## Acceptance Criteria

1. ✅ Co-hearing alignment refuses to pair readings > W apart (test_far_readings_not_paired)
2. ✅ n_heard correctly reflects co-hearing sample count (test_missing_sensor_is_nan)
3. ✅ W is configurable (ROOMSENSE_COHEARING_W_MS)
4. ✅ Aggregation windows A and overlap are configurable
5. ✅ Distributional stats computed correctly (test_distributional_stats)
6. ✅ frac_subwindows_heard correct (test_frac_heard)
7. ✅ Transfer features produce expected values on synthetic inputs
8. ✅ Channel confound documented with mitigation path
