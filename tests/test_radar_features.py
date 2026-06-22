"""Tests for src/radar_features.py — mmWave radar feature extraction."""
import math
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from radar_features import build_radar_features


SENSORS = ["esp_c1", "esp_c2", "esp_c3", "esp_c4"]


def _frame(source, ts, targets):
    """Helper: build a radar frame dict."""
    return {
        "source": source,
        "ts": ts,
        "n_targets": len(targets),
        "targets": [{"x": t[0], "y": t[1], "spd": t[2], "dist": t[3]}
                     for t in targets],
    }


class TestEmptyWindow:
    def test_no_rows(self):
        feat = build_radar_features([], 0.0, 20.0, SENSORS)
        assert feat["radar_total_max_targets"] == 0
        assert feat["radar_n_sensors_occupied"] == 0
        assert feat["radar_consensus_occupied"] == 0.0
        for s in SENSORS:
            assert feat[f"radar_frac_occupied__{s}"] == 0.0
            assert feat[f"radar_max_targets__{s}"] == 0

    def test_rows_outside_window(self):
        rows = [_frame("esp_c1", 50.0, [(100, 200, 10, 224)])]
        feat = build_radar_features(rows, 0.0, 20.0, SENSORS)
        assert feat["radar_total_max_targets"] == 0


class TestSingleTarget:
    def test_one_sensor_one_target(self):
        rows = [_frame("esp_c1", 5.0, [(1000, 2000, 50, 2236)])]
        feat = build_radar_features(rows, 0.0, 20.0, SENSORS)
        assert feat["radar_max_targets__esp_c1"] == 1
        assert feat["radar_mean_targets__esp_c1"] == 1.0
        assert feat["radar_frac_occupied__esp_c1"] == 1.0
        assert feat["radar_mean_dist__esp_c1"] == 2236.0
        assert feat["radar_min_dist__esp_c1"] == 2236.0
        assert feat["radar_mean_speed__esp_c1"] == 50.0
        # Other sensors empty
        assert feat["radar_frac_occupied__esp_c2"] == 0.0
        assert feat["radar_n_sensors_occupied"] == 1  # esp_c1 at 100% > 0.5 threshold
        assert feat["radar_total_max_targets"] == 1


class TestMultipleTargets:
    def test_three_targets(self):
        targets = [
            (500, 1000, 30, 1118),
            (-800, 1500, -60, 1700),
            (200, 3000, 10, 3007),
        ]
        rows = [_frame("esp_c1", 5.0, targets)]
        feat = build_radar_features(rows, 0.0, 20.0, SENSORS)
        assert feat["radar_max_targets__esp_c1"] == 3
        assert feat["radar_mean_dist__esp_c1"] > 0
        assert feat["radar_x_spread__esp_c1"] == 1300.0  # 500 - (-800)

    def test_multiple_frames(self):
        rows = [
            _frame("esp_c1", 1.0, [(100, 200, 10, 224)]),
            _frame("esp_c1", 2.0, [(100, 200, 10, 224), (300, 400, 20, 500)]),
            _frame("esp_c1", 3.0, []),  # empty frame
        ]
        feat = build_radar_features(rows, 0.0, 20.0, SENSORS)
        assert feat["radar_max_targets__esp_c1"] == 2
        assert abs(feat["radar_mean_targets__esp_c1"] - 1.0) < 0.01  # (1+2+0)/3
        assert abs(feat["radar_frac_occupied__esp_c1"] - 2.0/3) < 0.01


class TestMultiSensor:
    def test_two_sensors_occupied(self):
        rows = [
            # esp_c1: occupied in all frames
            _frame("esp_c1", 1.0, [(100, 200, 10, 224)]),
            _frame("esp_c1", 2.0, [(100, 200, 10, 224)]),
            # esp_c3: occupied in all frames
            _frame("esp_c3", 1.0, [(-500, 3000, 0, 3041)]),
            _frame("esp_c3", 2.0, [(-500, 3000, 0, 3041)]),
        ]
        feat = build_radar_features(rows, 0.0, 20.0, SENSORS)
        assert feat["radar_n_sensors_occupied"] == 2
        assert feat["radar_consensus_occupied"] == 0.5
        assert feat["radar_dist_spread"] > 0  # different distances

    def test_all_sensors_occupied(self):
        rows = []
        for s in SENSORS:
            rows.append(_frame(s, 5.0, [(100, 200, 10, 224)]))
        feat = build_radar_features(rows, 0.0, 20.0, SENSORS)
        assert feat["radar_n_sensors_occupied"] == 4
        assert feat["radar_consensus_occupied"] == 1.0


class TestMissingSensor:
    def test_missing_sensor_gets_nan_dist(self):
        rows = [_frame("esp_c1", 5.0, [(100, 200, 10, 224)])]
        feat = build_radar_features(rows, 0.0, 20.0, SENSORS)
        assert math.isnan(feat["radar_mean_dist__esp_c2"])
        assert math.isnan(feat["radar_min_dist__esp_c2"])


class TestDistSpread:
    def test_dist_spread_needs_two_sensors(self):
        rows = [_frame("esp_c1", 5.0, [(100, 200, 10, 224)])]
        feat = build_radar_features(rows, 0.0, 20.0, SENSORS)
        assert feat["radar_dist_spread"] == 0.0  # only 1 valid

    def test_dist_spread_two_sensors(self):
        rows = [
            _frame("esp_c1", 5.0, [(100, 200, 10, 1000)]),
            _frame("esp_c2", 5.0, [(100, 200, 10, 3000)]),
        ]
        feat = build_radar_features(rows, 0.0, 20.0, SENSORS)
        assert feat["radar_dist_spread"] == 2000.0


class TestFeatureCount:
    def test_expected_feature_count(self):
        rows = [_frame("esp_c1", 5.0, [(100, 200, 10, 224)])]
        feat = build_radar_features(rows, 0.0, 20.0, SENSORS)
        # 9 per-sensor features * 4 sensors + 4 cross-sensor = 40
        assert len(feat) == 40
