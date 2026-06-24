"""BLE advertising interval estimator.

Tracks per-(mac, sensor) timestamps to estimate each device's advertising
interval in milliseconds. Interval is stable across MAC rotations and can be
used as a dedup signal (different interval => different device).

Compute brain-side: centralize timestamps from all sensor nodes.
"""
import collections
import statistics
import threading
import time


class AdvertisingIntervalEstimator:
    """Estimates BLE advertising intervals from observation timestamps.

    Thread-safe: MQTT ingest thread calls add_observation(), evaluation
    thread calls estimate().
    """

    def __init__(self, window_s=120, min_observations=5):
        self._window_s = window_s
        self._min_obs = min_observations
        # (mac, sensor) -> deque of timestamps
        self._obs = collections.defaultdict(collections.deque)
        self._lock = threading.Lock()

    def add_observation(self, mac, sensor, ts=None):
        """Record a BLE advertisement observation."""
        ts = ts or time.time()
        key = (mac, sensor)
        with self._lock:
            dq = self._obs[key]
            dq.append(ts)
            # Trim old observations
            cutoff = ts - self._window_s
            while dq and dq[0] < cutoff:
                dq.popleft()

    def estimate(self, mac):
        """Estimate advertising interval for a MAC across all sensors.

        Returns:
            dict with {interval_ms, confidence, n_samples} or None if
            insufficient data.
        """
        with self._lock:
            all_ts = []
            for (m, _sensor), dq in self._obs.items():
                if m == mac and len(dq) >= 2:
                    all_ts.extend(dq)

        if len(all_ts) < self._min_obs:
            return None

        all_ts.sort()

        # Compute inter-arrival deltas
        deltas_ms = [(all_ts[i + 1] - all_ts[i]) * 1000
                     for i in range(len(all_ts) - 1)
                     if all_ts[i + 1] - all_ts[i] > 0.001]  # skip <1ms dupes

        if len(deltas_ms) < 3:
            return None

        # Filter outliers: keep deltas within 2x of median
        med = statistics.median(deltas_ms)
        if med <= 0:
            return None
        filtered = [d for d in deltas_ms if d <= med * 2]
        if len(filtered) < 3:
            return None

        interval = statistics.median(filtered)
        std = statistics.stdev(filtered) if len(filtered) > 1 else 0.0
        confidence = min(1.0, len(filtered) / 20)  # saturates at 20 samples

        return {
            "interval_ms": round(interval, 1),
            "confidence": round(confidence, 2),
            "n_samples": len(filtered),
            "std_ms": round(std, 1),
        }

    def cleanup(self):
        """Remove expired entries."""
        now = time.time()
        cutoff = now - self._window_s
        with self._lock:
            expired = [k for k, dq in self._obs.items()
                       if not dq or dq[-1] < cutoff]
            for k in expired:
                del self._obs[k]
