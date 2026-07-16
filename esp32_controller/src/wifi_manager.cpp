#include "wifi_manager.h"
#include "config.h"
#include <WiFi.h>

void connectWiFi() {
  IPAddress staticIP(IP_THIS_ESP32);
  IPAddress gateway(IP_GATEWAY);
  IPAddress subnet(IP_SUBNET);
  IPAddress dns(IP_DNS);

  WiFi.config(staticIP, gateway, subnet, dns);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Connecting to ");
  Serial.println(WIFI_SSID);

  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries < 20) {
    delay(500);
    Serial.print(".");
    tries++;
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("WiFi Connected! IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("WiFi Failed!");
  }
}