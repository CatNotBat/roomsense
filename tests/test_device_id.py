import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from device_id import (device_type, company_id, fast_pair,
                       apple_continuity_types, is_infra_candidate,
                       classify_random_addr,
                       APPLE, SAMSUNG, MSFT, GOOGLE)

def test_apple_cid_le():
    # 4c00 = Apple (0x004C little-endian)
    assert company_id("4c000a100000") == 0x004C

def test_appearance_watch():
    assert device_type(appearance=0x00C0) == "watch"

def test_fast_pair_disc():
    assert device_type(svc_hex="2cfeAABBCC") == "earbuds"

def test_rpa_prior_phone():
    assert device_type(addr_type=2) == "phone"

def test_unknown_public():
    assert device_type(addr_type=0) == "unknown"

def test_apple_airpods():
    # mfg_hex: cid=4c00, then TLV with type=0x07
    assert device_type(mfg_hex="4c0007030102") == "earbuds"

def test_apple_nearby_info():
    # TLV type=0x10
    assert device_type(mfg_hex="4c001002abcd") == "phone"


# --- Samsung ---

def test_samsung_cid():
    # 0x0075 little-endian = 7500
    assert company_id("7500aabbccdd") == SAMSUNG

def test_samsung_device_type():
    assert device_type(mfg_hex="7500aabbccdd") == "earbuds_or_galaxy"


# --- Microsoft ---

def test_msft_cid():
    # 0x0006 little-endian = 0600
    assert company_id("0600aabbccdd") == MSFT

def test_msft_device_type():
    assert device_type(mfg_hex="0600aabbccdd") == "laptop_or_pc"


# --- Android Fast Pair ---

def test_fast_pair_discoverable():
    fp = fast_pair("2cfeAABBCC")
    assert fp is not None
    assert fp[0] == "discoverable"

def test_fast_pair_hidden():
    # Long payload = hidden bloom filter
    fp = fast_pair("2cfe" + "AA" * 20)
    assert fp is not None
    assert fp[0] == "hidden"

def test_fast_pair_not_present():
    assert fast_pair("") is None
    assert fast_pair("abcd1234") is None


# --- Apple Continuity multi-TLV ---

def test_apple_multi_tlv():
    """Multiple Continuity types in one mfg_hex."""
    # cid=4c00, TLV: type=0x10 len=2 data=aabb, type=0x12 len=2 data=ccdd
    mfg = "4c001002aabb1202ccdd"
    types = apple_continuity_types(mfg)
    assert 0x10 in types
    assert 0x12 in types
    assert len(types) == 2

def test_apple_find_my_type():
    # TLV type=0x12 (Find My / AirTag) → tracker
    assert device_type(mfg_hex="4c001202aabb") == "tracker"

def test_apple_airplay_is_infra():
    # TLV type=0x09 (AirPlay Target) → infra (not a person)
    assert device_type(mfg_hex="4c000902aabb") == "infra"


# --- Infrastructure ---

def test_infra_candidate_public():
    assert is_infra_candidate(0) is True

def test_infra_candidate_rpa():
    assert is_infra_candidate(1) is False
    assert is_infra_candidate(2) is False


# --- Appearance ---

def test_appearance_phone():
    assert device_type(appearance=0x0040) == "phone"

def test_appearance_laptop():
    assert device_type(appearance=0x0080) == "laptop"

def test_appearance_earbuds():
    assert device_type(appearance=0x0841) == "earbuds"

def test_appearance_overrides_mfg():
    """Appearance takes priority over manufacturer data."""
    assert device_type(appearance=0x00C0, mfg_hex="4c001002aabb") == "watch"


# --- Edge cases ---

def test_empty_mfg():
    assert company_id("") is None
    assert company_id(None) is None

def test_short_mfg():
    assert company_id("4c") is None

def test_addr_type_3_is_phone():
    assert device_type(addr_type=3) == "phone"


# --- New v3.1 classification ---

def test_ibeacon_classified_as_beacon():
    # Apple CID + type 0x02 length 0x15 = iBeacon
    ibeacon_mfg = "4c000215" + "aa" * 21  # 0x02, len=0x15, then 21 bytes data
    assert device_type(mfg_hex=ibeacon_mfg) == "beacon"

def test_apple_homekit_is_infra():
    # TLV type=0x06 (HomeKit)
    assert device_type(mfg_hex="4c000602aabb") == "infra"

def test_apple_airprint_is_infra():
    # TLV type=0x01 (AirPrint)
    assert device_type(mfg_hex="4c000102aabb") == "infra"

def test_apple_watch_magic_switch():
    # TLV type=0x0A (Magic Switch) → watch
    assert device_type(mfg_hex="4c000a02aabb") == "watch"

def test_classify_rpa():
    # Top 2 bits = 01 → RPA
    assert classify_random_addr("4a:bb:cc:dd:ee:ff") == "rpa"

def test_classify_static_random():
    # Top 2 bits = 11 → static
    assert classify_random_addr("ca:bb:cc:dd:ee:ff") == "static"

def test_classify_nrpa():
    # Top 2 bits = 00 → non-resolvable
    assert classify_random_addr("0a:bb:cc:dd:ee:ff") == "nrpa"

def test_expanded_appearance_headphones():
    assert device_type(appearance=0x0844) == "earbuds"

def test_expanded_appearance_earbud():
    assert device_type(appearance=0x0846) == "earbuds"

def test_expanded_appearance_smartphone():
    assert device_type(appearance=0x0041) == "phone"
