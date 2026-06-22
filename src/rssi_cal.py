"""Load and apply per-node RSSI calibration offsets.

Usage:
    from rssi_cal import calibrate_rssi
    rssi_cal = calibrate_rssi(rssi_raw, sensor_id)  # rssi_raw + offset[sensor_id]

Offsets are loaded from calibration/node_offsets.json on import.
Call load_offsets() to reload after recalibration.

Auto-calibration:
    auto_calibrate() subscribes to MQTT for `duration` seconds, finds devices
    heard by ALL sensors, and computes relative RSSI offsets. No beacon needed.
"""
import collections, json, os, time
from statistics import median

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OFFSETS_FILE = os.path.join(_ROOT, "calibration", "node_offsets.json")

_offsets = {}  # sensor_id -> float offset


def load_offsets(path=None):
    """Load offsets from JSON file. Returns dict {sensor_id: float_offset}."""
    global _offsets
    p = path or _OFFSETS_FILE
    if os.path.exists(p):
        with open(p) as f:
            data = json.load(f)
        _offsets = {k: float(v) for k, v in data.get("offsets", {}).items()}
    else:
        _offsets = {}
    return dict(_offsets)


def calibrate_rssi(rssi, sensor_id):
    """Apply calibration: rssi_cal = rssi_raw + offset[sensor_id].
    Returns float. If no offset for sensor_id, returns rssi unchanged."""
    return rssi + _offsets.get(sensor_id, 0.0)


def auto_calibrate(duration=60, sensors=None, mqtt_host=None, mqtt_port=None,
                   save_path=None):
    """Auto-calibrate using shared BLE devices (no beacon needed).

    Subscribes to MQTT, collects all BLE readings, finds devices heard by
    ALL sensors, then computes per-node offsets as:
        offset[i] = global_median - node_median[i]

    Args:
        duration: seconds to collect data
        sensors: list of sensor IDs (defaults to config.SENSORS)
        mqtt_host: MQTT broker host (defaults to config.MQTT_HOST)
        mqtt_port: MQTT broker port (defaults to config.MQTT_PORT)
        save_path: where to save offsets (defaults to _OFFSETS_FILE)

    Returns:
        dict of {sensor_id: offset} or None if calibration failed
    """
    import paho.mqtt.client as mqtt
    from config import (MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS,
                        TOPIC_RSSI, SENSORS as CFG_SENSORS)

    sensors = sensors or CFG_SENSORS
    mqtt_host = mqtt_host or MQTT_HOST
    mqtt_port = mqtt_port or MQTT_PORT
    save_path = save_path or _OFFSETS_FILE

    # Collect: mac -> sensor -> [rssi]
    readings = collections.defaultdict(lambda: collections.defaultdict(list))

    def on_message(client, userdata, msg):
        try:
            p = msg.payload.decode().split("|")
            source, mac, rssi_s = p[0], p[1].lower(), p[2]
            if source in sensors:
                readings[mac][source].append(int(rssi_s))
        except Exception:
            pass

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_message = on_message
    client.connect(mqtt_host, mqtt_port, 60)
    client.subscribe(TOPIC_RSSI)

    print(f"Auto-calibrating for {duration}s using shared BLE devices...")
    client.loop_start()
    time.sleep(duration)
    client.loop_stop()
    client.disconnect()

    # Find devices heard by ALL sensors (with >=3 readings each)
    sensor_set = set(sensors)
    shared_macs = []
    for mac, sensor_data in readings.items():
        if set(sensor_data.keys()) >= sensor_set:
            if all(len(v) >= 3 for v in sensor_data.values()):
                shared_macs.append(mac)

    if len(shared_macs) < 3:
        print(f"Auto-calibration failed: only {len(shared_macs)} shared devices "
              f"(need >=3). Try a longer duration or check sensor placement.")
        return None

    # Per-sensor median across all shared devices
    per_sensor_medians = {}
    for sensor in sensors:
        all_medians = []
        for mac in shared_macs:
            all_medians.append(median(readings[mac][sensor]))
        per_sensor_medians[sensor] = median(all_medians)

    global_median = median(list(per_sensor_medians.values()))
    offsets = {s: round(global_median - m, 2) for s, m in per_sensor_medians.items()}

    result = {
        "offsets": offsets,
        "global_median_dBm": global_median,
        "per_node_medians_dBm": per_sensor_medians,
        "shared_device_count": len(shared_macs),
        "total_devices_seen": len(readings),
        "duration_s": duration,
        "method": "auto_shared_device",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "w") as f:
        json.dump(result, f, indent=2)

    # Reload offsets into module
    load_offsets(save_path)

    print(f"Auto-calibration complete. {len(shared_macs)} shared devices used.")
    print(f"Global median: {global_median:.1f} dBm")
    for s in sensors:
        print(f"  {s:<10} median={per_sensor_medians[s]:.1f}  offset={offsets[s]:+.1f}")

    return offsets


def has_calibration(path=None):
    """Check if calibration offsets file exists."""
    return os.path.exists(path or _OFFSETS_FILE)


# Auto-load on import
load_offsets()
