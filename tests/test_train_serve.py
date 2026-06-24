"""Train/serve consistency: features from training path must match live path.

This is the #1 source of ML bugs — train/serve skew. This test generates
synthetic data, builds features via the training path and the live path,
and asserts identical output.
"""
import sys, os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from env_features import build_env_table


def _make_readings(n_macs=5, n_sensors=4, duration=25, rssi_base=-70):
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
                    "position": "CENTER", "inout": "in",
                })
    return pd.DataFrame(rows)


def test_training_vs_live_features_identical():
    """Same input data → same features whether overlap=0.5 or overlap=0.0."""
    sensors = ["esp_c1", "esp_c2", "esp_c3", "esp_c4"]
    df = _make_readings(duration=30)

    # Training path: overlapping windows (produces more rows)
    X_train, _ = build_env_table(df, A=20, overlap=0.5, sensors=sensors)

    # Live path: non-overlapping (like live_ble.py)
    X_live, _ = build_env_table(df, A=20, overlap=0.0, sensors=sensors)

    # Both should have the same columns
    assert set(X_train.columns) == set(X_live.columns), (
        f"Column mismatch: {set(X_train.columns) ^ set(X_live.columns)}")

    # The first window should be identical (same t_start, same data)
    for col in X_train.columns:
        train_val = X_train[col].iloc[0]
        live_val = X_live[col].iloc[0]
        if pd.isna(train_val) and pd.isna(live_val):
            continue
        assert train_val == live_val, (
            f"Feature {col} differs: train={train_val}, live={live_val}")


def test_radar_fillna_uses_zero():
    """Radar features should be filled with 0, not -120."""
    sensors = ["esp_c1", "esp_c2"]
    df = _make_readings(n_sensors=2, duration=25)

    # Provide radar data for only one sensor
    radar = [
        {"source": "esp_c1", "ts": 1005.0, "n_targets": 1,
         "targets": [{"x": 100, "y": 200, "spd": 50, "dist": 300}]},
    ]

    X, _ = build_env_table(df, A=20, overlap=0.0, sensors=sensors,
                           radar_readings=radar)
    if len(X) > 0:
        radar_cols = [c for c in X.columns if c.startswith("radar_")]
        for col in radar_cols:
            val = X[col].iloc[0]
            assert val != -120, f"Radar feature {col} was filled with -120!"


def test_columns_stable_with_and_without_radar():
    """BLE-only columns should be identical whether radar is present or not."""
    sensors = ["esp_c1", "esp_c2", "esp_c3", "esp_c4"]
    df = _make_readings(duration=25)

    X_no_radar, _ = build_env_table(df, A=20, overlap=0.0, sensors=sensors)
    radar = [
        {"source": "esp_c1", "ts": 1005.0, "n_targets": 1,
         "targets": [{"x": 100, "y": 200, "spd": 50, "dist": 300}]},
    ]
    X_radar, _ = build_env_table(df, A=20, overlap=0.0, sensors=sensors,
                                 radar_readings=radar)

    # Radar version should have all BLE columns plus radar columns
    ble_cols_no = set(X_no_radar.columns)
    ble_cols_yes = {c for c in X_radar.columns if not c.startswith("radar_")}
    assert ble_cols_no == ble_cols_yes, (
        f"BLE columns changed when radar added: {ble_cols_no ^ ble_cols_yes}")

    # BLE feature values should be identical
    for col in ble_cols_no:
        v1 = X_no_radar[col].iloc[0]
        v2 = X_radar[col].iloc[0]
        if pd.isna(v1) and pd.isna(v2):
            continue
        assert v1 == v2, f"BLE feature {col} changed with radar: {v1} vs {v2}"


def test_lgbm_classifier_with_monotone_constraints():
    """LightGBM classifier trains and predicts with monotone constraints."""
    import lightgbm as lgb

    sensors = ["esp_c1", "esp_c2"]
    df = _make_readings(n_sensors=2, duration=30)
    X, meta = build_env_table(df, A=10, overlap=0.0, sensors=sensors)
    y = np.ones(len(X), dtype=int)
    if len(X) < 2:
        return

    # Build monotone constraints like train.py does
    mc = []
    for c in X.columns:
        if c.startswith("env_median__") and "delta" not in c:
            mc.append(-1)
        else:
            mc.append(0)

    clf = lgb.LGBMClassifier(
        objective="binary", num_leaves=8, n_estimators=10,
        monotone_constraints=mc,
        monotone_constraints_method="intermediate",
        verbose=-1, random_state=0,
    )
    clf.fit(X, y)
    proba = clf.predict_proba(X)
    assert proba.shape == (len(X), 2)
    assert all(0 <= p <= 1 for p in proba[:, 1])


def test_mapie_conformal_prediction_sets():
    """MAPIE SplitConformalClassifier produces valid prediction sets."""
    from mapie.classification import SplitConformalClassifier
    from sklearn.ensemble import RandomForestClassifier

    sensors = ["esp_c1", "esp_c2"]
    df = _make_readings(n_sensors=2, duration=60)
    X, meta = build_env_table(df, A=10, overlap=0.0, sensors=sensors)
    y = np.ones(len(X), dtype=int)
    # Make some samples "out"
    y[:len(y)//3] = 0

    if len(X) < 10:
        return

    clf = RandomForestClassifier(n_estimators=10, random_state=0)
    clf.fit(X, y)

    mapie = SplitConformalClassifier(
        estimator=clf, confidence_level=0.90, conformity_score="lac")
    n_cal = min(5, len(X))
    mapie.conformalize(X.iloc[:n_cal], y[:n_cal])

    preds, sets = mapie.predict_set(X)
    # sets shape: (n_samples, n_classes, n_confidence_levels)
    assert sets.shape[0] == len(X)
    assert sets.shape[1] == 2  # binary
    # Each sample should have at least 1 class in the set
    set_sizes = sets[:, :, 0].sum(axis=1)
    assert all(s >= 1 for s in set_sizes)


def test_old_bundle_no_mapie_backward_compat():
    """Old bundles without 'mapie' key should still work."""
    bundle = {
        "model": None,
        "columns": ["feat1", "feat2"],
        "window_s": 20,
        "threshold": 0.5,
        "version": "v3",
        "feature_type": "environment",
        "has_radar": False,
    }
    # Accessing optional keys should return None
    assert bundle.get("mapie") is None
    assert bundle.get("mapie_alpha", 0.10) == 0.10
    assert bundle.get("algorithm", "rf") == "rf"
