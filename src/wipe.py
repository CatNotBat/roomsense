#!/usr/bin/env python3
"""Delete all captured data and the room allowlist. Requires confirmation."""
import glob, os, sys

targets = glob.glob("data/*.csv") + glob.glob("data/*.kismet") + ["data/allowlist.json"]
targets = [p for p in targets if os.path.exists(p)]

if not targets:
    print("Nothing to delete."); sys.exit(0)

print("Files to delete:")
for p in targets:
    sz = os.path.getsize(p)
    unit = "MB" if sz > 1e6 else "KB"
    val = sz / 1e6 if sz > 1e6 else sz / 1e3
    print(f"  {p}  ({val:.1f} {unit})")

if "--yes" not in sys.argv:
    confirm = input('\nType "DELETE" to confirm: ').strip()
    if confirm != "DELETE":
        print("Aborted."); sys.exit(1)

for p in targets:
    os.remove(p); print("removed", p)
print("Done.")
