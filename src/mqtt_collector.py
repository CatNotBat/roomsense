#!/usr/bin/env python3
"""Collect ESP32 satellite RSSI reports via MQTT -> data/readings_raw.csv.
v3: pipe-delimited payload (8 fields with rx_ms), calibrated RSSI, paho 2.x compat."""
import csv, os, time, signal, sys
import paho.mqtt.client as mqtt
sys.path.insert(0, os.path.dirname(__file__))
from config import (MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS, TOPIC_RSSI,
                    HASH_ON_DISK, hash_mac, RAW_CSV_MAX_MB)
from rssi_cal import calibrate_rssi

OUT = "data/readings_raw.csv"
os.makedirs("data", exist_ok=True)
COLS = ["ts", "source", "mac", "rssi", "phy", "name",
        "addr_type", "appearance", "mfg_hex", "svc_hex", "rx_ms"]

# Rotate if oversized
if os.path.exists(OUT) and os.path.getsize(OUT) > RAW_CSV_MAX_MB * 1e6:
    os.rename(OUT, f"data/readings_raw.{int(time.time())}.csv")

new = not os.path.exists(OUT)
f = open(OUT, "a", newline="")
w = csv.writer(f)
if new:
    w.writerow(COLS)

skips = 0

def on_message(client, userdata, msg):
    global skips
    try:
        p = msg.payload.decode().split("|")
        # v3 format: source|mac|rssi|addrType|appearance|mfgHex|svcHex|rxMs
        fields = (p + [""] * 8)[:8]
        source, mac, rssi, atype, appr, mfg, svc, rx_ms = fields
        out_mac = hash_mac(mac) if HASH_ON_DISK else mac
        rssi_cal = calibrate_rssi(int(rssi), source)
        # Use satellite RX timestamp if available, else brain-arrival
        ts = f"{int(rx_ms) / 1000.0:.3f}" if rx_ms else f"{time.time():.3f}"
        w.writerow([ts, source, out_mac, rssi_cal, "btle", "",
                    atype, appr, mfg, svc, rx_ms])
        f.flush()
    except Exception as e:
        skips += 1
        if skips % 50 == 1:
            print(f"skip#{skips}: {msg.payload!r} {e}", file=sys.stderr)

def bye(*_):
    f.flush(); f.close(); print("\nStopped."); sys.exit(0)

signal.signal(signal.SIGINT, bye)

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
if MQTT_USER:
    client.username_pw_set(MQTT_USER, MQTT_PASS)
client.on_message = on_message
client.connect(MQTT_HOST, MQTT_PORT, 60)
client.subscribe(TOPIC_RSSI)
print(f"Collecting -> {OUT}. Ctrl-C to stop.")
client.loop_forever()
