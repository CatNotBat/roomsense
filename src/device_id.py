"""Deterministic device-TYPE classification from passively observed BLE fields.
Returns a CATEGORY only. Never returns or persists an identity.

Privacy boundary:
  - Never attempt to resolve an RPA
  - Never persist a per-unit fingerprint
  - Never correlate a hidden Fast Pair bloom filter
  - Never parse probed SSIDs
  - This module returns a category string and nothing else."""

APPLE, MSFT, GOOGLE, SAMSUNG = 0x004C, 0x0006, 0x00E0, 0x0075
APPEARANCE = {0x0040: "phone", 0x0080: "laptop", 0x00C0: "watch",
              0x03C1: "keyboard", 0x03C2: "mouse", 0x0841: "earbuds"}


def company_id(mfg_hex):
    """Extract little-endian company ID from manufacturer data hex string."""
    if not mfg_hex or len(mfg_hex) < 4:
        return None
    b = bytes.fromhex(mfg_hex)
    return b[0] | (b[1] << 8)  # little-endian, never byte-swap


def apple_continuity_types(mfg_hex):
    """Return set of Continuity TLV type bytes (cid already known == APPLE)."""
    b = bytes.fromhex(mfg_hex)
    i = 2
    types = set()
    while i + 1 < len(b):
        t, ln = b[i], b[i + 1]
        types.add(t)
        i += 2 + ln
    return types


def fast_pair(svc_hex):
    """('discoverable', model_hex) | ('hidden', None) | None.
    UUID 0xFE2C = '2cfe' LE in service data."""
    if not svc_hex or not svc_hex.lower().startswith("2cfe"):
        return None
    data = svc_hex[4:]
    if len(data) <= 8:  # short payload ~ 3-byte model id => discoverable accessory
        return ("discoverable", data)
    return ("hidden", None)  # rotating bloom filter — DO NOT correlate


def device_type(mfg_hex="", svc_hex="", appearance=-1, addr_type=1, svc_uuids=()):
    """Classify a device by type from BLE advertisement fields.
    Returns a category string only."""
    # 1) explicit appearance wins when present
    if appearance is not None and appearance >= 0 and appearance in APPEARANCE:
        return APPEARANCE[appearance]

    # 2) Fast Pair discoverable accessory
    fp = fast_pair(svc_hex)
    if fp and fp[0] == "discoverable":
        return "earbuds"

    # 3) manufacturer-data ecosystems
    cid = company_id(mfg_hex)
    if cid == APPLE:
        t = apple_continuity_types(mfg_hex)
        if 0x07 in t:
            return "earbuds"        # AirPods/Beats
        if 0x10 in t or 0x12 in t:
            return "phone"          # Apple handheld/computer-class
        return "apple_device"
    if cid == SAMSUNG:
        return "earbuds_or_galaxy"
    if cid == MSFT:
        return "laptop_or_pc"

    # 4) service UUIDs (weak)
    if 0x1812 in svc_uuids:
        return "keyboard_or_mouse"  # HID
    if 0x180D in svc_uuids:
        return "watch"              # heart rate

    # 5) address-type prior
    if addr_type in (1, 2, 3):
        return "phone"  # RPA/random => modern personal device

    return "unknown"


# ---- Infrastructure suppression ----

def is_infra_candidate(addr_type):
    """Only PUBLIC (0) addresses get OUI lookup — stable, not privacy-rotated."""
    return addr_type == 0


class InfraAllowlist:
    """Session allowlist for infrastructure devices (room AP, TV, speaker).
    Entries stored hashed. Volatile — never serialized to disk."""

    def __init__(self, preseeded_hashes=None):
        self._hashes = set(preseeded_hashes or [])

    def add(self, mac_hash):
        self._hashes.add(mac_hash)

    def is_allowed(self, mac_hash):
        return mac_hash in self._hashes
