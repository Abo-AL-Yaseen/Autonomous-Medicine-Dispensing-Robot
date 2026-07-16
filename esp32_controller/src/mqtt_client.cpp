#include "mqtt_client.h"
#include "chair_control.h"
#include "config.h"
#include <PubSubClient.h>
#include <WiFi.h>
#include <ArduinoJson.h>

static WiFiClient   wifiClient;
static PubSubClient mqttClient(wifiClient);
static bool         pendingMove  = false;
static String       pendingMode  = "";

// ─── استقبال أوامر ────────────────────────────────
static void onMessage(char* topic, byte* payload, unsigned int length) {
  String msg = "";
  for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];

  StaticJsonDocument<128> doc;
  if (deserializeJson(doc, msg)) return;

  // ← خذ الزاوية الحالية من السيرفر إذا موجودة
  if (doc.containsKey("currentAngle")) {
  setCurrentAngle(doc["currentAngle"].as<int>());
}

  if (doc.containsKey("mode")) {
    pendingMode = doc["mode"].as<String>();
    pendingMove = true;
  }
}

// ─── إعادة الاتصال ────────────────────────────────
static void reconnect() {
  int tries = 0;
  while (!mqttClient.connected() && tries < 5) {
    Serial.print("Connecting to MQTT...");
    if (mqttClient.connect(MQTT_CLIENT_ID)) {
      Serial.println("connected!");
      mqttClient.subscribe(TOPIC_CMD);
    } else {
      Serial.print("failed rc="); Serial.println(mqttClient.state());
      delay(2000);
      tries++;
    }
  }
}

// ─── تهيئة ───────────────────────────────────────
void initMQTT() {
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(onMessage);
  mqttClient.setKeepAlive(60);
  reconnect();
}

// ─── Loop ─────────────────────────────────────────
void mqttLoop() {
  if (!mqttClient.connected()) reconnect();
  mqttClient.loop();

  // تنفيذ الحركة خارج الـ callback عشان ما نعطل الـ MQTT
  if (pendingMove) {
    pendingMove = false;
    moveToMode(pendingMode);
    sendChairStatus();
  }
}

// ─── بعث حالة الكرسي ─────────────────────────────
void sendChairStatus() {
  if (!mqttClient.connected()) return;

  StaticJsonDocument<128> doc;
  doc["chairId"] = CHAIR_ID;
  doc["angle"]   = getCurrentAngle();
  doc["mode"]    = getCurrentMode();
  doc["status"]  = getChairStatus() == STATUS_MOVING ? "moving" :
                   getChairStatus() == STATUS_DONE   ? "done"   : "idle";

  String msg;
  serializeJson(doc, msg);
  mqttClient.publish(TOPIC_STATUS, msg.c_str());
  Serial.print("Status sent: "); Serial.println(msg);
}