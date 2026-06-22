#!/usr/bin/env python3
"""Per-node RSSI offset calibration.

Place the beacon at room center (or a known equidistant spot).
Run all satellites. This script collects beacon RSSI for a configurable
duration, computes per-node offsets, and saves them.

    offset[i] = median_all_nodes - median(node_i)

Usage:
    python src/calibrate.py                          # default 60s
    SENTINEL_CAL_DURATION_S=120 python src/calibrate.py
"""
import json, os, time, signal, sys
import paho.mqtt.client as mqtt

sys.path.insert(0, os.path.dirname(__file__))
from config import (MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS,
                    TOPIC_RSSI, SENSORS)

CALIBRATION_DURATION_S = int(os.getenv("SENTINEL_CAL_DURATION_S", "60"))
CALIBRATION_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "calibration"
)
OFFSETS_FILE = os.path.join(CALIBRATION_DIR, "node_offsets.json")
BEACON_MAC = os.getenv("SENTINEL_BEACON_MAC", "00:00:00:00:00:00").lower()


def run_calibration():
    """Collect RSSI from all satellites for CALIBRATION_DURATION_S seconds,
    compute offsets, save to node_offsets.json."""
    readings = []  # list of (source, rssi)

    def on_message(client, userdata, msg):
        try:
            p = msg.payload.decode().split("|")
            source, mac, rssi_s = p[0], p[1].lower(), p[2]
            if mac == BEACON_MAC:
                readings.append((source, int(rssi_s)))
        except Exception:
            pass

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.subscribe(TOPIC_RSSI)

    print(f"Calibrating for {CALIBRATION_DURATION_S}s")
    print(f"  Beacon MAC: {BEACON_MAC}")
    print(f"  Expected sensors: {SENSORS}")
    print(f"  Output: {OFFSETS_FILE}")

    client.loop_start()
    time.sleep(CALIBRATION_DURATION_S)
    client.loop_stop()
    client.disconnect()

    if not readings:
        print("ERROR: No beacon readings received. Is the beacon broadcasting?")
        return None

    # Compute per-node medians
    from statistics import median
    per_node = {}
    for source, rssi in readings:
        per_node.setdefault(source, []).append(rssi)

    node_medians = {s: median(vals) for s, vals in per_node.items()}
    global_median = median(list(node_medians.values()))

    offsets = {}
    for sensor in SENSORS:
        if sensor in node_medians:
            offsets[sensor] = round(global_median - node_medians[sensor], 2)
        else:
            print(f"WARNING: {sensor} had 0 readings during calibration")
            offsets[sensor] = 0.0

    result = {
        "offsets": offsets,
        "global_median_dBm": global_median,
        "per_node_medians_dBm": node_medians,
        "per_node_counts": {s: len(v) for s, v in per_node.items()},
        "beacon_mac": BEACON_MAC,
        "duration_s": CALIBRATION_DURATION_S,
        "total_readings": len(readings),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    os.makedirs(CALIBRATION_DIR, exist_ok=True)
    with open(OFFSETS_FILE, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\nCalibration complete. {len(readings)} readings.")
    print(f"Global median: {global_median:.1f} dBm")
    print()
    print(f"  {'Sensor':<10} {'Median':>8} {'Offset':>8} {'Count':>6}")
    print(f"  {'------':<10} {'------':>8} {'------':>8} {'-----':>6}")
    for s in SENSORS:
        m = node_medians.get(s, float("nan"))
        o = offsets.get(s, 0.0)
        c = len(per_node.get(s, []))
        print(f"  {s:<10} {m:>8.1f} {o:>+8.1f} {c:>6}")

    return result


if __name__ == "__main__":
    run_calibration()
