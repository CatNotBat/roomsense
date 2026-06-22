# Room Sentinel

Privacy-preserving room occupancy detection using BLE fingerprinting + mmWave radar fusion. Detects how many people are in a room and what devices they carry — no cameras, no identity tracking. Categories and counts only, never identities.

**Hardware cost:** ~$70 (4x ESP32 WR-32 + 4x LD2450 radar + Raspberry Pi)

## How It Works

4 ESP32 combo nodes in room corners each run BLE scanning + HLK-LD2450 24GHz mmWave radar. The BLE model classifies the room's BLE *environment* — not individual devices — as empty or occupied. The mmWave radar adds human presence detection that works through RF-transparent walls where BLE alone fails.

A single sensor can't tell inside from outside (a phone 2m away inside reads the same as one 2m away through the wall). Four sensors create a spatial fingerprint: the same phone produces a unique RSSI pattern across all 4 sensors based on its position relative to walls and corners.

### Why Environment-Level Features?

Apple devices rotate their BLE MAC address every ~15 minutes. Per-device tracking breaks. Instead, the model looks at aggregate BLE statistics per 10-second window:
- Per-sensor: median RSSI, device count, strong device count, signal distribution
- Cross-sensor: which sensor hears the loudest traffic, pairwise signal deltas, total unique devices

These features are identical whether a phone has rotated its address or not.

## Architecture

```
   esp_c1 (WR-32) ─┐                                          ┌─ esp_c3 (WR-32)
     BLE + LD2450   ├── MQTT (sentinel/rssi + sentinel/radar) ──┤  BLE + LD2450
   esp_c2 (WR-32) ─┘                                          └─ esp_c4 (WR-32)
                                    │
                                    v
                         BRAIN (laptop / RPi 4B)
                         Mosquitto MQTT broker
                         -> auto-calibrate RSSI offsets (shared-device method)
                         -> 20s environment-level feature windows
                         -> BLE + radar fused classifier (Random Forest)
                         -> Apple Continuity-aware device dedup
                         -> device-type classification (phone/earbuds/watch/laptop)
                         -> census-by-type + traffic light (NO MAC ever downstream)
                         -> Flask API + web UI
```

## Test Results (2026-06-20)

| Test | Presence | Detection Time | Device Count |
|------|----------|---------------|--------------|
| All devices inside (2 iPhones + AirPods) | correct (0.98) | 0s (warm) | 3/3 stable |
| All devices outside | correct (0.02) | <5s | 0, zero false positives |
| Single iPhone only | correct (0.94) | <5s | 1/1 perfectly stable |
| iPhone + AirPods | correct (0.88) | 5s | 2/2, occasional flicker to 3 |
| 2 iPhones + AirPods | correct (0.95) | <5s | 3/3, occasional flicker to 4 |
| Exit transition | correct | ~25s to quiet | — |
| Entry transition | correct | ~10s to present | — |

**Summary:** 100% presence accuracy. Device counting correct +/-1. Zero false positives in empty room.

### Model Metrics (LOPO cross-validation)

- **93.8% accuracy** excluding RF-transparent wall (physics limitation)
- 83.8% accuracy including all positions
- 500-tree Random Forest, threshold 0.50, 10s windows
- Environment-level features (MAC-rotation-proof)

## Quick Start

### Prerequisites
- Python 3.10+, Mosquitto MQTT broker
- 4x ESP32 boards (already flashed with v3 firmware)

### Install
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Run
```bash
# Start broker
mosquitto -c mosquitto_local.conf -d

# Start live system (auto-calibrates on first run if no offsets exist)
python src/live_ble.py
# -> http://localhost:8080
```

On first startup without calibration data, the system auto-calibrates by finding BLE devices visible to all 4 sensors and computing relative RSSI offsets. No dedicated beacon needed.

### Collect Training Data
```bash
# Record BLE readings + label positions interactively
python src/collect_walk.py
# Commands: "mark CENTER in", "mark OUTSIDE out", "stop"

# Prepare labeled dataset
python src/prepare_walk_data.py

# Train model
python src/train.py data/readings_labeled.csv
```

## File Layout

```
src/
  config.py               # All tunables (env vars)
  env_features.py         # Environment-level feature builder (10s windows)
  live_ble.py             # Live inference + Flask API + auto-calibration
  dedup.py                # RPA dedup + Continuity-aware device counting
  device_id.py            # BLE device-type classifier (Apple/Samsung/Google/etc)
  rssi_cal.py             # RSSI calibration (load/apply/auto-calibrate)
  calibrate.py            # Manual calibration CLI (beacon-based)
  train.py                # Model training (LOPO cross-validation)
  collect_walk.py         # Training data collector (MQTT + interactive labeler)
  prepare_walk_data.py    # Join readings with labels, apply calibration
  label_worn.py           # Worn-device labeling (MAC-filtered)
  aggregation.py          # Per-device aggregation features (v3 legacy path)
  cohearing.py            # Co-hearing alignment join (W=200ms)
  transfer_features.py    # TX-invariant features
  features.py             # Legacy 2s-window features (backward compat)
  templates/census.html   # Web UI

  wr32_combo/             # v2 combo firmware: BLE + LD2450 radar (dual-core)
  radar_features.py       # mmWave radar feature extraction
  esp32_satellite/        # [ARCHIVED] ESP32 classic BLE-only firmware (v1)
  xiao_s3_satellite/      # [ARCHIVED] XIAO ESP32-S3 BLE-only firmware (v1)

tests/                    # 116 tests, all passing
  test_radar_features.py  # mmWave radar features (11 tests)
  test_env_features.py    # Environment feature builder (13 tests)
  test_live_dedup.py      # Continuity-aware dedup (12 tests)
  test_device_id.py       # Device type classifier (26 tests)
  test_prepare_walk.py    # Data preparation (4 tests)
  test_calibration.py     # RSSI calibration (5 tests)
  test_cohearing.py       # Co-hearing alignment (6 tests)
  test_aggregation.py     # Aggregation windows (8 tests)
  test_transfer_features.py  # TX-invariant features (12 tests)
  test_dedup.py           # RPA dedup (4 tests)
  test_features.py        # Legacy features (3 tests)
  test_label_worn.py      # Worn-device labeling (4 tests)
  test_pipeline.py        # End-to-end pipeline (2 tests)

data/                     # Generated at runtime (gitignored)
models/                   # Trained model + metrics
calibration/              # node_offsets.json (auto-generated or manual)
```

## Configuration

All tunables in `src/config.py`, overridable via environment variables:

| Parameter | Env Var | Default | Purpose |
|-----------|---------|---------|---------|
| `SENSORS` | `SENTINEL_SENSORS` | `esp_c1,esp_c2,esp_c3,esp_c4` | Satellite IDs |
| `THRESH` | `SENTINEL_THRESH` | `0.50` | Classification threshold |
| `AGG_WINDOW_S` | `SENTINEL_AGG_WINDOW_S` | `20` | Aggregation window (seconds) |
| `MQTT_HOST` | `SENTINEL_MQTT_HOST` | `localhost` | MQTT broker address |
| `FLASK_PORT` | `SENTINEL_FLASK_PORT` | `8080` | Web UI port |

## API

```
GET /api/census
{
  "level": "present",           // "quiet" | "present" | "busy"
  "counts": {"phone": 2, "earbuds": 1},
  "total": 3,
  "room_prob": 0.982,
  "uncertain": 0
}
```

## Privacy

- No MAC address or device name ever leaves the volatile processing layer
- Only `{category: count}` is output (e.g., "2 phones, 1 earbuds")
- MACs hashed before any disk write
- RPA dedup is volatile/TTL'd, never serialized
- Device-type parser returns category strings only, never identities
- Web UI structurally cannot render identity fields

## Known Limitations

- **RF-transparent walls:** One test wall has ~0 dB BLE attenuation — BLE alone can't distinguish inside from right outside it. mmWave radar fusion (v2) addresses this
- **Apple multi-advertisement dedup:** iPhones broadcast from multiple BLE addresses simultaneously, causing occasional +/-1 count flicker
- **Exit latency:** ~25s due to EMA smoothing (tradeoff: faster = more flicker)

## Next Steps

See [FUTURE_STEPS.md](FUTURE_STEPS.md) for the roadmap.

## Hardware

### Board Assignments (v2 combo firmware)

| Board | Type | SENSOR_ID | Radar |
|-------|------|-----------|-------|
| WR-32 #1 | ESP32 (CH340C) | `esp_c1` | LD2450 |
| WR-32 #2 | ESP32 (CH340C) | `esp_c2` | LD2450 |
| WR-32 #3 | ESP32 (CH340C) | `esp_c3` | LD2450 |
| WR-32 #4 | ESP32 (CH340C) | `esp_c4` | LD2450 |

### MQTT Wire Protocol (v2)

**BLE** (`sentinel/rssi`): 8 pipe-delimited fields: `SENSOR_ID|mac|rssi|addrType|appearance|mfgHex|svcHex|rxMs`

**Radar** (`sentinel/radar`): 15 pipe-delimited fields: `SENSOR_ID|epochMs|nTargets|x0|y0|spd0|dist0|x1|y1|spd1|dist1|x2|y2|spd2|dist2`
