#!/usr/bin/env python3
"""Environment-level features: aggregate ALL BLE devices per time window.

Instead of per-device features (which require MAC tracking), this builds
features from the entire BLE environment seen by each sensor in a time window.
This is robust to MAC rotation since we don't track individual devices.

For each (window, sensor):
  - RSSI distribution stats (median, IQR, max, min of all devices)
  - Device count (unique MACs seen)
  - Strong device count (RSSI > -70, > -80)
  - Packet rate

Cross-sensor features:
  - Device count spread, ratios
  - RSSI distribution differences between sensors
  - Which sensor sees most strong devices
"""
import itertools
import numpy as np
import pandas as pd
import os, sys

sys.path.insert(0, os.path.dirname(__file__))
from config import AGG_WINDOW_S, AGG_OVERLAP, SENSORS


def build_env_table(readings, A=None, overlap=None, sensors=None,
                    radar_readings=None, baseline_stats=None):
    """Build environment-level feature table.

    Args:
        readings: DataFrame with [ts, source, mac, rssi, position, inout]
        A: window size in seconds
        overlap: fraction overlap
        radar_readings: list[dict] with radar frames (optional).
            Each dict: {source, ts, n_targets, targets:[{x,y,spd,dist}]}
        baseline_stats: dict from BaselineCapture.stats (optional).
            If provided, adds bdev_* z-score features per window.

    Returns:
        (X, meta) — feature DataFrame and metadata with labels
    """
    A = A if A is not None else AGG_WINDOW_S
    overlap = overlap if overlap is not None else AGG_OVERLAP
    sensors = sensors or sorted(SENSORS)
    has_labels = "position" in readings.columns

    step = A * (1 - overlap)
    t_min, t_max = readings["ts"].min(), readings["ts"].max()
    starts = np.arange(t_min, t_max - A + step, step)

    rows, meta_rows = [], []

    for t_start in starts:
        t_end = t_start + A
        win = readings[(readings["ts"] >= t_start) & (readings["ts"] < t_end)]
        if len(win) < 10:
            continue

        feat = {}

        for sensor in sensors:
            sw = win[win["source"] == sensor]
            rssi = sw["rssi"].values.astype(float)
            n_macs = sw["mac"].nunique()

            if len(rssi) == 0:
                feat[f"env_median__{sensor}"] = np.nan
                feat[f"env_iqr__{sensor}"] = 0.0
                feat[f"env_max__{sensor}"] = np.nan
                feat[f"env_min__{sensor}"] = np.nan
                feat[f"env_pkt_count__{sensor}"] = 0
                feat[f"env_mac_count__{sensor}"] = 0
                feat[f"env_strong80__{sensor}"] = 0
                feat[f"env_strong70__{sensor}"] = 0
                feat[f"env_top3_median__{sensor}"] = np.nan
            else:
                feat[f"env_median__{sensor}"] = float(np.median(rssi))
                feat[f"env_iqr__{sensor}"] = float(np.percentile(rssi, 75) - np.percentile(rssi, 25))
                feat[f"env_max__{sensor}"] = float(np.max(rssi))
                feat[f"env_min__{sensor}"] = float(np.min(rssi))
                feat[f"env_pkt_count__{sensor}"] = len(rssi)
                feat[f"env_mac_count__{sensor}"] = n_macs
                feat[f"env_strong80__{sensor}"] = int((rssi > -80).sum())
                feat[f"env_strong70__{sensor}"] = int((rssi > -70).sum())
                # Top-3 strongest devices median
                top3 = sw.groupby("mac")["rssi"].median().nlargest(3)
                feat[f"env_top3_median__{sensor}"] = float(top3.median())

        # Cross-sensor features
        mac_counts = {s: feat.get(f"env_mac_count__{s}", 0) for s in sensors}
        strong80 = {s: feat.get(f"env_strong80__{s}", 0) for s in sensors}
        medians = {s: feat.get(f"env_median__{s}", np.nan) for s in sensors}
        top3s = {s: feat.get(f"env_top3_median__{s}", np.nan) for s in sensors}

        # Total unique MACs across all sensors
        feat["env_total_macs"] = win["mac"].nunique()
        feat["env_total_pkts"] = len(win)

        # MAC count spread
        counts = [v for v in mac_counts.values() if v > 0]
        feat["env_mac_spread"] = max(counts) - min(counts) if len(counts) >= 2 else 0

        # Strong-device spread
        s80 = list(strong80.values())
        feat["env_strong80_spread"] = max(s80) - min(s80)

        # Pairwise sensor deltas (on top3 medians — TX-invariant)
        for a, b in itertools.combinations(sensors, 2):
            ma = top3s.get(a, np.nan)
            mb = top3s.get(b, np.nan)
            if not np.isnan(ma) and not np.isnan(mb):
                feat[f"env_top3_delta__{a}__{b}"] = ma - mb
            else:
                feat[f"env_top3_delta__{a}__{b}"] = 0.0

        # Which sensor has strongest top3 (one-hot)
        valid_top3 = {s: v for s, v in top3s.items() if not np.isnan(v)}
        if valid_top3:
            loudest = max(valid_top3, key=valid_top3.get)
            for s in sensors:
                feat[f"env_loudest__{s}"] = 1 if s == loudest else 0
        else:
            for s in sensors:
                feat[f"env_loudest__{s}"] = 0

        # Env max across all sensors
        all_maxes = [feat.get(f"env_max__{s}", np.nan) for s in sensors]
        valid_max = [v for v in all_maxes if not np.isnan(v)]
        feat["env_global_max"] = max(valid_max) if valid_max else np.nan

        # Merge radar features if available
        if radar_readings:
            from radar_features import build_radar_features
            radar_feat = build_radar_features(
                radar_readings, float(t_start), float(t_end), sensors)
            feat.update(radar_feat)

        rows.append(feat)

        m = {"t_start": float(t_start), "t_end": float(t_end)}
        if has_labels:
            wl = win[["position", "inout"]].mode()
            m["position"] = wl["position"].iloc[0] if len(wl) > 0 else win["position"].iloc[0]
            m["inout"] = wl["inout"].iloc[0] if len(wl) > 0 else win["inout"].iloc[0]
        meta_rows.append(m)

    # Temporal derivatives: delta from previous window
    for i, feat in enumerate(rows):
        for sensor in sensors:
            med_key = f"env_median__{sensor}"
            pkt_key = f"env_pkt_count__{sensor}"
            if i == 0:
                feat[f"env_median_delta__{sensor}"] = 0.0
                feat[f"env_pkt_rate_delta__{sensor}"] = 0.0
            else:
                prev = rows[i - 1]
                cur_med = feat.get(med_key)
                prev_med = prev.get(med_key)
                if cur_med is not None and prev_med is not None \
                        and not (isinstance(cur_med, float) and np.isnan(cur_med)) \
                        and not (isinstance(prev_med, float) and np.isnan(prev_med)):
                    feat[f"env_median_delta__{sensor}"] = cur_med - prev_med
                else:
                    feat[f"env_median_delta__{sensor}"] = 0.0

                cur_pkt = feat.get(pkt_key, 0)
                prev_pkt = prev.get(pkt_key, 0)
                feat[f"env_pkt_rate_delta__{sensor}"] = cur_pkt - prev_pkt

    # Baseline deviation features (z-scores vs empty-room baseline)
    if baseline_stats:
        from baseline import baseline_deviation_features
        for feat in rows:
            feat.update(baseline_deviation_features(feat, baseline_stats))

    X = pd.DataFrame(rows)
    meta = pd.DataFrame(meta_rows)

    if len(X) > 0:
        rssi_cols = [c for c in X.columns if not c.startswith("radar_")]
        radar_cols = [c for c in X.columns if c.startswith("radar_")]
        if rssi_cols:
            X[rssi_cols] = X[rssi_cols].fillna(-120)
        if radar_cols:
            X[radar_cols] = X[radar_cols].fillna(0)

    return X, meta
