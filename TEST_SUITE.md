# RoomSense — Comprehensive Data Collection & Test Suite

## Room Layout (4m x 6m)

```
                    6 meters (outside wall)
    S1 ─────────────────────────────────────── S2
    │                                           │
    │   neighbour                    outside     │
    │   wall                         wall        │
  4m│                                           │4m
    │   s4-s1                       s1-s2       │
    │                                           │
    │                                           │
    S4 ─────────────────────────────────────── S3
           hallway wall (thin, ~1m deep)
                s3-s4 shared wall
                    6 meters

Walls:
  S1-S2 (north, 6m): OUTSIDE wall (exterior — concrete/brick, high attenuation)
  S2-S3 (east, 4m):  shared with TOILET (thin interior wall)
  S3-S4 (south, 6m): shared with HALLWAY (~1m deep, thin wall)
  S4-S1 (west, 4m):  shared with NEIGHBOUR (unknown construction)
```

## Sensor Placement

5 sensors total: S1–S4 in corners, S_HUB on RPi (wall-mounted with RPi).

### Height Experiments (Phase 0 — do first, 30 min)

Test 3 heights to determine optimal before the main collection:
- **LOW**: 30cm from floor (under desk level)
- **MID**: 120cm (chest/table height)
- **HIGH**: 200cm (near ceiling)

**Protocol**: Place your iPhone at room CENTER. Mount ONE sensor (esp_c1) at each height for 3 minutes. Compare median RSSI and packet rate. Choose the height with highest packet rate and least variance. Mount ALL sensors at that height.

Expected: MID (120cm) will likely win — line-of-sight to pocket-height devices, less floor/ceiling multipath.

## Test Devices

| Device | ID | BLE Behavior | Role |
|--------|----|-------------|------|
| iPhone (yours) | iphone_1 | RPA rotation ~15min, Apple Continuity, multiple simultaneous MACs | Primary test device |
| iPhone (borrowed) | iphone_2 | Same as above | Multi-person simulation |
| Google Pixel 6a | pixel_1 | Less aggressive rotation, Google Fast Pair | Android baseline |
| AirPods | airpods_1 | iBeacon + Nearby Info, very short range (-80 to -95 typical) | Weak-signal test |

**Pre-test**: Note down each device's BLE MAC (or first few chars) from the dashboard. Mark which are RPA vs static.

---

## Phase 0: Sensor Height & Calibration (30 min)

### 0A. Height Test (15 min)

```
mark HEIGHT_LOW_CENTER in    — iPhone at CENTER, sensor at 30cm, 3 min
mark HEIGHT_MID_CENTER in    — iPhone at CENTER, sensor at 120cm, 3 min
mark HEIGHT_HIGH_CENTER in   — iPhone at CENTER, sensor at 200cm, 3 min
```

Decide height. Mount all 5 sensors at chosen height.

### 0B. Auto-Calibration Warmup (5 min)

Leave room completely empty for 5 minutes with all sensors running. This serves as:
1. RSSI auto-calibration baseline
2. Empty-room baseline capture (`POST /api/baseline` after 5 min)
3. Verification all 5 sensors are publishing

```
mark EMPTY_ROOM out          — nobody in room, 5 min
```

### 0C. Sensor Health Check (5 min)

Open dashboard, verify all 5 sensors show green dots. Check MQTT:
```bash
mosquitto_sub -h 192.168.1.200 -t 'roomsense/#' -C 50 | cut -d'|' -f1 | sort | uniq -c
```
Each sensor should have ~equal packet counts.

---

## Phase 1: Grid Position Sweep — Single Device (2 hours)

**Goal**: Map the room's RSSI fingerprint at every meaningful position. One device (iPhone) carried in hand at chest height.

**Duration per position**: 3 minutes minimum (yields ~6 non-overlapping 20s windows per position — minimum for LOPO to be meaningful).

### 1A. Inside Positions (60 min)

```
Position Name         Location                                Duration  Notes
─────────────────────────────────────────────────────────────────────────────────
CENTER                Room center (3m, 2m)                    3 min     Baseline "clearly inside"
CENTER_POCKET         Room center, phone in pocket            3 min     Attenuated signal, safety-critical
NEAR_S1               0.5m from corner S1                     3 min     Near outside+neighbour wall
NEAR_S2               0.5m from corner S2                     3 min     Near outside+toilet wall
NEAR_S3               0.5m from corner S3                     3 min     Near hallway+toilet wall
NEAR_S4               0.5m from corner S4                     3 min     Near hallway+neighbour wall
MID_WALL_N            Midpoint of S1-S2 wall, 0.5m from it   3 min     Outside wall center
MID_WALL_E            Midpoint of S2-S3 wall, 0.5m from it   3 min     Toilet wall center
MID_WALL_S            Midpoint of S3-S4 wall, 0.5m from it   3 min     Hallway wall center
MID_WALL_W            Midpoint of S4-S1 wall, 0.5m from it   3 min     Neighbour wall center
NEAR_DOOR             0.5m from door (inside)                 3 min     Transition zone
CENTER_FLOOR          Room center, phone on floor             3 min     Height variation
CENTER_DESK           Room center, phone on desk (~75cm)      3 min     Typical resting position
BED                   On/near bed (if applicable)             3 min     Furniture absorption
WALKING_INSIDE        Walking around inside room              5 min     Motion pattern
```

Label commands:
```
mark CENTER in
mark CENTER_POCKET in
mark NEAR_S1 in
mark NEAR_S2 in
mark NEAR_S3 in
mark NEAR_S4 in
mark MID_WALL_N in
mark MID_WALL_E in
mark MID_WALL_S in
mark MID_WALL_W in
mark NEAR_DOOR in
mark CENTER_FLOOR in
mark CENTER_DESK in
mark BED in
mark WALKING_INSIDE in
```

### 1B. Outside Positions (45 min)

**Critical**: These test the wall boundaries — the hardest classification problem.

```
Position Name              Location                           Duration  Notes
─────────────────────────────────────────────────────────────────────────────────
OUT_HALLWAY_CLOSE          Hallway, 0.5m from S3-S4 wall      3 min     Thin wall, hardest case
OUT_HALLWAY_MID            Hallway, 1m from wall (center)      3 min     Still close
OUT_HALLWAY_FAR            Hallway, beyond 1m depth            3 min     Should be easy
OUT_TOILET_CLOSE           Toilet, 0.5m from S2-S3 wall       3 min     Thin wall
OUT_TOILET_FAR             Toilet, far corner                  3 min     Should be easy
OUT_NEIGHBOUR_CLOSE        Outside S4-S1 wall, 0.5m           3 min     Unknown wall type — key test
OUT_OUTSIDE_CLOSE          Outside S1-S2 wall, 0.5m           3 min     Exterior wall — should be easy
OUT_OUTSIDE_FAR            Outside S1-S2 wall, 3m+            3 min     Very attenuated
OUT_DOOR_OPEN              Just outside door, door OPEN        3 min     Worst case transition
OUT_DOOR_CLOSED            Just outside door, door CLOSED      3 min     Better attenuation
OUT_FAR_CORRIDOR           End of corridor, 5m+ from room      3 min     Clearly outside baseline
OUT_WALKING_HALLWAY        Walking in hallway                  3 min     Motion outside
```

Label commands:
```
mark OUT_HALLWAY_CLOSE out
mark OUT_HALLWAY_MID out
mark OUT_HALLWAY_FAR out
mark OUT_TOILET_CLOSE out
mark OUT_TOILET_FAR out
mark OUT_NEIGHBOUR_CLOSE out
mark OUT_OUTSIDE_CLOSE out
mark OUT_OUTSIDE_FAR out
mark OUT_DOOR_OPEN out
mark OUT_DOOR_CLOSED out
mark OUT_FAR_CORRIDOR out
mark OUT_WALKING_HALLWAY out
```

### 1C. Transition Tests (15 min)

Stay at position for 3 min, walk to next at normal speed. The transition itself is data.

```
mark TRANSITION_ENTER_DOOR in    — Walk in through door, stay at center, 3 min
mark TRANSITION_EXIT_DOOR out    — Walk out through door, stay in hallway, 3 min
mark TRANSITION_ENTER_SLOW in   — Slowly walk in (10s walk), stay, 3 min
mark TRANSITION_EXIT_SLOW out   — Slowly walk out, stay outside, 3 min
```

---

## Phase 2: Multi-Device Scenarios (45 min)

**Goal**: Test how the environment-level features behave with multiple devices present.

### 2A. Device Combinations Inside (30 min)

```
Position Name                     Devices                          Duration
─────────────────────────────────────────────────────────────────────────────
MULTI_2IPHONE_CENTER              2 iPhones at center              3 min
MULTI_IPHONE_PIXEL_CENTER         iPhone + Pixel at center         3 min
MULTI_ALL_CENTER                  2 iPhones + Pixel + AirPods      3 min
MULTI_SCATTERED_IN                Devices at 4 different spots     3 min
MULTI_POCKET_ALL                  All devices in pockets           3 min
MULTI_1PHONE_1POCKET              1 hand, 1 pocket                 3 min
```

Labels: all `in`

### 2B. Mixed In/Out Scenarios (15 min)

**Critical edge cases**: Some devices inside, some outside.

```
Position Name                     Setup                            Label
─────────────────────────────────────────────────────────────────────────────
MIXED_1IN_1OUT_HALLWAY            iPhone inside, Pixel in hallway  in
MIXED_1IN_1OUT_TOILET             iPhone inside, Pixel in toilet   in
MIXED_ALL_OUT                     All devices in hallway           out
MIXED_PHONE_OUT_AIRPODS_IN        iPhone outside, AirPods inside   in
```

Note: Label based on whether PEOPLE are inside, not devices.

---

## Phase 3: Adversarial & Edge Cases (45 min)

**Goal**: Stress-test failure modes. This data is gold for improving the model.

### 3A. Wall Proximity Deep Dive (20 min)

For the HARDEST wall (likely hallway S3-S4, thin wall):

```
mark WALL_S34_INSIDE_0CM in      — Phone touching wall from inside, 3 min
mark WALL_S34_OUTSIDE_0CM out    — Phone touching wall from outside, 3 min
mark WALL_S34_INSIDE_20CM in     — 20cm from wall inside, 3 min
mark WALL_S34_OUTSIDE_20CM out   — 20cm from wall outside, 3 min
mark WALL_S34_INSIDE_50CM in     — 50cm from wall inside, 3 min
mark WALL_S34_OUTSIDE_50CM out   — 50cm from wall outside, 3 min
```

Repeat for neighbour wall (S4-S1) if time permits.

### 3B. Signal Manipulation (15 min)

```
mark BODY_BLOCK_CENTER in        — Phone behind body (body blocks signal), 3 min
mark BAG_CENTER in               — Phone in bag/backpack, 3 min
mark UNDER_BLANKET in            — Phone under blanket/pillow, 3 min
mark HAND_HIGH in                — Phone held above head, 3 min
mark PHONE_ON_WINDOWSILL in     — Near outside wall on surface, 3 min
```

### 3C. Temporal Edge Cases (10 min)

```
mark STATIONARY_LONG in          — Don't move for 5 min straight (tests drift)
mark RAPID_MOVEMENT in           — Walk rapidly back and forth for 3 min
mark EMPTY_AFTER_OCCUPIED out    — Leave room after it was occupied, 3 min
```

---

## Phase 4: Radar-Specific Tests (30 min — only with LD2450 radars)

**Goal**: Validate mmWave radar features independently and in fusion with BLE.

### 4A. Radar Detection Zones (15 min)

```
mark RADAR_CENTER_STILL in       — Standing still at center, 3 min
mark RADAR_CENTER_MOVING in      — Walking at center, 3 min
mark RADAR_NEAR_WALL_STILL in    — Standing near hallway wall, 3 min
mark RADAR_CORNER_STILL in       — Standing in corner, 3 min
mark RADAR_EMPTY out             — Nobody in room, 3 min (radar false positive test)
```

### 4B. Radar Through-Wall (15 min)

```
mark RADAR_HALLWAY_WALKING out   — Walking in hallway, 3 min (radar may see through wall)
mark RADAR_TOILET_MOVING out     — Moving in toilet, 3 min
mark RADAR_HALLWAY_STILL out     — Standing still in hallway, 3 min (should NOT detect)
```

---

## Phase 5: Repeatability & Long Soak (60 min)

### 5A. Position Repeat (30 min)

Re-collect 5 key positions to test temporal stability:
```
mark CENTER_R2 in                — Same CENTER position, later in the day
mark OUT_HALLWAY_CLOSE_R2 out
mark NEAR_S3_R2 in
mark WALL_S34_INSIDE_0CM_R2 in
mark OUT_DOOR_CLOSED_R2 out
```

Each 3 min. Compare with Phase 1 data for drift.

### 5B. Long Soak (30 min)

Leave system running with known state:
```
mark SOAK_OCCUPIED in            — Sit normally in room, 15 min (normal activity)
mark SOAK_EMPTY out              — Leave room completely, 15 min
```

---

## Data Collection Summary

| Phase | Duration | Positions | Primary Focus |
|-------|----------|-----------|---------------|
| 0: Setup | 30 min | 3 | Height, calibration, health |
| 1: Grid sweep | 2 hours | 27 | Single-device RSSI fingerprint |
| 2: Multi-device | 45 min | 10 | Environment-level features |
| 3: Adversarial | 45 min | 14 | Edge cases, wall proximity |
| 4: Radar | 30 min | 8 | mmWave features |
| 5: Repeatability | 60 min | 7 | Temporal stability |
| **Total** | **~5 hours** | **~69** | |

**Expected data volume**: ~500k+ BLE readings, ~100k+ radar frames

---

## Enhanced Logging (add before test day, remove after)

### Extra fields to capture during collection

Add these temporary enhancements to `collect_walk.py` for richer data:

1. **Per-sensor packet rate log** — every 10s, log packets-per-sensor to a side CSV
2. **Appearance field** — currently not saved in collect_walk.py but IS in the MQTT format
3. **advType field** — same, exists in MQTT v3.1 but not captured by collector
4. **RSSI histogram** — per 20s window, write a histogram of all RSSI values (for debugging fillna)
5. **Sensor-to-sensor timing** — log the clock offset between sensor rx_ms values (for co-hearing debug)

---

## Post-Collection Analysis Plan (for Claude remote sessions)

### Session 1: Data Quality & Exploration (2-3 hours)

**Input**: All raw CSVs from collection day
**Tasks**:
1. Data integrity check: missing sensors, gaps, packet rates
2. Per-position RSSI heatmaps (sensor × position matrix)
3. Wall attenuation measurement: inside vs outside pairs for each wall
4. Device type breakdown: what MACs were seen, RPA rotation patterns
5. Radar coverage map: which positions have radar targets
6. Identify the "hard" positions (low RSSI separation between in/out)
7. Generate `readings_labeled.csv` and `radar_labeled.csv`

### Session 2: Baseline Model Training & Evaluation (2-3 hours)

**Input**: Labeled data from Session 1
**Tasks**:
1. Train v3_env model (RF) with LOPO — full 5-sensor array
2. Train v3_env model (LightGBM) with LOPO
3. Per-position accuracy breakdown — find failure positions
4. Confusion matrix analysis — FP vs FN patterns
5. Feature importance ranking — what matters most
6. Single-sensor ablation: drop each of 5 sensors, measure degradation
7. Train radar-only, BLE-only, and fused models — quantify radar contribution
8. MAPIE conformal prediction calibration and coverage check
9. Save all metrics to `models/metrics.json`

### Session 3: Sensor Reduction Experiments (3-4 hours)

**Input**: Full dataset + Session 2 baseline
**Tasks**:
1. **Leave-one-sensor-out**: 5 experiments, each dropping 1 sensor
2. **All pairs (C(5,2)=10)**: Train with only 2 sensors, measure accuracy
3. **All triples (C(5,3)=10)**: Train with 3 sensors
4. **All quads (C(5,4)=5)**: Train with 4 sensors
5. Rank sensor positions by contribution
6. Find minimum viable sensor set for 90%+ accuracy
7. Identify if hub sensor adds value vs corner-only
8. Generate a comprehensive sensor reduction report with tables

### Session 4: Wall Problem Deep Dive (2-3 hours)

**Input**: Full dataset + wall proximity data from Phase 3
**Tasks**:
1. Per-wall attenuation profiles (RSSI vs distance, both sides)
2. Radar through-wall detection analysis
3. Train wall-specific sub-models
4. Geometric radar features: triangulate position from multiple radars
5. Fused BLE+radar model specifically for wall-adjacent positions
6. Door open vs closed impact analysis
7. Determine which walls are RF-transparent and at what frequencies

### Session 5: Feature Engineering Experiments (3-4 hours)

**Input**: Full dataset
**Tasks**:
1. Try different window sizes: 5s, 10s, 15s, 20s, 30s, 60s
2. Try different overlap ratios: 0%, 25%, 50%, 75%
3. Add new features:
   - RSSI gradient (change over consecutive windows)
   - Device dwell time features
   - Radar motion correlation with BLE packet rate
   - Cross-sensor RSSI correlation coefficients
   - Time-of-day features (if multi-session data)
4. Feature selection: recursive elimination, find minimal feature set
5. Train with raw RSSI + engineered features vs engineered only
6. Hyperparameter sweep: RF trees, LightGBM lr/leaves/depth

### Session 6: Advanced Models (2-3 hours)

**Input**: Full dataset + best features from Session 5
**Tasks**:
1. XGBoost comparison
2. Simple neural network (2-3 layer MLP)
3. Temporal model: sliding window with history features
4. Ensemble: RF + LightGBM + XGB voting
5. Calibrated probabilities: isotonic regression on OOF predictions
6. Multi-class model: "inside" / "near_wall" / "outside" (3-class)
7. Anomaly detection for unknown positions

### Session 7: Production Hardening (2-3 hours)

**Input**: Best model from Sessions 2-6
**Tasks**:
1. Threshold optimization: precision-recall tradeoff analysis
2. Transition smoothing: entry/exit latency optimization
3. Dedup accuracy: MAC rotation handling under best model
4. Device count accuracy per scenario
5. Sensor failure graceful degradation testing
6. Model size/latency for RPi deployment
7. A/B test: old model vs new model on soak test data
8. Final model bundle + deploy to RPi

---

## Checklist for Test Day

### Before Starting
- [ ] All 5 ESP32s flashed with `roomsense/*` MQTT topics
- [ ] All 5 sensors mounted at chosen height in corners + hub
- [ ] LD2450 radars wired and verified (if arrived)
- [ ] RPi running `roomsense` service, dashboard accessible
- [ ] `mosquitto_sub -t 'roomsense/#'` shows data from all 5 sensors
- [ ] Enhanced `collect_walk.py` deployed (with extra logging)
- [ ] Phone fully charged (or charger nearby)
- [ ] Borrowed iPhone arranged
- [ ] Timer/stopwatch ready (3 min per position)
- [ ] This document printed or on second screen
- [ ] External BLE devices minimized (turn off unnecessary Bluetooth things)

### During Collection
- [ ] Check sensor health between phases (dashboard green dots)
- [ ] Flush data every phase (`readings_f.flush()` is automatic every 500 readings)
- [ ] Note any anomalies (sensor drops, WiFi issues) with timestamps
- [ ] Take photo of room with sensor positions marked

### After Collection
- [ ] Copy all CSVs from RPi to laptop: `data/walk_readings_raw.csv`, `data/walk_radar_raw.csv`, `data/walk_labels.csv`
- [ ] Run `python src/prepare_walk_data.py` — verify all positions matched
- [ ] Quick sanity train: `python src/train.py --env` — check baseline accuracy
- [ ] Backup raw data (these are irreplaceable!)
- [ ] Commit data + initial results to git
