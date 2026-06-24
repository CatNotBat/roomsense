#!/usr/bin/env python3
"""Live BLE census: subscribe to 4 sensors, window, classify, de-dup,
display counts-by-type + traffic light. No MAC or name ever downstream.

v3: aggregated features, co-hearing alignment, calibrated RSSI."""
import threading, time, collections, json, os, sys, joblib
import pandas as pd
import paho.mqtt.client as mqtt
from flask import Flask, jsonify, render_template

sys.path.insert(0, os.path.dirname(__file__))
from config import (MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS, TOPIC_RSSI,
                    TOPIC_RADAR, SENSORS,
                    WINDOW_S as CFG_WINDOW_S, THRESHOLD as CFG_THRESHOLD,
                    DWELL_IN_S, FORGET_S, VOTE_OF_N, FLASK_HOST, FLASK_PORT,
                    AGG_WINDOW_S, hash_mac)
from features import build_table, NOT_HEARD
from aggregation import build_aggregated_table
from env_features import build_env_table
from device_id import device_type, is_infra_candidate, InfraAllowlist
from dedup import RPADedup, count_nearby_devices
from adv_interval import AdvertisingIntervalEstimator
from baseline import BaselineCapture, BASELINE_PATH
from rssi_cal import calibrate_rssi, has_calibration, auto_calibrate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load model bundle; its saved threshold/window_s take precedence
bundle = joblib.load(os.path.join(ROOT, "models", "model.joblib"))
MODEL, COLS = bundle["model"], bundle["columns"]
WINDOW_S = bundle.get("window_s", CFG_WINDOW_S)
MODEL_VERSION = bundle.get("version", "v2")
FEATURE_TYPE = bundle.get("feature_type", "per_device")
USE_ENV = FEATURE_TYPE in ("environment", "environment_fused")
HAS_RADAR = bundle.get("has_radar", False)
USE_AGG = MODEL_VERSION == "v3" and not USE_ENV
MAPIE_MODEL = bundle.get("mapie")
MAPIE_ALPHA = bundle.get("mapie_alpha", 0.10)
BUFFER_S = WINDOW_S * 2 if USE_ENV else (AGG_WINDOW_S if USE_AGG else WINDOW_S * 2)
THRESH = CFG_THRESHOLD if os.getenv("SENTINEL_THRESH") else bundle.get("threshold", CFG_THRESHOLD)

# Load empty-room baseline (optional)
_baseline = BaselineCapture.load()
_baseline_stats = _baseline.stats if _baseline else None

# Infrastructure allowlist (hashed MACs)
_allow_path = os.path.join(ROOT, "data", "allowlist.json")
_preseeded = set(json.load(open(_allow_path))) if os.path.exists(_allow_path) else set()
infra = InfraAllowlist(_preseeded)

# Volatile state
buf = collections.deque()
radar_buf = collections.deque()
lock = threading.Lock()
dedup = RPADedup()
adv_estimator = AdvertisingIntervalEstimator()

# Per-device state for display stability (keyed by hashed mac)
# {hashed_mac: {first, last_in, category, votes: [bool], prob}}
_display = {}
_prob_history = {}  # mac -> smoothed probability (EMA across evaluations)
_type_cache = {}    # mac -> best known device type (specific beats generic)
_sensor_last_seen = {s: 0.0 for s in SENSORS}  # sensor -> last packet timestamp

# ---- MQTT ingest thread ----

def mqtt_thread():
    def on_message(client, userdata, msg):
        try:
            if msg.topic == TOPIC_RSSI:
                p = msg.payload.decode().split("|")
                # v3.1 format: source|mac|rssi|addrType|appearance|mfgHex|svcHex|rxMs|advType
                fields = (p + [""] * 9)[:9]
                source, mac, rssi_s, atype_s, appr_s, mfg, svc, rx_ms, advtype_s = fields
                rssi = int(rssi_s)
                addr_type = int(atype_s) if atype_s else 1
                appearance = int(appr_s) if appr_s and appr_s != "" else -1
                adv_type = int(advtype_s) if advtype_s else -1
                # Always use brain-arrival time for live buffering (satellite
                # SNTP clocks may drift). Training data uses its own timestamps.
                ts = time.time()
                mac_lower = mac.lower()
                with lock:
                    buf.append({
                        "ts": ts, "source": source, "mac": mac_lower,
                        "rssi": calibrate_rssi(rssi, source),
                        "addr_type": addr_type, "appearance": appearance,
                        "mfg_hex": mfg, "svc_hex": svc,
                        "adv_type": adv_type,
                    })
                adv_estimator.add_observation(mac_lower, source, ts)

            elif msg.topic == TOPIC_RADAR:
                p = msg.payload.decode().split("|")
                if len(p) < 15:
                    return
                ts = time.time()
                targets = []
                for i in range(3):
                    off = 3 + i * 4
                    d = int(p[off + 3])
                    if d > 0:
                        targets.append({
                            "x": int(p[off]), "y": int(p[off + 1]),
                            "spd": int(p[off + 2]), "dist": d,
                        })
                with lock:
                    radar_buf.append({
                        "ts": ts, "source": p[0],
                        "n_targets": int(p[2]), "targets": targets,
                    })
        except Exception:
            pass

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.subscribe(TOPIC_RSSI)
    if HAS_RADAR:
        client.subscribe(TOPIC_RADAR)
    client.loop_forever()

# ---- Classification + display ----

VOTE_K, VOTE_N = VOTE_OF_N  # need K of N votes to show
SENSOR_WARN_S = WINDOW_S * 2  # warn if no packets for 2 windows


def _sensor_health(now):
    """Return per-sensor health status."""
    status = {}
    for s in SENSORS:
        last = _sensor_last_seen.get(s, 0)
        age = now - last if last > 0 else float("inf")
        if age > SENSOR_WARN_S:
            status[s] = "offline"
        else:
            status[s] = "ok"
    return status


def evaluate():
    now = time.time()

    # Trim old data from buffer
    with lock:
        while buf and now - buf[0]["ts"] > BUFFER_S:
            buf.popleft()
        rows = list(buf)
        # Trim radar buffer
        while radar_buf and now - radar_buf[0]["ts"] > BUFFER_S:
            radar_buf.popleft()
        radar_rows = list(radar_buf) if HAS_RADAR else None

    if not rows:
        return {"level": "quiet", "counts": {}, "total": 0, "uncertain": 0,
                "room_prob": 0.0, "sensors": _sensor_health(now)}

    # Track per-sensor last-seen time
    for r in rows:
        src = r.get("source")
        if src and r["ts"] > _sensor_last_seen.get(src, 0):
            _sensor_last_seen[src] = r["ts"]

    # Build DataFrame from buffer
    df = pd.DataFrame([{"ts": r["ts"], "source": r["source"], "mac": r["mac"],
                        "rssi": r["rssi"], "phy": "btle"} for r in rows])

    if USE_ENV:
        # Environment-level: one prediction for the whole room
        return _evaluate_env(df, rows, now, radar_rows=radar_rows)
    else:
        # Per-device: prediction per MAC
        return _evaluate_per_device(df, rows, now)


def _evaluate_env(df, rows, now, radar_rows=None):
    """Environment-level inference: is someone inside based on overall BLE signature?"""
    X, meta = build_env_table(df, A=WINDOW_S, overlap=0.0,
                              radar_readings=radar_rows,
                              baseline_stats=_baseline_stats)
    if len(X) == 0:
        return {"level": "quiet", "counts": {}, "total": 0, "uncertain": 0,
                "room_prob": 0.0, "sensors": _sensor_health(now)}

    X = X.reindex(columns=COLS, fill_value=-120)
    prob = MODEL.predict_proba(X)[:, 1]
    room_prob = float(prob.mean())

    # Smooth across evaluations
    prev = _prob_history.get("__room__", room_prob)
    room_prob = 0.4 * room_prob + 0.6 * prev
    _prob_history["__room__"] = room_prob

    # MAPIE uncertainty for env path
    env_uncertain = False
    if MAPIE_MODEL is not None:
        try:
            _, pred_sets = MAPIE_MODEL.predict_set(X)
            # If any window has both classes in set, flag uncertain
            for i in range(len(pred_sets)):
                if pred_sets[i, :, 0].sum() > 1:
                    env_uncertain = True
                    break
        except Exception:
            pass

    occupied = room_prob >= THRESH

    if occupied:
        counts = count_nearby_devices(rows, infra_allowlist=infra,
                                          strong_thresh=-78)
        total = max(1, sum(counts.values())) if counts else 1
        level = "busy" if total >= 4 else "present"
    else:
        counts = {}
        total = 0
        level = "quiet"

    return {
        "level": level,
        "counts": counts,
        "total": total,
        "uncertain": 1 if env_uncertain else 0,
        "room_prob": round(room_prob, 3),
        "sensors": _sensor_health(now),
    }


def _evaluate_per_device(df, rows, now):
    """Per-device inference (legacy v2/v3 path)."""
    if USE_AGG:
        X, meta = build_aggregated_table(df, A=WINDOW_S, overlap=0.0)
    else:
        X, meta = build_table(df, window_s=WINDOW_S)
    X = X.reindex(columns=COLS, fill_value=NOT_HEARD)
    prob = MODEL.predict_proba(X)[:, 1]

    # MAPIE prediction sets for uncertainty (if available)
    _mapie_uncertain = set()  # indices with multi-class prediction sets
    if MAPIE_MODEL is not None:
        try:
            _, pred_sets = MAPIE_MODEL.predict_set(X)
            # pred_sets shape: (n_samples, n_classes, n_confidence_levels)
            for i in range(len(pred_sets)):
                set_size = pred_sets[i, :, 0].sum()
                if set_size > 1:  # both classes in prediction set
                    _mapie_uncertain.add(i)
        except Exception:
            pass  # fallback to margin-based uncertainty

    # Gather device metadata per mac (latest wins)
    meta_info = {}  # mac -> {addr_type, appearance, mfg_hex, svc_hex, rssi_vec}
    mac_rssi = collections.defaultdict(list)
    for r in rows:
        mac = r["mac"]
        mac_rssi[mac].append(r["rssi"])
        meta_info[mac] = {
            "addr_type": r.get("addr_type", 1),
            "appearance": r.get("appearance", -1),
            "mfg_hex": r.get("mfg_hex", ""),
            "svc_hex": r.get("svc_hex", ""),
        }

    # Map predictions to macs — average prob across windows (more stable)
    mac_probs = collections.defaultdict(list)
    mac_mapie_uncertain = set()  # macs with MAPIE multi-class sets
    for i in range(len(meta)):
        mac = meta.iloc[i]["mac"]
        mac_probs[mac].append(float(prob[i]))
        if i in _mapie_uncertain:
            mac_mapie_uncertain.add(mac)
    mac_best_prob = {mac: max(ps) for mac, ps in mac_probs.items()}

    # Smooth across evaluations: EMA of per-mac probability
    for mac, p in mac_best_prob.items():
        prev = _prob_history.get(mac, p)
        smoothed = 0.4 * p + 0.6 * prev
        _prob_history[mac] = smoothed
        mac_best_prob[mac] = smoothed

    inside_devices = {}   # mac -> category
    uncertain_macs = set()
    margin = 0.10  # fallback threshold margin for "uncertain" bucket

    for mac, p in mac_best_prob.items():
        # Skip infra
        h = hash_mac(mac)
        if infra.is_allowed(h):
            continue

        mi = meta_info.get(mac, {})

        # Uncertainty check: MAPIE prediction sets if available, else margin
        is_uncertain = (mac in mac_mapie_uncertain) if MAPIE_MODEL else (abs(p - THRESH) < margin)
        if is_uncertain:
            uncertain_macs.add(mac)
            continue

        if p >= THRESH:
            cat = device_type(
                mfg_hex=mi.get("mfg_hex", ""),
                svc_hex=mi.get("svc_hex", ""),
                appearance=mi.get("appearance", -1),
                addr_type=mi.get("addr_type", 1),
            )
            # Cache specific types; prefer cached specific over generic "phone"
            _GENERIC = {"phone", "unknown", "apple_device"}
            prev = _type_cache.get(mac)
            if prev and cat in _GENERIC and prev not in _GENERIC:
                cat = prev  # keep the specific type we saw before
            else:
                _type_cache[mac] = cat
            inside_devices[mac] = cat

            # Build per-sensor RSSI vector for spatial dedup
            mac_per_sensor = collections.defaultdict(list)
            for r in rows:
                if r["mac"] == mac:
                    mac_per_sensor[r["source"]].append(r["rssi"])
            rssi_vec = [
                (sum(mac_per_sensor[s]) / len(mac_per_sensor[s]))
                if s in mac_per_sensor else -120
                for s in SENSORS
            ]
            # Get advertising interval estimate for dedup
            interval_est = adv_estimator.estimate(mac)
            interval_ms = interval_est["interval_ms"] if interval_est else None
            dedup.update(mac, rssi_vec, cat, interval_ms=interval_ms)

    # De-dup: get category counts (no MAC exits this call)
    counts = dedup.get_counts(inside_devices)

    # Display stability: dwell-in + vote
    for mac, cat in inside_devices.items():
        h = hash_mac(mac)
        entry = _display.setdefault(h, {"first": now, "votes": [], "category": cat, "prob": 0})
        entry["last_in"] = now
        entry["category"] = cat
        entry["votes"].append(True)
        if len(entry["votes"]) > VOTE_N:
            entry["votes"] = entry["votes"][-VOTE_N:]

    # Expire old display entries
    for h in list(_display):
        if now - _display[h].get("last_in", 0) > FORGET_S:
            del _display[h]

    # Count only devices that pass dwell + vote
    shown_counts = {}
    for h, entry in _display.items():
        age = now - entry["first"]
        if age < DWELL_IN_S:
            continue
        votes_true = sum(entry["votes"][-VOTE_N:])
        if votes_true < VOTE_K:
            continue
        cat = entry["category"]
        shown_counts[cat] = shown_counts.get(cat, 0) + 1

    total = sum(shown_counts.values())
    level = "quiet" if total == 0 else ("busy" if total >= 4 else "present")

    return {
        "level": level,
        "counts": shown_counts,
        "total": total,
        "uncertain": len(uncertain_macs),
        "room_prob": 0.0,
        "sensors": _sensor_health(now),
    }


# ---- Flask app ----

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("census.html")


@app.route("/api/census")
def census():
    return jsonify(evaluate())


@app.route("/api/baseline", methods=["POST"])
def capture_baseline():
    """Capture empty-room baseline from current buffer (5+ min of data)."""
    global _baseline, _baseline_stats
    with lock:
        rows = list(buf)
    if len(rows) < 100:
        return jsonify({"error": "Not enough data in buffer. Wait 5+ minutes."}), 400

    df = pd.DataFrame([{"ts": r["ts"], "source": r["source"], "mac": r["mac"],
                        "rssi": r["rssi"]} for r in rows])
    bc = BaselineCapture()
    radar_rows = list(radar_buf) if HAS_RADAR else None
    bc.capture(df, A=WINDOW_S, radar_readings=radar_rows)
    bc.save()
    _baseline = bc
    _baseline_stats = bc.stats
    return jsonify({"status": "ok", "features": len(bc.stats)})


if __name__ == "__main__":
    # Auto-calibrate on first startup if no offsets exist
    if not has_calibration():
        print("No calibration found. Running auto-calibration (60s)...")
        auto_calibrate(duration=60)

    threading.Thread(target=mqtt_thread, daemon=True).start()
    mode = "env+radar" if USE_ENV and HAS_RADAR else ("env" if USE_ENV else ("agg" if USE_AGG else "legacy"))
    print(f"Room Sentinel v3 ({mode}) — thresh={THRESH:.2f} — {FLASK_HOST}:{FLASK_PORT}")
    app.run(host=FLASK_HOST, port=FLASK_PORT)
