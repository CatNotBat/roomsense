# Room Sentinel v2 — Future Steps

## When Hardware Arrives

### Step 1: Flash & Test One Combo Node (30 min)

1. Wire one LD2450 to one WR-32 board:
   - LD2450 TX → ESP32 GPIO16 (RX2)
   - LD2450 RX → ESP32 GPIO17 (TX2)
   - LD2450 VCC → 5V, GND → GND

2. Edit `src/wr32_combo/secrets.h` with your WiFi/MQTT credentials

3. Edit SENSOR_ID in `wr32_combo.ino` line 29: `#define SENSOR_ID "esp_c1"`

4. Flash:
   ```bash
   arduino-cli compile --fqbn esp32:esp32:esp32:PartitionScheme=huge_app src/wr32_combo/
   arduino-cli upload --fqbn esp32:esp32:esp32:PartitionScheme=huge_app -p /dev/ttyUSB0 src/wr32_combo/
   ```

5. Verify on Serial Monitor (115200 baud):
   - "SNTP sync OK"
   - "MQTT connected!"
   - "Setup complete — BLE scan + LD2450 radar active."

6. Verify MQTT messages:
   ```bash
   mosquitto_sub -t sentinel/rssi -C 3    # should see BLE readings
   mosquitto_sub -t sentinel/radar -C 3   # should see radar frames
   ```

### Step 2: Flash All 4 Boards (15 min)

Change `SENSOR_ID` for each board: `esp_c1`, `esp_c2`, `esp_c3`, `esp_c4`.

Flash each board, verify both topics receive messages from all 4 sensors.

### Step 3: Mount & Calibrate (20 min)

1. Mount boards in room corners (same positions as v1 satellites)
2. Point LD2450 sensors toward room center (120-degree FOV)
3. Start broker: `mosquitto -c mosquitto_local.conf -d`
4. Run auto-calibration: system auto-calibrates on first `live_ble.py` startup

### Step 4: Collect Training Data (30 min)

```bash
python src/collect_walk.py
```

Walk through 8+ positions (CENTER, NEAR_WALL_N/S/E/W, OUTSIDE, OUT_HALLWAY, OUT_SHARED_WALL). Spend 60-90s at each position. The collector now records both BLE and radar data simultaneously.

```bash
python src/prepare_walk_data.py
```

This produces both `data/readings_labeled.csv` (BLE) and `data/radar_labeled.csv` (radar).

### Step 5: Train Fused Model (5 min)

```bash
python src/train.py --env data/readings_labeled.csv
```

This automatically picks up `data/radar_labeled.csv` and trains a fused BLE+radar model. Compare metrics with the BLE-only baseline — the C2-C3 wall accuracy should jump from 78% toward 90%+.

### Step 6: Go Live

```bash
python src/live_ble.py
# -> http://localhost:8080
```

The system auto-detects the fused model and subscribes to both `sentinel/rssi` and `sentinel/radar`.

---

## After v2 Is Working

### Zero-Calibration Baseline Mode
- On first deploy, assume room is empty for 5 min -> capture baseline env + radar features
- When features shift significantly -> mark as "occupied"
- No labeled walk needed for basic detection

### Android Device Testing
- Collect training data with Android phones
- Test dedup with Android multi-advertisement patterns
- Budget Android phones may have weaker BLE — verify detection

### Deploy to Raspberry Pi 4B
Deployment files ready in `deploy/`:
1. Copy repo to RPi: `rsync -av --exclude .venv . pi@<rpi_ip>:/opt/room-sentinel/`
2. Run setup: `sudo bash /opt/room-sentinel/deploy/setup-rpi.sh`
3. Copy trained model + calibration to `/opt/room-sentinel/models/` and `/opt/room-sentinel/calibration/`
4. Update ESP32 firmware `MQTT_SERVER` to RPi's IP, re-flash all 4 nodes
5. Start: `sudo systemctl start room-sentinel`
6. Optional: 5" DSI IPS screen + `deploy/kiosk.sh` for dedicated dashboard display

### Adaptive Threshold
- Track running statistics of env feature distributions
- Auto-adjust threshold when moved to a new room

### Multi-Room Support
- Each room gets its own 4-node array + model
- Brain runs multiple room instances
- Shared MQTT broker, separate topics per room

---

## Hardware Reference

| Part | Qty | Purpose |
|------|-----|---------|
| ESP32 WR-32 (CH340C) | 4 | Combo node: BLE scan + radar UART |
| HLK-LD2450 (24GHz mmWave) | 4 | Human presence/tracking (3 targets, x/y/speed) |
| Raspberry Pi 4B | 1 | Brain (planned, laptop for now) |

### LD2450 Wiring (per node)

| LD2450 Pin | ESP32 Pin |
|------------|-----------|
| VCC | 5V |
| GND | GND |
| TX | GPIO16 (RX2) |
| RX | GPIO17 (TX2) |

### LD2450 Specs
- 24GHz FMCW radar, 256000 baud UART
- Tracks up to 3 simultaneous targets
- Output: x/y coordinates (mm), speed (mm/s), distance (mm)
- 10 frames per second
- FOV: 120 degrees horizontal, 70 degrees vertical
- Range: up to 6m positioning
- Does NOT penetrate drywall at 24GHz (this is the feature, not a bug)
