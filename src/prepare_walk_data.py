#!/usr/bin/env python3
"""Join walk readings with time-window labels to produce readings_labeled.csv.

Takes raw readings from collect_walk.py and labels from the interactive session,
then produces a labeled CSV compatible with train.py. Optionally processes
radar data from LD2450 mmWave sensors.

Usage:
    python src/prepare_walk_data.py
    python src/prepare_walk_data.py --readings data/walk_readings_raw.csv \
                                    --labels data/walk_labels.csv \
                                    --output data/readings_labeled.csv \
                                    --radar data/walk_radar_raw.csv \
                                    --radar-output data/radar_labeled.csv
"""
import argparse, os, sys
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from rssi_cal import load_offsets, calibrate_rssi


def prepare(readings_path, labels_path, output_path,
            radar_path=None, radar_output_path=None):
    readings = pd.read_csv(readings_path)
    labels = pd.read_csv(labels_path)

    print(f"Readings: {len(readings)} rows")
    print(f"Labels: {len(labels)} time windows")

    # Apply calibration offsets
    offsets = load_offsets()
    if offsets:
        print(f"Applying RSSI calibration offsets: {offsets}")
        readings["rssi"] = readings.apply(
            lambda r: calibrate_rssi(r["rssi"], r["source"]), axis=1
        )

    # Join readings with labels by time window
    parts = []
    for _, label in labels.iterrows():
        start_ts = float(label["start_ts"])
        end_ts = float(label["end_ts"])
        position = label["position"]
        inout = label["inout"]

        mask = (readings["ts"] >= start_ts) & (readings["ts"] <= end_ts)
        matched = readings[mask].copy()

        if len(matched) == 0:
            print(f"  WARNING: {position} ({inout}) matched 0 readings")
            continue

        matched["position"] = position
        matched["inout"] = inout
        parts.append(matched)

        dur = end_ts - start_ts
        print(f"  {position:25} {inout:3}  {len(matched):6} readings  ({dur:.0f}s)")

    if not parts:
        print("ERROR: No readings matched any labels")
        return

    result = pd.concat(parts, ignore_index=True)

    # Ensure columns match what train.py expects
    required = ["ts", "source", "mac", "rssi", "position", "inout"]
    # Preserve v4 columns if present (appearance, adv_type)
    optional_cols = ["addr_type", "appearance", "mfg_hex", "svc_hex", "rx_ms", "adv_type"]
    for col in required:
        if col not in result.columns:
            print(f"ERROR: missing required column: {col}")
            return

    result.to_csv(output_path, index=False)

    print(f"\nLabeled dataset: {len(result)} rows")
    print(f"Positions: {sorted(result['position'].unique())}")
    print(f"In/Out split:")
    print(result.groupby(["position", "inout"]).size().to_string())
    print(f"\nSaved to {output_path}")

    # --- Radar data (optional) ---
    if radar_path and os.path.exists(radar_path):
        radar_out = radar_output_path or "data/radar_labeled.csv"
        radar = pd.read_csv(radar_path)
        print(f"\nRadar: {len(radar)} frames")

        radar_parts = []
        for _, label in labels.iterrows():
            start_ts = float(label["start_ts"])
            end_ts = float(label["end_ts"])
            mask = (radar["ts"] >= start_ts) & (radar["ts"] <= end_ts)
            matched = radar[mask].copy()
            if len(matched) > 0:
                matched["position"] = label["position"]
                matched["inout"] = label["inout"]
                radar_parts.append(matched)
                dur = end_ts - start_ts
                print(f"  {label['position']:25} {label['inout']:3}  "
                      f"{len(matched):6} radar frames  ({dur:.0f}s)")

        if radar_parts:
            radar_labeled = pd.concat(radar_parts, ignore_index=True)
            radar_labeled.to_csv(radar_out, index=False)
            print(f"\nRadar labeled: {len(radar_labeled)} frames → {radar_out}")
        else:
            print("WARNING: No radar frames matched any labels")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--readings", default="data/walk_readings_raw.csv")
    parser.add_argument("--labels", default="data/walk_labels.csv")
    parser.add_argument("--output", default="data/readings_labeled.csv")
    parser.add_argument("--radar", default="data/walk_radar_raw.csv",
                        help="Radar readings CSV (optional, skipped if missing)")
    parser.add_argument("--radar-output", default="data/radar_labeled.csv")
    args = parser.parse_args()
    prepare(args.readings, args.labels, args.output,
            args.radar, args.radar_output)
