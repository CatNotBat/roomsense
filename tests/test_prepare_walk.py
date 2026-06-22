"""Tests for src/prepare_walk_data.py — label joining and calibration."""
import sys, os, tempfile, json
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from prepare_walk_data import prepare


def _write_csv(path, rows, header):
    with open(path, "w") as f:
        f.write(",".join(header) + "\n")
        for row in rows:
            f.write(",".join(str(v) for v in row) + "\n")


def test_basic_label_join(tmp_path):
    """Readings within a label window get position/inout assigned."""
    readings_path = str(tmp_path / "readings.csv")
    labels_path = str(tmp_path / "labels.csv")
    output_path = str(tmp_path / "output.csv")

    _write_csv(readings_path,
               [[100.0, "esp_c1", "aa:bb", -60, "btle"],
                [105.0, "esp_c1", "aa:bb", -65, "btle"],
                [110.0, "esp_c1", "aa:bb", -70, "btle"],
                [200.0, "esp_c1", "aa:bb", -80, "btle"]],
               ["ts", "source", "mac", "rssi", "phy"])

    _write_csv(labels_path,
               [[99.0, 115.0, "CENTER", "in"],
                [190.0, 210.0, "OUTSIDE", "out"]],
               ["start_ts", "end_ts", "position", "inout"])

    prepare(readings_path, labels_path, output_path)

    result = pd.read_csv(output_path)
    assert len(result) == 4
    center = result[result["position"] == "CENTER"]
    outside = result[result["position"] == "OUTSIDE"]
    assert len(center) == 3
    assert len(outside) == 1
    assert all(center["inout"] == "in")
    assert all(outside["inout"] == "out")


def test_gap_between_labels(tmp_path):
    """Readings between label windows are excluded."""
    readings_path = str(tmp_path / "readings.csv")
    labels_path = str(tmp_path / "labels.csv")
    output_path = str(tmp_path / "output.csv")

    _write_csv(readings_path,
               [[100.0, "esp_c1", "aa:bb", -60, "btle"],
                [150.0, "esp_c1", "aa:bb", -65, "btle"],  # In gap
                [200.0, "esp_c1", "aa:bb", -70, "btle"]],
               ["ts", "source", "mac", "rssi", "phy"])

    _write_csv(labels_path,
               [[99.0, 110.0, "CENTER", "in"],
                [190.0, 210.0, "OUTSIDE", "out"]],
               ["start_ts", "end_ts", "position", "inout"])

    prepare(readings_path, labels_path, output_path)

    result = pd.read_csv(output_path)
    assert len(result) == 2  # Gap reading excluded


def test_empty_label_window(tmp_path):
    """Label window with no matching readings: prepare() returns early."""
    readings_path = str(tmp_path / "readings.csv")
    labels_path = str(tmp_path / "labels.csv")
    output_path = str(tmp_path / "output.csv")

    _write_csv(readings_path,
               [[100.0, "esp_c1", "aa:bb", -60, "btle"]],
               ["ts", "source", "mac", "rssi", "phy"])

    _write_csv(labels_path,
               [[200.0, 300.0, "OUTSIDE", "out"]],
               ["start_ts", "end_ts", "position", "inout"])

    prepare(readings_path, labels_path, output_path)

    # No readings matched → prepare() returns without creating output
    assert not os.path.exists(output_path)


def test_required_columns_present(tmp_path):
    """Output should have ts, source, mac, rssi, position, inout."""
    readings_path = str(tmp_path / "readings.csv")
    labels_path = str(tmp_path / "labels.csv")
    output_path = str(tmp_path / "output.csv")

    _write_csv(readings_path,
               [[100.0, "esp_c1", "aa:bb", -60, "btle"]],
               ["ts", "source", "mac", "rssi", "phy"])

    _write_csv(labels_path,
               [[99.0, 110.0, "CENTER", "in"]],
               ["start_ts", "end_ts", "position", "inout"])

    prepare(readings_path, labels_path, output_path)

    result = pd.read_csv(output_path)
    for col in ["ts", "source", "mac", "rssi", "position", "inout"]:
        assert col in result.columns
