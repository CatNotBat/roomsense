/*
 * RoomSense v3 — BLE-only satellite sensor
 * Flash to all 4 boards, changing SENSOR_ID on each.
 *
 * Publishes to MQTT topic "roomsense/rssi" with pipe-delimited payload:
 *   SENSOR_ID|mac|rssi|addrType|appearance|mfgHex|svcHex|rxMs
 *
 * rxMs = epoch milliseconds at packet reception (SNTP-synced).
 * No Wi-Fi scanning (BLE-only during POC to avoid starving BLE scan time).
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <esp_sntp.h>
#include <time.h>
#include "secrets.h"

// *** CHANGE PER BOARD: esp_c1 / esp_c2 / esp_c3 / esp_c4 ***
#define SENSOR_ID "esp_c4"

// SNTP config
#define NTP_SERVER "pool.ntp.org"
#define SNTP_RESYNC_S 3600

WiFiClient wc;
PubSubClient mq(wc);
BLEScan* pScan;

// Time sync state
static volatile bool ntpSynced = false;

// Get epoch milliseconds using gettimeofday (SNTP-corrected wall clock)
static unsigned long long epochMs() {
  struct timeval tv;
  gettimeofday(&tv, NULL);
  return (unsigned long long)tv.tv_sec * 1000ULL + tv.tv_usec / 1000ULL;
}

// Convert raw bytes to lowercase hex string
void toHex(const uint8_t* src, int len, char* dst, int maxLen) {
  int j = 0;
  for (int i = 0; i < len && j + 2 < maxLen; i++) {
    sprintf(dst + j, "%02x", src[i]);
    j += 2;
  }
  dst[j] = '\0';
}

class SatelliteCallbacks : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice d) override {
    if (!mq.connected()) return;

    // RX timestamp (epoch ms, SNTP-synced)
    unsigned long long rxMs = epochMs();

    // MAC + RSSI
    String mac = d.getAddress().toString().c_str();
    int rssi = d.getRSSI();
    int addrType = d.getAddressType();

    // Appearance (-1 if absent)
    int appearance = -1;
    if (d.haveAppearance()) {
      appearance = d.getAppearance();
    }

    // Manufacturer data (AD type 0xFF) as full hex (includes company ID bytes)
    String mfgHex = "";
    if (d.haveManufacturerData()) {
      String raw = d.getManufacturerData();
      int len = raw.length();
      if (len > 40) len = 40;  // cap at 40 bytes = 80 hex chars
      char hexBuf[81];
      toHex((const uint8_t*)raw.c_str(), len, hexBuf, sizeof(hexBuf));
      mfgHex = hexBuf;
    }

    // Service data (AD type 0x16) as hex (includes UUID bytes)
    String svcHex = "";
    if (d.getServiceDataCount() > 0) {
      String sd = d.getServiceData(0);
      BLEUUID sdUuid = d.getServiceDataUUID(0);
      String uuidStr = sdUuid.toString();
      int len = sd.length();
      if (len > 32) len = 32;
      char hexBuf[65];
      toHex((const uint8_t*)sd.c_str(), len, hexBuf, sizeof(hexBuf));
      // For 16-bit UUIDs, extract the short form
      String uuidHex = "";
      if (uuidStr.length() == 4) {
        uuidHex = uuidStr;
      } else if (uuidStr.length() >= 8) {
        uuidHex = uuidStr.substring(4, 8);
      }
      svcHex = uuidHex + String(hexBuf);
    }

    // Pipe-delimited payload: SENSOR_ID|mac|rssi|addrType|appearance|mfgHex|svcHex|rxMs
    char buf[420];
    snprintf(buf, sizeof(buf), "%s|%s|%d|%d|%d|%s|%s|%llu",
             SENSOR_ID, mac.c_str(), rssi, addrType,
             appearance, mfgHex.c_str(), svcHex.c_str(), rxMs);
    mq.publish("roomsense/rssi", buf);
  }
};

void sntpInit() {
  esp_sntp_setoperatingmode(ESP_SNTP_OPMODE_POLL);
  esp_sntp_setservername(0, NTP_SERVER);
  esp_sntp_init();

  // Wait up to 10s for initial sync
  Serial.print("SNTP sync");
  int tries = 0;
  time_t now = 0;
  while (now < 1700000000 && tries < 20) {  // epoch > ~2023
    delay(500);
    time(&now);
    Serial.print(".");
    tries++;
  }
  if (now >= 1700000000) {
    ntpSynced = true;
    Serial.printf(" OK (epoch=%ld)\n", (long)now);
  } else {
    Serial.println(" FAILED — timestamps will be boot-relative");
  }
}

void setup() {
  Serial.begin(115200);
  Serial.println("RoomSense satellite v3 booting...");

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.printf("WiFi status: %d (try %d)\n", WiFi.status(), ++tries);
    if (tries > 30) { Serial.println("WiFi FAILED, restarting..."); ESP.restart(); }
  }
  Serial.printf("WiFi connected! IP: %s\n", WiFi.localIP().toString().c_str());

  // SNTP time sync (before MQTT, after WiFi)
  sntpInit();

  // MQTT
  mq.setServer(MQTT_HOST, 1883);
  mq.setBufferSize(512);  // enriched payloads can exceed default 256
  if (strlen(MQTT_USER) > 0) {
    Serial.println("MQTT auth enabled");
  }

  // BLE init — ~99% duty continuous scan
  BLEDevice::init("");
  pScan = BLEDevice::getScan();
  pScan->setAdvertisedDeviceCallbacks(new SatelliteCallbacks(), true);
  pScan->setActiveScan(true);
  pScan->setInterval(100);   // 62.5 ms
  pScan->setWindow(99);      // ~99% duty

  Serial.println("Setup complete — continuous BLE scan starting.");
}

void mqttReconnect() {
  if (mq.connected()) return;
  Serial.println("MQTT connecting...");
  bool ok;
  if (strlen(MQTT_USER) > 0) {
    ok = mq.connect(SENSOR_ID, MQTT_USER, MQTT_PASS);
  } else {
    ok = mq.connect(SENSOR_ID);
  }
  if (ok) Serial.println("MQTT connected!");
  else { Serial.printf("MQTT failed, rc=%d\n", mq.state()); delay(2000); }
}

void loop() {
  mqttReconnect();
  mq.loop();

  // BLE scan: 3s windows, results via callback
  pScan->start(3, false);
  pScan->clearResults();
  mq.loop();
}
