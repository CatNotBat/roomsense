import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dedup import RPADedup


def test_basic_counting():
    d = RPADedup(ttl_s=60)
    d.update("aa:bb:cc:dd:ee:01", [-50, -60], "phone")
    d.update("aa:bb:cc:dd:ee:02", [-55, -65], "earbuds")
    counts = d.get_counts({
        "aa:bb:cc:dd:ee:01": "phone",
        "aa:bb:cc:dd:ee:02": "earbuds",
    })
    assert counts == {"phone": 1, "earbuds": 1}


def test_no_mac_leaks():
    """get_counts must return only category→count, never any MAC."""
    d = RPADedup(ttl_s=60)
    d.update("aa:bb:cc:dd:ee:01", [-50], "phone")
    result = d.get_counts({"aa:bb:cc:dd:ee:01": "phone"})
    for key in result:
        assert ":" not in key, f"MAC leaked in result key: {key}"
    for val in result.values():
        assert isinstance(val, int)


def test_ttl_expiry():
    d = RPADedup(ttl_s=0.1)
    d.update("aa:bb:cc:dd:ee:01", [-50], "phone")
    time.sleep(0.2)
    d._expire()
    assert "aa:bb:cc:dd:ee:01" not in d._entries


def test_same_mac_updates():
    d = RPADedup(ttl_s=60)
    d.update("aa:bb:cc:dd:ee:01", [-50], "phone")
    d.update("aa:bb:cc:dd:ee:01", [-45], "phone")
    counts = d.get_counts({"aa:bb:cc:dd:ee:01": "phone"})
    assert counts == {"phone": 1}
