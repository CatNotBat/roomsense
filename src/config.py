"""All tunables in one place. Import from here; never redefine elsewhere."""
import os, hashlib

# windowing / model
WINDOW_S   = int(os.getenv("SENTINEL_WINDOW_S", "2"))
ARGMAX_STABILITY_S = int(os.getenv("SENTINEL_STAB_S", "10"))
THRESHOLD  = float(os.getenv("SENTINEL_THRESH", "0.5"))

# the 4 sensors (homogeneous array). Brain is NOT in this list.
SENSORS = os.getenv("SENTINEL_SENSORS", "esp_c1,esp_c2,esp_c3,esp_c4").split(",")

# calibration
BEACON_MAC = os.getenv("SENTINEL_BEACON_MAC", "").lower()

# co-hearing alignment
COHEARING_W_MS = int(os.getenv("SENTINEL_COHEARING_W_MS", "200"))

# aggregation
AGG_WINDOW_S = int(os.getenv("SENTINEL_AGG_WINDOW_S", "20"))
AGG_OVERLAP  = float(os.getenv("SENTINEL_AGG_OVERLAP", "0.5"))

# reference node (sensor placed outside room, if any)
REFERENCE_SENSOR = os.getenv("SENTINEL_REFERENCE_SENSOR", "")

# live UI smoothing
DWELL_IN_S = int(os.getenv("SENTINEL_DWELL_S", "20"))
FORGET_S   = int(os.getenv("SENTINEL_FORGET_S", "8"))
VOTE_OF_N  = (3, 5)   # 3-of-5 voting window for display stability

# MQTT
MQTT_HOST  = os.getenv("SENTINEL_MQTT_HOST", "localhost")
MQTT_PORT  = int(os.getenv("SENTINEL_MQTT_PORT", "1883"))
MQTT_USER  = os.getenv("SENTINEL_MQTT_USER", "")
MQTT_PASS  = os.getenv("SENTINEL_MQTT_PASS", "")
TOPIC_RSSI = "sentinel/rssi"
TOPIC_RADAR = "sentinel/radar"
TOPIC_PRESENCE = "sentinel/presence"
RADAR_MAX_TARGETS = 3

# web
FLASK_HOST = os.getenv("SENTINEL_FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.getenv("SENTINEL_FLASK_PORT", "8080"))

# privacy
HASH_SALT  = os.getenv("SENTINEL_SALT", "sentinel_allowlist_v1")
HASH_ON_DISK   = os.getenv("SENTINEL_HASH_ON_DISK", "true").lower() == "true"
RAW_CSV_MAX_MB = int(os.getenv("SENTINEL_RAW_CSV_MAX_MB", "200"))
RPA_TTL_S      = int(os.getenv("SENTINEL_RPA_TTL_S", "60"))

def hash_mac(mac: str) -> str:
    return hashlib.sha256((mac + HASH_SALT).encode()).hexdigest()[:12]
