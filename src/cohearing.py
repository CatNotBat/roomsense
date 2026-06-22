"""Co-hearing alignment: pair cross-sensor readings within W ms.

Cross-sensor features (RSSI differences, spread, n_heard) are only
meaningful when readings describe the *same instant*. This module
enforces a strict max-gap constraint: for a given device at time t,
each satellite contributes only its nearest reading within W/2.
If no reading exists within the window, that satellite is marked
MISSING (NaN), distinct from NOT_HEARD (-120 dBm).
"""
import numpy as np
import pandas as pd
import os, sys

sys.path.insert(0, os.path.dirname(__file__))
from config import COHEARING_W_MS, SENSORS

MISSING = np.nan


def cohearing_samples(readings, W_ms=None, sensors=None):
    """Build co-hearing aligned samples from raw readings.

    For each (device, candidate_time_center), finds the nearest reading
    from each satellite within W/2. Satellites with no reading in the
    window are marked NaN (not backfilled).

    Args:
        readings: DataFrame with columns [ts, source, mac, rssi].
                  RSSI should already be calibrated.
        W_ms: co-hearing window in milliseconds (default from config).
        sensors: list of sensor IDs (default from config).

    Returns:
        DataFrame with columns:
            ts_center, mac, {sensor}_rssi for each sensor, n_heard
    """
    W = (W_ms if W_ms is not None else COHEARING_W_MS) / 1000.0
    half_W = W / 2.0
    sensors = sensors or sorted(SENSORS)
    min_center_gap = W / 4.0

    samples = []

    for mac, device_df in readings.groupby("mac"):
        # Pre-split by source for efficient lookup
        by_source = {}
        for s in sensors:
            sub = device_df[device_df["source"] == s].sort_values("ts")
            by_source[s] = (sub["ts"].values, sub["rssi"].values) if len(sub) > 0 else (np.array([]), np.array([]))

        # Candidate centers: all unique timestamps, thinned
        all_ts = np.sort(device_df["ts"].values)
        if len(all_ts) == 0:
            continue

        centers = [all_ts[0]]
        for t in all_ts[1:]:
            if t - centers[-1] >= min_center_gap:
                centers.append(t)

        for t in centers:
            sample = {"ts_center": t, "mac": mac}
            n_heard = 0

            for s in sensors:
                ts_arr, rssi_arr = by_source[s]
                if len(ts_arr) == 0:
                    sample[f"{s}_rssi"] = MISSING
                    continue

                # Find nearest reading within half_W
                idx = np.searchsorted(ts_arr, t)
                best_delta = half_W + 1
                best_rssi = None

                # Check idx and idx-1 (the two candidates around t)
                for candidate in (idx - 1, idx):
                    if 0 <= candidate < len(ts_arr):
                        delta = abs(ts_arr[candidate] - t)
                        if delta <= half_W and delta < best_delta:
                            best_delta = delta
                            best_rssi = rssi_arr[candidate]

                if best_rssi is not None:
                    sample[f"{s}_rssi"] = float(best_rssi)
                    n_heard += 1
                else:
                    sample[f"{s}_rssi"] = MISSING

            sample["n_heard"] = n_heard
            if n_heard > 0:
                samples.append(sample)

    if not samples:
        cols = ["ts_center", "mac"] + [f"{s}_rssi" for s in sensors] + ["n_heard"]
        return pd.DataFrame(columns=cols)

    return pd.DataFrame(samples)
