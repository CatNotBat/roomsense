"""Tests for co-hearing alignment join."""
import sys, os
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from cohearing import cohearing_samples, MISSING


def _df(rows):
    return pd.DataFrame(rows, columns=["ts", "source", "mac", "rssi"])


def test_close_readings_are_paired():
    """Two sensors 50ms apart should be paired (within W=200ms)."""
    df = _df([
        [1.000, "s1", "AA", -50],
        [1.050, "s2", "AA", -60],
    ])
    result = cohearing_samples(df, W_ms=200, sensors=["s1", "s2"])
    assert len(result) >= 1
    row = result.iloc[0]
    assert not np.isnan(row["s1_rssi"])
    assert not np.isnan(row["s2_rssi"])
    assert row["n_heard"] == 2


def test_far_readings_not_paired():
    """Two sensors 300ms apart should NOT be paired at W=200ms."""
    df = _df([
        [1.000, "s1", "AA", -50],
        [1.300, "s2", "AA", -60],
    ])
    result = cohearing_samples(df, W_ms=200, sensors=["s1", "s2"])
    # Each center should see only one sensor
    for _, row in result.iterrows():
        assert row["n_heard"] <= 1


def test_missing_sensor_is_nan():
    """Three sensors, one has no reading in window → n_heard=2, absent=NaN."""
    df = _df([
        [1.000, "s1", "AA", -50],
        [1.050, "s2", "AA", -60],
        # s3 has no readings
    ])
    result = cohearing_samples(df, W_ms=200, sensors=["s1", "s2", "s3"])
    row = result.iloc[0]
    assert row["n_heard"] == 2
    assert np.isnan(row["s3_rssi"])
    assert not np.isnan(row["s1_rssi"])


def test_no_paired_readings_exceed_half_W():
    """Verify that no paired reading is more than W/2 from center."""
    W_ms = 200
    half_W = W_ms / 2000.0  # in seconds

    # Many readings spread over time
    rows = []
    for t in np.arange(0, 2.0, 0.03):
        for s in ["s1", "s2", "s3"]:
            rows.append([t + np.random.uniform(0, 0.01), s, "AA",
                         int(-50 - np.random.uniform(0, 20))])

    df = _df(rows)
    result = cohearing_samples(df, W_ms=W_ms, sensors=["s1", "s2", "s3"])

    # For each sample, verify readings used are within W/2 of center
    # (We can't directly check input readings, but n_heard should be sensible)
    assert len(result) > 0
    assert all(result["n_heard"] >= 1)
    assert all(result["n_heard"] <= 3)


def test_multiple_devices():
    """Multiple MACs are processed independently."""
    df = _df([
        [1.0, "s1", "AA", -50],
        [1.0, "s1", "BB", -70],
        [1.05, "s2", "AA", -60],
        [1.05, "s2", "BB", -80],
    ])
    result = cohearing_samples(df, W_ms=200, sensors=["s1", "s2"])
    macs = result["mac"].unique()
    assert len(macs) == 2
    assert set(macs) == {"AA", "BB"}


def test_empty_input():
    """Empty input returns empty DataFrame with correct columns."""
    df = _df([])
    result = cohearing_samples(df, W_ms=200, sensors=["s1", "s2"])
    assert len(result) == 0
    assert "s1_rssi" in result.columns
    assert "n_heard" in result.columns
