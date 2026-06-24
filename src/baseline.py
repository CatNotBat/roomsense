"""Empty-room baseline learning and deviation features.

Captures per-feature statistics (median, MAD) during a known-empty period.
Produces z-score deviation features: how far is the current reading from
the empty-room baseline?

Usage:
    # Capture baseline (5-10 min of empty room data)
    bc = BaselineCapture()
    bc.capture(readings_df, radar_readings=None)
    bc.save()

    # Load and compute deviations
    bc = BaselineCapture.load()
    z_scores = baseline_deviation_features(feature_row, bc.stats)
"""
import json
import os
import numpy as np
import pandas as pd


BASELINE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "calibration", "baseline.json")


class BaselineCapture:
    """Captures empty-room feature statistics."""

    def __init__(self, stats=None):
        self.stats = stats or {}  # {feature_name: {median, mad, p5, p95}}

    def capture(self, readings, A=20, sensors=None, radar_readings=None):
        """Build features from empty-room readings and compute stats.

        Args:
            readings: DataFrame with BLE readings during empty room
            A: window size in seconds
            sensors: sensor list
            radar_readings: optional radar data
        """
        from env_features import build_env_table

        X, _ = build_env_table(readings, A=A, overlap=0.5, sensors=sensors,
                               radar_readings=radar_readings)
        if len(X) == 0:
            return

        self.stats = {}
        for col in X.columns:
            vals = X[col].dropna().values.astype(float)
            if len(vals) < 3:
                continue
            med = float(np.median(vals))
            mad = float(np.median(np.abs(vals - med)))
            self.stats[col] = {
                "median": med,
                "mad": mad,
                "p5": float(np.percentile(vals, 5)),
                "p95": float(np.percentile(vals, 95)),
            }

    def save(self, path=None):
        """Save baseline stats to JSON."""
        path = path or BASELINE_PATH
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.stats, f, indent=2)

    @classmethod
    def load(cls, path=None):
        """Load baseline stats from JSON."""
        path = path or BASELINE_PATH
        if not os.path.exists(path):
            return None
        with open(path) as f:
            stats = json.load(f)
        return cls(stats=stats)


def baseline_deviation_features(feature_row, stats):
    """Compute z-score deviations from empty-room baseline.

    Args:
        feature_row: dict of {feature_name: value} for one window
        stats: dict from BaselineCapture.stats

    Returns:
        dict of {f"bdev_{feature}": z_score} for each feature with baseline
    """
    result = {}
    for feat, val in feature_row.items():
        if feat not in stats:
            continue
        s = stats[feat]
        median = s["median"]
        mad = s["mad"]

        if val is None or (isinstance(val, float) and np.isnan(val)):
            result[f"bdev_{feat}"] = 0.0
            continue

        # Scale: MAD * 1.4826 ≈ std for normal distribution
        # Fallback to IQR-based scale if MAD=0
        scale = mad * 1.4826
        if scale < 1e-6:
            iqr = s["p95"] - s["p5"]
            scale = iqr / 3.0 if iqr > 0 else 1.0

        z = (float(val) - median) / scale
        result[f"bdev_{feat}"] = round(z, 4)

    return result
