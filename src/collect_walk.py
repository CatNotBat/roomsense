#!/usr/bin/env python3
"""Combined MQTT recorder + interactive labeler for training data collection.

Records ALL BLE readings from MQTT while you label your position interactively.
Uses full-environment fingerprinting (no MAC filtering needed).

v4: captures appearance + advType fields, per-sensor packet rate log.

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
SENSOR_STATS_FILE = "data/walk_sensor_stats.csv"

# v4: added appearance + advType columns
READING_COLS = ["ts", "source", "mac", "rssi", "addr_type", "appearance",
                "mfg_hex", "svc_hex", "rx_ms", "adv_type"]
RADAR_COLS = ["ts", "source", "n_targets",
              "x0", "y0", "spd0", "dist0",
              "x1", "y1", "spd1", "dist1",
              "x2", "y2", "spd2", "dist2"]
LABEL_COLS = ["start_ts", "end_ts", "position", "inout"]
STATS_COLS = ["ts", "sensor", "ble_pkts_10s", "unique_macs_10s",
              "radar_frames_10s", "min_rssi", "max_rssi", "median_rssi"]


def main():
    os.makedirs("data", exist_ok=True)

    # --- MQTT recorder ---
    readings_f = open(READINGS_FILE, "w", newline="")
    readings_w = csv.writer(readings_f)
    readings_w.writerow(READING_COLS)

    radar_f = open(RADAR_FILE, "w", newline="")
    radar_w = csv.writer(radar_f)
    radar_w.writerow(RADAR_COLS)

    stats_f = open(SENSOR_STATS_FILE, "w", newline="")
    stats_w = csv.writer(stats_f)
    stats_w.writerow(STATS_COLS)

    count = [0]
    radar_count = [0]

    # Per-sensor stats tracking (reset every 10s)
    sensor_stats = {s: {"pkts": 0, "radar": 0, "macs": set(), "rssis": []}
                    for s in SENSORS}
    stats_lock = threading.Lock()

    def flush_stats():
        """Write per-sensor stats every 10s."""
        while True:
            time.sleep(10)
            ts = time.time()
            with stats_lock:
                for s in SENSORS:
                    st = sensor_stats[s]
                    rssis = st["rssis"]
                    if rssis:
                        rssis_sorted = sorted(rssis)
                        mid = len(rssis_sorted) // 2
                        median_r = rssis_sorted[mid]
                        min_r = rssis_sorted[0]
                        max_r = rssis_sorted[-1]
                    else:
                        median_r = min_r = max_r = ""
                    stats_w.writerow([
                        f"{ts:.3f}", s, st["pkts"], len(st["macs"]),
                        st["radar"], min_r, max_r, median_r
                    ])
                    # Reset
                    sensor_stats[s] = {"pkts": 0, "radar": 0,
                                       "macs": set(), "rssis": []}
                stats_f.flush()

    stats_thread = threading.Thread(target=flush_stats, daemon=True)
    stats_thread.start()

    def on_message(client, userdata, msg):
        try:
            if msg.topic == TOPIC_RSSI:
                p = msg.payload.decode().split("|")
                if len(p) < 8:
                    return
                # v3.1 format: source|mac|rssi|addrType|appearance|mfgHex|svcHex|rxMs|advType
                fields = (p + [""] * 9)[:9]
                sensor = fields[0]
                mac = fields[1].lower()
                rssi = fields[2]
                addr_type = fields[3]
                appearance = fields[4]
                mfg = fields[5]
                svc = fields[6]
                rx_ms = fields[7]
                adv_type = fields[8]
                ts = time.time()

                readings_w.writerow([f"{ts:.3f}", sensor, mac, rssi,
                                     addr_type, appearance, mfg, svc,
                                     rx_ms, adv_type])
                count[0] += 1
                if count[0] % 500 == 0:
                    readings_f.flush()

                # Track stats
                rssi_int = int(rssi) if rssi else -120
                with stats_lock:
                    if sensor in sensor_stats:
                        sensor_stats[sensor]["pkts"] += 1
                        sensor_stats[sensor]["macs"].add(mac)
                        sensor_stats[sensor]["rssis"].append(rssi_int)

            elif msg.topic == TOPIC_RADAR:
                p = msg.payload.decode().split("|")
                if len(p) < 15:
                    return
                ts = time.time()
                sensor = p[0]
                radar_w.writerow([f"{ts:.3f}", sensor, p[2],
                                  p[3], p[4], p[5], p[6],
                                  p[7], p[8], p[9], p[10],
                                  p[11], p[12], p[13], p[14]])
                radar_count[0] += 1
                if radar_count[0] % 100 == 0:
                    radar_f.flush()

                with stats_lock:
                    if sensor in sensor_stats:
                        sensor_stats[sensor]["radar"] += 1
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

    print("=== RoomSense Data Collection (v4: BLE + Radar + Stats) ===")
    print(f"Recording BLE to:       {READINGS_FILE}")
    print(f"Recording radar to:     {RADAR_FILE}")
    print(f"Sensor stats to:        {SENSOR_STATS_FILE}")
    print(f"Labels to:              {LABELS_FILE}")
    print(f"Sensors expected:       {SENSORS}")
    print()
    print("Commands:")
    print("  mark <position> <in|out>  — e.g. 'mark CENTER in'")
    print("  status                    — show per-sensor packet counts")
    print("  stop                      — end session")
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

            if cmd == "status":
                with stats_lock:
                    print(f"\n  {'Sensor':<12} {'BLE pkts':>10} {'Radar':>8} {'MACs':>6}")
                    print(f"  {'-'*40}")
                    for s in SENSORS:
                        st = sensor_stats[s]
                        print(f"  {s:<12} {st['pkts']:>10} {st['radar']:>8} {len(st['macs']):>6}")
                    print()
                continue

            parts = cmd.split()
            if len(parts) < 3 or parts[0] != "mark":
                print("Usage: mark <position> <in|out>  |  status  |  stop")
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
        stats_f.close()

    print(f"\nDone! {count[0]} BLE readings saved to {READINGS_FILE}")
    print(f"      {radar_count[0]} radar frames saved to {RADAR_FILE}")
    print(f"Labels saved to {LABELS_FILE}")
    print(f"Sensor stats saved to {SENSOR_STATS_FILE}")
    print()
    print("Next steps:")
    print(f"  1. python src/prepare_walk_data.py")
    print(f"  2. python src/train.py --env")


if __name__ == "__main__":
    main()
