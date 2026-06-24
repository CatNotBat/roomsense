"""Tests for src/adv_interval.py — BLE advertising interval estimation."""
import sys, os, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from adv_interval import AdvertisingIntervalEstimator


def test_regular_interval_estimation():
    """Regular 100ms interval should be estimated accurately."""
    est = AdvertisingIntervalEstimator(min_observations=5)
    t0 = 1000.0
    for i in range(20):
        est.add_observation("aa:bb:cc:dd:ee:00", "esp_c1", t0 + i * 0.1)

    result = est.estimate("aa:bb:cc:dd:ee:00")
    assert result is not None
    assert 80 <= result["interval_ms"] <= 120  # ~100ms ±20%
    assert result["confidence"] > 0
    assert result["n_samples"] >= 5


def test_insufficient_observations():
    """Too few observations should return None."""
    est = AdvertisingIntervalEstimator(min_observations=5)
    est.add_observation("aa:bb:cc:dd:ee:00", "esp_c1", 1000.0)
    est.add_observation("aa:bb:cc:dd:ee:00", "esp_c1", 1000.1)

    result = est.estimate("aa:bb:cc:dd:ee:00")
    assert result is None


def test_outlier_filtering():
    """Outlier deltas (>2x median) should be filtered."""
    est = AdvertisingIntervalEstimator(min_observations=5)
    t0 = 1000.0
    # Regular 100ms interval with one 5s gap (outlier)
    for i in range(10):
        est.add_observation("aa:bb:cc:dd:ee:00", "esp_c1", t0 + i * 0.1)
    # Big gap then resume
    for i in range(10):
        est.add_observation("aa:bb:cc:dd:ee:00", "esp_c1", t0 + 5.0 + i * 0.1)

    result = est.estimate("aa:bb:cc:dd:ee:00")
    assert result is not None
    assert 80 <= result["interval_ms"] <= 120  # outlier filtered


def test_multi_sensor_combines():
    """Observations from multiple sensors should be combined."""
    est = AdvertisingIntervalEstimator(min_observations=5)
    t0 = 1000.0
    for i in range(5):
        est.add_observation("aa:bb:cc:dd:ee:00", "esp_c1", t0 + i * 0.1)
        est.add_observation("aa:bb:cc:dd:ee:00", "esp_c2", t0 + i * 0.1 + 0.005)

    result = est.estimate("aa:bb:cc:dd:ee:00")
    assert result is not None
    assert result["n_samples"] >= 5


def test_window_expiry():
    """Old observations outside window should be dropped."""
    est = AdvertisingIntervalEstimator(window_s=10, min_observations=5)
    t0 = 1000.0
    # Old observations
    for i in range(10):
        est.add_observation("aa:bb:cc:dd:ee:00", "esp_c1", t0 + i * 0.1)
    # Add one new observation far in the future to trigger cleanup
    est.add_observation("aa:bb:cc:dd:ee:00", "esp_c1", t0 + 20.0)

    result = est.estimate("aa:bb:cc:dd:ee:00")
    # Only 1 observation in window → insufficient
    assert result is None


def test_unknown_mac():
    """Unknown MAC should return None."""
    est = AdvertisingIntervalEstimator()
    assert est.estimate("ff:ff:ff:ff:ff:ff") is None


def test_cleanup_removes_expired():
    """cleanup() should remove stale entries."""
    est = AdvertisingIntervalEstimator(window_s=5)
    t0 = 1000.0
    for i in range(10):
        est.add_observation("aa:bb:cc:dd:ee:00", "esp_c1", t0 + i * 0.1)

    # Add observation far in future so old ones expire
    est.add_observation("ff:ff:ff:ff:ff:ff", "esp_c1", t0 + 100.0)
    est.cleanup()

    # Old mac's observations should be gone
    result = est.estimate("aa:bb:cc:dd:ee:00")
    assert result is None


def test_dedup_interval_blocks_merge():
    """RPADedup should block merge when intervals differ by >20%."""
    from dedup import RPADedup

    dd = RPADedup(ttl_s=30)
    # First device: 100ms interval
    dd.update("aa:00", [-60, -70, -80, -90], "phone", interval_ms=100)

    # Make it stale
    dd._entries["aa:00"]["last_seen"] = time.time() - 5

    # Second device with very different interval (500ms) — should NOT merge
    dd.update("bb:00", [-61, -71, -81, -91], "phone", interval_ms=500)

    # If merge was blocked, both should be separate entries
    assert "aa:00" in dd._entries
    assert "bb:00" in dd._entries
    assert "bb:00" not in dd._merges  # not merged into aa:00


def test_dedup_interval_allows_merge():
    """RPADedup should allow merge when intervals are similar."""
    from dedup import RPADedup

    dd = RPADedup(ttl_s=30)
    # First device: 100ms interval
    dd.update("aa:00", [-60, -70, -80, -90], "phone", interval_ms=100)

    # Make it stale
    dd._entries["aa:00"]["last_seen"] = time.time() - 5

    # Second device with similar interval (110ms, within 20%) and similar RSSI
    dd.update("bb:00", [-62, -72, -82, -92], "phone", interval_ms=110)

    # Should have been merged
    assert dd._merges.get("bb:00") == "aa:00"
