"""Tests for temporal aggregation windows."""
import sys, os
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from aggregation import build_aggregated_table


def _df(rows):
    return pd.DataFrame(rows, columns=["ts", "source", "mac", "rssi"])


def test_window_count():
    """40s of data, A=20s, overlap=0.5 → step=10s → 3 windows."""
    rows = []
    for t in np.arange(0, 40, 0.5):
        rows.append([t, "s1", "AA", -50])
        rows.append([t, "s2", "AA", -60])
    df = _df(rows)
    X, meta = build_aggregated_table(df, A=20, overlap=0.5,
                                      sensors=["s1", "s2"])
    # Windows: [0,20), [10,30), [20,40) = 3
    assert len(X) == 3
    assert len(meta) == 3


def test_distributional_stats():
    """Known input → exact expected stats."""
    # 10 readings at exactly -50 dBm from one sensor
    rows = [[i * 0.5, "s1", "AA", -50] for i in range(40)]
    df = _df(rows)
    X, meta = build_aggregated_table(df, A=20, overlap=0.5,
                                      sensors=["s1"])
    row = X.iloc[0]
    assert row["rssi_median__s1"] == -50
    assert row["rssi_iqr__s1"] == 0
    assert row["rssi_mad__s1"] == 0
    assert row["pkt_count__s1"] == 40  # 20s / 0.5s spacing = 40 pkts


def test_frac_heard():
    """Readings only in first half → frac_heard ≈ 0.5."""
    rows = [[i * 0.5, "s1", "AA", -50] for i in range(20)]  # 0-10s
    df = _df(rows)
    X, meta = build_aggregated_table(df, A=20, overlap=0.0,
                                      sensors=["s1"])
    row = X.iloc[0]
    assert row["frac_heard__s1"] == pytest.approx(0.5, abs=0.1)


def test_n_heard():
    """Two sensors → n_heard=2."""
    rows = [[0, "s1", "AA", -50], [0, "s2", "AA", -60]]
    rows += [[10, "s1", "AA", -50], [10, "s2", "AA", -60]]
    df = _df(rows)
    X, _ = build_aggregated_table(df, A=20, overlap=0.0,
                                   sensors=["s1", "s2"])
    assert X.iloc[0]["n_heard"] == 2


def test_transfer_features_present():
    """Verify transfer features are computed."""
    rows = []
    for t in range(0, 20):
        rows.append([t, "s1", "AA", -50])
        rows.append([t, "s2", "AA", -60])
        rows.append([t, "s3", "AA", -70])
    df = _df(rows)
    X, _ = build_aggregated_table(df, A=20, overlap=0.0,
                                   sensors=["s1", "s2", "s3"])
    assert "anisotropy" in X.columns
    assert "argmax_coverage" in X.columns
    assert "ref_delta" in X.columns
    assert "rssi_normed__s1" in X.columns
    assert X.iloc[0]["anisotropy"] > 0  # sensors differ by 10 dB each


def test_configurable_A_and_overlap():
    """Different A and overlap produce different window counts."""
    rows = [[t, "s1", "AA", -50] for t in np.arange(0, 60, 1)]
    df = _df(rows)

    X10, _ = build_aggregated_table(df, A=10, overlap=0.5, sensors=["s1"])
    X30, _ = build_aggregated_table(df, A=30, overlap=0.5, sensors=["s1"])

    assert len(X10) > len(X30)


def test_empty_input():
    df = _df([])
    X, meta = build_aggregated_table(df, A=20, overlap=0.5, sensors=["s1"])
    assert len(X) == 0


def test_pairwise_deltas():
    """Pairwise deltas are TX-power-invariant."""
    rows = []
    for t in range(0, 20):
        rows.append([t, "s1", "AA", -50])
        rows.append([t, "s2", "AA", -60])
    df = _df(rows)
    X, _ = build_aggregated_table(df, A=20, overlap=0.0,
                                   sensors=["s1", "s2"])
    assert "delta__s1__s2" in X.columns
    assert X.iloc[0]["delta__s1__s2"] == pytest.approx(10.0)  # -50 - (-60)
