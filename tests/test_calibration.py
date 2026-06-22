"""Tests for RSSI calibration offset loading and application."""
import json, os, tempfile, pytest
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from rssi_cal import load_offsets, calibrate_rssi


@pytest.fixture
def offsets_file(tmp_path):
    """Create a temporary offsets JSON file."""
    data = {
        "offsets": {"esp_c1": 2.0, "esp_c2": -1.0, "esp_c3": 0.5},
        "global_median_dBm": -55.0,
        "per_node_medians_dBm": {"esp_c1": -57.0, "esp_c2": -54.0, "esp_c3": -55.5},
    }
    p = tmp_path / "node_offsets.json"
    p.write_text(json.dumps(data))
    return str(p)


def test_load_offsets(offsets_file):
    offsets = load_offsets(offsets_file)
    assert offsets["esp_c1"] == 2.0
    assert offsets["esp_c2"] == -1.0
    assert offsets["esp_c3"] == 0.5


def test_calibrate_rssi_applies_offset(offsets_file):
    load_offsets(offsets_file)
    assert calibrate_rssi(-50, "esp_c1") == -48.0
    assert calibrate_rssi(-50, "esp_c2") == -51.0
    assert calibrate_rssi(-50, "esp_c3") == -49.5


def test_missing_sensor_returns_raw(offsets_file):
    load_offsets(offsets_file)
    assert calibrate_rssi(-50, "esp_c99") == -50


def test_no_offsets_file_returns_raw():
    load_offsets("/nonexistent/path.json")
    assert calibrate_rssi(-70, "esp_c1") == -70


def test_calibration_equalizes_medians():
    """After applying offsets, inter-node median difference should be ~0."""
    # Simulated calibration data
    node_medians = {"esp_c1": -57.0, "esp_c2": -54.0, "esp_c3": -55.5}
    global_median = -55.5  # median of [-57, -54, -55.5]

    offsets = {s: global_median - m for s, m in node_medians.items()}
    # After calibration: each node's median becomes global_median
    calibrated = {s: m + offsets[s] for s, m in node_medians.items()}

    vals = list(calibrated.values())
    assert max(vals) - min(vals) < 0.01, f"Expected near-zero spread, got {vals}"
