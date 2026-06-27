#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEServer.h>
#include <BLEAdvertising.h>
#include <esp_bt.h>

// Advertises a CONSTANT name (filterable) while CYCLING transmit power,
// so the classifier learns not to depend on absolute signal strength.
esp_power_level_t LEVELS[] = {ESP_PWR_LVL_N12, ESP_PWR_LVL_N3,
                              ESP_PWR_LVL_P3,  ESP_PWR_LVL_P9};
const int N_LEVELS = 4;
int idx = 0;

void setup() {
  BLEDevice::init("ROOMSENSE_BEACON");
  BLEAdvertising *adv = BLEDevice::getAdvertising();
  adv->setMinInterval(0x20);   // ~20 ms - advertise often for dense RSSI samples
  adv->setMaxInterval(0x30);
  adv->start();
}

void loop() {
  BLEDevice::setPower(LEVELS[idx], ESP_BLE_PWR_TYPE_ADV);
  idx = (idx + 1) % N_LEVELS;
  delay(2000);                 // hold each power level ~2 s
}
