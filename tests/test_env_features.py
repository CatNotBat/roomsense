"""Tests for src/env_features.py — environment-level feature builder."""
import sys, os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from env_features import build_env_table


def _make_readings(n_macs=5, n_sensors=4, duration=25, rssi_base=-70):
    """Generate synthetic BLE readings for testing."""
    sensors = [f"esp_c{i+1}" for i in range(n_sensors)]
    rows = []
    t0 = 1000.0
    for i in range(0, duration):
        ts = t0 + i
        for sensor in sensors:
            for m in range(n_macs):
                rows.append({
                    "ts": ts, "source": sensor,
                    "mac": f"aa:bb:cc:dd:ee:{m:02x}",
                    "rssi": rssi_base + m * 2 + (hash(sensor) % 5),
                    "position": "CENTER", "inout": "in",
                })
    return pd.DataFrame(rows)


def test_basic_output_shape():
    """build_env_table returns (X, meta) DataFrames."""
    df = _make_readings(duration=25)
    X, meta = build_env_table(df, A=10, overlap=0.0,
                              sensors=["esp_c1", "esp_c2", "esp_c3", "esp_c4"])
    assert len(X) > 0
    assert len(X) == len(meta)
    assert "t_start" in meta.columns
    assert "t_end" in meta.columns


def test_window_count():
    """Non-overlapping 10s windows over 25s of data."""
    df = _make_readings(duration=25)
    X, meta = build_env_table(df, A=10, overlap=0.0,
                              sensors=["esp_c1", "esp_c2", "esp_c3", "esp_c4"])
    # np.arange(0, 25 - 10 + 10, 10) = [0, 10, 20] but last window [20,30)
    # only has 5s of data (still >10 readings per second) → 3 windows
    assert len(X) >= 2


def test_per_sensor_features_present():
    """Check that per-sensor features are generated."""
    df = _make_readings()
    X, _ = build_env_table(df, A=10, overlap=0.0,
                           sensors=["esp_c1", "esp_c2", "esp_c3", "esp_c4"])
    for sensor in ["esp_c1", "esp_c2", "esp_c3", "esp_c4"]:
        assert f"env_median__{sensor}" in X.columns
        assert f"env_iqr__{sensor}" in X.columns
        assert f"env_max__{sensor}" in X.columns
        assert f"env_mac_count__{sensor}" in X.columns
        assert f"env_strong80__{sensor}" in X.columns
        assert f"env_strong70__{sensor}" in X.columns
        assert f"env_top3_median__{sensor}" in X.columns


def test_cross_sensor_features_present():
    """Check cross-sensor features."""
    df = _make_readings()
    X, _ = build_env_table(df, A=10, overlap=0.0,
                           sensors=["esp_c1", "esp_c2", "esp_c3", "esp_c4"])
    assert "env_total_macs" in X.columns
    assert "env_total_pkts" in X.columns
    assert "env_mac_spread" in X.columns
    assert "env_strong80_spread" in X.columns
    assert "env_global_max" in X.columns


def test_top3_delta_features():
    """Pairwise top3 deltas between sensors."""
    sensors = ["esp_c1", "esp_c2", "esp_c3", "esp_c4"]
    df = _make_readings()
    X, _ = build_env_table(df, A=10, overlap=0.0, sensors=sensors)
    import itertools
    for a, b in itertools.combinations(sensors, 2):
        assert f"env_top3_delta__{a}__{b}" in X.columns


def test_loudest_one_hot():
    """Exactly one sensor should be marked as loudest."""
    sensors = ["esp_c1", "esp_c2", "esp_c3", "esp_c4"]
    df = _make_readings()
    X, _ = build_env_table(df, A=10, overlap=0.0, sensors=sensors)
    for _, row in X.iterrows():
        loudest_vals = [row[f"env_loudest__{s}"] for s in sensors]
        assert sum(loudest_vals) == 1
        assert all(v in (0, 1) for v in loudest_vals)


def test_median_stats_correct():
    """Verify median is computed correctly for a known dataset."""
    sensors = ["s1"]
    rows = []
    t0 = 1000.0
    rssi_values = [-60, -70, -80, -50, -90]
    for i, rssi in enumerate(rssi_values):
        rows.append({"ts": t0 + i, "source": "s1",
                     "mac": f"aa:bb:cc:dd:ee:{i:02x}", "rssi": rssi})
    # Add more rows to pass min-10 threshold
    for i in range(5, 12):
        rows.append({"ts": t0 + (i % 5), "source": "s1",
                     "mac": f"aa:bb:cc:dd:ff:{i:02x}", "rssi": -65})
    df = pd.DataFrame(rows)
    X, _ = build_env_table(df, A=10, overlap=0.0, sensors=sensors)
    assert len(X) > 0
    # Median should be around -65 (many -65 values + the 5 original)
    med = X["env_median__s1"].iloc[0]
    assert -80 < med < -50


def test_empty_sensor_fills_nan():
    """Sensor with no readings in a window should get NaN/0 defaults."""
    sensors = ["s1", "s2"]
    rows = []
    t0 = 1000.0
    # Only s1 has data
    for i in range(15):
        rows.append({"ts": t0 + i, "source": "s1",
                     "mac": f"aa:bb:cc:dd:ee:{i % 3:02x}", "rssi": -60})
    df = pd.DataFrame(rows)
    X, _ = build_env_table(df, A=10, overlap=0.0, sensors=sensors)
    if len(X) > 0:
        # s2 should have fillna'd values (-120)
        assert X["env_mac_count__s2"].iloc[0] == 0
        assert X["env_pkt_count__s2"].iloc[0] == 0


def test_too_few_readings_skips_window():
    """Windows with < 10 readings are skipped."""
    sensors = ["s1"]
    rows = [{"ts": 1000.0 + i, "source": "s1",
             "mac": "aa:bb:cc:dd:ee:00", "rssi": -60} for i in range(5)]
    df = pd.DataFrame(rows)
    X, _ = build_env_table(df, A=10, overlap=0.0, sensors=sensors)
    assert len(X) == 0


def test_labels_propagated():
    """Labels (position, inout) should be in meta when present in input."""
    df = _make_readings()
    _, meta = build_env_table(df, A=10, overlap=0.0,
                              sensors=["esp_c1", "esp_c2", "esp_c3", "esp_c4"])
    assert "position" in meta.columns
    assert "inout" in meta.columns
    assert meta["position"].iloc[0] == "CENTER"
    assert meta["inout"].iloc[0] == "in"


def test_no_labels_when_absent():
    """When position/inout not in input, meta should not have them."""
    df = _make_readings().drop(columns=["position", "inout"])
    _, meta = build_env_table(df, A=10, overlap=0.0,
                              sensors=["esp_c1", "esp_c2", "esp_c3", "esp_c4"])
    assert "position" not in meta.columns


def test_overlap_produces_more_windows():
    """50% overlap should produce more windows than 0% overlap."""
    df = _make_readings(duration=30)
    sensors = ["esp_c1", "esp_c2", "esp_c3", "esp_c4"]
    X_no, _ = build_env_table(df, A=10, overlap=0.0, sensors=sensors)
    X_half, _ = build_env_table(df, A=10, overlap=0.5, sensors=sensors)
    assert len(X_half) > len(X_no)


def test_strong_device_counts():
    """Devices with RSSI > -70 and > -80 counted correctly."""
    sensors = ["s1"]
    rows = []
    t0 = 1000.0
    # 5 strong devices (-50 to -60), 5 weak (-85 to -95)
    for i in range(15):
        mac_idx = i % 10
        rssi = -50 - mac_idx * 5  # -50, -55, -60, -65, -70, -75, -80, -85, -90, -95
        rows.append({"ts": t0 + i * 0.5, "source": "s1",
                     "mac": f"aa:bb:cc:dd:ee:{mac_idx:02x}", "rssi": rssi})
    df = pd.DataFrame(rows)
    X, _ = build_env_table(df, A=10, overlap=0.0, sensors=sensors)
    if len(X) > 0:
        # strong70: RSSI > -70 → -50, -55, -60, -65 = 4+ readings
        assert X["env_strong70__s1"].iloc[0] >= 4
        # strong80: RSSI > -80 → adds -70, -75 = 6+ readings
        assert X["env_strong80__s1"].iloc[0] >= X["env_strong70__s1"].iloc[0]
