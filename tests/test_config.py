import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from config import hash_mac, SENSORS, WINDOW_S, HASH_ON_DISK


def test_hash_mac_deterministic():
    h1 = hash_mac("AA:BB:CC:DD:EE:FF")
    h2 = hash_mac("AA:BB:CC:DD:EE:FF")
    assert h1 == h2


def test_hash_mac_different_for_different_macs():
    h1 = hash_mac("AA:BB:CC:DD:EE:FF")
    h2 = hash_mac("11:22:33:44:55:66")
    assert h1 != h2


def test_hash_mac_length():
    h = hash_mac("AA:BB:CC:DD:EE:FF")
    assert len(h) == 12


def test_sensors_default():
    assert len(SENSORS) == 4
    assert SENSORS[0] == "esp_c1"


def test_window_default():
    assert WINDOW_S == 2


def test_hash_on_disk_default():
    # Default is true unless env var overrides
    assert isinstance(HASH_ON_DISK, bool)
