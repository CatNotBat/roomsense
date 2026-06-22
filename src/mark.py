#!/usr/bin/env python3
"""Phase 1: record one labeled position window -> data/labels.csv."""
import csv, os, time

OUT = "data/labels.csv"
os.makedirs("data", exist_ok=True)

def main():
    pos = input("Position name (e.g. IN_CENTER, OUT_SHARED_WALL): ").strip()
    io = ""
    while io not in ("in", "out"):
        io = input("Inside the room? type 'in' or 'out': ").strip().lower()
    input(f"Stand at [{pos}] holding the beacon. Press Enter to START...")
    start = time.time()
    print("Recording ~90s — move the beacon naturally within this spot.")
    input("Press Enter to STOP (aim ~90s)...")
    end = time.time()
    new = not os.path.exists(OUT)
    with open(OUT, "a", newline="") as f:
        wr = csv.writer(f)
        if new: wr.writerow(["position", "inout", "start_ts", "end_ts"])
        wr.writerow([pos, io, f"{start:.3f}", f"{end:.3f}"])
    print(f"Saved {pos} ({io}) {end - start:.0f}s\n")

if __name__ == "__main__":
    main()
