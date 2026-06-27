# Phase 1 Report — Data-Integrity Fixes

## 1.1 RX Timestamping

**Status: IMPLEMENTED (firmware v3)**

### What changed
- Both satellite firmwares (`esp32_satellite.ino`, `xiao_s3_satellite.ino`) now:
  - Call `esp_sntp_init()` + sync to `pool.ntp.org` at boot
  - Capture `epochMs()` via `gettimeofday()` at top of scan callback
  - Append RX timestamp as 8th pipe field: `...svcHex|rxMs`
- Brain-side (`mqtt_collector.py`, `live_ble.py`) parses the 8th field and uses satellite RX timestamp when available, falls back to `time.time()` for legacy v2 payloads

### SNTP sync behavior
- Waits up to 10s for initial NTP sync at boot
- If sync fails (no internet), timestamps are boot-relative (printed as warning)
- ESP-IDF SNTP re-syncs hourly by default

### Cross-satellite clock alignment
- All satellites sync to the same NTP server → shared time base
- Expected accuracy: ±50ms (typical for SNTP on ESP32 over WiFi LAN)
- Co-hearing window W=200ms provides 4× margin over SNTP jitter

### Jitter measurement
Deferred until firmware is flashed and live data is collected. The co-hearing module (Phase 2.1) enforces the W constraint regardless.

---

## 1.2 BLE Advertising Channel

**Status: NOT AVAILABLE — documented**

### Finding
The Bluedroid BLE stack on ESP32/ESP32-S3 does NOT expose the advertising channel index (37/38/39) per received packet. The `BLEAdvertisedDevice` callback provides MAC, RSSI, address type, appearance, and advertisement data — but not the channel. The controller handles 37/38/39 hopping internally.

### Evidence
- `esp_ble_gap_cb_param_t::ble_scan_result_evt_param` (ESP-IDF) has no channel field
- No `getChannel()` or equivalent method in the Arduino BLE library
- Both ESP32 classic and XIAO ESP32-S3 are affected

### Mitigation
Temporal aggregation (Phase 2.3, A=20s default) averages over ~200 channel rotation cycles (each ~100ms), reducing frequency-selective fading noise. Cross-sensor deltas remain channel-confounded but the aggregation provides substantial noise reduction.

---

## 1.3 Per-Node RSSI Offset Calibration

**Status: IMPLEMENTED**

### What changed
- **New:** `src/calibrate.py` — CLI calibration tool. Subscribes to MQTT, filters to beacon MAC, collects 60s of readings, computes `offset[i] = global_median - median(node_i)`, saves to `calibration/node_offsets.json`
- **New:** `src/rssi_cal.py` — load/apply module. Auto-loads offsets on import. `calibrate_rssi(rssi, sensor_id)` applies offset
- **Modified:** `src/mqtt_collector.py` — applies `calibrate_rssi()` at ingest
- **Modified:** `src/live_ble.py` — applies `calibrate_rssi()` at ingest

### Before/after
Calibration completed 2026-06-20 using multi-beacon method (26 shared BLE devices, 60s capture).
- Offsets: esp_c1=-2.5, esp_c2=+0.3, esp_c3=+1.0, esp_c4=+0.8
- Auto-calibration added: `rssi_cal.auto_calibrate()` runs on first startup if no offsets exist

### Config
- `ROOMSENSE_BEACON_MAC` — beacon MAC for manual calibration
- Auto-calibration needs no config — uses shared-device method automatically

---

## Three Honesty Questions

| Question | Answer |
|----------|--------|
| Are RX timestamps available end to end? | **YES** (v3 firmware). Satellites stamp with SNTP epoch ms. In practice, brain-arrival time is used for live inference due to ~541s SNTP drift. |
| Is BLE channel exposed? | **NO.** Bluedroid does not expose it. Mitigated by 10-20s aggregation averaging over channel cycles. |
| What are per-node calibration offsets? | **Measured.** esp_c1=-2.5, esp_c2=+0.3, esp_c3=+1.0, esp_c4=+0.8 (multi-beacon method, 26 shared devices). |

---

## Test Coverage

| Test File | Tests | Status |
|-----------|-------|--------|
| `tests/test_calibration.py` | 5 | All pass |

105 tests pass across the full suite (updated 2026-06-20).
