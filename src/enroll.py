#!/usr/bin/env python3
"""Learn the room's OWN fixed devices (AP, TV, etc.) so the live
census ignores them. Run once in the EMPTY room. Stores hashed MACs only."""
import asyncio, json, time, collections, os, sys
from bleak import BleakScanner

sys.path.insert(0, os.path.dirname(__file__))
from config import hash_mac

OUT  = "data/allowlist.json"
SECONDS = 60

async def main():
    counts = collections.Counter()
    def cb(device, adv): counts[device.address] += 1
    s = BleakScanner(detection_callback=cb, scanning_mode="active")
    print(f"Enrolling empty-room devices for {SECONDS}s - leave the room empty...")
    await s.start(); await asyncio.sleep(SECONDS); await s.stop()
    # keep only consistently-seen devices (real fixtures, not a passing phone)
    keep = [m for m, c in counts.items() if c >= 5]
    json.dump([hash_mac(m) for m in keep], open(OUT, "w"))
    print(f"Enrolled {len(keep)} fixed devices -> {OUT}")

if __name__ == "__main__":
    asyncio.run(main())
