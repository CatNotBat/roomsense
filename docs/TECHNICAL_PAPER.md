# RoomSense — Technical Paper

*A complete technical reference for the project. Covers every design decision, the full evolution from v1 to v2, all ML and signal-processing choices, the physics, the failures, and the current state.*

*Last updated: 2026-06-26*

---

## Table of Contents

1. [What RoomSense Does](#1-what-roomsense-does)
2. [The Problem: Why This Is Hard](#2-the-problem-why-this-is-hard)
3. [Hardware Architecture](#3-hardware-architecture)
4. [Firmware Design](#4-firmware-design)
5. [The ML Journey: Four Attempts](#5-the-ml-journey-four-attempts)
6. [Feature Engineering (Current v3_env)](#6-feature-engineering-current-v3_env)
7. [Calibration](#7-calibration)
8. [Training Pipeline](#8-training-pipeline)
9. [Device Identification & Deduplication](#9-device-identification--deduplication)
10. [mmWave Radar Fusion (v2)](#10-mmwave-radar-fusion-v2)
11. [Live Inference Pipeline](#11-live-inference-pipeline)
12. [Privacy Architecture](#12-privacy-architecture)
13. [RF Physics Reference](#13-rf-physics-reference)
14. [Problems Encountered & Solutions](#14-problems-encountered--solutions)
15. [Results](#15-results)
16. [Known Limitations & Next Steps](#16-known-limitations--next-steps)
17. [Deployment](#17-deployment)
18. [Quick Reference: Key Numbers](#18-quick-reference-key-numbers)

---

## 1. What RoomSense Does

RoomSense answers one question: **"How many people are in this room and what devices do they carry?"**

Output example: `{"phone": 2, "earbuds": 1, "watch": 1}` — categories and counts, never identities.

It uses Bluetooth Low Energy (BLE) fingerprinting with optional 24GHz mmWave radar fusion. No cameras. No microphones. No identity tracking. Privacy is a structural constraint, not a policy promise — the data structures physically cannot hold identities.

**Cost:** ~$70 for a full 4-node system with radar, ~$12 for BLE-only.

---

## 2. The Problem: Why This Is Hard

### 2.1 Why a single sensor fails

Every phone, earbuds, watch, and laptop continuously broadcasts BLE advertisements. An ESP32 can listen passively and measure the signal strength (RSSI, in dBm). Stronger signal = closer device. Sounds simple.

The problem: **a phone 2 meters away inside the room reads -65 dBm. A neighbor's phone 2 meters through a wall also reads -65 dBm.** A single sensor measures distance but not direction. The distributions genuinely overlap — no threshold can separate inside from outside.

### 2.2 Why multiple sensors work

With 4 sensors in the room's corners, the same phone produces a unique RSSI **pattern** across all sensors. A phone near corner 1 reads strong on sensors 1 and 4, weak on sensors 2 and 3. A phone outside the north wall reads weak on all sensors, but with a specific attenuation pattern.

**The key insight: RSSI *differences* between sensors cancel out the device's transmit power.** A phone at full power and earbuds at low power at the same position produce different absolute RSSI values but the *same* difference pattern. If sensor 1 reads 30 dB stronger than sensor 3, that encodes position — regardless of how loud the device is.

### 2.3 The body shadow problem

When a phone is in someone's pocket, their body attenuates the signal by 10–15 dB toward sensors behind them. This is both a challenge and an opportunity:
- **Challenge:** With 3 sensors, one blocked sensor drops you to 2 usable readings — not enough for reliable pattern recognition.
- **Opportunity:** Body shadowing creates **anisotropic** signal patterns (different in different directions). Outside devices show **isotropic** patterns (similar wall attenuation in all directions). The model can learn this difference.
- **Why 4 sensors:** With 4 sensors in corners, even worst-case body orientation leaves 2–3 clean readings. With 4 sensors you have 6 pairwise differences; losing one sensor still gives you 3 clean pairs.

### 2.4 The neighbor problem

In any apartment or office, 90–95% of BLE devices detected are neighbors' phones, smart TVs, routers, and IoT devices coming through walls. These are **always present**, day and night. Any system that tries to track individual devices must somehow separate the 5% "real" signal from the 95% noise — which is essentially impossible without knowing in advance which MACs belong to occupants.

### 2.5 The MAC rotation problem

Apple devices rotate their BLE MAC address every ~15 minutes. Android devices do similar things. This means you cannot track a device over time by its MAC address. Any approach that builds per-device histories breaks every 15 minutes.

---

## 3. Hardware Architecture

### 3.1 Evolution: v1 → v2

**v1 (BLE-only):**
- Mixed hardware: 2× XIAO ESP32-S3 + 2× ESP32-D0WD classic boards
- BLE scanning only, MQTT publish
- Single MQTT topic: `roomsense/rssi`
- Achieved: 93.8% accuracy (excluding RF-transparent wall)

**v2 (BLE + mmWave radar fusion):**
- Uniform hardware: 4× WR-32 ESP32 boards (CH340C USB, ~$3 each)
- Each board paired with HLK-LD2450 24GHz FMCW radar (~$3–5 each)
- Dual-core: Core 1 = WiFi + BLE + MQTT, Core 0 = LD2450 UART reader
- Two MQTT topics: `roomsense/rssi` (BLE) + `roomsense/radar` (mmWave)
- Purpose: solve the RF-transparent wall problem that BLE alone cannot fix

### 3.2 Default deployment (2-node)

The recommended minimum deployment uses just 2 combo nodes:
- **Hub:** Wall-mounted near one corner. Contains an ESP32+LD2450 strapped to a Raspberry Pi 4B with a 5" DSI screen. Single power cable.
- **Remote:** Opposite corner. One ESP32+LD2450, powered by USB.

Estimated accuracy: 92–94%. Scaling to 4 nodes (all corners) brings accuracy to ~96%.

### 3.3 Why not 3 sensors?

Triangulation with 3 sensors is theoretically sound in free space, but:
1. **Body shadowing kills it.** A phone in a pocket loses 10–15 dB toward sensors behind the person. With 3 sensors, one blocked reading drops below the minimum for reliable triangulation. With 4, you keep 2–3 good readings.
2. **We don't do geometric triangulation.** The system uses ML on RSSI difference patterns, not geometric distance estimation. With 4 sensors you get 6 pairwise differences; losing 1 sensor to body shadow still leaves 3 pairs. With 3 sensors you get 3 pairs — lose one and you have 1 pair, which isn't enough.
3. **BLE RSSI doesn't give reliable distances anyway.** Indoor path loss exponents range from 2.0 to 3.0. Without knowing the exact exponent at every point, geometric triangulation from RSSI has 2–3 meter errors — bigger than most rooms.

### 3.4 Why not the Raspberry Pi as a BLE sensor?

Tested. BlueZ (the Linux Bluetooth stack) is 10–15% worse than ESP32 for BLE scanning — more missed advertisements, less reliable timing. The ESP32's dedicated Bluetooth hardware on Core 1 outperforms it significantly.

### 3.5 Why not battery-powered ESP32?

BLE continuous scanning + WiFi + MQTT draws ~250mA. An 18650 battery (3000mAh) lasts ~13 hours. You can't use sleep modes because the scanner must run continuously. USB power is the only practical option.

### 3.6 Component list

| Component | Model | Qty | Unit Cost | Role |
|-----------|-------|-----|-----------|------|
| Microcontroller | WR-32 ESP32 (CH340C) | 4 | ~$3 | BLE scan + radar reader |
| mmWave radar | HLK-LD2450 (24GHz FMCW) | 4 | ~$3–5 | Human presence detection |
| Brain | Raspberry Pi 4B | 1 | ~$35 | MQTT broker + inference |
| Display | 5" DSI IPS (800×480) | 1 | ~$30 | Dashboard display |
| **Total** | | | **~$70** | |

---

## 4. Firmware Design

### 4.1 Dual-core architecture (wr32_combo.ino)

The ESP32 has two cores. We use both:

**Core 1 (Arduino loop — WiFi + BLE + MQTT):**
- Connects to WiFi at boot, restarts after 30 failed attempts
- Syncs time via SNTP (pool.ntp.org) at boot + hourly resync
- Runs BLE passive scan at ~99% duty cycle (interval 100ms, window 99ms)
- On each BLE advertisement received, publishes to MQTT:
  ```
  roomsense/rssi: SENSOR_ID|mac|rssi|addrType|appearance|mfgHex|svcHex|rxMs|advType
  ```
- Fields: sensor ID, MAC address, RSSI (dBm), address type (0=public, 1=random), GAP appearance code, manufacturer data hex (up to 80 chars), service data hex, timestamp (epoch milliseconds), advertisement type (connectable/non-connectable)

**Core 0 (FreeRTOS task — LD2450 UART reader):**
- Reads LD2450 at 256000 baud on Serial2 (GPIO16=RX, GPIO17=TX)
- Frame format: 4-byte header (`0xAA 0xFF 0x03 0x00`) + 24 bytes data (3 targets × 8 bytes) + 2-byte tail (`0x55 0xCC`)
- Per target: x/y position (signed mm), speed (signed mm/s), distance (unsigned mm)
- Sign convention: bit 15 is sign flag, bits 14–0 are magnitude (not two's complement)
- Publishes to MQTT:
  ```
  roomsense/radar: SENSOR_ID|epochMs|nTargets|x0|y0|spd0|dist0|...|x2|y2|spd2|dist2
  ```

**Thread safety:** A FreeRTOS mutex protects the shared MQTT client. The mutex timeout is 50ms (increased from 5ms after discovering that shorter timeouts caused radar frame drops — the BLE callback on Core 1 was holding the mutex too long).

### 4.2 Configuration per board

Each board needs a unique `SENSOR_ID` defined at compile time:
```c
#define SENSOR_ID "esp_c1"  // Change to esp_c2, esp_c3, esp_c4
```

WiFi and MQTT credentials are in `secrets.h` (gitignored):
```c
#define WIFI_SSID  "MyNetwork"
#define WIFI_PASS  "password"
#define MQTT_HOST  "192.168.1.200"  // Brain IP (change to yours)
```

### 4.3 Flash command

```bash
arduino-cli compile --fqbn esp32:esp32:esp32:PartitionScheme=huge_app src/wr32_combo/
arduino-cli upload  --fqbn esp32:esp32:esp32:PartitionScheme=huge_app -p /dev/ttyUSB0 src/wr32_combo/
```

The `huge_app` partition scheme gives 3MB for the firmware (vs 1.3MB default), needed because BLE + WiFi + MQTT libraries are large.

---

## 5. The ML Journey: Four Attempts

### 5.1 Attempt 1: Single sensor (abandoned)

**Approach:** One ESP32, threshold on RSSI to classify inside/outside.

**Result:** Impossible. A phone inside at -65 dBm and a neighbor's phone outside at -65 dBm are indistinguishable. The RSSI distributions overlap completely. No threshold works.

**Lesson:** A single sensor measures distance, not direction. You need multiple viewpoints to determine which side of a wall a device is on.

### 5.2 Attempt 2: Beacon-trained model with 4 sensors (worked for beacon, failed for real devices)

**Approach:** Carry a dedicated BLE beacon (an ESP32 that broadcasts at known power) to ~12 positions inside and outside the room. Train a Random Forest on per-device RSSI features.

**Result on beacon data:** Excellent. 3.9% wall false-positive rate, 95.7% pocket recall. LOPO cross-validation.

**Result on real devices:** AUC = 0.586 (barely above random). The model genuinely cannot distinguish inside from outside for real phones and earbuds.

**Why it failed:**
1. **The model learned "loud = inside."** Top features were all absolute RSSI values (`rssi_max__esp_c3`, `rssi_vec_max`). The beacon broadcasts at consistent high power. Inside positions are close to sensors = loud. Real phones are in pockets (10–15 dB body shadow), have different transmit powers, different antennas. A real phone inside can be quieter than the beacon was outside.

2. **Differential features failed too.** We tried removing absolute RSSI and keeping only cross-sensor differences. AUC dropped from 0.586 to 0.424 — worse. The signal geometry itself was domain-shifted (a beacon sitting on a desk vs a phone in a pocket produce fundamentally different spatial patterns).

3. **Real devices have partial hearing.** The beacon was heard by all sensors 97% of the time. Real phones in pockets were heard by all sensors only 72% of the time. The model never trained on these partial-hearing patterns.

**Lesson:** Models trained on beacon data don't transfer to real devices. The domain shift is too large.

### 5.3 Attempt 3: Per-device tracking on real devices (56.3% accuracy)

**Approach:** Instead of using a beacon, train on ALL BLE devices heard during labeled time windows. For each MAC address, build a feature vector from its RSSI across all 4 sensors.

**Result:** 56.3% accuracy. Catastrophic failure.

**Why it failed:**
1. **Neighbor poisoning:** During a "room is occupied" training window, 95% of detected MACs are actually neighbors' phones, routers, and smart TVs through the walls. These get labeled "inside" even though they're outside. The model learns the stationary neighbor signature, not occupancy geometry.

2. **Sparse signal:** The user's carried devices (phone, earbuds) produce only ~500 readings out of 50,000+ total readings. The signal-to-noise ratio is terrible.

3. **MAC rotation:** Apple devices change their MAC every ~15 minutes. You can't build temporal profiles across rotations.

**Lesson:** Per-device tracking is fundamentally broken for this problem. You cannot separate your devices from neighbors' devices without prior knowledge of which MACs are yours — and that violates privacy.

### 5.4 Attempt 4: Environment-level features (93.8% accuracy — current approach)

**Approach:** Stop tracking individual devices entirely. Instead, measure the room's aggregate BLE environment and ask: "Does this room look occupied?"

**Core insight:** When a person walks into a room with their phone and earbuds, the BLE environment changes in predictable ways:
- More strong signals appear on nearby sensors
- The RSSI distribution shifts upward on sensors close to the person
- The sensor closest to the person sees disproportionately more strong devices
- The total count of strong BLE emitters changes

These changes are the same whether the phone has rotated its MAC or not. We don't track any individual device — we look at aggregate statistics across ALL devices in the BLE landscape.

**Result:** 93.8% accuracy (LOPO cross-validation, excluding RF-transparent wall). 83.8% including all positions. 100% presence accuracy in live manual testing.

**Why it works:**
- **Immune to MAC rotation:** Features aggregate across ALL devices, so rotation has zero impact
- **Immune to neighbor poisoning:** Neighbors are part of the room's steady-state BLE landscape; a person entering changes the landscape relative to this baseline
- **Immune to transmit power variance:** Cross-sensor difference features cancel out device-specific transmit power
- **Strong signal:** Instead of trying to find 5% signal in 95% noise, the environment approach uses ALL the data — the shift in the aggregate distribution IS the signal

---

## 6. Feature Engineering (Current v3_env)

### 6.1 Aggregation windows

Features are computed over 20-second sliding windows with 50% overlap (configurable via `AGG_WINDOW_S` and `AGG_OVERLAP` in config.py).

Why 20 seconds:
- Averages over ~200+ BLE channel rotation cycles (BLE alternates channels 37/38/39 at ~10Hz per device)
- Mitigates deep fading (Rayleigh fading causes ±6 dB variations)
- Produces ~200 BLE packets per sensor per window — enough for reliable statistics
- Acceptable latency for a traffic-light display

### 6.2 Per-sensor features (8 × N sensors)

For each sensor in each window:

| Feature | Description | Why it matters |
|---------|-------------|----------------|
| `env_median` | Median RSSI of all devices | Central tendency of signal landscape |
| `env_iqr` | Interquartile range | Signal spread (more devices nearby = wider) |
| `env_max` | Maximum RSSI | Strongest device (proximity indicator) |
| `env_min` | Minimum RSSI | Weakest device (noise floor indicator) |
| `env_pkt_count` | Total BLE packets received | Activity level |
| `env_mac_count` | Unique MAC addresses | Device density |
| `env_strong80` | Devices with RSSI > -80 dBm | Nearby device count (moderate range) |
| `env_strong70` | Devices with RSSI > -70 dBm | Very nearby device count (close range) |

### 6.3 Cross-sensor features (11 features)

| Feature | Description | Why it matters |
|---------|-------------|----------------|
| `env_total_macs` | Total unique devices across all sensors | Global device density |
| `env_total_pkts` | Total BLE packets across all sensors | Global activity level |
| `env_mac_spread` | Max − min of per-sensor `mac_count` | Asymmetry indicator (inside = asymmetric) |
| `env_strong80_spread` | Max − min of per-sensor `strong80` | Asymmetry of nearby devices |
| `env_top3_delta__sA__sB` | Difference in top-3 median RSSI between sensor pairs | **The spatial fingerprint** — this is the most important feature set |
| `env_loudest__s` | One-hot: which sensor sees the strongest signal | Position quadrant indicator |
| `env_global_max` | Strongest RSSI across all sensors | Proximity ceiling |

**Why `top3_delta` is the key feature:**

For each sensor, take the 3 strongest devices' median RSSI (called `env_top3_median`). Then for each pair of sensors (6 pairs with 4 sensors), compute the difference: `top3_median_sensorA - top3_median_sensorB`.

This captures where in the room the strongest signals are concentrated. If a person is near corner 1:
- Sensor 1's top3 median is high (say -55)
- Sensor 3's top3 median is lower (say -72)
- Delta = +17

A different person with a quieter phone at the same spot:
- Sensor 1: -68, Sensor 3: -85
- Delta = +17 (same!)

The delta is TX-power-invariant. It encodes position geometry.

### 6.4 Temporal derivative features

| Feature | Description |
|---------|-------------|
| `env_median_delta__s` | Change in per-sensor median from previous window |
| `env_pkt_rate_delta__s` | Change in packet count from previous window |

These capture motion and transitions. A person entering causes a rapid increase in median RSSI on nearby sensors.

### 6.5 Baseline deviation features (optional)

If an empty-room baseline has been captured:

| Feature | Description |
|---------|-------------|
| `bdev_*` | Z-score deviation from empty-room medians using MAD scale |

Formula: `z = (value - baseline_median) / (MAD * 1.4826)`

This tells the model "how different is this window from what the room looks like when empty?" — a direct anomaly detection signal.

### 6.6 Feature fillna strategy

**Critical implementation detail:** RSSI features use -120 dBm as fill value (below ESP32 detection floor of -95 dBm). Radar features use 0. Using -120 for radar features was a bug that poisoned the radar signal — fixed 2026-06-23.

---

## 7. Calibration

### 7.1 The problem

Different ESP32 chips have different RSSI biases due to manufacturing variance, antenna placement, and local RF environment. Measured offsets in our deployment ranged from -2.5 to +1.0 dB. Without calibration, cross-sensor comparisons (the foundation of our spatial fingerprint) are unreliable.

### 7.2 The original plan (failed)

Use the laptop as a BLE beacon at known positions. This requires root/sudo on Linux (D-Bus restriction on BLE advertising). Tried bluetoothctl, D-Bus API, raw HCI — all require elevated privileges.

### 7.3 The solution: shared-device auto-calibration

Instead of a dedicated beacon, use the ~20–30 neighbor BLE devices already visible to all 4 sensors as natural reference points:

1. Subscribe to MQTT for 60 seconds
2. Find all BLE devices heard by ALL sensors simultaneously
3. For each shared device, compute per-sensor median RSSI
4. Per-sensor offset: `offset[i] = global_median_across_all_shared_devices - sensor_i_median`
5. Apply offset to all future RSSI readings

**Why this works:** A neighbor's router at a fixed position should read roughly the same RSSI on all sensors (after accounting for distance differences). The per-sensor offsets capture the hardware bias.

**Why this is actually better than a beacon:** Uses real-world signals from real positions, not a single test beacon at a few positions. More robust calibration.

**Measured offsets (2026-06-20):**
- esp_c1: -2.5 dBm
- esp_c2: +0.31 dBm
- esp_c3: +1.0 dBm
- esp_c4: +0.75 dBm

### 7.4 Co-hearing alignment

Before computing cross-sensor features, readings must be aligned in time. A device heard by sensor 1 at time T might be heard by sensor 2 at time T+50ms (different BLE advertising channel, different propagation path).

**Co-hearing window:** W = 200ms (configurable). For each device at time T, find each sensor's nearest reading within [T-100ms, T+100ms]. Missing sensors get NaN (not backfilled with -120 sentinel — important distinction).

This produces a per-device, per-moment RSSI vector across all sensors — the input to cross-sensor features.

---

## 8. Training Pipeline

### 8.1 Data collection

The user walks through labeled positions using `collect_walk.py`:
```
mark CENTER in        # Stand at room center
mark NEAR_WALL_C2 in  # Stand near the C2 wall
mark OUT_DOOR out     # Stand outside the door
stop                  # Stop collection
```

Each position: 60–90 seconds. All BLE readings recorded with timestamps + position labels. Three collection rounds for robustness (different times = different BLE ambient conditions).

**Critical addition:** After initial training failed on phone-only scenarios, added dedicated positions:
- `CENTER_PHONE_ONLY` — earbuds removed
- `CENTER_AIRPODS_ONLY` — phone removed
- `EMPTY_ROOM` — no devices present

### 8.2 Cross-validation: Leave-One-Position-Out (LOPO)

Standard train/test splitting would leak temporal information — BLE readings within a position are highly correlated (same ambient, same channel conditions). Random splits would overestimate accuracy.

**LOPO:** Train on 7 positions, test on the 8th, rotate through all 8. Each fold tests on a position the model has never seen. This gives a conservative, realistic accuracy estimate.

### 8.3 Model training

**Default: Random Forest** (300 trees, 500 estimators in report — both configurations tested)
- Robust to noisy features
- No hyperparameter sensitivity
- Fast training on small datasets (~200 samples)

**Optional: LightGBM** (`--lgbm` flag)
- Gradient-boosted trees, generally +2–4% accuracy improvement
- **Monotone constraints:** `env_median__*` features get constraint -1 (higher RSSI = closer = more likely inside). This enforces physics, prevents the model from learning spurious inverse correlations.
- Expected to improve wall boundary accuracy

### 8.4 Threshold selection

Default: 0.50 (empirically optimal for 95% pocket recall). The threshold balances:
- **False negatives** (missing a person in the room) — higher threshold = more missed
- **False positives** (detecting a person who's outside) — lower threshold = more false alarms

### 8.5 Conformal prediction (MAPIE)

Optional uncertainty quantification:
- Uses MAPIE's `SplitConformalClassifier` with LAC (Least Ambiguous Class) conformity score
- Calibration set: 20% of training data, stratified by position
- Coverage: 90% (alpha=0.10)
- Output: for each prediction, a set of possible labels. If the set has more than 1 label, the prediction is "uncertain"
- In live inference: `uncertain` field in API response indicates low-confidence predictions

### 8.6 Model output

Saved as `models/model.joblib`:
```python
{
    "model": <RandomForest or LGBMClassifier>,
    "columns": [...],           # Feature column names (for train/serve consistency)
    "threshold": 0.50,
    "version": "v3_env",
    "feature_type": "env",
    "has_radar": True/False,
    "algorithm": "rf" or "lgbm"
}
```

A consistency test (`test_train_serve.py`) verifies that the feature columns used in training match those produced during live inference — preventing train/serve skew.

---

## 9. Device Identification & Deduplication

### 9.1 The device counting problem

When the room is occupied, we want to report *what* devices are present (e.g., "2 phones, 1 earbuds"). This requires:
1. **Classification:** What type of device is this? (phone, earbuds, watch, laptop)
2. **Deduplication:** A single iPhone broadcasts from 3 different MAC addresses simultaneously (different Apple Continuity protocol types). Without dedup, 1 iPhone looks like 3 phones.

### 9.2 Device type classification (device_id.py)

Classification hierarchy (highest priority first):

1. **GAP Appearance codes** — standardized Bluetooth categories
   - 0x0040 → phone, 0x0080 → laptop, 0x00C0 → watch, 0x0841 → earbuds

2. **Google Fast Pair** — Service UUID 0xFE2C with short payload → earbuds

3. **Apple Continuity** — Manufacturer data with company ID 0x004C (Apple)
   - Parse TLV (Type-Length-Value) structure:
   - Type 0x02 (iBeacon) → "beacon" — fixed infrastructure, not a person
   - Type 0x01/0x03/0x06/0x09 (AirPrint/AirPlay/HomeKit/AirPlay Target) → "infra" — infrastructure devices
   - Type 0x0A (Watch Magic Switch) → "watch"
   - Type 0x07 (AirPods proximity) → "earbuds"
   - Type 0x12 (Find My) → "tracker" — AirTags, not people (unless attached to keys)
   - Type 0x10 (Nearby Info) → "phone" — the primary phone advertisement

4. **Manufacturer ecosystems**
   - Samsung (0x0075) → "earbuds_or_galaxy"
   - Microsoft (0x0006) → "laptop_or_pc"

5. **Service UUIDs**
   - 0x1812 (HID) → "keyboard_or_mouse"
   - 0x180D (Heart rate) → "watch"

6. **Address type fallback** — Random/RPA addresses → "phone" (modern personal device heuristic)

7. **Fallback** → "unknown"

**Privacy boundary:** This function returns a category string only, never any identifying information.

### 9.3 RPA deduplication (dedup.py)

Modern devices use Resolvable Private Addresses (RPAs) that rotate every ~15 minutes. The dedup layer links rotating MACs into stable device counts without storing identities.

**How it works:**

1. New MAC arrives with its per-sensor RSSI vector and device category
2. Check for recently-departed MACs (gone 2–60 seconds) that could be the same device:
   - Same device category (phone≠earbuds)
   - If both have known BLE advertising intervals: intervals within 20% (stable across rotations)
   - RSSI vector similarity: Euclidean distance < 6 dB across shared sensors
3. If match found: merge new MAC into the old canonical MAC
4. Return canonical MAC for counting

**Entries are volatile:** TTL'd at 60 seconds (TODO: increase to 900 seconds for 15-minute rotation cycles). Never serialized to disk. Never leave the dedup layer.

### 9.4 Continuity-aware device counting

The final counting step handles Apple's multi-MAC broadcasting:

1. Filter to devices with median RSSI > -85 dBm (proximity threshold)
2. Group by device category
3. Within each category, cluster by RSSI spatial similarity (RMSE < 6 dB across sensors)
4. **Critical rule:** If two MACs broadcast the **same** Apple Continuity type → they are **different physical devices** (one phone cannot broadcast type 0x10 from two MACs simultaneously)
5. If **different** Continuity types + similar RSSI → **same device** (typical: iPhone broadcasts from 3 MACs with types 0x10, 0x09, 0x12)

Output: `{"phone": 2, "earbuds": 1}` — no MAC exits this function.

### 9.5 Advertising interval fingerprinting (adv_interval.py)

BLE advertising interval is device-specific and stable across MAC rotations. A phone that advertises every 200ms will still advertise every 200ms after rotating its MAC.

The `AdvertisingIntervalEstimator`:
- Maintains per-(MAC, sensor) observation buffers (120-second sliding window)
- Computes inter-arrival deltas, filters outliers (keep ≤ 2× median)
- Estimates interval as median of filtered deltas
- Confidence: min(1.0, n_samples / 20)

Used by RPADedup as an additional merge constraint: if two MACs have known intervals that differ by >20%, they are different devices — block the merge.

---

## 10. mmWave Radar Fusion (v2)

### 10.1 Why radar?

The C2-C3 wall in the test room has ~0 dB BLE attenuation — RF-transparent at 2.4 GHz. BLE alone cannot distinguish inside from outside this wall (78% accuracy vs 93.8% elsewhere).

Radar operates at 24 GHz — different physics, different propagation, complementary information. The LD2450 detects humans through micro-motion (breathing, subtle body movement).

### 10.2 LD2450 specifications

| Parameter | Value |
|-----------|-------|
| Frequency | 24 GHz FMCW |
| Max targets | 3 simultaneous |
| Output per target | x, y (mm), speed (mm/s), distance (mm) |
| FOV | 120° horizontal, 70° vertical |
| Range | Up to 6m |
| Update rate | ~10 fps |
| Drywall penetration | 1–3 dB (nearly transparent) |
| Concrete | 20–30 dB (blocks radar) |
| Metal | >40 dB (completely blocks) |

**Critical finding:** The LD2450 DOES penetrate drywall (1–3 dB loss). This was initially documented as "does not penetrate" and corrected during the deep research session. This means radar alone can't solve the wall problem through attenuation — we need geometric features (is the target inside or outside room bounds?).

### 10.3 Radar features (radar_features.py)

**Per-sensor features (9 × N sensors):**

| Feature | Description |
|---------|-------------|
| `radar_max_targets__s` | Max targets in any frame during window |
| `radar_mean_targets__s` | Average target count |
| `radar_frac_occupied__s` | Fraction of frames with ≥1 target |
| `radar_mean_dist__s` | Mean distance to targets |
| `radar_min_dist__s` | Minimum distance |
| `radar_dist_std__s` | Distance standard deviation |
| `radar_mean_speed__s` | Mean absolute speed |
| `radar_max_speed__s` | Maximum speed |
| `radar_x_spread__s` | Horizontal spread (max-min x coordinate) |

**Cross-sensor features (4):**

| Feature | Description |
|---------|-------------|
| `radar_total_max_targets` | Max targets across all sensors |
| `radar_n_sensors_occupied` | Sensors with frac_occupied > 0.5 |
| `radar_dist_spread` | Max-min of per-sensor mean distances |
| `radar_consensus_occupied` | Fraction of sensors seeing targets |

### 10.4 Planned: radar geometric features

The real power of radar for the wall problem isn't signal strength — it's geometry:
- Each sensor has a known position and orientation in the room
- Radar gives target coordinates in the sensor's local frame
- Transform to room coordinates: `local_to_room()` via rotation + translation
- **Key feature:** Is the target inside or outside room bounds?
- Multi-sensor triangulation consistency: do different sensors agree on target position?

Expected improvement: +8–15% on RF-transparent wall accuracy.

---

## 11. Live Inference Pipeline

### 11.1 Architecture (live_ble.py)

```
MQTT (roomsense/rssi + roomsense/radar)
    │
    ▼
┌─────────────────────────┐
│ Ingest Thread            │
│ - Parse MQTT messages    │
│ - Apply RSSI calibration │
│ - Buffer (40s rolling)   │
│ - Update adv interval    │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ Evaluation Thread (~1-2s)│
│ - Extract env features   │
│ - Model predict_proba    │
│ - EMA smooth probability │
│ - Count nearby devices   │
│ - Update display state   │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ Flask API + Web UI       │
│ GET /api/census          │
│ POST /api/baseline       │
│ GET / (census.html)      │
└─────────────────────────┘
```

### 11.2 EMA smoothing

Raw model output fluctuates. Exponential moving average stabilizes the display:

```
smoothed = 0.4 × new_prob + 0.6 × previous_smoothed
```

Trade-off: stability vs latency. Current settings produce:
- Entry detection: ~10 seconds
- Exit detection: ~25 seconds (asymmetric — takes longer to "forget" a person)

### 11.3 Display voting (VOTE_OF_N)

Device count display uses 3-of-5 voting: keep the last 5 count evaluations, show the count only if ≥3 agree. This prevents flicker between, say, 2 and 3 devices when multi-MAC dedup is borderline.

### 11.4 Sensor health monitoring

Each sensor's last-packet timestamp is tracked. If a sensor is silent for 2× WINDOW_S (40 seconds), it's marked "offline." Health status is included in the `/api/census` response and displayed as colored dots in the web UI.

---

## 12. Privacy Architecture

### 12.1 Design principle

Privacy is **structural**, not **policy**. The system is architecturally incapable of leaking identities, regardless of who operates it.

### 12.2 Data flow

```
BLE advertisement (contains MAC address)
    │
    ▼
Ingest buffer (volatile RAM, 40s TTL)
    │
    ├──▶ Environment features (aggregates across ALL devices, no per-device data)
    │     │
    │     ▼
    │     Model prediction: room_prob (scalar float)
    │
    └──▶ Dedup layer (volatile RAM, 60s TTL)
          │
          ▼
          count_nearby_devices() → {"phone": 2, "earbuds": 1}
          (NO MAC exits this function)
          │
          ▼
          Flask API → Web UI
```

### 12.3 Privacy guarantees

| Layer | Guarantee |
|-------|-----------|
| **Features** | Environment-level: aggregate stats across ALL devices, no per-device features |
| **Dedup** | Volatile, TTL'd, never serialized to disk |
| **Disk writes** | MACs hashed (SHA-256 + salt, truncated to 12 chars) before any CSV write |
| **API** | Returns only `{category: count}` — structurally cannot return identities |
| **Web UI** | Cannot render identity fields (they don't exist in the API response) |
| **Cross-session** | No persistent fingerprinting database. Each power cycle resets RPA state |

### 12.4 What it does NOT do

- Does not defeat MAC randomization
- Does not fingerprint devices across sessions
- Does not correlate device presence with user identity
- Does not store raw MAC addresses on disk
- Does not make any outbound network connections (runs fully local)

---

## 13. RF Physics Reference

### 13.1 Key numbers

| Parameter | Value |
|-----------|-------|
| BLE path loss exponent (indoor) | 2.0–3.0 |
| BLE advertising channels | 37 (2402 MHz), 38 (2426 MHz), 39 (2480 MHz) |
| Body shadowing @ 2.4 GHz | 10–15 dB attenuation |
| Drywall attenuation @ 2.4 GHz | <1–3 dB (nearly transparent) |
| Concrete @ 2.4 GHz | 10–15 dB |
| RSSI standard deviation (moving people) | 4–8 dBm |
| ESP32 RSSI accuracy | ±6 dBm absolute, ±1–2 dBm relative |
| ESP32 detection floor | -90 to -95 dBm (hard cutoff) |
| Drywall @ 24 GHz (radar) | 1–3 dB (also nearly transparent) |
| Concrete @ 24 GHz | 20–30 dB (blocks radar) |
| Metal @ 24 GHz | >40 dB (completely blocks) |
| LD2450 range resolution | 0.75m practical |
| LD2450 angular accuracy | ±2° boresight, ±20° at edges |

### 13.2 Why RSSI is noisy

Several factors make raw RSSI readings unreliable:

1. **Multipath fading (Rayleigh):** Radio waves bounce off walls, furniture, people. At 2.4 GHz (wavelength ~12.5 cm), moving a device by 6 cm can cause ±10 dB variations as reflected paths constructively or destructively interfere.

2. **Channel variation:** BLE advertising alternates between 3 channels (2402/2426/2480 MHz). Each channel sees different multipath. ESP32 doesn't expose which channel a reading came from.

3. **Body shadowing:** 10–15 dB variation depending on body orientation relative to sensor.

4. **Transmit power diversity:** An iPhone may broadcast at 0 dBm, AirPods at -6 dBm, a smartwatch at -12 dBm. Same position, different absolute RSSI.

5. **Manufacturing variance:** Even identical ESP32 boards show ±3 dB bias differences.

**Mitigation strategy:** 20-second aggregation windows average over all of these sources, producing stable statistics. Cross-sensor differences cancel transmit power and much of the manufacturing variance.

### 13.3 Why the C2-C3 wall is a problem

The wall between positions C2 and C3 in the test room has ~0 dB BLE attenuation. The signal passes through as if the wall weren't there. This means:
- A device inside near this wall produces the exact same RSSI pattern as a device outside near this wall
- No amount of BLE ML can distinguish them — the physics provides zero discriminating signal
- Accuracy on this wall: 78% (vs 93.8% on other walls)

This is physics, not a software bug. The solution is a different sensing modality (radar geometric features) or a different physical sensor (PIR motion, which cannot penetrate any wall).

---

## 14. Problems Encountered & Solutions

### Problem 1: Calibration without root access

**What happened:** Planned to use the laptop as a BLE calibration beacon. BLE advertising requires root/sudo on Linux.

**Solution:** Invented "shared-device" auto-calibration — use 20+ neighbor BLE devices visible to all sensors as natural reference points. Zero setup, actually more robust than a single beacon.

### Problem 2: Beacon model doesn't transfer (AUC 0.586)

**What happened:** Model trained on beacon data worked perfectly for the beacon but couldn't classify real phones/earbuds.

**Root cause:** The model learned "loud = inside" from the high-power beacon. Real devices have variable power, body shadowing, partial hearing.

**Solution:** Abandoned per-device tracking entirely. Environment-level features don't need to identify any specific device.

### Problem 3: Per-device tracking fails (56.3%)

**What happened:** Training on all visible BLE devices during labeled windows.

**Root cause:** 95% of visible devices are neighbors — labeled as "inside" when they're actually outside.

**Solution:** Environment-level features (see Attempt 4 above).

### Problem 4: Satellite clock drift (541 seconds)

**What happened:** ESP32 SNTP timestamps were ~541 seconds behind system time. The live inference buffer trimmed all data as "too old," producing room_prob = 0.0 constantly.

**Root cause:** SNTP sync only at boot, no periodic resync. Over hours, the ESP32's crystal oscillator drifts.

**Solution:** (1) Added hourly SNTP resync to firmware. (2) Use brain-arrival time for live buffering (the brain's clock is reliable). Satellite timestamps are only used for training data (where drift is consistent within a session).

### Problem 5: Phone-only detection fails

**What happened:** Model trained with 2 iPhones + AirPods together. Tested with just 1 iPhone (AirPods removed): room_prob dropped to 0.28 ("quiet").

**Root cause:** Model learned "occupied = strong70 count 2–4." With only a phone, strong70 = 0 (phone broadcasts weaker than earbuds at close range because earbuds broadcast from both ears).

**Solution:** Collected additional training data: phone-only, earbuds-only, empty room. After retraining, both scenarios detect at 95%.

### Problem 6: iPhone double-counting

**What happened:** One iPhone counted as 2–3 separate phones.

**Root cause:** iPhones broadcast from multiple MACs simultaneously using different Apple Continuity protocol types (Nearby Info, AirPlay, Handoff). Without dedup, each MAC looks like a separate phone.

**Solution:** Continuity-type-aware dedup. Same type = different device. Different types + similar RSSI = same device. (See Section 9.4)

### Problem 7: RF-transparent wall (physics limitation)

**What happened:** 78% accuracy on the C2-C3 wall vs 93.8% elsewhere.

**Root cause:** Wall has ~0 dB BLE attenuation. Physics ceiling — no BLE-only solution exists.

**Planned solution:** Radar geometric features (target inside/outside room bounds). PIR sensors ($2 each, cannot penetrate any wall). Expected improvement: +8–15%.

### Problem 8: Radar frame drops

**What happened:** LD2450 radar data was arriving corrupted — frames were being dropped.

**Root cause:** The FreeRTOS mutex that protects the shared MQTT client had a 5ms timeout. BLE callbacks on Core 1 sometimes held the mutex for >5ms, causing the radar task on Core 0 to fail to publish and eventually overflow the UART buffer.

**Solution:** Increased mutex timeout from 5ms to 50ms. Radar frame integrity verified.

### Problem 9: Broken RPADedup spatial comparison

**What happened:** RPA dedup was merging devices that were in different locations.

**Root cause:** The per-sensor RSSI vector passed to the dedup function was a 1D scalar (just the most recent RSSI) instead of an N-sensor vector. Spatial comparison was meaningless.

**Solution:** Fixed to pass proper 4-sensor RSSI vector. Spatial dedup now works correctly.

### Problem 10: Wrong fillna for radar features

**What happened:** Radar features were being poisoned during training.

**Root cause:** Both RSSI and radar features used `fillna(-120)`. For RSSI, -120 dBm is below the detection floor and makes sense as "not heard." For radar, -120 is meaningless and creates a strong false signal.

**Solution:** Split fillna: RSSI features get -120, radar features get 0.

---

## 15. Results

### 15.1 Model accuracy (LOPO cross-validation, v3_env)

| Metric | Value |
|--------|-------|
| Accuracy (all positions) | 83.8% |
| Accuracy (excl. C2-C3 wall) | **93.8%** |
| Phone-only detection | 95% |
| Earbuds-only detection | 95% |
| Empty room (no false positives) | 100% |
| Training samples | ~377 windows from 199,692 BLE readings |
| Positions | 8 labeled + 3 supplementary (phone-only, earbuds-only, empty) |

### 15.2 Live manual testing (2026-06-20)

| Scenario | Presence | Detection Time | Device Count |
|----------|----------|---------------|--------------|
| 2 iPhones + AirPods (inside) | 0.98 (present) | <1s (warm) | 3/3 correct |
| All devices outside | 0.02 (quiet) | <5s | 0 (zero FP) |
| Single iPhone | 0.94 (present) | <5s | 1/1 correct |
| iPhone + AirPods | 0.88 (present) | ~5s | 2/2 (occasional flicker to 3) |
| 2 iPhones + AirPods | 0.95 (present) | <5s | 3/3 (occasional flicker to 4) |
| Entry transition | → present | ~10s | — |
| Exit transition | → quiet | ~25s | — |

**Summary:** 100% presence accuracy across all scenarios. Device counting correct ±1. Zero false positives in empty room.

### 15.3 Per-position accuracy

| Position | Accuracy | Notes |
|----------|----------|-------|
| CENTER | ~99% | Easiest — strong signal on all sensors |
| NEAR_WALL_C1_C2 | >95% | Standard wall with attenuation |
| NEAR_WALL_C3_C4 | >95% | Standard wall |
| NEAR_WALL_C4_C1 | >95% | Standard wall |
| OUT_DOOR | 100% | Door provides good signal boundary |
| OUT_SHARED_WALL_C3_C4 | >90% | Standard wall |
| **OUT_SHARED_WALL_C2_C3** | **~60%** | **RF-transparent wall — physics limit** |

### 15.4 Code quality

- 152 automated tests, all passing
- Coverage: features, radar, dedup, device ID, calibration, baseline, co-hearing, aggregation, transfer features, training consistency
- LOPO cross-validation (no temporal leakage)
- Train/serve consistency test (feature columns match between training and inference)

---

## 16. Known Limitations & Next Steps

### 16.1 Current limitations

| Limitation | Impact | Cause | Mitigation |
|------------|--------|-------|------------|
| RF-transparent wall | 78% accuracy on one wall | Physics (~0 dB attenuation) | Radar geometric features |
| Device count flicker | ±1 device occasionally | Apple multi-MAC broadcasting | Improved dedup heuristics |
| Exit latency | ~25 seconds | EMA smoothing (0.4/0.6) | Adjustable alpha, trade stability for speed |
| BLE channel confound | ~2-4% accuracy loss | ESP32 doesn't expose channel per packet | 20s window averaging |
| Single-room design | One brain per room | Architecture assumes single boundary | Multi-room extension needed |

### 16.2 Planned improvements (priority order)

1. **Radar geometric features** (+8-15% wall accuracy) — coordinate transforms, room bounds checking, multi-sensor triangulation consistency
2. **PIR sensors** (+5-10% wall accuracy, $2/node) — motion detection that cannot penetrate walls
3. **More training data** (+5-10%) — 30+ positions (vs current 18), especially around problematic walls
4. **Room heatmap visualization** — BLE weighted centroid + radar coordinate overlay
5. **Device-to-person ratio learning** — use radar person count as ground truth
6. **Wi-Fi probe sniffing** — additional device fingerprinting from WiFi probe requests
7. **Active BLE mesh** — inter-sensor RSSI measurement for body shadow detection

---

## 17. Deployment

### 17.1 RPi 4B deployment (scripts ready)

```bash
# 1. Flash firmware to each ESP32 (change SENSOR_ID per board)
arduino-cli upload --fqbn esp32:esp32:esp32:PartitionScheme=huge_app \
  -p /dev/ttyUSB0 src/wr32_combo/

# 2. Copy to RPi
rsync -av --exclude .venv . <brain-user>@<brain-ip>:/opt/roomsense/

# 3. Run setup (installs Mosquitto, Python, systemd service)
sudo bash /opt/roomsense/deploy/setup-rpi.sh

# 4. Copy trained model
cp models/model.joblib /opt/roomsense/models/

# 5. Start
sudo systemctl start roomsense

# 6. Optional: enable kiosk mode (5" screen)
bash /opt/roomsense/deploy/kiosk.sh
```

### 17.2 Systemd service

The service runs as a dedicated `sentinel` user with no login shell. Auto-restarts on failure. Logs to journalctl.

### 17.3 Web UI

Dashboard at `http://<rpi_ip>:8080`:
- Traffic light indicator (quiet/present/busy)
- Device count by category
- Room probability bar
- Per-sensor health dots
- Manual baseline capture button

---

## 18. Quick Reference: Key Numbers

| What | Number |
|------|--------|
| Hardware cost (full system) | ~$70 |
| Sensors needed (minimum) | 2 (hub + remote) |
| Sensors needed (maximum accuracy) | 4 (all corners) |
| Accuracy (excluding transparent wall) | 93.8% |
| Accuracy (all positions) | 83.8% |
| Entry detection time | ~10 seconds |
| Exit detection time | ~25 seconds |
| BLE packets per sensor per 20s window | ~200 |
| Body shadow attenuation | 10–15 dB |
| RSSI measurement noise (std dev) | 4–8 dBm |
| ESP32 detection floor | -90 to -95 dBm |
| LD2450 range | up to 6m |
| LD2450 drywall penetration | 1–3 dB |
| Aggregation window | 20 seconds |
| Co-hearing alignment window | 200 ms |
| RPA rotation period (Apple) | ~15 minutes |
| Number of automated tests | 152 |
| Training data | 199,692 BLE readings |
| Training positions | 8 + 3 supplementary |
| Feature count (env, 4 sensors) | ~50 |

---

## Appendix A: RF & Radio Physics Deep Dive

*Everything you need to hold your ground in a debate about radio propagation, RSSI, and indoor sensing.*

### A.1 What is RSSI, really?

RSSI (Received Signal Strength Indicator) is the power of a received radio signal, measured in **dBm** (decibels relative to 1 milliwatt). The dBm scale is logarithmic:

| dBm | Power | Meaning |
|-----|-------|---------|
| 0 dBm | 1.0 mW | Strong, very close transmitter |
| -30 dBm | 1.0 μW | Very close (~1m, line of sight) |
| -50 dBm | 10 nW | Same room, close |
| -70 dBm | 0.1 nW | Same room, far corner |
| -90 dBm | 1 pW | Through walls, near detection limit |
| -100 dBm | 0.1 pW | Below most receivers' sensitivity |

**Key property of dBm:** Every 10 dB = 10× power. Every 3 dB = 2× power. A -60 dBm signal has 10× the power of a -70 dBm signal. This is why you can't take arithmetic means of dBm values — they're logarithmic. Median is the correct central tendency (which is why we use it).

### A.2 The Log-Distance Path Loss Model

The fundamental equation for indoor radio propagation:

```
RSSI = TX_power - PL(d)
PL(d) = PL(d₀) + 10·n·log₁₀(d/d₀) + X_σ
```

Where:
- `TX_power`: transmitter power (device-specific, unknown, 0 to -20 dBm for BLE)
- `PL(d₀)`: path loss at reference distance d₀ (typically 1 meter, ~40 dB at 2.4 GHz)
- `n`: **path loss exponent** (the key parameter)
- `d`: distance in meters
- `X_σ`: log-normal shadow fading (random variable, σ = 4–8 dB indoors)

**Path loss exponents:**

| Environment | n |
|-------------|---|
| Free space | 2.0 |
| Open office | 2.0–2.5 |
| Residential room | 2.5–3.0 |
| Cluttered indoor | 3.0–4.0 |
| Through 1 wall | 3.5–5.0 |

**Why this matters for RoomSense:**
- At n=2.5, doubling distance loses ~7.5 dB. That's within the noise margin (σ = 4–8 dB).
- At 5 meters, the RSSI difference between n=2.0 and n=3.0 is 7 dB — enormous, but you don't know n in advance.
- This is why RSSI → distance conversion is unreliable indoors (±2–3 meter errors).
- Our system sidesteps this entirely by using **difference patterns** between sensors, not absolute distances.

### A.3 Multipath Fading (Rayleigh Fading)

Radio waves don't travel in a straight line indoors. They reflect off walls, floors, ceilings, furniture, and people. At the receiver, the direct signal and all reflections combine. Sometimes they add up (constructive interference = stronger signal), sometimes they cancel out (destructive interference = weaker signal).

**The physics:** At 2.4 GHz, the wavelength is ~12.5 cm. Moving a device by half a wavelength (~6 cm) can change RSSI by 20+ dB as the phase relationship between direct and reflected paths changes.

**Rayleigh fading statistics:**
- Follows a Rayleigh distribution (when no dominant line-of-sight path exists)
- 10% of the time, the signal is >10 dB below its mean — called a "deep fade"
- Deep fades are spatially narrow (~6 cm) and temporally brief (if anything moves)
- **Mitigation:** Averaging over time (our 20-second windows) and space (4 sensors) reduces fading impact. A single 2-second snapshot could catch a deep fade; a 20-second average almost never will.

### A.4 Fresnel Zones and Wall Penetration

Radio propagation between a transmitter and receiver isn't a laser beam — it's an ellipsoid called the **Fresnel zone**. At 2.4 GHz over 5 meters, the first Fresnel zone has a radius of ~25 cm at the midpoint. Any obstacle within this zone (including walls, furniture, people) causes signal loss.

**Wall attenuation depends on:**
- Material: drywall (<1 dB), wood (2–3 dB), brick (5–10 dB), concrete (10–15 dB), metal (>30 dB)
- Thickness: roughly linear with thickness for homogeneous materials
- Angle of incidence: perpendicular penetration loses less than oblique
- Frequency: higher frequencies generally attenuate more through solid materials (but less through glass)

**Why the C2-C3 wall is transparent:** Standard interior drywall (two sheets of gypsum board on wood studs, total ~12 cm) has near-zero attenuation at 2.4 GHz. The studs are spaced 40–60 cm apart — wider than the wavelength — so they don't create significant reflections. This isn't unusual; most interior drywall walls are nearly RF-transparent. Our other walls must have additional materials (metal-backed insulation, concrete block, dense brick) that provide the attenuation we rely on.

### A.5 BLE Advertising Deep Dive

**BLE advertising channels:** BLE uses 40 channels (0–39). Channels 37, 38, 39 are dedicated advertising channels at 2402, 2426, and 2480 MHz. These frequencies are chosen to avoid the most common WiFi channels (1, 6, 11).

**Advertising process:**
1. A BLE device broadcasts advertisement packets on channels 37, 38, 39 in sequence
2. Each advertisement takes ~1–2 ms per channel
3. The device then sleeps for an **advertising interval** (typically 20–1000 ms)
4. Repeat forever

**Advertising interval:**
- Apple devices: ~20–200 ms depending on state (actively used phone → ~20 ms; idle → ~200 ms; background → ~1–2 s)
- AirPods: ~200 ms when in case, ~20 ms when in use
- Beacons: configurable, typically 100–1000 ms
- Important: the interval is stable across MAC rotations — it's a hardware/firmware characteristic, not tied to the address

**Why active scan matters:** Our firmware uses `setActiveScan(true)`. Active scanning means the ESP32 sends a `SCAN_REQ` after receiving an advertisement, and the advertiser responds with a `SCAN_RSP` containing additional data (more manufacturer data, service data, etc.). This gives us richer data for device classification. Trade-off: slightly higher power and airtime usage, but negligible for a wall-powered device.

### A.6 BLE MAC Address Types

| Type | Bits [47:46] | Name | Behavior |
|------|-------------|------|----------|
| 0 | N/A | Public | Fixed, globally unique (IEEE OUI). Routers, beacons, legacy devices. |
| 1 | 01 | RPA (Resolvable Private) | Rotates every ~15 min. Modern phones, earbuds, watches. Can be resolved by bonded devices with the IRK. |
| 2 | 11 | Static Random | Fixed per power cycle, random. Some IoT devices. |
| 3 | 00 | NRPA (Non-Resolvable Private) | Fully random, no resolution possible. Rare. |

**Apple MAC rotation:**
- iPhones rotate RPA every ~15 minutes (exact interval varies by iOS version)
- Each rotation generates a new random MAC using the device's IRK (Identity Resolving Key)
- Only bonded devices (your Apple Watch, your MacBook) can resolve the new MAC back to the original device
- We don't bond — we can't resolve RPAs, by design (privacy)

### A.7 24 GHz Radar Physics

**FMCW (Frequency-Modulated Continuous Wave):**
- The LD2450 transmits a chirp signal that sweeps from ~24.00 to ~24.25 GHz over a few microseconds
- The reflected signal is mixed with the current transmitted signal
- The frequency difference (beat frequency) is proportional to distance: `d = c·Δf / (2·S)` where S is sweep rate
- Multiple targets at different distances produce multiple beat frequencies, separated by FFT

**Doppler processing:**
- Phase change between successive chirps encodes target velocity
- Stationary objects (walls, furniture) have zero Doppler and can be filtered out
- Human breathing: ~0.3 Hz micro-Doppler signature (chest moves ~5 mm)
- Walking: 0.5–2 m/s Doppler shift

**Why radar + BLE fusion works:**
- BLE tells you "some devices are nearby" — but you don't know if a human is holding them
- Radar tells you "a human body is at (x, y)" — but you don't know if they have a phone
- Together: "a human with 2 BLE devices is at position (3.2m, 1.8m)" — this is the real answer
- Radar through walls: detects the human body (via breathing/motion), not the phone. A person outside the wall with their phone inside (or vice versa) produces a radar signal from their body position, not the phone position.

---

## Appendix B: Machine Learning Foundations

*The ML concepts behind RoomSense, explained for someone who can code but hasn't done formal ML.*

### B.1 Classification vs. Regression

RoomSense is a **binary classification** problem: is the room occupied (1) or empty (0)? We don't predict a continuous value (regression) like "how many people" — we predict a probability (0.0 to 1.0) and threshold it.

**Why binary, not multi-class?**
- Multi-class (0 people, 1 person, 2 people, ...) would require training data for each count
- The BLE environment doesn't scale linearly with people count (2 people don't produce 2× the signal change of 1 person)
- Binary "occupied / not" is the core use case; device counting is handled separately by the dedup layer

### B.2 Random Forest: How It Works

A Random Forest is an **ensemble** of decision trees. Each tree is a flowchart:

```
Is env_top3_delta__c1__c3 > 5.2?
├── Yes: Is env_strong70__c2 > 2?
│   ├── Yes: INSIDE (confidence 0.95)
│   └── No:  Is env_median__c4 > -72?
│       ├── Yes: INSIDE (confidence 0.78)
│       └── No:  OUTSIDE (confidence 0.82)
└── No: Is env_mac_spread > 4?
    ├── Yes: INSIDE (confidence 0.61)
    └── No:  OUTSIDE (confidence 0.91)
```

**Training:** Each tree is trained on a random subset of the data (bootstrap sample) and considers only a random subset of features at each split. This decorrelates the trees and reduces overfitting.

**Prediction:** All 300 trees vote. The probability is the fraction that voted "inside." If 250/300 vote inside, room_prob = 0.83.

**Why Random Forest for this problem:**
- Handles noisy features gracefully (RSSI is inherently noisy)
- No feature scaling needed (unlike SVM, logistic regression, neural nets)
- Fast inference (~1ms for 300 trees, 50 features)
- Naturally provides feature importance (how much each feature contributes to decisions)
- Works well with small datasets (~200–400 samples)
- Resistant to overfitting compared to a single deep tree

**Downsides:**
- Can't extrapolate (if test data is outside training range, predictions are unreliable)
- Large model file (~5–20 MB for 300 trees) — not an issue on RPi
- No monotonicity constraints (can't enforce "higher RSSI = more likely inside") — this is why we also offer LightGBM

### B.3 LightGBM: How It Differs

LightGBM (Light Gradient Boosting Machine) is a **gradient-boosted** ensemble. Unlike Random Forest (where trees are independent and averaged), boosted trees are built sequentially:

1. Train tree 1 on the data
2. Compute the residual errors (where tree 1 was wrong)
3. Train tree 2 specifically on the residuals
4. Train tree 3 on tree 2's residuals
5. ... repeat for N iterations
6. Final prediction = sum of all trees' predictions

**Monotone constraints (key advantage for us):**
LightGBM allows you to specify that certain features must have a monotone relationship with the output. We constrain `env_median__*` features to be monotone decreasing with output probability — meaning higher RSSI (closer device) must always increase the "inside" probability. This encodes physics into the model and prevents spurious learned correlations.

**When to use LightGBM vs Random Forest:**
- LightGBM: when you have domain knowledge to encode as constraints, when every percentage point matters
- Random Forest: when you want robustness with minimal tuning, when the dataset is very small
- In practice, LightGBM often gives +2–5% accuracy improvement over RF on structured data

### B.4 Cross-Validation: Why LOPO Matters

**Naive approach (wrong):** Split data 80/20 randomly into train/test sets.

**Why it's wrong for us:** BLE readings within a 90-second labeled window at position X are highly correlated — same ambient RF, same nearby devices, same channel conditions. If you randomly split, some readings from the same window end up in both train and test. The model memorizes the specific RF conditions of that moment, not the position geometry. Test accuracy looks great (~98%) but is meaningless.

**Leave-One-Position-Out (LOPO):**
- 8 positions → 8 folds
- Each fold: train on 7 positions, test on the 8th
- The test position was never seen during training — any temporal or ambient correlations can't help
- This simulates the real question: "if I stand somewhere the model hasn't seen before, does it still work?"
- LOPO accuracy is always lower than random-split accuracy, but it's honest

**K-fold vs LOPO:**
- K-fold (e.g., 5-fold) is standard but doesn't respect our data structure (positions)
- LOPO is a special case of "Leave-One-Group-Out" where groups = positions
- With only 8 groups, we can afford to do all 8 folds (no computational issue)

### B.5 Overfitting and How We Prevent It

**Overfitting:** The model learns the training data's noise instead of the underlying pattern. Signs: 99% training accuracy, 70% test accuracy.

**Our risk factors:**
- Small dataset (~200–400 windows from 8 positions)
- Many features (~50) relative to samples — "curse of dimensionality"
- 300 trees on 200 samples is borderline aggressive

**Our mitigations:**
1. **LOPO cross-validation** — gives honest accuracy estimate, immediately reveals overfitting
2. **Random Forest's built-in regularization** — each tree sees a subset of data and features
3. **Environment-level features** — each feature is an aggregate (median, IQR, count), not a raw reading. This is a form of implicit regularization — noisy readings are smoothed before they become features
4. **Monotone constraints (LightGBM)** — constraining feature directions reduces the hypothesis space
5. **Feature engineering over feature selection** — we designed features with domain knowledge rather than throwing raw data at the model and letting it figure things out

### B.6 Probability Calibration

A model outputs "probability 0.73" — but does that actually mean the room is occupied 73% of the time when the model says 0.73? That's the **calibration** question.

**Random Forest calibration:** RF probabilities are the fraction of trees voting "inside." With enough trees, these tend to be well-calibrated (a property called **consistency**). However, RF probabilities are often **conservative** — they cluster toward 0.5 rather than confidently predicting 0.0 or 1.0.

**Conformal prediction (MAPIE):** Instead of asking "what's the probability?", conformal prediction asks "what's the set of possible labels with guaranteed coverage?" If we set alpha=0.10 (90% coverage), then 90% of the time, the true label is in the predicted set. When the set contains both "inside" and "outside," the prediction is uncertain.

**Why we use threshold 0.50:**
- Empirically optimal for 95% pocket recall on our data
- A phone in a pocket (body-shadowed, weaker signal) typically scores 0.6–0.8 — well above 0.50
- An empty room scores 0.01–0.10
- The gap between occupied and empty is wide enough that the exact threshold isn't critical

### B.7 Feature Importance and What It Tells Us

Random Forest provides **Gini importance** (also called MDI — Mean Decrease in Impurity): how much each feature contributes to reducing classification uncertainty across all trees.

**Our top features and what they mean:**
1. `env_top3_delta__c1__c3` (~8%) — The spatial fingerprint. This difference between diagonal sensors is the strongest position signal.
2. `env_median__c4` (~7%) — How loud the BLE environment is near sensor 4. Relevant because of sensor 4's specific position relative to the door.
3. `env_strong70__c3` (~6%) — How many very nearby devices sensor 3 sees. A proxy for "is someone standing near corner 3?"
4. `env_global_max` (~5%) — The loudest single signal anywhere. When someone is in the room, there's always at least one strong signal.

**Interpreting importance:**
- High importance ≠ "this feature alone is enough." It means the feature participates in many tree decisions.
- Features with zero importance can still be useful — they might only matter in rare edge cases.
- Feature importance doesn't tell you direction (positive or negative correlation) — use partial dependence plots or SHAP values for that.

### B.8 The Bias-Variance Tradeoff

Every ML model balances two types of errors:

- **Bias:** The model is too simple to capture the real pattern. Example: using only 1 feature (env_median) to classify — misses the spatial fingerprint.
- **Variance:** The model is too complex and memorizes noise. Example: a single deep tree that perfectly fits training data but fails on new data.

**Where RoomSense sits:**
- 300-tree Random Forest with 50 features on 200 samples: moderate variance risk
- Environment-level features (aggregates, not raw readings): low bias (captures the relevant patterns)
- LOPO reveals the actual bias-variance balance: 93.8% on non-wall positions means we're in a good sweet spot
- The 78% on the transparent wall is **irreducible error** (bias from missing information), not a bias-variance issue

### B.9 EMA Smoothing: Signal Processing Basics

**Exponential Moving Average:** `y[t] = α·x[t] + (1-α)·y[t-1]`

Where:
- `x[t]` = new model output (room_prob)
- `y[t]` = smoothed output
- `α` = 0.4 (responsiveness parameter)
- `1-α` = 0.6 (memory parameter)

**Properties:**
- Acts as a low-pass filter — removes rapid fluctuations (noise) while preserving slow trends (real occupancy changes)
- Time constant τ = -1/ln(1-α) ≈ 1.2 evaluation cycles
- With evaluations every ~2 seconds and α=0.4: effective time constant is ~2.4 seconds
- But entry requires multiple consecutive high readings to push through, hence ~10s detection time
- Exit is slower (~25s) because the smoothed value has to decay from ~0.95 to below 0.50

**Why not a simple moving average?**
- SMA weights all recent values equally — old readings have the same influence as new ones
- EMA exponentially discounts older readings — recent readings matter more
- EMA is also cheaper: O(1) per update vs O(N) for SMA

**The asymmetry (entry faster than exit):**
- Entry: one strong signal from a nearby device immediately shifts env_median up → model outputs 0.9+ → EMA rises quickly from 0.0 to 0.9
- Exit: the person leaves but their BLE signal lingers (multipath, reflections, nearby neighbor devices still present) → model drops to 0.3, then 0.1, then 0.02 over several cycles → EMA decays slowly

### B.10 Why Not Deep Learning?

A common question. Several reasons:

1. **Small dataset:** ~200–400 training samples. Neural networks need thousands to generalize. A 3-layer MLP on 200 samples would memorize training data instantly.

2. **Tabular data:** Our features are structured (50 numeric columns). Research (Grinsztajn et al., 2022) consistently shows that tree-based models (RF, XGBoost, LightGBM) outperform deep learning on tabular data, especially with small datasets.

3. **Interpretability:** We can inspect feature importance, trace individual tree decisions, and understand why the model made a specific prediction. A neural network is a black box — bad for debugging and trust.

4. **Inference speed:** RF prediction is ~1ms. A neural network inference, even small, takes 10–50ms on a Raspberry Pi (no GPU). For a system that evaluates every 2 seconds, this matters.

5. **No sequence modeling needed:** We already do temporal aggregation in feature engineering (20-second windows, EMA). There's no hidden temporal pattern that an LSTM/Transformer would find that our features don't already capture.

**When deep learning WOULD make sense:**
- If we had raw RSSI sequences (thousands of readings per second) and wanted end-to-end learning without feature engineering
- If we had image data (e.g., radar heatmaps as 2D images)
- If we had 10,000+ labeled positions across many rooms (transfer learning across spaces)

---

## Appendix C: Alternative Approaches and Why We Didn't Use Them

*Arguments you might face in debates, and how to respond.*

### C.1 "Why not WiFi fingerprinting?"

WiFi fingerprinting (used in Google Indoor Maps, Apple Indoor Positioning) typically measures RSSI from known WiFi access points.

**Why we don't use it:**
- Requires known, fixed AP positions — we're deploying in arbitrary rooms with unknown WiFi topology
- WiFi RSSI is noisier than BLE (wider channels, more interference)
- WiFi probes are rarer than BLE advertisements (seconds vs milliseconds)
- ESP32 can do both, but BLE gives 10× more readings per second
- We DO plan to add WiFi probe sniffing as a supplementary signal (device fingerprinting, not positioning)

### C.2 "Why not UWB (Ultra-Wideband)?"

UWB (used in Apple AirTag, Samsung Galaxy SmartTag+) provides centimeter-level positioning via time-of-flight.

**Why we don't use it:**
- UWB requires specialized hardware on BOTH the tag and receivers — ESP32 doesn't have UWB
- UWB receivers cost $20–50 each (vs $3 for ESP32)
- UWB only works with devices that have UWB (iPhone 11+, Galaxy S21+) — not all BLE devices
- Our accuracy requirement is room-level (inside/outside), not centimeter-level
- UWB cannot passively detect devices — it requires active ranging sessions

### C.3 "Why not just use a PIR sensor?"

PIR (Passive Infrared) detects body heat and is dirt cheap (~$1).

**Why PIR alone isn't enough:**
- PIR detects presence but not device count or type
- PIR has no concept of "inside vs outside" unless carefully aimed at doorways
- PIR can't distinguish 1 person from 5 people
- PIR triggers on pets, on warm drafts from HVAC, on sunlight

**Why we DO plan to add PIR ($2/node):**
- PIR cannot penetrate ANY wall (infrared is blocked by all solid materials)
- This solves the RF-transparent wall problem — PIR triggered = definitely inside
- Combined with BLE: PIR provides hard wall boundary, BLE provides device counting
- Expected improvement: +5–10% on wall accuracy

### C.4 "Why not cameras with CV?"

Computer vision can count people precisely using object detection (YOLO, etc.).

**Why we don't use cameras:**
- **Privacy.** Camera footage can always be repurposed, stored, leaked, hacked, or subpoenaed. Our system physically cannot capture images.
- Camera-based systems require significant compute (GPU or coral TPU)
- Cameras don't work in the dark without IR illumination
- Cameras have blind spots (behind furniture, around corners)
- Cameras can't identify WHICH devices a person carries
- Many environments prohibit cameras (bedrooms, bathrooms, therapy rooms, some offices)

### C.5 "Why not Time of Arrival (ToA) or Time Difference of Arrival (TDoA)?"

ToA/TDoA use precise timing to calculate distance from signal travel time.

**Why not with BLE:**
- BLE timing resolution is ~1 μs, which gives ~300m distance resolution — useless for room-level positioning
- True ToA requires nanosecond-precision synchronized clocks — ESP32 doesn't have this
- BLE doesn't include timestamps in advertising packets
- This is why UWB exists — it has nanosecond timing. BLE doesn't.
- Some BLE 5.1 devices support Angle of Arrival (AoA) with antenna arrays — ESP32 doesn't have the required multi-antenna setup

### C.6 "Why not commercial solutions?"

Commercial occupancy systems exist (e.g., Density, VergeSense, Butlr).

| Feature | RoomSense | Commercial |
|---------|---------------|------------|
| Cost | ~$70 | $500–2000 per room |
| Privacy | Structural (no identity data) | Policy (trust vendor) |
| Device counting | Yes (by type) | Varies |
| Open source | Yes | No |
| Self-hosted | Yes | Cloud-dependent |
| Accuracy | 93.8% | 95–99% (with more sensors/modalities) |
| Setup time | 30 min | Professional installation |

RoomSense trades peak accuracy for privacy, cost, and independence.

### C.7 "Why 4 sensors? Isn't that overkill?"

**The geometry argument:**
- 1 sensor: can measure signal strength but not direction → unusable (50% accuracy)
- 2 sensors: 1 pairwise difference → can distinguish "near sensor A" from "near sensor B" but not wall side → marginal improvement (~70%)
- 3 sensors: 3 pairwise differences → triangulation is theoretically possible, but body shadowing kills 1 sensor → fragile
- 4 sensors: 6 pairwise differences → lose 1 to body shadow, still have 3 clean pairs → robust

**The accuracy vs. cost curve:**
- 2 sensors + radar (current default): ~92–94% accuracy, $40
- 4 sensors + radar (max accuracy): ~96% accuracy, $70
- Diminishing returns beyond 4: 8 sensors would add ~1–2% for 2× the cost
- The jump from 1 to 4 sensors is the critical region; beyond 4, the gains are marginal

### C.8 "Can't you just track phone MAC addresses?"

**No.** Modern phones (iOS 8+, Android 8+) use randomized MAC addresses for BLE and WiFi. The MAC changes every ~15 minutes (BLE) or per-network (WiFi). There is no reliable way to track a specific device across address rotations without either:
1. Bonding with the device (requires user consent and pairing — defeats the purpose)
2. Exploiting protocol vulnerabilities (counter-randomization attacks exist in academic literature but are unreliable, ethically questionable, and explicitly against our privacy-by-design principle)

Our system treats this as a feature, not a bug. We don't want to track individuals. Environment-level features work precisely BECAUSE they don't require device identity.

### C.9 "What about Zigbee, Z-Wave, or Thread?"

These are IoT mesh protocols. They're not useful for occupancy detection because:
- Very few consumer devices broadcast on Zigbee/Z-Wave/Thread (mostly smart home hubs, light bulbs, sensors)
- The devices that do broadcast are infrastructure (stationary), not carried by people
- BLE has 10–100× the number of broadcasting devices in a typical environment
- Thread (based on 802.15.4) is gaining adoption (Apple HomeKit, Google Nest) but devices don't continuously advertise like BLE

---

## Appendix D: Competitive Landscape & Research Context

### D.1 Academic Indoor Positioning (vs. our approach)

Most academic BLE indoor positioning research focuses on **coordinate-level accuracy** (predicting x, y coordinates within 1–3 meters). Our problem is simpler: binary classification (inside/outside a room boundary). This is important because:

- Coordinate regression requires dense reference point grids (~1 per m²) — we use 8 positions
- Coordinate methods are sensitive to environment changes (furniture moved, people density) — binary boundary detection is more stable
- Most academic papers report results in controlled lab settings with <5 interfering devices — we operate in a real apartment with 30+ neighbor devices

**Relevant research we drew from:**
- **RADAR (Microsoft, 2000):** First WiFi fingerprint system. Showed k-NN on signal vectors works.
- **Horus (2005):** Probabilistic WiFi positioning. Introduced the idea that signal distributions encode location.
- **SSD (Signal Strength Difference):** Using differences between APs instead of absolute values. The foundation of our `top3_delta` features.
- **Device-heterogeneous fingerprinting (various, 2015–2020):** Research on making fingerprint models work across different phone models. Led to our environment-level approach (sidesteps the problem entirely).

### D.2 Why Environment-Level is Novel

Most BLE/WiFi fingerprinting systems track **individual devices** and try to position each one. Our approach of measuring the room's **aggregate BLE landscape** is unusual. The closest related work:

- **Crowd density estimation from WiFi:** Some papers count WiFi probe requests per time window — similar in spirit but less informative (WiFi probes are sparse, no manufacturer data).
- **Ambient RF fingerprinting:** Using background RF as a location signature — conceptually similar but typically used for the device TO locate itself, not for a fixed sensor to detect occupancy.

Our innovation is the combination of:
1. Environment-level aggregation (no per-device tracking)
2. Cross-sensor difference patterns (TX-power-invariant)
3. Apple Continuity-aware dedup (protocol-specific device counting)
4. Privacy-by-architecture (structural guarantee, not policy)

### D.3 How We Compare to Similar Projects

| Project | Method | Privacy | Cost | Accuracy |
|---------|--------|---------|------|----------|
| **RoomSense** | BLE env fingerprint + radar | Structural (no identity data) | ~$70 | 93.8% |
| ESP32 presence detection (community) | BLE device tracking | None (tracks MACs) | ~$5 | ~60–80% |
| ESPresense | BLE trilateration | Partial (hashes MACs) | ~$15–30 | ~70–85% |
| mmWave-only (LD2410) | Radar presence | Full (no RF ID) | ~$5 | ~95% presence, no device ID |
| Meraki MT sensor | WiFi + BLE | Vendor policy | ~$200+ | ~90% |

---

## Appendix E: Common Debate Questions & Answers

### "Why not just use RSSI thresholding?"

RSSI thresholding (e.g., "if any sensor reads > -60 dBm, room is occupied") fails because:
1. Transmit power varies by device (phone vs earbuds: 10–20 dB difference)
2. Body shadowing adds 10–15 dB variance depending on orientation
3. Multipath fading causes ±10 dB variations at the same position
4. Neighbor devices through thin walls can read > -60 dBm

Our environment-level approach handles all of these by using distributions and differences rather than absolute values.

### "How do you handle new/unseen devices?"

We don't need to "handle" them. Environment-level features aggregate across ALL visible devices. A new device type (say, smart glasses that didn't exist during training) simply adds one more signal to the environment. As long as it broadcasts BLE advertisements, it contributes to env_median, env_mac_count, env_strong70, etc. The model has never seen smart glasses specifically, but it has learned "more strong BLE signals near sensor 3 = someone near corner 3."

### "What if everyone turns off Bluetooth?"

Then the system detects nothing — it reports the room as empty. This is a known limitation. However:
- ~95% of smartphones have Bluetooth enabled (needed for earbuds, watches, car connections)
- Even with BT "off" in settings, some phones still broadcast limited BLE advertisements
- Radar fusion provides human detection independent of Bluetooth
- If privacy-conscious users disable BT, the system fails gracefully (no false positive — just a miss)

### "Doesn't 20-second detection lag make this useless?"

Depends on the use case:
- **Office space management:** 20 seconds is instant (meetings last minutes to hours)
- **Smart home automation:** 10-second entry delay is acceptable (lights, HVAC). 25-second exit delay means lights stay on briefly after leaving — actually desirable to avoid "phantom off" when you're briefly still
- **Security monitoring:** Too slow. This is not a security system.
- The lag is tunable: α=0.7 gives ~5s detection at the cost of more flicker

### "What about spoofing / adversarial attacks?"

Someone could theoretically:
1. **Broadcast fake BLE advertisements** to make the room appear occupied when it isn't — yes, this works. RoomSense is not a security system. It's for convenience (HVAC, lighting, occupancy analytics).
2. **Flood the BLE spectrum** to jam detection — possible but would also jam all Bluetooth devices in the area (earbuds, keyboards, etc.). Obviously destructive.
3. **Try to extract identity data** from the system — structurally impossible. The API returns `{"phone": 2}`, not MAC addresses. Even compromising the brain's memory during runtime only reveals volatile, TTL'd MAC entries that expire in 60 seconds.

### "How does accuracy change in a larger room?"

Larger rooms generally give BETTER accuracy because:
- Greater distance between inside and outside positions → larger RSSI differences
- More wall length → more chance of attenuation
- However: sensors in corners may not cover the center well if the room is very large (>8m diagonal)
- Rule of thumb: works well up to ~30 m² with 4 corner sensors. Larger rooms may need additional sensors along walls.

### "What about multi-story buildings?"

Floors are typically more RF-attenuating than walls (concrete, steel reinforcement). A person on the floor above/below would be classified as "outside" if the floor provides >6 dB attenuation (most do). This hasn't been tested explicitly but the physics suggests it works.

---

## Appendix F: Video & Reading Resources

*Curated resources organized by topic. Videos first (easier to absorb), then deeper reading.*

### F.1 Bluetooth Low Energy (BLE)

**Videos:**
- [Bluetooth & BLE Explained: The Protocol Behind IoT and Wearables](https://www.youtube.com/watch?v=AUGwL2KB97I) — Great high-level overview of how BLE works, the advertising process, and why it matters for IoT
- [Everything You Need to Know About BLE Advertising](https://www.youtube.com/watch?v=CJcLabp42b4) — Deep dive into BLE advertising specifically: channels, intervals, packet structure, and scanning
- [BLE Explained: The Ultimate Beginner's Guide](https://www.youtube.com/watch?v=k6DpB8hmgrs) — Comprehensive beginner-friendly walkthrough
- [Understanding BLE - Theoretical Overview](https://www.youtube.com/watch?v=GnRRutaqE5s) — More theoretical/academic angle on BLE core principles

**Reading:**
- [BLE Advertising Primer (Argenox)](https://argenox.com/library/bluetooth-low-energy/ble-advertising-primer) — The best single-page technical reference for BLE advertising
- [RSSI and Proximity (bluetooth.com)](https://www.bluetooth.com/blog/proximity-and-rssi/) — Official Bluetooth SIG article on RSSI and distance estimation
- [RSSI-Based Indoor Positioning (Novelbits)](https://novelbits.io/bluetooth-rtls-direction-finding-and-rssi/) — RSSI vs direction finding for real-time location

### F.2 RSSI, Signal Strength & RF Physics

**Videos:**
- [What is RSSI & How is It Used in Indoor Positioning? (Navigine)](https://www.youtube.com/shorts/WTULRnmNn9g) — Quick intro to RSSI in positioning context
- [WiFi Signal Strength Basics (Oscium)](https://www.oscium.com/training/wifi-signal-strength-basics/) — Covers dBm scale, what the numbers mean, and practical signal levels (applies equally to BLE)

**Reading:**
- [The Engineer's Guide to Decibels: dB, dBm, dBi, dBW (rftools.io)](https://rftools.io/blog/decibels-explained-db-dbm-dbi/) — Everything about the dB scale, why it's logarithmic, how to convert, and what each variant means
- [The RF Engineer's Guide to the Decibel (AllAboutCircuits)](https://www.allaboutcircuits.com/textbook/radio-frequency-analysis-design/rf-principles-components/the-rf-engineers-guide-to-the-decibel/) — Textbook-quality reference on decibels in RF engineering
- [Multipath Radio Propagation (Electronics Notes)](https://www.electronics-notes.com/articles/antennas-propagation/propagation-overview/multipath-propagation.php) — Explains multipath, Rayleigh fading, and why indoor RF is noisy

### F.3 mmWave Radar (FMCW)

**Videos:**
- [What is FMCW Radar and Why is It Useful?](https://www.youtube.com/watch?v=xUGWHGjCtII) — Excellent explainer of how frequency-modulated continuous wave radar works, beat frequencies, and range detection
- [TI mmWave Sensing: FMCW Radars (5-part series)](https://www.ti.com/video/5415203482001) — Texas Instruments' official tutorial series. Very detailed: range estimation, velocity estimation, angle estimation. The gold standard for FMCW education
- [How Do You Build an FMCW Radar?](https://www.youtube.com/watch?v=MlcydOwmRIY) — Practical build perspective, good for understanding the hardware

**Reading:**
- [mmWave Radar Sensing: Everything You Need to Know About FMCW (Seeed Studio)](https://www.seeedstudio.com/blog/2022/01/03/mmwave-radar-sensing-fmcw-radar/) — Comprehensive article covering FMCW principles, the LD2410/LD2450 family, and practical applications
- [FMCW Radar Tutorial (RadarTutorial.eu)](https://www.radartutorial.eu/02.basics/Frequency%20Modulated%20Continuous%20Wave%20Radar.en.html) — Technical reference with diagrams and math

### F.4 Machine Learning (Random Forest, Gradient Boosting, Cross-Validation)

**Videos (StatQuest — the gold standard for ML education):**
- [Random Forest Algorithm Clearly Explained](https://www.youtube.com/watch?v=v6VJ2RO66Ag) — How random forests work, why they're better than single trees, out-of-bag error
- [Random Forests Explained](https://www.youtube.com/watch?v=ru8nGIJEzmU) — Alternative explanation with different visualizations
- [Gradient Boost Part 1: Main Ideas](https://www.youtube.com/watch?v=3CC4N4z3GJc) — How gradient boosting builds trees sequentially on residuals. Watch this before the LightGBM video
- [StatQuest Gradient Boost & XGBoost Full Playlist](https://www.youtube.com/playlist?list=PLZ5DHV9_5h9vQwAImmNi1RfoTtSuOUjwM) — The complete 4-part series on gradient boosting. Essential viewing
- [LightGBM 101: Faster Gradient Boosting for Large-Scale ML](https://www.youtube.com/watch?v=BiaPCbiEYas) — Specifically covers how LightGBM differs from XGBoost (histogram binning, leaf-wise growth)
- [What is LightGBM and How Does It Compare to XGBoost?](https://www.youtube.com/watch?v=n_ZMQj09S6w) — Side-by-side comparison
- [Cross-Validation Explained (StatQuest)](https://www.youtube.com/watch?v=hEtWQcIL3NI) — Why you need cross-validation, k-fold, and leave-one-out. Directly relevant to our LOPO approach

**Reading:**
- [Random Forest: A Complete Guide (Built In)](https://builtin.com/data-science/random-forest-algorithm) — Comprehensive written guide with examples
- [Gradient Boosting Algorithm Explained (Towards Data Science)](https://towardsdatascience.com/all-you-need-to-know-about-gradient-boosting-algorithm-part-1-regression-2520a34a502/) — Detailed walkthrough with math

### F.5 ESP32 & Hardware

**Videos:**
- [BLE with ESP32 Tutorial: The Server](https://www.youtube.com/watch?v=0Yvd_k0hbVs) — Practical ESP32 BLE programming tutorial
- [ESP32 BLE Scanner Tutorial](https://www.youtube.com/watch?v=audY9Hd_9yc) — Building a BLE scanner on ESP32, similar to what our firmware does

**Reading:**
- [ESP32 BLE on Arduino IDE (Random Nerd Tutorials)](https://randomnerdtutorials.com/esp32-bluetooth-low-energy-ble-arduino-ide/) — Step-by-step guide, the go-to reference for ESP32 BLE development
- [ESP-IDF BLE Introduction (Espressif)](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-guides/ble/get-started/ble-introduction.html) — Official Espressif documentation on BLE

### F.6 Suggested Learning Path

If you want to get up to speed quickly, watch these in order:

1. **BLE basics** (20 min): [Bluetooth & BLE Explained](https://www.youtube.com/watch?v=AUGwL2KB97I)
2. **RSSI & dBm** (10 min): [dBm Guide (rftools.io)](https://rftools.io/blog/decibels-explained-db-dbm-dbi/)
3. **Random Forest** (15 min): [Random Forest Clearly Explained](https://www.youtube.com/watch?v=v6VJ2RO66Ag)
4. **Cross-validation** (10 min): [Cross-Validation (StatQuest)](https://www.youtube.com/watch?v=hEtWQcIL3NI)
5. **Gradient Boosting** (20 min): [Gradient Boost Part 1](https://www.youtube.com/watch?v=3CC4N4z3GJc)
6. **FMCW radar** (15 min): [What is FMCW Radar?](https://www.youtube.com/watch?v=xUGWHGjCtII)
7. **The full paper above** (30 min): Read sections 1–6 and 13–14 for the project-specific story

Total: ~2 hours to go from zero to being able to debate anyone on the project.

---

*This document is the single source of truth for all RoomSense design decisions. If this document and the code disagree, the code is right and this document needs updating.*
