#!/usr/bin/env python3
"""Worn-device labeling tool for real-device data collection.

Two modes:
  record — Interactive session recording carried-device positions
  join   — Join readings with labels, filtering to carried MACs only

Usage:
    python src/label_worn.py record --macs "aa:bb:cc:dd:ee:ff,11:22:33:44:55:66"
    > mark IN_CENTER in [orientation] [notes]
    > stop

    python src/label_worn.py join \\
        --readings data/readings_raw.csv \\
        --labels data/worn_labels.csv \\
        --output data/readings_worn_labeled.csv
"""
import argparse, csv, time, os, sys
import pandas as pd

LABELS_FILE = "data/worn_labels.csv"
LABEL_COLS = ["start_ts", "end_ts", "position", "inout", "orientation",
              "carried_macs", "notes"]


def start_session(carried_macs, output=None):
    """Interactive labeling session. Records position changes with timestamps."""
    out = output or LABELS_FILE
    os.makedirs(os.path.dirname(out), exist_ok=True)

    new = not os.path.exists(out)
    f = open(out, "a", newline="")
    w = csv.writer(f)
    if new:
        w.writerow(LABEL_COLS)

    macs_str = ";".join(m.lower() for m in carried_macs)
    print(f"Labeling session started.")
    print(f"  Carried MACs: {carried_macs}")
    print(f"  Output: {out}")
    print()
    print("Commands:")
    print("  mark <position> <in|out> [orientation] [notes]")
    print("  stop")
    print()

    current_pos = None
    current_label = None
    current_orient = ""
    mark_start = None

    try:
        while True:
            try:
                cmd = input("> ").strip()
            except EOFError:
                break

            if not cmd:
                continue

            if cmd == "stop":
                if current_pos and mark_start:
                    w.writerow([f"{mark_start:.3f}", f"{time.time():.3f}",
                               current_pos, current_label, current_orient,
                               macs_str, ""])
                    f.flush()
                    print(f"  Closed {current_pos} ({time.time() - mark_start:.0f}s)")
                break

            parts = cmd.split(maxsplit=4)
            if len(parts) < 3 or parts[0] != "mark":
                print("Usage: mark <position> <in|out> [orientation] [notes]")
                continue

            # Close previous mark
            if current_pos and mark_start:
                w.writerow([f"{mark_start:.3f}", f"{time.time():.3f}",
                           current_pos, current_label, current_orient,
                           macs_str, ""])
                f.flush()
                dur = time.time() - mark_start
                print(f"  Closed {current_pos} ({dur:.0f}s)")

            current_pos = parts[1]
            current_label = parts[2]
            current_orient = parts[3] if len(parts) > 3 else ""
            notes = parts[4] if len(parts) > 4 else ""
            mark_start = time.time()

            print(f"  [{time.strftime('%H:%M:%S')}] Marking: {current_pos} = "
                  f"{current_label} {current_orient}")

    finally:
        f.close()

    print(f"\nLabels saved to {out}")


def join_labels(readings_path, labels_path, output_path):
    """Join readings with worn-device labels, filtering to carried MACs.

    Only readings from carried devices within labeled time windows are kept.
    This prevents neighbor-device label poisoning.
    """
    readings = pd.read_csv(readings_path)
    labels = pd.read_csv(labels_path)

    print(f"Readings: {len(readings)} rows")
    print(f"Labels: {len(labels)} entries")

    parts = []
    for _, label in labels.iterrows():
        carried = set(m.strip().lower()
                      for m in str(label["carried_macs"]).split(";")
                      if m.strip())

        start_ts = float(label["start_ts"])
        end_ts = float(label["end_ts"])

        # Filter to time window AND carried MACs only
        mask = ((readings["ts"] >= start_ts) &
                (readings["ts"] <= end_ts) &
                (readings["mac"].str.lower().isin(carried)))

        matched = readings[mask].copy()
        if len(matched) == 0:
            print(f"  WARNING: {label['position']} matched 0 readings")
            continue

        matched["position"] = label["position"]
        matched["inout"] = label["inout"]
        matched["orientation"] = label.get("orientation", "")
        parts.append(matched)

        print(f"  {label['position']:25} {label['inout']:3}  "
              f"{len(matched):5} readings  "
              f"({len(matched[matched['mac'].str.lower().isin(carried)]['mac'].unique())} MACs)")

    if not parts:
        print("WARNING: No readings matched any labels")
        pd.DataFrame().to_csv(output_path, index=False)
        return pd.DataFrame()

    result = pd.concat(parts, ignore_index=True)
    result.to_csv(output_path, index=False)

    print(f"\nLabeled worn-device rows: {len(result)}")
    print(f"Positions: {sorted(result['position'].unique())}")
    print(f"MACs: {sorted(result['mac'].str.lower().unique())}")
    print(result.groupby(["position", "inout"]).size())

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Worn-device labeling tool")
    sub = parser.add_subparsers(dest="command")

    rec = sub.add_parser("record", help="Start interactive labeling session")
    rec.add_argument("--macs", required=True,
                     help="Comma-separated carried device MACs")
    rec.add_argument("--output", default=LABELS_FILE,
                     help=f"Output labels file (default: {LABELS_FILE})")

    join = sub.add_parser("join", help="Join readings with worn-device labels")
    join.add_argument("--readings", default="data/readings_raw.csv",
                      help="Raw readings CSV path")
    join.add_argument("--labels", default=LABELS_FILE,
                      help="Worn labels CSV path")
    join.add_argument("--output", default="data/readings_worn_labeled.csv",
                      help="Output labeled CSV path")

    args = parser.parse_args()
    if args.command == "record":
        macs = [m.strip() for m in args.macs.split(",")]
        start_session(macs, args.output)
    elif args.command == "join":
        join_labels(args.readings, args.labels, args.output)
    else:
        parser.print_help()
