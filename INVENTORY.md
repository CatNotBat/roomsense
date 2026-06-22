# Room Sentinel — Pipeline Inventory (Phase 0)

Generated 2026-06-18. Updated 2026-06-20 after v3_env implementation.

---

## 1. Data Flow Map

```
ESP32 Satellite                 MQTT Broker              Brain
───────────────────────────────────────────────────────────────
BLE scan callback               topic: sentinel/rssi
  onResult(BLEAdvertisedDevice)   7 pipe-delimited fields
  ↓                               ↓
  MQTT publish ──────────────────→ on_message()
                                   + ts = time.time()     ← brain-arrival
                                   ↓
                              mqtt_collector.py → data/readings_raw.csv
                              live_ble.py       → deque buffer
                                   ↓
                              features.build_table()
                              (2s windows, floor-division)
                                   ↓
                              MODEL.predict_proba()
                              (RandomForest 300 trees)
                                   ↓
                              EMA smooth → dedup → display
```

### Source file locations

| Stage | File | Key lines |
|-------|------|-----------|
| Satellite firmware (ESP32) | `src/esp32_satellite/esp32_satellite.ino` | L38-91 (callback+publish), L115-125 (setup+scan) |
| Satellite firmware (XIAO S3) | `src/xiao_s3_satellite/xiao_s3_satellite.ino` | L52-104 (callback+publish), L130-140 (setup+scan) |
| Raw CSV collector | `src/mqtt_collector.py` | L27-40 (on_message), L12-13 (columns) |
| Live pipeline | `src/live_ble.py` | L46-70 (MQTT ingest), L77-197 (evaluate) |
| Feature engineering | `src/features.py` | L37-126 (build_table) |
| Model training | `src/train.py` | L20-180 |
| Env features | `src/env_features.py` | build_env_table() |
| Data prep | `src/prepare_walk_data.py` | prepare() |
| Device dedup | `src/dedup.py` | count_nearby_devices() |
| Config | `src/config.py` | L1-37 |

---

## 2. Reading Schema (wire + CSV)

### 2.1 Wire format (satellite → MQTT)

Topic: `sentinel/rssi`. Payload: pipe-delimited, 7 fields.

```
SENSOR_ID|mac|rssi|addrType|appearance|mfgHex|svcHex
```

| # | Field | Type | Units | Source (firmware line) |
|---|-------|------|-------|-----------------------|
| 1 | SENSOR_ID | string | — | Hardcoded `#define` (esp32: L19) |
| 2 | mac | string | lowercase colon-separated | `d.getAddress()` (esp32: L43) |
| 3 | rssi | int | **dBm, 1 dBm resolution** | `d.getRSSI()` (esp32: L44) |
| 4 | addrType | int | 0=public, 1=random, 2=RPA, 3=static | `d.getAddressType()` (esp32: L45) |
| 5 | appearance | int | GAP code, -1 if absent | `d.getAppearance()` (esp32: L49-50) |
| 6 | mfgHex | hex string | AD type 0xFF, up to 80 hex chars | `d.getManufacturerData()` (esp32: L56-61) |
| 7 | svcHex | hex string | UUID(4 hex) + data, up to 64 chars | `d.getServiceData(0)` (esp32: L67-81) |

### 2.2 CSV schema (brain disk)

File: `data/readings_raw.csv` — written by `mqtt_collector.py`.

| Column | Source | Notes |
|--------|--------|-------|
| ts | `time.time()` at brain arrival | float, seconds, 3 decimal places |
| source | wire field 1 | sensor ID |
| mac | wire field 2 | hashed if `HASH_ON_DISK=true` |
| rssi | wire field 3 | integer dBm |
| phy | hardcoded `"btle"` | always BLE |
| name | hardcoded `""` | never transmitted |
| addr_type | wire field 4 | integer |
| appearance | wire field 5 | integer |
| mfg_hex | wire field 6 | hex string |
| svc_hex | wire field 7 | hex string |

### 2.3 Three critical questions

**Q1: Does a reading carry a satellite-side RX timestamp?**
> **YES (v3 firmware).** Both firmwares use SNTP sync at boot + `gettimeofday()` for epoch ms. The 8th MQTT field contains the satellite RX timestamp. However, in live inference we use brain-arrival time (`time.time()`) because satellite SNTP clocks drift ~541s — a known issue mitigated by the brain-side timestamp.

**Q2: Is the BLE advertising channel (37/38/39) present per packet?**
> **NO.** The Bluedroid stack's `BLEAdvertisedDevice` class wraps `esp_ble_gap_cb_param_t::ble_scan_result_evt_param`. This struct contains `ble_addr_type`, `rssi`, `ble_evt_type`, and raw adv data — but NOT the channel index. The BLE controller handles 37/38/39 hopping internally and does not report which channel a specific advertisement was received on. Neither firmware file attempts to access channel information.

**Q3: What is the RSSI unit and resolution, and is per-node calibration applied?**
> **Unit: dBm, integer (1 dBm resolution).** `d.getRSSI()` returns `int`. **Per-node calibration IS applied (v3).** `rssi_cal.py` loads offsets from `calibration/node_offsets.json` and applies them at ingest. Auto-calibration uses shared-device method (26 devices seen by all 4 sensors). Current offsets: esp_c1=-2.5, esp_c2=+0.3, esp_c3=+1.0, esp_c4=+0.8.

---

## 3. Feature Extraction

Source: `src/features.py`, function `build_table(df, window_s=2)`.

### 3.1 Windowing

- Window size: `WINDOW_S = 2` seconds (config.py: L5)
- Method: floor-division `win = ((ts - t0) // window_s)` (features.py: L44)
- No overlap
- Grouping: `(mac, phy, win)`
- **No co-hearing alignment** — readings from different satellites in the same 2s window are paired regardless of their actual time separation within that window

### 3.2 Per-source features (9 stats × N sensors)

| Feature | Code | Line |
|---------|------|------|
| `rssi_median__{src}` | `s.median()` | L26 |
| `rssi_mean__{src}` | `s.mean()` | L27 |
| `rssi_std__{src}` | `s.std()`, NaN→0 | L28, L19-21 |
| `rssi_min__{src}` | `s.min()` | L29 |
| `rssi_max__{src}` | `s.max()` | L30 |
| `rssi_p25__{src}` | `s.quantile(.25)` | L31 |
| `rssi_p75__{src}` | `s.quantile(.75)` | L32 |
| `rssi_range__{src}` | `max - min` | L33 |
| `pkt_count__{src}` | `len(s)` | L34 |

Missing sensor: all stats set to `NOT_HEARD = -120` (L14, L68-71).

### 3.3 Cross-sensor features

| Feature | Calculation | Line |
|---------|------------|------|
| `n_heard` | count of sensors with readings | L74 |
| `rssi_vec_max` | `max(heard_medians)` | L76 |
| `rssi_spread` | `max - min` of heard medians | L77 |
| `delta__{a}__{b}` | `median_a - median_b` (C(N,2) pairs) | L82-84 |
| `is_loudest__{src}` | 1 for loudest sensor, 0 otherwise | L86-90 |
| `argmax_stability` | fraction of recent windows (10s lookback) with same loudest | L105-124 |
| `phy_is_wifi` | always 0 (BLE-only) | L93 |

**Cross-sensor differences use uncalibrated RSSI and have no co-hearing time constraint.**

### 3.4 Total feature count

For N=3 sensors: 9×3 per-source + 3 pkt_count + 3 aggregate + 3 deltas + 3 is_loudest + 1 stability + 1 phy_is_wifi = **38 features**.

---

## 4. Data Assets Snapshot

| File | Rows | Columns | Notes |
|------|------|---------|-------|
| `data/readings_raw.csv` | 1,330,596 | ts,source,mac,rssi,phy,name,addr_type,appearance,mfg_hex,svc_hex | Raw BLE captures, 3 sensors |
| `data/readings_labeled.csv` | 48,581 | + position, inout | Time-joined with labels |
| `data/labels.csv` | 17 | position,inout,start_ts,end_ts | 12 beacon + 4 real-device positions |
| `data/backup_single_sensor/` | — | — | Pre-multi-sensor data (326,897 rows) |
| `data/backup_v1_presession/` | — | — | Earlier session data |
| `models/model.joblib` | — | — | RandomForest + columns + threshold |
| `models/metrics.json` | — | — | Per-position accuracy breakdown |
| `models/REPORT.md` | — | — | Human-readable summary |

Read-only snapshots copied to `data/raw/` for reference.
