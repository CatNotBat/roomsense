#!/usr/bin/env python3
"""Non-interactive labeling: takes position, inout, and duration as CLI args."""
import csv, os, sys, time

OUT = "data/labels.csv"
os.makedirs("data", exist_ok=True)

pos = sys.argv[1]       # e.g. IN_CENTER
io = sys.argv[2]        # in or out
dur = int(sys.argv[3])  # seconds

start = time.time()
print(f"Recording [{pos}] ({io}) for {dur}s ...")
time.sleep(dur)
end = time.time()

new = not os.path.exists(OUT)
with open(OUT, "a", newline="") as f:
    wr = csv.writer(f)
    if new:
        wr.writerow(["position", "inout", "start_ts", "end_ts"])
    wr.writerow([pos, io, f"{start:.3f}", f"{end:.3f}"])
print(f"Saved {pos} ({io}) {end - start:.0f}s")
