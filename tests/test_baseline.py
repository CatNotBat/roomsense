"""Tests for src/baseline.py — empty-room baseline learning."""
import sys, os, json, tempfile
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from baseline import BaselineCapture, baseline_deviation_features


def _make_readings(n_macs=5, n_sensors=2, duration=60, rssi_base=-70):
    sensors = [f"esp_c{i+1}" for i in range(n_sensors)]
    rows = []
    t0 = 1000.0
    for i in range(duration):
        for sensor in sensors:
            for m in range(n_macs):
                rows.append({
                    "ts": t0 + i, "source": sensor,
                    "mac": f"aa:bb:cc:dd:ee:{m:02x}",
                    "rssi": rssi_base + m * 2 + (hash(sensor) % 5),
                })
    return pd.DataFrame(rows)


def test_capture_produces_stats():
    """Capture should produce stats for env features."""
    bc = BaselineCapture()
    df = _make_readings(duration=60)
    bc.capture(df, A=10, sensors=["esp_c1", "esp_c2"])

    assert len(bc.stats) > 0
    for feat, s in bc.stats.items():
        assert "median" in s
        assert "mad" in s
        assert "p5" in s
        assert "p95" in s


def test_save_load_roundtrip():
    """Save and load should preserve stats exactly."""
    bc = BaselineCapture()
    df = _make_readings(duration=60)
    bc.capture(df, A=10, sensors=["esp_c1", "esp_c2"])

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        bc.save(path)
        loaded = BaselineCapture.load(path)
        assert loaded is not None
        assert set(loaded.stats.keys()) == set(bc.stats.keys())
        for feat in bc.stats:
            assert loaded.stats[feat]["median"] == bc.stats[feat]["median"]
            assert loaded.stats[feat]["mad"] == bc.stats[feat]["mad"]
    finally:
        os.unlink(path)


def test_load_missing_file():
    """Loading from non-existent path should return None."""
    result = BaselineCapture.load("/tmp/nonexistent_baseline_xyz.json")
    assert result is None


def test_z_score_values():
    """Z-scores should be 0 when value equals baseline median."""
    stats = {
        "env_median__esp_c1": {"median": -70.0, "mad": 5.0, "p5": -80.0, "p95": -60.0},
    }
    row = {"env_median__esp_c1": -70.0}
    result = baseline_deviation_features(row, stats)
    assert "bdev_env_median__esp_c1" in result
    assert abs(result["bdev_env_median__esp_c1"]) < 0.01


def test_z_score_positive_deviation():
    """Value above baseline should give positive z-score."""
    stats = {
        "env_median__esp_c1": {"median": -70.0, "mad": 5.0, "p5": -80.0, "p95": -60.0},
    }
    row = {"env_median__esp_c1": -50.0}  # stronger than baseline
    result = baseline_deviation_features(row, stats)
    assert result["bdev_env_median__esp_c1"] > 0


def test_z_score_zero_mad_fallback():
    """When MAD=0, should fallback to IQR-based scale."""
    stats = {
        "env_pkt_count__esp_c1": {"median": 100.0, "mad": 0.0, "p5": 80.0, "p95": 120.0},
    }
    row = {"env_pkt_count__esp_c1": 110.0}
    result = baseline_deviation_features(row, stats)
    assert "bdev_env_pkt_count__esp_c1" in result
    # Should not be NaN or inf
    z = result["bdev_env_pkt_count__esp_c1"]
    assert np.isfinite(z)
    assert z > 0  # above median


def test_z_score_nan_value():
    """NaN input value should produce z-score of 0."""
    stats = {
        "env_median__esp_c1": {"median": -70.0, "mad": 5.0, "p5": -80.0, "p95": -60.0},
    }
    row = {"env_median__esp_c1": float("nan")}
    result = baseline_deviation_features(row, stats)
    assert result["bdev_env_median__esp_c1"] == 0.0


def test_baseline_features_in_env_table():
    """build_env_table with baseline_stats should add bdev_ columns."""
    from env_features import build_env_table

    sensors = ["esp_c1", "esp_c2"]
    df = _make_readings(duration=30)

    # First capture baseline
    bc = BaselineCapture()
    bc.capture(df, A=10, sensors=sensors)

    # Then build features with baseline
    X, _ = build_env_table(df, A=10, overlap=0.0, sensors=sensors,
                           baseline_stats=bc.stats)
    assert len(X) > 0
    bdev_cols = [c for c in X.columns if c.startswith("bdev_")]
    assert len(bdev_cols) > 0
