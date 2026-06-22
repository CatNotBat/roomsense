#!/usr/bin/env python3
"""Combined MQTT recorder + interactive labeler for training data collection.

Records ALL BLE readings from MQTT while you label your position interactively.
Uses full-environment fingerprinting (no MAC filtering needed).

Usage:
    python src/collect_walk.py

Commands during session:
    mark <position> <in|out>   — label current position (e.g. "mark CENTER in")
    stop                       — end session and save

Positions should be consistent labels like:
    CENTER, NEAR_WALL_N, NEAR_WALL_S, NEAR_DOOR, OUTSIDE, OUT_HALLWAY, etc.
"""
import csv, os, sys, time, threading
import paho.mqtt.client as mqtt

sys.path.insert(0, os.path.dirname(__file__))
from config import (MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS,
                    TOPIC_RSSI, TOPIC_RADAR, SENSORS)

READINGS_FILE = "data/walk_readings_raw.csv"
RADAR_FILE = "data/walk_radar_raw.csv"
LABELS_FILE = "data/walk_labels.csv"
READING_COLS = ["ts", "source", "mac", "rssi", "addr_type", "mfg_hex", "svc_hex", "rx_ms"]
RADAR_COLS = ["ts", "source", "n_targets",
              "x0", "y0", "spd0", "dist0",
              "x1", "y1", "spd1", "dist1",
              "x2", "y2", "spd2", "dist2"]
LABEL_COLS = ["start_ts", "end_ts", "position", "inout"]


def main():
    os.makedirs("data", exist_ok=True)

    # --- MQTT recorder ---
    readings_f = open(READINGS_FILE, "w", newline="")
    readings_w = csv.writer(readings_f)
    readings_w.writerow(READING_COLS)

    radar_f = open(RADAR_FILE, "w", newline="")
    radar_w = csv.writer(radar_f)
    radar_w.writerow(RADAR_COLS)

    count = [0]
    radar_count = [0]

    def on_message(client, userdata, msg):
        try:
            if msg.topic == TOPIC_RSSI:
                p = msg.payload.decode().split("|")
                if len(p) < 8:
                    return
                sensor, mac, rssi = p[0], p[1].lower(), p[2]
                addr_type, mfg, svc, rx_ms = p[3], p[5], p[6], p[7]
                ts = time.time()
                readings_w.writerow([f"{ts:.3f}", sensor, mac, rssi,
                                     addr_type, mfg, svc, rx_ms])
                count[0] += 1
                if count[0] % 500 == 0:
                    readings_f.flush()

            elif msg.topic == TOPIC_RADAR:
                p = msg.payload.decode().split("|")
                if len(p) < 15:
                    return
                ts = time.time()
                # source, epochMs, nTargets, then 3×(x,y,spd,dist)
                radar_w.writerow([f"{ts:.3f}", p[0], p[2],
                                  p[3], p[4], p[5], p[6],
                                  p[7], p[8], p[9], p[10],
                                  p[11], p[12], p[13], p[14]])
                radar_count[0] += 1
                if radar_count[0] % 100 == 0:
                    radar_f.flush()
        except Exception:
            pass

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.subscribe(TOPIC_RSSI)
    client.subscribe(TOPIC_RADAR)
    client.loop_start()

    # --- Interactive labeler ---
    labels_f = open(LABELS_FILE, "w", newline="")
    labels_w = csv.writer(labels_f)
    labels_w.writerow(LABEL_COLS)

    print("=== Walk Data Collection (v2: BLE + Radar) ===")
    print(f"Recording BLE to:   {READINGS_FILE}")
    print(f"Recording radar to: {RADAR_FILE}")
    print(f"Labels to: {LABELS_FILE}")
    print(f"Sensors expected: {SENSORS}")
    print()
    print("Commands:")
    print("  mark <position> <in|out>  — e.g. 'mark CENTER in'")
    print("  stop                      — end session")
    print()
    print("Suggested positions: CENTER, NEAR_WALL_N, NEAR_WALL_S,")
    print("  NEAR_WALL_E, NEAR_WALL_W, NEAR_DOOR, OUTSIDE, OUT_HALLWAY")
    print()

    current_pos = None
    current_inout = None
    mark_start = None

    try:
        while True:
            try:
                cmd = input(f"[BLE:{count[0]} radar:{radar_count[0]}] > ").strip()
            except EOFError:
                break

            if not cmd:
                continue

            if cmd == "stop":
                if current_pos and mark_start:
                    end = time.time()
                    labels_w.writerow([f"{mark_start:.3f}", f"{end:.3f}",
                                       current_pos, current_inout])
                    labels_f.flush()
                    print(f"  Closed {current_pos} ({end - mark_start:.0f}s)")
                break

            parts = cmd.split()
            if len(parts) < 3 or parts[0] != "mark":
                print("Usage: mark <position> <in|out>")
                continue

            # Close previous
            if current_pos and mark_start:
                end = time.time()
                labels_w.writerow([f"{mark_start:.3f}", f"{end:.3f}",
                                   current_pos, current_inout])
                labels_f.flush()
                dur = end - mark_start
                print(f"  Closed {current_pos} ({dur:.0f}s)")

            current_pos = parts[1].upper()
            current_inout = parts[2].lower()
            mark_start = time.time()
            print(f"  [{time.strftime('%H:%M:%S')}] Marking: {current_pos} = {current_inout}")

    finally:
        client.loop_stop()
        client.disconnect()
        readings_f.close()
        radar_f.close()
        labels_f.close()

    print(f"\nDone! {count[0]} BLE readings saved to {READINGS_FILE}")
    print(f"      {radar_count[0]} radar frames saved to {RADAR_FILE}")
    print(f"Labels saved to {LABELS_FILE}")
    print()
    print("Next: run training with this data:")
    print(f"  .venv/bin/python src/train_walk.py")


if __name__ == "__main__":
    main()
