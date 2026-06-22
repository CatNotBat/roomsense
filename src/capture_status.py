#!/usr/bin/env python3
"""Live balance monitor: tail readings_raw.csv and print per-source row counts
and recent RSSI every 5s. All four esp_c* counts must climb together.
Run in a 3rd terminal during calibration."""
import os, sys, time
import pandas as pd

RAW = "data/readings_raw.csv"
INTERVAL = 5

if not os.path.exists(RAW):
    print(f"Waiting for {RAW} to appear...")
    while not os.path.exists(RAW):
        time.sleep(1)

print(f"Monitoring {RAW} — all 4 esp_c* counts must rise together.\n")

last_lines = 0
while True:
    try:
        df = pd.read_csv(RAW)
        new_lines = len(df) - last_lines
        last_lines = len(df)

        print(f"\n{'='*60}")
        print(f"  Total rows: {len(df)}   (+{new_lines} since last check)")
        print(f"{'='*60}")

        # Per-source counts
        src_counts = df.groupby("source").size().sort_index()
        print("\n  Per-source row counts:")
        max_count = src_counts.max() if len(src_counts) else 1
        for src, cnt in src_counts.items():
            pct = cnt / max_count * 100
            bar = "#" * int(pct / 5)
            warn = " *** LOW ***" if pct < 20 else ""
            print(f"    {src:15} {cnt:>8}  ({pct:5.1f}%) {bar}{warn}")

        # Recent RSSI per source (last 100 rows)
        recent = df.tail(100)
        if len(recent):
            print("\n  Recent avg RSSI (last 100 rows):")
            for src in sorted(recent["source"].unique()):
                sub = recent[recent["source"] == src]
                avg_rssi = sub["rssi"].mean()
                print(f"    {src:15} {avg_rssi:>7.1f} dBm  (n={len(sub)})")

    except Exception as e:
        print(f"  Read error (harmless): {e}")

    time.sleep(INTERVAL)
