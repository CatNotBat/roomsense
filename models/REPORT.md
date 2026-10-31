# RoomSense — Model Report

Trained: 2026-06-20
Model: v3_env (environment-level features)

## Configuration
- Algorithm: Random Forest, 500 trees
- Features: environment-level (not per-device)
- Window: 10s, no overlap
- Threshold: 0.50
- Cross-validation: Leave-One-Position-Out (LOPO)

## Training Data
- 199,692 BLE readings across 21 labeled time windows
- 8 positions: CENTER, NEAR_WALL_C1_C2, NEAR_WALL_C2_C3, NEAR_WALL_C3_C4, NEAR_WALL_C4_C1, OUT_DOOR, OUT_SHARED_WALL_C2_C3, OUT_SHARED_WALL_C3_C4
- Additional: CENTER_PHONE_ONLY, CENTER_AIRPODS_ONLY, EMPTY_ROOM
- 3 data collection rounds (60s, 90s, 120s per position)
- Calibration: multi-beacon method (26 shared devices)

## Results

| Metric | Value |
|--------|-------|
| LOPO accuracy (all positions) | 83.8% |
| LOPO accuracy (excl. C2-C3 wall) | **93.8%** |
| Phone-only detection | 95% |
| AirPods-only detection | 95% |
| Empty room (no false positives) | 100% |

## Live Testing (manual, 2026-06-20)

| Scenario | Presence | Count |
|----------|----------|-------|
| 2 iPhones + AirPods | room_prob 0.98 | 3 (correct) |
| Empty room | room_prob 0.02 | 0 (correct) |
| Single iPhone | room_prob 0.94 | 1 (correct) |
| Entry detection | ~10s | — |
| Exit detection | ~25s | — |

## Known Limitation
Wall between sensors C2 and C3 is RF-transparent (~0 dB BLE attenuation). The model cannot distinguish inside from outside this specific wall. Recommended fix: mmWave radar fusion.
