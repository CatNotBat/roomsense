"""Temporal aggregation: distributional features over A-second windows.

Replaces the 2-second snapshot windowing with 20-second (configurable)
aggregation windows with 50% overlap. This is the highest-impact single
change — it averages out deep fading, channel rotation noise, and
single-packet outliers.

For each (device, agg_window):
  - Per-sensor distributional stats (median, IQR, MAD, max, min, count, coverage)
  - Cross-sensor features from co-hearing sub-samples (spread, deltas, n_heard)
  - TX-invariant transfer features (self-normalization, anisotropy, argmax coverage)
"""
import itertools
import numpy as np
import pandas as pd
import os, sys

sys.path.insert(0, os.path.dirname(__file__))
from config import AGG_WINDOW_S, AGG_OVERLAP, SENSORS, COHEARING_W_MS, REFERENCE_SENSOR
from cohearing import cohearing_samples
from transfer_features import self_normalize, anisotropy, argmax_coverage, reference_node_delta

NOT_HEARD = -120  # sentinel for unheard sensor (backwards compat)
N_SUBWINDOWS = 10  # for frac_subwindows_heard


def _frac_subwindows_heard(timestamps, t_start, t_end, n_sub=N_SUBWINDOWS):
    """Fraction of n_sub equal sub-windows containing at least one reading."""
    if len(timestamps) == 0:
        return 0.0
    sub_len = (t_end - t_start) / n_sub
    if sub_len <= 0:
        return 0.0
    heard = 0
    for i in range(n_sub):
        s = t_start + i * sub_len
        e = s + sub_len
        if ((timestamps >= s) & (timestamps < e)).any():
            heard += 1
    return heard / n_sub


def _per_sensor_stats(rssi_series, timestamps, t_start, t_end):
    """Distributional features for one (device, sensor) in one agg window."""
    if len(rssi_series) == 0:
        return {
            "rssi_median": np.nan, "rssi_iqr": np.nan, "rssi_mad": np.nan,
            "rssi_max": np.nan, "rssi_min": np.nan, "pkt_count": 0,
            "frac_heard": 0.0,
        }
    s = rssi_series.astype(float)
    med = float(s.median())
    return {
        "rssi_median": med,
        "rssi_iqr": float(s.quantile(0.75) - s.quantile(0.25)),
        "rssi_mad": float((s - med).abs().median()),
        "rssi_max": float(s.max()),
        "rssi_min": float(s.min()),
        "pkt_count": int(len(s)),
        "frac_heard": _frac_subwindows_heard(timestamps, t_start, t_end),
    }


def build_aggregated_table(readings, A=None, overlap=None, sensors=None,
                           cohearing_w_ms=None, reference_sensor=None):
    """Build feature table with temporal aggregation.

    Args:
        readings: DataFrame with columns [ts, source, mac, rssi]
                  (and optionally position, inout for training).
        A: aggregation window in seconds (default from config).
        overlap: fraction overlap between windows (default from config).
        sensors: list of sensor IDs (default from config).
        cohearing_w_ms: co-hearing window in ms (default from config).
        reference_sensor: sensor tagged as reference/outside (default from config).

    Returns:
        (X, meta) tuple:
            X: DataFrame with all features, one row per (mac, window)
            meta: DataFrame with mac, t_start, t_end [, position, inout]
    """
    A = A if A is not None else AGG_WINDOW_S
    overlap = overlap if overlap is not None else AGG_OVERLAP
    sensors = sensors or sorted(SENSORS)
    cohearing_w_ms = cohearing_w_ms if cohearing_w_ms is not None else COHEARING_W_MS
    ref_sensor = reference_sensor or REFERENCE_SENSOR or None
    interior_sensors = [s for s in sensors if s != ref_sensor] if ref_sensor else sensors

    has_labels = "position" in readings.columns
    step = A * (1 - overlap)

    rows, meta_rows = [], []

    for mac, mac_df in readings.groupby("mac"):
        t_min, t_max = mac_df["ts"].min(), mac_df["ts"].max()

        # Generate overlapping windows
        starts = np.arange(t_min, t_max - A + step, step)

        for t_start in starts:
            t_end = t_start + A
            win_mask = (mac_df["ts"] >= t_start) & (mac_df["ts"] < t_end)
            win_df = mac_df[win_mask]

            if len(win_df) == 0:
                continue

            feat = {}
            sensor_medians = {}

            # --- Per-sensor distributional stats ---
            for sensor in sensors:
                s_mask = win_df["source"] == sensor
                s_rssi = win_df.loc[s_mask, "rssi"]
                s_ts = win_df.loc[s_mask, "ts"]
                stats = _per_sensor_stats(s_rssi, s_ts, t_start, t_end)

                for k, v in stats.items():
                    feat[f"{k}__{sensor}"] = v

                sensor_medians[sensor] = stats["rssi_median"]

            # --- Aggregate cross-sensor features ---
            heard = {s: m for s, m in sensor_medians.items() if not np.isnan(m)}
            heard_vals = list(heard.values())
            feat["n_heard"] = len(heard)

            if heard_vals:
                feat["rssi_vec_max"] = max(heard_vals)
                feat["rssi_spread"] = max(heard_vals) - min(heard_vals) if len(heard_vals) >= 2 else 0.0
            else:
                feat["rssi_vec_max"] = NOT_HEARD
                feat["rssi_spread"] = 0.0

            # Pairwise deltas (TX-power-invariant)
            for a, b in itertools.combinations(sensors, 2):
                ma = sensor_medians.get(a, np.nan)
                mb = sensor_medians.get(b, np.nan)
                if not np.isnan(ma) and not np.isnan(mb):
                    feat[f"delta__{a}__{b}"] = ma - mb
                else:
                    feat[f"delta__{a}__{b}"] = 0.0

            # --- Co-hearing sub-samples for argmax features ---
            co_samples = cohearing_samples(win_df, W_ms=cohearing_w_ms, sensors=sensors)
            sub_argmaxes = []
            if len(co_samples) > 0:
                rssi_cols = [f"{s}_rssi" for s in sensors]
                for _, row in co_samples.iterrows():
                    vals = {s: row[f"{s}_rssi"] for s in sensors
                            if not np.isnan(row[f"{s}_rssi"])}
                    if vals:
                        sub_argmaxes.append(max(vals, key=vals.get))

            # Loudest sensor one-hot (from aggregated medians)
            if len(heard) >= 2:
                loudest = max(heard, key=heard.get)
                for s in sensors:
                    feat[f"is_loudest__{s}"] = 1 if s == loudest else 0
            else:
                for s in sensors:
                    feat[f"is_loudest__{s}"] = 0

            # --- Transfer features ---
            # Self-normalization
            normed = self_normalize(sensor_medians, sensors)
            for s in sensors:
                feat[f"rssi_normed__{s}"] = normed[s] if not np.isnan(normed.get(s, np.nan)) else 0.0

            # Anisotropy (IQR of per-satellite medians)
            feat["anisotropy"] = anisotropy(sensor_medians)

            # Argmax coverage (fraction of distinct satellites ever loudest)
            feat["argmax_coverage"] = argmax_coverage(sub_argmaxes, len(sensors))

            # Reference node delta
            ref_delta = reference_node_delta(sensor_medians, ref_sensor, interior_sensors)
            feat["ref_delta"] = ref_delta if ref_delta is not None else 0.0

            rows.append(feat)

            m = {"mac": mac, "t_start": float(t_start), "t_end": float(t_end)}
            if has_labels:
                # Majority label in window
                m["position"] = win_df["position"].mode().iloc[0] if len(win_df["position"].mode()) > 0 else win_df["position"].iloc[0]
                m["inout"] = win_df["inout"].mode().iloc[0] if len(win_df["inout"].mode()) > 0 else win_df["inout"].iloc[0]
            meta_rows.append(m)

    X = pd.DataFrame(rows)
    meta = pd.DataFrame(meta_rows)

    # Fill any remaining NaN with NOT_HEARD for RSSI columns, 0 for others
    if len(X) > 0:
        rssi_cols = [c for c in X.columns if "rssi" in c and "normed" not in c]
        other_cols = [c for c in X.columns if c not in rssi_cols]
        X[rssi_cols] = X[rssi_cols].fillna(NOT_HEARD)
        X[other_cols] = X[other_cols].fillna(0)

    return X, meta
