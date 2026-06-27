/*
 * RoomSense v3 — BLE-only satellite sensor (Seeed XIAO ESP32-S3 variant)
 *
 * Functionally identical to esp32_satellite.ino.
 * Differences: onboard RGB LED on GPIO 21 for status, USB-C native.
 *
 * Board setup in Arduino IDE / arduino-cli:
 *   Board manager URL: https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
 *   Board: "XIAO_ESP32S3"
 *
 * Compile:
 *   arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3
 *
 * Flash:
 *   arduino-cli upload --fqbn esp32:esp32:XIAO_ESP32S3 -p /dev/ttyACM0
 *
 * Publishes to MQTT topic "roomsense/rssi" with pipe-delimited payload:
 *   SENSOR_ID|mac|rssi|addrType|appearance|mfgHex|svcHex|rxMs
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
#define SENSOR_ID "esp_c2"

// Status LED (XIAO ESP32-S3 onboard RGB is on GPIO 21)
#define LED_PIN 21

// SNTP config
#define NTP_SERVER "pool.ntp.org"
#define SNTP_RESYNC_S 3600

WiFiClient wc;
PubSubClient mq(wc);
BLEScan* pScan;

static volatile bool ntpSynced = false;

void ledOn()  { digitalWrite(LED_PIN, LOW);  }  // active-low on XIAO
void ledOff() { digitalWrite(LED_PIN, HIGH); }

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
      if (len > 40) len = 40;
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

  Serial.print("SNTP sync");
  int tries = 0;
  time_t now = 0;
  while (now < 1700000000 && tries < 20) {
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
  pinMode(LED_PIN, OUTPUT);
  ledOn();

  Serial.println("Sentinel satellite v3 (XIAO S3) booting...");

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
  mq.setBufferSize(512);
  if (strlen(MQTT_USER) > 0) {
    Serial.println("MQTT auth enabled");
  }

  // BLE init — ~99% duty continuous scan
  BLEDevice::init("");
  pScan = BLEDevice::getScan();
  pScan->setAdvertisedDeviceCallbacks(new SatelliteCallbacks(), true);
  pScan->setActiveScan(true);
  pScan->setInterval(100);
  pScan->setWindow(99);

  ledOff();
  Serial.println("Setup complete — continuous BLE scan starting.");
}

void mqttReconnect() {
  if (mq.connected()) return;
  ledOn();
  Serial.println("MQTT connecting...");
  bool ok;
  if (strlen(MQTT_USER) > 0) {
    ok = mq.connect(SENSOR_ID, MQTT_USER, MQTT_PASS);
  } else {
    ok = mq.connect(SENSOR_ID);
  }
  if (ok) { Serial.println("MQTT connected!"); ledOff(); }
  else { Serial.printf("MQTT failed, rc=%d\n", mq.state()); delay(2000); }
}

void loop() {
  mqttReconnect();
  mq.loop();

  pScan->start(3, false);
  pScan->clearResults();
  mq.loop();
}
