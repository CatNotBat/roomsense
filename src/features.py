"""Shared feature engineering for the 4-sensor differential model.
One sample = one (mac, phy) over one time window.
Per-source RSSI stats become columns. With >=2 sources, transmit-power-invariant
DIFFERENCE features appear automatically (RSSI_A - RSSI_B cancels TX power).

v2 additions: rssi_spread, rssi_vec_max, n_heard, argmax_stability.

CHANNEL CONFOUND NOTE (Phase 1.2 finding):
  BLE advertising channel (37/38/39) is NOT exposed by the Bluedroid stack.
  Cross-sensor RSSI differences mix geometry with frequency-selective fading
  across channels 37 (2402 MHz), 38 (2426 MHz), 39 (2480 MHz).
  Mitigation: temporal aggregation (aggregation.py, A=20s default) averages
  over many channel-rotation cycles (~100ms each), reducing this confound.
  If a future firmware exposes channel, pass a 'channel' column and the
  aggregation module will compute within-channel features automatically.
"""
import itertools, math
import numpy as np
import pandas as pd
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from config import SENSORS, ARGMAX_STABILITY_S

NOT_HEARD = -120  # dBm sentinel: "this sensor did not hear this device this window"

STAT_KEYS = ["rssi_median", "rssi_mean", "rssi_std", "rssi_min", "rssi_max",
             "rssi_p25", "rssi_p75", "rssi_range"]

def _safe_std(s):
    v = s.std()
    return 0.0 if (v is None or np.isnan(v)) else float(v)

def _stats(g):
    s = g["rssi"].astype(float)
    return {
        "rssi_median": float(s.median()),
        "rssi_mean":   float(s.mean()),
        "rssi_std":    _safe_std(s),
        "rssi_min":    float(s.min()),
        "rssi_max":    float(s.max()),
        "rssi_p25":    float(s.quantile(.25)),
        "rssi_p75":    float(s.quantile(.75)),
        "rssi_range":  float(s.max() - s.min()),
        "pkt_count":   int(len(s)),
    }

def build_table(df, window_s=2):
    """df needs columns: ts, source, mac, rssi, phy [, position, inout].
    Returns (X, meta). X and meta are aligned row-for-row.
    meta ALWAYS has columns: mac, phy, win [+ position, inout if present]."""
    df = df.copy()
    df["mac"] = df["mac"].str.lower()
    t0 = df["ts"].min()
    df["win"] = ((df["ts"] - t0) // window_s).astype(int)

    # Use configured sensors if all present, else discover from data
    sources = sorted(df["source"].unique())
    if all(s in sources for s in SENSORS):
        sources = sorted(SENSORS)

    has_labels = "position" in df.columns

    rows, meta_rows = [], []
    for (mac, phy, win), grp in df.groupby(["mac", "phy", "win"]):
        feat = {}
        per_source_median = {}
        heard_medians = []

        for src in sources:
            sub = grp[grp["source"] == src]
            if len(sub):
                st = _stats(sub)
                for k, v in st.items():
                    feat[f"{k}__{src}"] = v
                per_source_median[src] = st["rssi_median"]
                heard_medians.append(st["rssi_median"])
            else:
                for k in STAT_KEYS:
                    feat[f"{k}__{src}"] = NOT_HEARD
                feat[f"pkt_count__{src}"] = 0
                per_source_median[src] = NOT_HEARD

        # v2: aggregate features across sensors
        feat["n_heard"] = len(heard_medians)
        if heard_medians:
            feat["rssi_vec_max"] = max(heard_medians)
            feat["rssi_spread"] = max(heard_medians) - min(heard_medians)
        else:
            feat["rssi_vec_max"] = NOT_HEARD
            feat["rssi_spread"] = 0

        # TX-power-invariant difference features (C(N,2) pairwise diffs)
        for a, b in itertools.combinations(sources, 2):
            feat[f"delta__{a}__{b}"] = per_source_median[a] - per_source_median[b]

        # Argmax (loudest sensor) one-hot
        if len(sources) >= 2:
            loudest = max(sources, key=lambda s: per_source_median[s])
            for src in sources:
                feat[f"is_loudest__{src}"] = 1 if src == loudest else 0
            feat["_loudest"] = loudest  # temp, for argmax_stability post-pass

        feat["phy_is_wifi"] = 1 if phy == "wifi" else 0

        rows.append(feat)
        m = {"mac": mac, "phy": phy, "win": int(win)}
        if has_labels:
            m["position"] = grp["position"].iloc[0]
            m["inout"] = grp["inout"].iloc[0]
        meta_rows.append(m)

    X = pd.DataFrame(rows).fillna(NOT_HEARD)
    meta = pd.DataFrame(meta_rows)

    # Argmax stability: fraction of recent windows where loudest sensor matches
    if "_loudest" in X.columns and len(X) > 1:
        stab_windows = max(1, math.ceil(ARGMAX_STABILITY_S / window_s))
        stabilities = []
        for idx in range(len(X)):
            mac_val = meta.iloc[idx]["mac"]
            win_val = meta.iloc[idx]["win"]
            current_loudest = X.iloc[idx]["_loudest"]
            # Find recent windows for this mac
            mask = (meta["mac"] == mac_val) & (meta["win"] <= win_val) & (meta["win"] > win_val - stab_windows)
            recent = X.loc[mask.values, "_loudest"]
            if len(recent) <= 1:
                stabilities.append(1.0)
            else:
                stabilities.append(float((recent == current_loudest).mean()))
        X["argmax_stability"] = stabilities
        X = X.drop(columns=["_loudest"])
    elif "_loudest" in X.columns:
        X["argmax_stability"] = 1.0
        X = X.drop(columns=["_loudest"])

    return X, meta
