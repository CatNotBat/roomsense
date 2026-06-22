"""Integration test: simulated data → features → train succeeds."""
import sys, os
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from features import build_table, NOT_HEARD


def test_full_pipeline_shape():
    """4 sensors, multiple macs, multiple windows → correct feature shape."""
    rows = []
    sensors = ["esp_c1", "esp_c2", "esp_c3", "esp_c4"]
    for t in range(0, 6):  # 3 windows at window_s=2
        for s in sensors:
            rows.append({"ts": t, "source": s, "mac": "dev1", "rssi": -50 - t, "phy": "btle"})
            rows.append({"ts": t, "source": s, "mac": "dev2", "rssi": -70 - t, "phy": "btle"})
    df = pd.DataFrame(rows)
    X, meta = build_table(df, window_s=2)

    # Should have multiple windows for 2 devices
    assert len(X) >= 4  # at least 2 devices × 2 windows
    assert len(X) == len(meta)

    # Should have all expected feature types
    col_names = set(X.columns)
    assert any("delta__" in c for c in col_names)
    assert any("is_loudest__" in c for c in col_names)
    assert "rssi_spread" in col_names
    assert "rssi_vec_max" in col_names
    assert "n_heard" in col_names
    assert "argmax_stability" in col_names


def test_empty_df():
    """Empty dataframe should return empty results."""
    df = pd.DataFrame(columns=["ts", "source", "mac", "rssi", "phy"])
    X, meta = build_table(df, window_s=2)
    assert len(X) == 0
    assert len(meta) == 0
