"""Ephemeral within-session de-dup for rotating BLE addresses (RPA).

Volatile, TTL'd structure. Links old→new RPA as the same COUNT (not identity)
using RSSI/spatial continuity + payload-type continuity.

Hard rules:
  - Entries expire at RPA_TTL_S
  - Nothing here is ever serialized to disk
  - Addresses live ONLY inside this layer
  - Downstream of de-dup, NO MAC may exist — only {category → count}
"""
import collections, statistics, time
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from config import RPA_TTL_S
from device_id import (device_type, company_id, apple_continuity_types,
                       APPLE)


class RPADedup:
    """Volatile de-dup layer. Merges rotating addresses into stable counts."""

    def __init__(self, ttl_s=None):
        self._ttl = ttl_s or RPA_TTL_S
        # mac -> {last_seen, rssi_vec, category, adv_interval_est}
        self._entries = {}
        # merged_mac -> canonical_mac (tracks which addresses were collapsed)
        self._merges = {}

    def _expire(self):
        now = time.time()
        expired = [m for m, e in self._entries.items() if now - e["last_seen"] > self._ttl]
        for m in expired:
            del self._entries[m]
        # Clean merges pointing to expired entries
        self._merges = {k: v for k, v in self._merges.items() if v in self._entries}

    def _find_merge_candidate(self, mac, rssi_vec, category, interval_ms=None):
        """Find a recently-departed entry that looks like the same device."""
        now = time.time()
        best = None
        best_sim = 0
        for old_mac, entry in self._entries.items():
            if old_mac == mac:
                continue
            # Must be stale (not currently active) to be a rotation candidate
            age = now - entry["last_seen"]
            if age < 2 or age > self._ttl:
                continue
            # Category must match
            if entry["category"] != category:
                continue
            # Advertising interval check: if both have intervals and they
            # differ by >20%, these are different devices — block merge
            old_interval = entry.get("interval_ms")
            if interval_ms and old_interval and old_interval > 0:
                ratio = abs(interval_ms - old_interval) / old_interval
                if ratio > 0.20:
                    continue
            # RSSI vector similarity (cosine-ish: small diff = likely same device)
            if rssi_vec and entry["rssi_vec"]:
                diffs = [abs(a - b) for a, b in zip(rssi_vec, entry["rssi_vec"])
                         if a > -120 and b > -120]
                if diffs:
                    avg_diff = sum(diffs) / len(diffs)
                    sim = max(0, 1 - avg_diff / 30)  # 30 dB diff = 0 similarity
                    if sim > best_sim and sim > 0.5:
                        best_sim = sim
                        best = old_mac
        return best

    def update(self, mac, rssi_vec, category, interval_ms=None):
        """Register/update a device. Returns the canonical mac for counting."""
        self._expire()

        # Already tracking this mac
        if mac in self._entries:
            self._entries[mac]["last_seen"] = time.time()
            self._entries[mac]["rssi_vec"] = rssi_vec
            self._entries[mac]["category"] = category
            if interval_ms:
                self._entries[mac]["interval_ms"] = interval_ms
            return self._merges.get(mac, mac)

        # Check if this looks like a rotation of a recently-departed address
        candidate = self._find_merge_candidate(mac, rssi_vec, category,
                                               interval_ms=interval_ms)
        if candidate:
            canonical = self._merges.get(candidate, candidate)
            self._merges[mac] = canonical
        else:
            canonical = mac

        self._entries[mac] = {
            "last_seen": time.time(),
            "rssi_vec": rssi_vec,
            "category": category,
            "interval_ms": interval_ms,
        }
        return canonical

    def get_counts(self, inside_devices):
        """Given {mac: category} of inside devices, return {category: count}.
        This is the privacy boundary — NO MAC exits this function.

        Args:
            inside_devices: dict of {mac: category} for devices classified inside
        Returns:
            dict of {category: count}
        """
        # Resolve merges to canonical macs
        canonical_cats = {}
        for mac, cat in inside_devices.items():
            canon = self._merges.get(mac, mac)
            canonical_cats[canon] = cat

        # Count by category
        counts = {}
        for cat in canonical_cats.values():
            counts[cat] = counts.get(cat, 0) + 1

        # ASSERTION: no MAC leaves this layer
        return counts


def count_nearby_devices(rows, infra_allowlist=None, strong_thresh=-85,
                         dedup_sensor_dist=6.0):
    """Count nearby devices by category with Continuity-aware dedup.

    Clusters BLE advertisements by device type and spatial RSSI similarity,
    using Apple Continuity TLV types to distinguish same-device multi-MAC
    broadcasts from genuinely different devices.

    Args:
        rows: list of dicts with keys: mac, source, rssi, addr_type,
              appearance, mfg_hex, svc_hex
        infra_allowlist: InfraAllowlist instance (optional)
        strong_thresh: minimum average RSSI to consider a device nearby
        dedup_sensor_dist: RMSE threshold for merging per-sensor RSSI vectors

    Returns:
        dict of {category: count} — NO MAC exits this function.
    """
    from config import hash_mac

    # Build per-MAC metadata (latest wins) and per-sensor RSSI lists
    meta_info = {}
    mac_sensor_rssi = collections.defaultdict(
        lambda: collections.defaultdict(list))
    for r in rows:
        mac = r["mac"]
        meta_info[mac] = {
            "addr_type": r.get("addr_type", 1),
            "appearance": r.get("appearance", -1),
            "mfg_hex": r.get("mfg_hex", ""),
            "svc_hex": r.get("svc_hex", ""),
        }
        mac_sensor_rssi[mac][r["source"]].append(r["rssi"])

    # Per-MAC: overall avg RSSI + per-sensor vector
    mac_avg_rssi = {}
    mac_sensor_vec = {}
    for mac, sensors in mac_sensor_rssi.items():
        all_rssi = [v for vals in sensors.values() for v in vals]
        mac_avg_rssi[mac] = statistics.median(all_rssi)
        mac_sensor_vec[mac] = {s: statistics.median(v) for s, v in sensors.items()}

    # Classify nearby MACs into categories
    cat_macs = collections.defaultdict(list)
    for mac, avg in mac_avg_rssi.items():
        if avg <= strong_thresh:
            continue
        if infra_allowlist and infra_allowlist.is_allowed(hash_mac(mac)):
            continue
        mi = meta_info.get(mac, {})
        mfg = mi.get("mfg_hex", "")
        cat = device_type(
            mfg_hex=mfg,
            svc_hex=mi.get("svc_hex", ""),
            appearance=mi.get("appearance", -1),
            addr_type=mi.get("addr_type", 1),
        )
        cont_types = frozenset()
        if mfg and company_id(mfg) == APPLE:
            cont_types = frozenset(apple_continuity_types(mfg))
        cat_macs[cat].append((mac, avg, cont_types))

    # Dedup within each category using spatial + Continuity-type clustering
    counts = {}
    for cat, macs in cat_macs.items():
        macs_sorted = sorted(macs, key=lambda x: x[1], reverse=True)
        clusters = []
        for mac, rssi, cont in macs_sorted:
            vec = mac_sensor_vec.get(mac, {})
            merged = False
            for cluster in clusters:
                if cont and cluster["cont_types"]:
                    if cont & cluster["cont_types"]:
                        continue  # Same Continuity type = different device
                shared = set(vec) & set(cluster["vec"])
                if shared:
                    dist = (sum((vec[s] - cluster["vec"][s]) ** 2
                                for s in shared) / len(shared)) ** 0.5
                    if dist < dedup_sensor_dist:
                        cluster["cont_types"] |= cont
                        merged = True
                        break
            if not merged:
                clusters.append({"vec": vec, "cont_types": set(cont)})
        if clusters:
            counts[cat] = len(clusters)

    return counts
