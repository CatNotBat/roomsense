"""TX-invariant / transfer features.

These features are designed to be invariant to the device's own transmit
power and antenna gain, which can vary by 10-40 dB across device types
(larger than the wall penalty we're trying to detect).

All functions operate on per-sensor medians within one aggregation window.
"""
import numpy as np


def self_normalize(sensor_medians, sensors):
    """Per-device self-normalization within an aggregation window.

    ref = median(rssi_cal over all heard sensors)
    Returns {sensor: rssi_cal - ref} for each sensor.

    Args:
        sensor_medians: dict {sensor_id: float or NaN}
        sensors: list of sensor IDs

    Returns:
        dict {sensor_id: float or NaN}
    """
    heard = [v for s in sensors
             for v in [sensor_medians.get(s)]
             if v is not None and not np.isnan(v)]
    if not heard:
        return {s: np.nan for s in sensors}
    ref = float(np.median(heard))
    result = {}
    for s in sensors:
        v = sensor_medians.get(s)
        if v is not None and not np.isnan(v):
            result[s] = v - ref
        else:
            result[s] = np.nan
    return result


def anisotropy(sensor_medians):
    """IQR of per-satellite medians within one window.

    Single scalar measuring how unequally the sensors see this device.
    Rotation-invariant and level-invariant.

    Returns 0.0 if fewer than 2 sensors heard the device.
    """
    heard = [v for v in sensor_medians.values()
             if v is not None and not np.isnan(v)]
    if len(heard) < 2:
        return 0.0
    q75, q25 = np.percentile(heard, [75, 25])
    return float(q75 - q25)


def argmax_coverage(sub_window_argmaxes, n_sensors):
    """Fraction of distinct satellites that were ever the loudest.

    Interior movement visits all corners → coverage ~ 1.0
    Exterior stays on one side → coverage ~ 1/N

    Args:
        sub_window_argmaxes: list of sensor_id strings, one per sub-window
        n_sensors: total number of sensors

    Returns:
        float in [0, 1]
    """
    if not sub_window_argmaxes or n_sensors == 0:
        return 0.0
    unique = len(set(sub_window_argmaxes))
    return unique / n_sensors


def reference_node_delta(sensor_medians, reference_sensor, interior_sensors):
    """median(interior_nodes) - median(reference_node).

    Returns None if reference node is not configured or not heard.

    Args:
        sensor_medians: dict {sensor_id: float or NaN}
        reference_sensor: sensor_id string, or None/empty
        interior_sensors: list of non-reference sensor IDs
    """
    if not reference_sensor:
        return None
    ref_val = sensor_medians.get(reference_sensor)
    if ref_val is None or np.isnan(ref_val):
        return None
    interior_vals = [sensor_medians[s] for s in interior_sensors
                     if s in sensor_medians
                     and sensor_medians[s] is not None
                     and not np.isnan(sensor_medians[s])]
    if not interior_vals:
        return None
    return float(np.median(interior_vals) - ref_val)
