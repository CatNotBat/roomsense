# Room Sentinel — Full Project Briefing for LinkedIn Post

This document explains the Room Sentinel project in detail: what it does, how it was built, what problems were encountered and solved, the actual logic behind every component, and the results. Use this to write an engaging LinkedIn post.

---

## What Is Room Sentinel?

A system that answers: "How many people are in this room and what devices do they carry?" — using only Bluetooth, no cameras, no identity tracking. Output is categories and counts only (e.g., "2 phones, 1 earbuds"). Privacy is a hard constraint, not an afterthought.

**Total hardware cost:** ~$50 (4 ESP32 microcontrollers at ~$3 each + a Raspberry Pi or laptop as the brain).

---

## The Journey: What Was Tried and Why

### Attempt 1: Single Sensor (Failed)

The first idea was simple: put one ESP32 in the room, listen to BLE advertisements (every phone, earbuds, watch broadcasts these constantly), and use signal strength (RSSI) to determine if a device is inside or outside.

**Why it failed:** A phone 2 meters away inside the room reads -65 dBm. A neighbor's phone 2 meters away on the other side of the wall also reads -65 dBm. A single sensor can measure distance but not direction. It cannot tell which side of the wall a device is on. The distributions genuinely overlap — no threshold can separate them.

### Attempt 2: Four Sensors in Corners (Breakthrough)

Placing 4 sensors in the room's corners changed everything. Now the same phone produces a unique RSSI *pattern* across all 4 sensors. A phone near corner 1 reads strong on sensors 1 and 4, weak on sensors 2 and 3. A phone outside the north wall reads weak on all sensors, but with a specific pattern based on wall attenuation.

**The geometry creates a spatial fingerprint that a single sensor cannot.**

This is the core insight: cross-sensor RSSI differentials encode position relative to walls. The model doesn't need to know where exactly the device is — just whether it's inside or outside.

### Attempt 3: Per-Device Tracking (Failed — 56% accuracy)

The first ML approach tracked individual BLE devices: for each MAC address, build a feature vector from its RSSI across all 4 sensors, and classify it as inside/outside.

**Why it failed (56.3% accuracy):**
1. **MAC rotation:** Apple devices change their BLE address every ~15 minutes. You can't track a device across time.
2. **Neighbor poisoning:** During a "room is occupied" training window, 95% of detected BLE devices are actually neighbors' phones, smart TVs, routers through the walls. These get labeled "inside" even though they're outside. The model learns nothing useful.
3. **Sparse data:** The user's carried devices (phone, earbuds) produce only ~500 readings out of 50,000+ total BLE readings in a training session. The signal-to-noise ratio is terrible.

### Attempt 4: Environment-Level Features (Success — 93.8%)

Instead of asking "is THIS device inside?", the model asks "does the room's overall BLE environment look occupied?"

**Key insight:** When a person walks into a room with their phone and earbuds, the BLE environment changes in predictable ways:
- More strong signals appear on nearby sensors
- The distribution of signal strengths shifts upward
- The sensor closest to the person sees disproportionately more strong devices
- The total count of strong BLE emitters near each sensor changes

These patterns are the same whether the phone has rotated its MAC address or not. We don't track any individual device — we look at the aggregate statistics.

---

## How It Actually Works (Technical Detail)

### Hardware Layer

4 ESP32 microcontrollers (2× XIAO ESP32-S3, 2× ESP32 classic) placed in the room's 4 corners. Each one:
- Continuously scans for BLE advertisements (passive, not connecting to any device)
- For each advertisement received, captures: MAC address, RSSI (signal strength in dBm), address type (public/random/RPA), GAP appearance code, manufacturer data hex, service data hex, SNTP-synced RX timestamp
- Publishes to MQTT broker as 8 pipe-delimited fields: `SENSOR_ID|mac|rssi|addrType|appearance|mfgHex|svcHex|rxMs`
- Each sensor sees 40-60 BLE advertisements per second from all devices in range (phones, earbuds, watches, smart TVs, routers, neighbor devices through walls)

The brain (laptop during dev, Raspberry Pi for deployment) runs Mosquitto MQTT broker and the Python inference pipeline.

### Calibration

Different ESP32 chips have different RSSI biases (several dB). Without calibration, cross-sensor comparisons are unreliable.

**Auto-calibration method (no dedicated beacon needed):**
1. Subscribe to MQTT for 60 seconds
2. Find all BLE devices heard by ALL 4 sensors simultaneously (typically 20-30 devices — these are neighbor devices, routers, etc. that have strong enough signals to reach all corners)
3. For each shared device, compute the median RSSI per sensor
4. Compute per-sensor offset: `offset[i] = global_median - sensor_median[i]`
5. Apply offset to all future RSSI readings

This runs automatically on first startup if no calibration file exists. In the test deployment, offsets ranged from -2.5 to +1.0 dB.

### Feature Engineering (The Core ML Logic)

Every 10 seconds, the system snapshots the entire BLE landscape each sensor sees. For each sensor in the window:

**Per-sensor features:**
- `env_median`: Median RSSI of ALL devices heard by this sensor
- `env_iqr`: Interquartile range (signal strength spread)
- `env_max`, `env_min`: Strongest and weakest signals
- `env_pkt_count`: Total BLE packets received
- `env_mac_count`: Unique devices heard
- `env_strong80`, `env_strong70`: Count of devices with RSSI > -80 dBm and > -70 dBm (strong = nearby)
- `env_top3_median`: Median of the 3 strongest devices' median RSSI

**Cross-sensor features:**
- `env_total_macs`: Total unique devices across all sensors
- `env_mac_spread`: Difference between sensor with most and fewest devices
- `env_strong80_spread`: Same for strong devices
- `env_top3_delta__sensorA__sensorB`: Pairwise difference of top-3 medians between each sensor pair (6 features for 4 sensors) — this is the spatial fingerprint
- `env_loudest__sensor`: One-hot encoding of which sensor sees the strongest devices
- `env_global_max`: The single strongest RSSI across all sensors

**Why these features work:**
- When someone is in the room, the 2 nearest sensors see significantly more strong devices and higher median RSSI than the 2 far sensors. The `top3_delta` features capture this asymmetry.
- When the room is empty, all 4 sensors see roughly the same BLE landscape (just neighbor devices through walls, roughly equidistant).
- When someone is outside the room (near a wall), only 1-2 sensors see a slight increase, and the pattern is different from the "inside" pattern.

### Training

Data collection: the user walks through 8 labeled positions (center, near each wall, outside the door, outside shared walls) spending 60-90 seconds at each position. All BLE readings are recorded with position labels.

Training uses **Leave-One-Position-Out (LOPO) cross-validation**: train on 7 positions, test on the 8th, rotate. This is more rigorous than random train/test splits because BLE readings within a position are highly correlated — random splitting would leak information.

The model is a 500-tree Random Forest. Environment-level features are extracted at 10-second windows with no overlap.

Additional training data was collected for robustness:
- Phone-only (earbuds removed) — to ensure detection works with just a phone
- AirPods-only (phone removed) — to ensure earbuds alone trigger detection
- Empty room — explicit negative samples

### Live Inference

The live system:
1. Subscribes to MQTT, buffers all readings for 20 seconds (2× the 10s window)
2. Every evaluation cycle, extracts environment-level features from the buffer
3. Runs the Random Forest model, gets probability of occupancy
4. Applies EMA smoothing (40% new + 60% previous) for display stability
5. If `room_prob >= 0.50`: room is occupied

### Device Counting (Apple Continuity-Aware Dedup)

When the room is occupied, the system counts devices by type. This is where it gets tricky:

**The problem:** A single iPhone broadcasts BLE advertisements from multiple MAC addresses simultaneously. It uses different Apple Continuity protocol types:
- Nearby Info (type 0x10) — proximity awareness
- Handoff (type 0x12) — cross-device workflow
- AirPlay (type 0x09) — media streaming discovery

Each type broadcasts from a different random MAC. Without dedup, one iPhone looks like 3 devices.

**The solution — Continuity-type-aware dedup:**
1. For each detected BLE MAC above -78 dBm average RSSI:
   - Parse manufacturer data to identify Apple devices (company ID 0x004C)
   - Extract which Continuity TLV types are present in the advertisement
   - Classify device type (phone, earbuds, watch, laptop) from advertisement fields
2. Group by device type (phones with phones, earbuds with earbuds)
3. Within each group, cluster by spatial similarity (per-sensor RSSI vector, Euclidean distance < 6 dB)
4. **Key rule:** If two MACs have the SAME Continuity type, they MUST be different physical devices (one phone can't broadcast the same type from two MACs). If they have DIFFERENT types and similar RSSI patterns, they're likely the same device.

This correctly resolves:
- 1 iPhone broadcasting from 3 MACs → 1 phone
- 2 iPhones at the same location → 2 phones (they share Continuity type 0x10)
- 1 iPhone + 1 AirPods → 1 phone + 1 earbuds (different device categories)

### Device Type Classification

The system identifies device types from BLE advertisement fields without any identity tracking:
- **Apple devices:** Parse Continuity TLV types — 0x07 = AirPods/Beats, 0x10/0x12 = phone/laptop
- **Samsung:** Company ID 0x0075
- **Google Fast Pair:** Service UUID 0xFE2C (discoverable mode = earbuds)
- **Microsoft:** Company ID 0x0006
- **GAP Appearance codes:** Watch (0x00C0), phone (0x0040), laptop (0x0080), earbuds (0x0841)
- **Address type fallback:** Random/RPA addresses (types 1-3) are almost always personal devices → "phone"

### Privacy Architecture

Privacy is structural, not policy:
- MAC addresses exist ONLY in the volatile dedup layer (RAM, TTL'd, never serialized)
- MACs are hashed (SHA-256 + salt, truncated to 12 chars) before any disk write
- The dedup function outputs `{category: count}` — no MAC ever exits this function
- The Flask API returns only `{"phone": 2, "earbuds": 1}` — the web UI structurally cannot render identities
- No cross-session tracking, no fingerprinting to defeat MAC randomization

---

## Problems Encountered and Solved

### Problem 1: Calibration Without Root Access
Planned to use the laptop as a BLE beacon for calibration, but BLE advertising requires root/sudo on Linux. Tried 3 approaches (bluetoothctl, D-Bus, raw HCI) — all failed without root.

**Solution:** Invented the "shared device" calibration method — use the 20+ neighbor BLE devices already visible to all 4 sensors as natural reference points. No dedicated beacon needed at all. This is actually better because it uses real-world signals.

### Problem 2: Per-Device Model Catastrophic Failure (56% accuracy)
Training on individual BLE devices failed because 95% of visible MACs are stationary neighbor devices that look the same inside and outside.

**Solution:** Environment-level features. Don't track devices, track the room's BLE landscape. Accuracy jumped to 93.8%.

### Problem 3: MAC Address Rotation
Apple devices rotate their BLE MAC every ~15 minutes, breaking any per-device tracking approach.

**Solution:** Environment-level features are inherently immune — they aggregate statistics across ALL devices, so MAC rotation has zero impact.

### Problem 4: Satellite Clock Drift
ESP32 SNTP timestamps were ~541 seconds behind system time. The live inference buffer trimmed all data as "too old" — the system produced room_prob=0.0 constantly.

**Solution:** Use brain-arrival time (`time.time()` on the server) instead of satellite timestamps for live buffering. Training data uses its own timestamps. The drift is a firmware issue (SNTP only syncs at boot).

### Problem 5: Phone-Only Detection Failure
The model was trained with all 3 devices together (2 phones + earbuds). When tested with just a phone (earbuds removed), it dropped to room_prob=0.28 — "quiet."

**Root cause:** The model learned that "occupied" means strong70 count = 2-4. With only a phone, strong70 = 0 (phone broadcasts weaker than earbuds at close range).

**Solution:** Collected additional training data: phone-only, earbuds-only, and empty room. After retraining, both phone-only and earbuds-only detect at 95%.

### Problem 6: iPhone Double-Counting
One iPhone was counted as 2-3 phones because it broadcasts from multiple MAC addresses via different Apple Continuity protocol types.

**Solution:** Continuity-type-aware dedup (described above). Same Continuity type = different device. Different types + similar RSSI = same device.

### Problem 7: RF-Transparent Wall
One wall in the test room has ~0 dB BLE attenuation — the signal passes through with almost no loss. The model cannot distinguish inside from outside this wall.

**This is a physics limitation, not a software bug.** No amount of ML can overcome it with BLE alone.

**Planned solution:** mmWave radar fusion (HLK-LD2410, ~$3 each). Radar detects stationary humans through breathing — completely different physics, complementary blind spots.

---

## Results Summary

### Model Accuracy (LOPO Cross-Validation)
- **93.8% accuracy** excluding the RF-transparent wall
- 83.8% including all positions
- Phone-only: 95%, AirPods-only: 95%, Empty room: 100%

### Live Manual Testing
- 100% presence accuracy across all test scenarios
- Entry detection: ~10 seconds
- Exit detection: ~25 seconds (EMA smoothing tradeoff)
- Device counting: correct ±1
- Zero false positives in empty room
- Tested with: 1 iPhone, 2 iPhones, AirPods, combinations

### Code Quality
- 105 automated tests, all passing
- Covers: environment features, Continuity dedup, device classification, calibration, data preparation, co-hearing alignment, aggregation, transfer features

---

## Hardware

| Component | Model | Qty | Cost |
|-----------|-------|-----|------|
| ESP32-S3 | XIAO ESP32-S3 | 2 | ~$6 |
| ESP32 classic | ESP32-D0WD dev board | 2 | ~$6 |
| Brain | Laptop (RPi 4B planned) | 1 | ~$35 |
| **Total** | | | **~$47** |

### Planned Addition
| Component | Model | Qty | Cost |
|-----------|-------|-----|------|
| mmWave radar | HLK-LD2410 (24GHz) | 4 | ~$12 |

---

## Tech Stack
- **Firmware:** Arduino + ESP-IDF (BLE scan + MQTT publish + SNTP)
- **Broker:** Mosquitto MQTT
- **Backend:** Python 3.14, scikit-learn (Random Forest), pandas, Flask
- **Protocol:** BLE 4.2 passive scanning (no connections made to any device)

---

## Key Takeaways for the Post

1. **One sensor can't do it** — you need geometry (multiple viewpoints) to distinguish "near on this side" from "near on the other side"
2. **Don't track devices, track the environment** — aggregate features are immune to MAC rotation and don't require knowing which device is which
3. **Calibration can be automatic** — using shared BLE devices as natural reference points, no manual setup needed
4. **Apple's Continuity protocol is both a curse and a blessing** — it causes multi-MAC broadcasts (hard to count), but the protocol structure lets you distinguish same-device from different-device
5. **Physics has a ceiling** — some walls are transparent to 2.4GHz radio, and no amount of ML can fix that. Different sensor modalities (mmWave radar) are the answer
6. **Privacy by architecture, not by policy** — if the data structure can't hold identities, they can't leak

---

## Tone Guidance

The post should feel like someone sharing a weekend project they're genuinely excited about. Not a product launch. Not a research paper. The interesting parts are:
- The journey from "this should be simple" to "oh wait, physics"
- Each failure teaching something about BLE, signal propagation, or ML
- The satisfying moment when environment-level features clicked
- The Apple Continuity dedup being a detective puzzle
- The $50 price point vs commercial solutions ($500+)
- The privacy angle (no cameras, structural guarantees, not policy promises)
