"""Tests for worn-device labeling tool."""
import sys, os, csv
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from label_worn import join_labels


@pytest.fixture
def data_dir(tmp_path):
    """Create synthetic readings and labels for testing."""
    # Readings: 3 MACs, 2 sensors
    readings = tmp_path / "readings.csv"
    rows = [
        ["ts", "source", "mac", "rssi", "phy", "name", "addr_type",
         "appearance", "mfg_hex", "svc_hex"],
    ]
    for t in range(100, 200):
        for mac in ["aa:bb:cc:11:22:33", "dd:ee:ff:44:55:66", "99:88:77:66:55:44"]:
            for src in ["esp_c1", "esp_c2"]:
                rows.append([str(t), src, mac, "-50", "btle", "",
                            "1", "-1", "", ""])
    with open(readings, "w", newline="") as f:
        csv.writer(f).writerows(rows)

    # Labels: only 2 of 3 MACs are carried
    labels = tmp_path / "labels.csv"
    label_rows = [
        ["start_ts", "end_ts", "position", "inout", "orientation",
         "carried_macs", "notes"],
        ["100.000", "150.000", "IN_CENTER", "in", "facing_door",
         "aa:bb:cc:11:22:33;dd:ee:ff:44:55:66", ""],
        ["150.000", "200.000", "OUT_HALLWAY", "out", "",
         "aa:bb:cc:11:22:33;dd:ee:ff:44:55:66", ""],
    ]
    with open(labels, "w", newline="") as f:
        csv.writer(f).writerows(label_rows)

    return tmp_path, str(readings), str(labels)


def test_join_filters_to_carried_macs(data_dir):
    """Only carried MACs should appear in output — neighbor excluded."""
    tmp_path, readings_path, labels_path = data_dir
    output = str(tmp_path / "output.csv")

    result = join_labels(readings_path, labels_path, output)

    # The third MAC (99:88:77:66:55:44) should NOT appear
    macs = set(result["mac"].str.lower().unique())
    assert "aa:bb:cc:11:22:33" in macs
    assert "dd:ee:ff:44:55:66" in macs
    assert "99:88:77:66:55:44" not in macs


def test_join_assigns_correct_labels(data_dir):
    """Readings in different time windows get correct position/inout labels."""
    tmp_path, readings_path, labels_path = data_dir
    output = str(tmp_path / "output.csv")

    result = join_labels(readings_path, labels_path, output)

    in_rows = result[result["inout"] == "in"]
    out_rows = result[result["inout"] == "out"]

    # All "in" rows should have ts in [100, 150]
    assert all(in_rows["ts"] >= 100)
    assert all(in_rows["ts"] <= 150)

    # All "out" rows should have ts in [150, 200]
    assert all(out_rows["ts"] >= 150)
    assert all(out_rows["ts"] <= 200)


def test_join_both_positions_present(data_dir):
    tmp_path, readings_path, labels_path = data_dir
    output = str(tmp_path / "output.csv")

    result = join_labels(readings_path, labels_path, output)
    positions = set(result["position"].unique())
    assert positions == {"IN_CENTER", "OUT_HALLWAY"}


def test_output_file_written(data_dir):
    tmp_path, readings_path, labels_path = data_dir
    output = str(tmp_path / "output.csv")

    join_labels(readings_path, labels_path, output)
    assert os.path.exists(output)
    written = pd.read_csv(output)
    assert len(written) > 0
