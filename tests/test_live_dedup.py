"""Tests for Continuity-aware dedup in src/dedup.py:count_nearby_devices()."""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dedup import count_nearby_devices
from device_id import InfraAllowlist


def _make_rows(macs_config, sensors=None):
    """Build synthetic BLE rows for dedup testing.

    macs_config: list of (mac, rssi_per_sensor, mfg_hex, addr_type)
        rssi_per_sensor: dict {sensor: rssi}
    """
    sensors = sensors or ["esp_c1", "esp_c2", "esp_c3", "esp_c4"]
    rows = []
    for mac, rssi_map, mfg_hex, addr_type in macs_config:
        for sensor, rssi in rssi_map.items():
            rows.append({
                "mac": mac, "source": sensor, "rssi": rssi,
                "addr_type": addr_type, "appearance": -1,
                "mfg_hex": mfg_hex, "svc_hex": "",
            })
    return rows


# Apple Continuity mfg_hex helpers
# cid=4c00 (Apple LE), then TLV: type, length, data
def _apple_mfg(*tlv_types):
    """Build Apple mfg_hex with given Continuity TLV types."""
    parts = "4c00"
    for t in tlv_types:
        parts += f"{t:02x}02aabb"  # type, len=2, dummy data
    return parts


class TestSingleiPhoneDedup:
    """One iPhone broadcasting multiple MACs with different Continuity types."""

    def test_same_device_different_types_merged(self):
        """Multiple MACs with different Continuity types at similar RSSI → 1 device."""
        rows = _make_rows([
            ("aa:01", {"esp_c1": -50, "esp_c2": -60}, _apple_mfg(0x10), 1),  # Nearby
            ("aa:02", {"esp_c1": -51, "esp_c2": -61}, _apple_mfg(0x12), 1),  # Handoff
            ("aa:03", {"esp_c1": -52, "esp_c2": -59}, _apple_mfg(0x09), 1),  # AirPlay
        ])
        counts = count_nearby_devices(rows)
        assert counts.get("phone", 0) == 1

    def test_same_device_same_type_not_merged(self):
        """Two MACs with same Continuity type = different devices."""
        rows = _make_rows([
            ("aa:01", {"esp_c1": -50, "esp_c2": -60}, _apple_mfg(0x10), 1),  # Nearby
            ("aa:02", {"esp_c1": -51, "esp_c2": -61}, _apple_mfg(0x10), 1),  # Nearby
        ])
        counts = count_nearby_devices(rows)
        assert counts.get("phone", 0) == 2


class TestTwoiPhones:
    """Two iPhones at the same location."""

    def test_two_phones_same_location(self):
        """Two iPhones sharing Continuity type 0x10 → 2 devices."""
        rows = _make_rows([
            # Phone 1: Nearby + Handoff
            ("aa:01", {"esp_c1": -50, "esp_c2": -60}, _apple_mfg(0x10), 1),
            ("aa:02", {"esp_c1": -51, "esp_c2": -61}, _apple_mfg(0x12), 1),
            # Phone 2: Nearby (same type as phone 1's first MAC → different device)
            ("bb:01", {"esp_c1": -52, "esp_c2": -59}, _apple_mfg(0x10), 1),
            ("bb:02", {"esp_c1": -53, "esp_c2": -60}, _apple_mfg(0x09), 1),
        ])
        counts = count_nearby_devices(rows)
        assert counts.get("phone", 0) == 2

    def test_two_phones_different_locations(self):
        """Two phones at different locations (different RSSI patterns) → 2."""
        rows = _make_rows([
            ("aa:01", {"esp_c1": -45, "esp_c2": -75}, _apple_mfg(0x12), 1),
            ("bb:01", {"esp_c1": -75, "esp_c2": -45}, _apple_mfg(0x12), 1),
        ])
        counts = count_nearby_devices(rows)
        assert counts.get("phone", 0) == 2


class TestNonAppleDevices:
    """Devices without Apple Continuity data fall back to RSSI clustering."""

    def test_non_apple_similar_rssi_merged(self):
        """Two non-Apple MACs at similar RSSI → 1 device."""
        rows = _make_rows([
            ("aa:01", {"esp_c1": -50, "esp_c2": -60}, "", 1),
            ("aa:02", {"esp_c1": -51, "esp_c2": -61}, "", 1),
        ])
        counts = count_nearby_devices(rows)
        assert counts.get("phone", 0) == 1

    def test_non_apple_different_rssi_separate(self):
        """Two non-Apple MACs at very different RSSI → 2 devices."""
        rows = _make_rows([
            ("aa:01", {"esp_c1": -40, "esp_c2": -80}, "", 1),
            ("aa:02", {"esp_c1": -80, "esp_c2": -40}, "", 1),
        ])
        counts = count_nearby_devices(rows)
        assert counts.get("phone", 0) == 2


class TestMixedDeviceTypes:
    """Phone + earbuds should be counted separately."""

    def test_phone_and_earbuds(self):
        """iPhone + AirPods at similar RSSI → separate categories."""
        rows = _make_rows([
            ("aa:01", {"esp_c1": -50, "esp_c2": -60}, _apple_mfg(0x10), 1),
            ("bb:01", {"esp_c1": -51, "esp_c2": -61}, _apple_mfg(0x07), 1),
        ])
        counts = count_nearby_devices(rows)
        assert counts.get("phone", 0) == 1
        assert counts.get("earbuds", 0) == 1


class TestInfraFiltering:
    """Infrastructure devices should be excluded."""

    def test_infra_excluded(self):
        from config import hash_mac
        infra_mac = "ff:ff:ff:ff:ff:01"
        infra_hash = hash_mac(infra_mac)
        allowlist = InfraAllowlist({infra_hash})

        rows = _make_rows([
            (infra_mac, {"esp_c1": -50, "esp_c2": -60}, "", 0),
            ("aa:01", {"esp_c1": -55, "esp_c2": -65}, "", 1),
        ])
        counts = count_nearby_devices(rows, infra_allowlist=allowlist)
        # Infra device excluded, only the phone remains
        total = sum(counts.values())
        assert total == 1


class TestWeakDevicesFiltered:
    """Devices below strong_thresh should be excluded."""

    def test_weak_device_excluded(self):
        rows = _make_rows([
            ("aa:01", {"esp_c1": -50}, "", 1),   # Strong
            ("bb:01", {"esp_c1": -95}, "", 1),   # Weak (below -85)
        ])
        counts = count_nearby_devices(rows, strong_thresh=-85)
        total = sum(counts.values())
        assert total == 1

    def test_custom_threshold(self):
        rows = _make_rows([
            ("aa:01", {"esp_c1": -70}, "", 1),
        ])
        # With strict threshold, this device passes
        counts = count_nearby_devices(rows, strong_thresh=-75)
        assert sum(counts.values()) == 1
        # With stricter threshold, it doesn't
        counts = count_nearby_devices(rows, strong_thresh=-65)
        assert sum(counts.values()) == 0


class TestEmptyInput:
    """Edge cases."""

    def test_no_rows(self):
        counts = count_nearby_devices([])
        assert counts == {}

    def test_all_weak(self):
        rows = _make_rows([
            ("aa:01", {"esp_c1": -95}, "", 1),
        ])
        counts = count_nearby_devices(rows, strong_thresh=-85)
        assert counts == {}
