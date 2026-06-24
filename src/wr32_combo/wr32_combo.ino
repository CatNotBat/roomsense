/*
 * Room Sentinel v2 — BLE + LD2450 mmWave combo node
 * Flash to all 4 WR-32 boards, changing SENSOR_ID on each.
 *
 * Core 1 (Arduino default): WiFi + SNTP + MQTT + BLE scan
 * Core 0 (FreeRTOS task):   LD2450 UART reader + MQTT publish
 *
 * Publishes BLE to "sentinel/rssi" (v3.1 format — added advType field):
 *   SENSOR_ID|mac|rssi|addrType|appearance|mfgHex|svcHex|rxMs|advType
 *
 * Publishes radar to "sentinel/radar":
 *   SENSOR_ID|epochMs|nTargets|x0|y0|spd0|dist0|x1|y1|spd1|dist1|x2|y2|spd2|dist2
 *
 * LD2450 wiring: TX→GPIO16(RX2), RX→GPIO17(TX2), VCC→5V, GND→GND
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
#define SENSOR_ID "esp_c1"

// SNTP config
#define NTP_SERVER "pool.ntp.org"
#define SNTP_RESYNC_S 3600

// LD2450 UART config
#define RADAR_RX_PIN 16    // LD2450 TX → ESP32 GPIO16 (RX2)
#define RADAR_TX_PIN 17    // LD2450 RX → ESP32 GPIO17 (TX2)
#define RADAR_BAUD   256000

// LD2450 frame constants
#define LD2450_FRAME_LEN 30   // 4 header + 24 data + 2 tail
static const uint8_t LD2450_HEADER[] = {0xAA, 0xFF, 0x03, 0x00};
static const uint8_t LD2450_TAIL_0 = 0x55;
static const uint8_t LD2450_TAIL_1 = 0xCC;

// Shared objects
WiFiClient wc;
PubSubClient mq(wc);
BLEScan* pScan;
SemaphoreHandle_t mqMutex;

static volatile bool ntpSynced = false;

// ---------- Helpers ----------

static unsigned long long epochMs() {
  struct timeval tv;
  gettimeofday(&tv, NULL);
  return (unsigned long long)tv.tv_sec * 1000ULL + tv.tv_usec / 1000ULL;
}

void toHex(const uint8_t* src, int len, char* dst, int maxLen) {
  int j = 0;
  for (int i = 0; i < len && j + 2 < maxLen; i++) {
    sprintf(dst + j, "%02x", src[i]);
    j += 2;
  }
  dst[j] = '\0';
}

// Thread-safe MQTT publish (50ms mutex timeout — longer to prevent radar frame drops)
static bool safePub(const char* topic, const char* payload) {
  if (xSemaphoreTake(mqMutex, pdMS_TO_TICKS(50))) {
    bool ok = mq.publish(topic, payload);
    xSemaphoreGive(mqMutex);
    return ok;
  }
  return false;
}

// ---------- LD2450 radar task (Core 0) ----------

struct RadarTarget {
  int16_t  x_mm;
  int16_t  y_mm;
  int16_t  speed_mms;
  uint16_t dist_mm;
};

// Sign correction for LD2450 coordinates:
// Bit 15 is sign flag (1=negative), bits 14-0 are magnitude.
static int16_t ld2450_signed(uint16_t raw) {
  if (raw & 0x8000) return -(int16_t)(raw & 0x7FFF);
  return (int16_t)raw;
}

void radarTask(void* param) {
  Serial2.begin(RADAR_BAUD, SERIAL_8N1, RADAR_RX_PIN, RADAR_TX_PIN);

  uint8_t buf[LD2450_FRAME_LEN];
  int hdrPos = 0;  // header sync position
  int dataPos = 0; // data bytes collected after header

  for (;;) {
    while (Serial2.available()) {
      uint8_t b = Serial2.read();

      // Phase 1: sync to 4-byte header
      if (hdrPos < 4) {
        if (b == LD2450_HEADER[hdrPos]) {
          buf[hdrPos] = b;
          hdrPos++;
        } else {
          hdrPos = (b == LD2450_HEADER[0]) ? 1 : 0;
          if (hdrPos == 1) buf[0] = b;
        }
        continue;
      }

      // Phase 2: collect remaining 26 bytes (24 data + 2 tail)
      buf[4 + dataPos] = b;
      dataPos++;

      if (dataPos >= 26) {
        // Validate tail bytes
        if (buf[28] == LD2450_TAIL_0 && buf[29] == LD2450_TAIL_1) {
          // Parse 3 target slots
          RadarTarget targets[3];
          int nTargets = 0;

          for (int i = 0; i < 3; i++) {
            int off = 4 + i * 8;
            uint16_t raw_x    = buf[off]     | (buf[off + 1] << 8);
            uint16_t raw_y    = buf[off + 2] | (buf[off + 3] << 8);
            uint16_t raw_spd  = buf[off + 4] | (buf[off + 5] << 8);
            uint16_t raw_dist = buf[off + 6] | (buf[off + 7] << 8);

            targets[i].x_mm      = ld2450_signed(raw_x);
            targets[i].y_mm      = ld2450_signed(raw_y);
            targets[i].speed_mms = ld2450_signed(raw_spd);
            targets[i].dist_mm   = raw_dist;

            if (raw_dist > 0) nTargets = i + 1;
          }

          // Publish
          unsigned long long ms = epochMs();
          char payload[256];
          snprintf(payload, sizeof(payload),
            "%s|%llu|%d|%d|%d|%d|%u|%d|%d|%d|%u|%d|%d|%d|%u",
            SENSOR_ID, ms, nTargets,
            targets[0].x_mm, targets[0].y_mm,
            targets[0].speed_mms, targets[0].dist_mm,
            targets[1].x_mm, targets[1].y_mm,
            targets[1].speed_mms, targets[1].dist_mm,
            targets[2].x_mm, targets[2].y_mm,
            targets[2].speed_mms, targets[2].dist_mm);

          safePub("sentinel/radar", payload);
        }

        // Reset for next frame
        hdrPos = 0;
        dataPos = 0;
      }
    }

    vTaskDelay(1);  // yield to IDLE task / watchdog
  }
}

// ---------- BLE callbacks (Core 1) ----------

class SatelliteCallbacks : public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice d) override {
    if (!mq.connected()) return;

    unsigned long long rxMs = epochMs();

    String mac = d.getAddress().toString().c_str();
    int rssi = d.getRSSI();
    int addrType = d.getAddressType();

    int appearance = -1;
    if (d.haveAppearance()) {
      appearance = d.getAppearance();
    }

    String mfgHex = "";
    if (d.haveManufacturerData()) {
      String raw = d.getManufacturerData();
      int len = raw.length();
      if (len > 40) len = 40;
      char hexBuf[81];
      toHex((const uint8_t*)raw.c_str(), len, hexBuf, sizeof(hexBuf));
      mfgHex = hexBuf;
    }

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

    // ADV_IND=0, ADV_DIRECT_IND=1, ADV_SCAN_IND=2, ADV_NONCONN_IND=3, SCAN_RSP=4
    int advType = d.getAdvType();

    char buf[420];
    snprintf(buf, sizeof(buf), "%s|%s|%d|%d|%d|%s|%s|%llu|%d",
             SENSOR_ID, mac.c_str(), rssi, addrType,
             appearance, mfgHex.c_str(), svcHex.c_str(), rxMs, advType);
    safePub("sentinel/rssi", buf);
  }
};

// ---------- SNTP ----------

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

// ---------- MQTT reconnect ----------

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

// ---------- Setup & Loop ----------

void setup() {
  Serial.begin(115200);
  Serial.println("Sentinel v2 combo node booting...");

  mqMutex = xSemaphoreCreateMutex();

  // WiFi
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.printf("WiFi status: %d (try %d)\n", WiFi.status(), ++tries);
    if (tries > 30) { Serial.println("WiFi FAILED, restarting..."); ESP.restart(); }
  }
  Serial.printf("WiFi connected! IP: %s\n", WiFi.localIP().toString().c_str());

  // SNTP
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

  // Launch radar task on Core 0
  xTaskCreatePinnedToCore(radarTask, "radar", 4096, NULL, 1, NULL, 0);

  Serial.println("Setup complete — BLE scan + LD2450 radar active.");
}

void loop() {
  mqttReconnect();

  if (xSemaphoreTake(mqMutex, pdMS_TO_TICKS(10))) {
    mq.loop();
    xSemaphoreGive(mqMutex);
  }

  // BLE scan: 3s windows, results via callback
  pScan->start(3, false);
  pScan->clearResults();

  if (xSemaphoreTake(mqMutex, pdMS_TO_TICKS(10))) {
    mq.loop();
    xSemaphoreGive(mqMutex);
  }
}
