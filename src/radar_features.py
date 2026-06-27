"""mmWave radar (HLK-LD2450) feature extraction for RoomSense v2.

Ingests buffered radar frames and produces per-window features
aligned with BLE aggregation windows.

Each radar frame has: source, ts, n_targets, targets[{x,y,spd,dist}].
"""
import numpy as np
from config import SENSORS, RADAR_MAX_TARGETS


def build_radar_features(radar_rows, t_start, t_end, sensors=None):
    """Build radar features for one time window.

    Parameters
    ----------
    radar_rows : list[dict]
        Each dict has keys: source, ts, n_targets,
        targets (list of dicts with x, y, spd, dist).
    t_start, t_end : float
        Window boundaries (epoch seconds).
    sensors : list[str] or None
        Sensor IDs. Defaults to config.SENSORS.

    Returns
    -------
    dict
        Feature name → value. Missing sensors get 0/NaN fill.
    """
    if sensors is None:
        sensors = SENSORS

    # Filter to window
    rows = [r for r in radar_rows
            if t_start <= r["ts"] < t_end]

    feat = {}

    # Per-sensor features
    occupied_counts = []
    mean_dists = []

    for s in sensors:
        s_rows = [r for r in rows if r["source"] == s]
        n_frames = len(s_rows)

        if n_frames == 0:
            feat[f"radar_max_targets__{s}"] = 0
            feat[f"radar_mean_targets__{s}"] = 0.0
            feat[f"radar_frac_occupied__{s}"] = 0.0
            feat[f"radar_mean_dist__{s}"] = np.nan
            feat[f"radar_min_dist__{s}"] = np.nan
            feat[f"radar_mean_speed__{s}"] = 0.0
            feat[f"radar_max_speed__{s}"] = 0.0
            feat[f"radar_dist_std__{s}"] = 0.0
            feat[f"radar_x_spread__{s}"] = 0.0
            occupied_counts.append(0.0)
            mean_dists.append(np.nan)
            continue

        target_counts = [r["n_targets"] for r in s_rows]
        feat[f"radar_max_targets__{s}"] = max(target_counts)
        feat[f"radar_mean_targets__{s}"] = float(np.mean(target_counts))

        occupied = sum(1 for c in target_counts if c > 0)
        frac_occ = occupied / n_frames
        feat[f"radar_frac_occupied__{s}"] = frac_occ
        occupied_counts.append(frac_occ)

        # Collect all target measurements from this sensor
        all_dists = []
        all_speeds = []
        all_x = []
        for r in s_rows:
            for t in r.get("targets", []):
                d = t.get("dist", 0)
                if d > 0:
                    all_dists.append(d)
                    all_speeds.append(abs(t.get("spd", 0)))
                    all_x.append(t.get("x", 0))

        if all_dists:
            feat[f"radar_mean_dist__{s}"] = float(np.mean(all_dists))
            feat[f"radar_min_dist__{s}"] = float(np.min(all_dists))
            feat[f"radar_dist_std__{s}"] = float(np.std(all_dists))
            mean_dists.append(float(np.mean(all_dists)))
        else:
            feat[f"radar_mean_dist__{s}"] = np.nan
            feat[f"radar_min_dist__{s}"] = np.nan
            feat[f"radar_dist_std__{s}"] = 0.0
            mean_dists.append(np.nan)

        if all_speeds:
            feat[f"radar_mean_speed__{s}"] = float(np.mean(all_speeds))
            feat[f"radar_max_speed__{s}"] = float(np.max(all_speeds))
        else:
            feat[f"radar_mean_speed__{s}"] = 0.0
            feat[f"radar_max_speed__{s}"] = 0.0

        if all_x:
            feat[f"radar_x_spread__{s}"] = float(np.max(all_x) - np.min(all_x))
        else:
            feat[f"radar_x_spread__{s}"] = 0.0

    # Cross-sensor features
    feat["radar_total_max_targets"] = max(
        (feat.get(f"radar_max_targets__{s}", 0) for s in sensors), default=0)
    feat["radar_n_sensors_occupied"] = sum(
        1 for oc in occupied_counts if oc > 0.5)

    valid_dists = [d for d in mean_dists if not np.isnan(d)]
    if len(valid_dists) >= 2:
        feat["radar_dist_spread"] = max(valid_dists) - min(valid_dists)
    else:
        feat["radar_dist_spread"] = 0.0

    feat["radar_consensus_occupied"] = (
        feat["radar_n_sensors_occupied"] / len(sensors) if sensors else 0.0)

    return feat
