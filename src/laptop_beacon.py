#!/usr/bin/env python3
"""Laptop-based BLE beacon for calibration.

Broadcasts a BLE advertisement with a known identity so satellites can
measure RSSI from a known position. Uses BlueZ D-Bus API via the
`bluetooth-advertise` capability.

Usage:
    sudo python src/laptop_beacon.py              # broadcast for 60s
    sudo SENTINEL_CAL_DURATION_S=120 python src/laptop_beacon.py

Requires: Linux with BlueZ 5.x, bluetoothctl available.
The laptop's BLE MAC is printed at start — set SENTINEL_BEACON_MAC to it.
"""
import subprocess, time, os, sys, signal

DURATION = int(os.getenv("SENTINEL_CAL_DURATION_S", "60"))


def get_local_mac():
    """Get the laptop's BLE adapter MAC address."""
    try:
        out = subprocess.check_output(
            ["bluetoothctl", "show"], text=True, timeout=5
        )
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("Controller"):
                return line.split()[1].lower()
    except Exception as e:
        print(f"Could not get BLE MAC: {e}", file=sys.stderr)
    return None


def advertise(duration_s):
    """Use bluetoothctl to broadcast a discoverable advertisement."""
    mac = get_local_mac()
    if mac:
        print(f"Laptop BLE MAC: {mac}")
        print(f"Set SENTINEL_BEACON_MAC={mac} for calibration")
    else:
        print("WARNING: Could not determine BLE MAC")

    print(f"\nBroadcasting for {duration_s}s...")
    print("Place laptop at room center, then run calibrate.py on the brain.\n")

    # Enable BLE adapter and set discoverable
    cmds = [
        "power on",
        "discoverable on",
        "set-alias SENTINEL_BEACON",
        "advertise on",
    ]

    proc = subprocess.Popen(
        ["bluetoothctl"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    for cmd in cmds:
        proc.stdin.write(cmd + "\n")
        proc.stdin.flush()
        time.sleep(0.5)

    print(f"Advertising... (Ctrl-C or wait {duration_s}s to stop)")

    def cleanup(*_):
        proc.stdin.write("advertise off\n")
        proc.stdin.write("discoverable off\n")
        proc.stdin.flush()
        time.sleep(0.5)
        proc.terminate()
        print("\nBeacon stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)

    time.sleep(duration_s)
    cleanup()


if __name__ == "__main__":
    advertise(DURATION)
