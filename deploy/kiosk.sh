#!/usr/bin/env bash
# Launch dashboard in fullscreen kiosk mode on the RPi's display.
# Add to ~/.config/autostart/ or call from /etc/xdg/autostart/ for boot-on-screen.
#
# Requires: chromium-browser (pre-installed on Raspberry Pi OS)

# Wait for the roomsense service to be ready
sleep 5

# Hide mouse cursor after 3s idle
unclutter -idle 3 &

# Disable screen blanking
xset s off
xset -dpms
xset s noblank

# Launch Chromium in kiosk mode
chromium-browser \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --incognito \
    "http://localhost:8080"
