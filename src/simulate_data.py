#!/usr/bin/env python3
"""Generate synthetic 4-sensor RSSI data with labels for pipeline testing.
No hardware needed. Simulates the physics: inside devices have anisotropic
RSSI (1-2 clear paths, others shadowed), outside devices have correlated
wall-attenuated RSSI across all sensors.

Usage:
  python src/simulate_data.py            # generate data/readings_raw.csv + data/labels.csv
  python src/simulate_data.py --clean    # remove old data first
"""
import csv, os, sys, time
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from config import SENSORS

np.random.seed(42)

OUT_RAW = "data/readings_raw.csv"
OUT_LABELS = "data/labels.csv"
COLS = ["ts", "source", "mac", "rssi", "phy", "name",
        "addr_type", "appearance", "mfg_hex", "svc_hex"]

# Positions and their physics
POSITIONS = {
    # Inside positions: anisotropic RSSI, 1-2 sensors strong, others weaker
    "IN_CENTER":   {"inout": "in",  "base": [-55, -58, -57, -56], "noise": 4},
    "IN_CORNER_1": {"inout": "in",  "base": [-40, -65, -70, -68], "noise": 5},
    "IN_CORNER_2": {"inout": "in",  "base": [-66, -42, -65, -70], "noise": 5},
    "IN_CORNER_3": {"inout": "in",  "base": [-68, -67, -41, -64], "noise": 5},
    "IN_CORNER_4": {"inout": "in",  "base": [-70, -68, -65, -43], "noise": 5},
    "IN_DOOR":     {"inout": "in",  "base": [-50, -62, -60, -55], "noise": 4},
    "IN_POCKET":   {"inout": "in",  "base": [-65, -72, -68, -70], "noise": 6},
    "IN_WINDOW":   {"inout": "in",  "base": [-58, -55, -65, -62], "noise": 4},
    # Outside: correlated wall attenuation, all sensors see similar weak signal
    "OUT_HALLWAY":       {"inout": "out", "base": [-78, -80, -82, -79], "noise": 3},
    "OUT_ADJACENT_ROOM": {"inout": "out", "base": [-85, -83, -86, -84], "noise": 3},
    "OUT_SHARED_WALL_1": {"inout": "out", "base": [-72, -75, -80, -78], "noise": 4},
    "OUT_SHARED_WALL_2": {"inout": "out", "base": [-74, -73, -79, -81], "noise": 4},
    "OUT_SHARED_WALL_3": {"inout": "out", "base": [-71, -76, -82, -77], "noise": 4},
}

WINDOW_DURATION = 90  # seconds per position
PACKETS_PER_SECOND = 2  # per sensor


def generate():
    if "--clean" in sys.argv:
        for f in [OUT_RAW, OUT_LABELS]:
            if os.path.exists(f):
                os.remove(f)
                print(f"Removed {f}")

    os.makedirs("data", exist_ok=True)

    # Generate labels
    t = time.time() - len(POSITIONS) * WINDOW_DURATION  # backdate
    with open(OUT_LABELS, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["position", "inout", "start_ts", "end_ts"])
        for pos, info in POSITIONS.items():
            start = t
            end = t + WINDOW_DURATION
            w.writerow([pos, info["inout"], f"{start:.3f}", f"{end:.3f}"])
            t = end + 5  # small gap between positions

    # Generate raw readings
    # Use 3 "devices" per position to simulate multiple devices
    t = time.time() - len(POSITIONS) * WINDOW_DURATION
    device_counter = 0
    with open(OUT_RAW, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)

        for pos, info in POSITIONS.items():
            base = info["base"]
            noise = info["noise"]
            start = t
            end = t + WINDOW_DURATION

            # 3 simulated devices per position
            for dev in range(3):
                device_counter += 1
                mac = f"AA:BB:CC:DD:{device_counter:02X}:{dev:02X}"
                # Each device gets slightly different base RSSI
                dev_offset = np.random.randint(-3, 4, size=4)

                ts = start
                while ts < end:
                    for si, sensor in enumerate(SENSORS):
                        rssi = base[si] + dev_offset[si] + np.random.normal(0, noise)
                        rssi = int(np.clip(rssi, -120, -20))

                        # Inside devices: occasionally one sensor doesn't hear
                        if info["inout"] == "in" and np.random.random() < 0.05:
                            continue  # simulates body blocking

                        # Outside devices: occasionally not heard at all
                        if info["inout"] == "out" and np.random.random() < 0.1:
                            continue

                        addr_type = 1  # RPA
                        appearance = -1
                        mfg_hex = "4c001002abcd" if dev == 0 else ""  # first dev = Apple
                        svc_hex = ""

                        w.writerow([f"{ts:.3f}", sensor, mac, rssi, "btle", "",
                                    addr_type, appearance, mfg_hex, svc_hex])

                    ts += 1.0 / PACKETS_PER_SECOND

            t = end + 5

    # Count what we generated
    total = sum(1 for _ in open(OUT_RAW)) - 1
    print(f"Generated {total} rows across {len(POSITIONS)} positions, {device_counter} devices")
    print(f"  {OUT_RAW}: {os.path.getsize(OUT_RAW) / 1e6:.1f} MB")
    print(f"  {OUT_LABELS}: {len(POSITIONS)} position windows")
    print(f"\nRun the pipeline:")
    print(f"  python src/label_join.py")
    print(f"  python src/train.py")


if __name__ == "__main__":
    generate()
