#!/usr/bin/env bash
# Room Sentinel — RPi 4B setup script
# Run as root: sudo bash deploy/setup-rpi.sh
set -euo pipefail

INSTALL_DIR="/opt/room-sentinel"
SERVICE_USER="sentinel"

echo "=== Room Sentinel RPi Setup ==="

# 1. System packages
echo "[1/6] Installing system packages..."
apt-get update -qq
apt-get install -y -qq mosquitto mosquitto-clients python3 python3-venv

# 2. Enable and start Mosquitto
echo "[2/6] Configuring Mosquitto..."
cp "$INSTALL_DIR/mosquitto_local.conf" /etc/mosquitto/conf.d/room-sentinel.conf
systemctl enable mosquitto
systemctl restart mosquitto

# 3. Create service user (no login shell)
echo "[3/6] Creating service user..."
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# 4. Python venv + deps
echo "[4/6] Setting up Python environment..."
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

# 5. Fix ownership
echo "[5/6] Setting permissions..."
chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"

# 6. Install and start service
echo "[6/6] Installing systemd service..."
cp "$INSTALL_DIR/deploy/room-sentinel.service" /etc/systemd/system/
cp "$INSTALL_DIR/deploy/room-sentinel.env" /etc/room-sentinel.env
systemctl daemon-reload
systemctl enable room-sentinel

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Copy your trained model to $INSTALL_DIR/models/model.joblib"
echo "  2. Start the service:  sudo systemctl start room-sentinel"
echo "  3. Check status:       sudo systemctl status room-sentinel"
echo "  4. View logs:          journalctl -u room-sentinel -f"
echo "  5. Open dashboard:     http://$(hostname -I | awk '{print $1}'):8080"
echo ""
echo "To update firmware MQTT_SERVER on your ESP32 nodes,"
echo "point them to this RPi's IP: $(hostname -I | awk '{print $1}')"
