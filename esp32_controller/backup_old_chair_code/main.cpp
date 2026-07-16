#include <Arduino.h>
#include "config.h"
#include "wifi_manager.h"
#include "chair_control.h"
#include "mqtt_client.h"

void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println("=== Red Chair Module ===");

  connectWiFi();
  initChair();
  calibrateGyro();
  initMQTT();

  // بعث الحالة الأولية
  sendChairStatus();

  Serial.println("Red Chair Ready! Waiting for commands...");
}

void loop() {

  mqttLoop();
}
