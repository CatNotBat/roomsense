import sys, os, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from features import build_table, NOT_HEARD

def _df(rows):
    return pd.DataFrame(rows, columns=["ts", "source", "mac", "rssi", "phy"])

def test_four_sensor_vector_and_deltas():
    df = _df([[0, "esp_c1", "AA", -50, "btle"], [0, "esp_c2", "AA", -60, "btle"],
              [0, "esp_c3", "AA", -70, "btle"], [0, "esp_c4", "AA", -80, "btle"]])
    X, meta = build_table(df, window_s=2)
    assert len(X) == len(meta) == 1
    assert sum(c.startswith("delta__") for c in X.columns) >= 6   # C(4,2)
    assert any(c.startswith("rssi_median__esp_c") for c in X.columns)
    assert "rssi_spread" in X.columns
    assert "rssi_vec_max" in X.columns
    assert "n_heard" in X.columns
    assert X.iloc[0]["n_heard"] == 4
    assert X.iloc[0]["rssi_vec_max"] == -50
    assert X.iloc[0]["rssi_spread"] == 30  # -50 - (-80)

def test_unheard_sensor_is_not_heard():
    df = _df([[0, "esp_c1", "AA", -50, "btle"], [0, "esp_c2", "BB", -60, "btle"]])
    X, meta = build_table(df, window_s=2)
    i = meta.index[meta["mac"] == "aa"][0]
    assert X.loc[i].get("rssi_median__esp_c2", NOT_HEARD) == NOT_HEARD

def test_argmax_stability_present():
    df = _df([[0, "esp_c1", "AA", -50, "btle"], [0, "esp_c2", "AA", -60, "btle"],
              [0, "esp_c3", "AA", -70, "btle"], [0, "esp_c4", "AA", -80, "btle"],
              [3, "esp_c1", "AA", -50, "btle"], [3, "esp_c2", "AA", -60, "btle"],
              [3, "esp_c3", "AA", -70, "btle"], [3, "esp_c4", "AA", -80, "btle"]])
    X, meta = build_table(df, window_s=2)
    assert "argmax_stability" in X.columns
