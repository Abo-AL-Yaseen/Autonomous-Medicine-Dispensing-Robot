#pragma once
#include <IPAddress.h>

// Historical chair-controller configuration.
// This source is excluded by the current PlatformIO src_filter.
// Replace placeholders locally only if the legacy target is intentionally restored.

#define WIFI_SSID           "YOUR_WIFI_SSID"
#define WIFI_PASSWORD       "YOUR_WIFI_PASSWORD"

// RFC 5737 documentation-only network values.
#define IP_THIS_ESP32       192,0,2,105
#define IP_GATEWAY          192,0,2,1
#define IP_SUBNET           255,255,255,0
#define IP_DNS              192,0,2,1

#define MQTT_BROKER         "YOUR_MQTT_BROKER"
#define MQTT_PORT           1883
#define MQTT_CLIENT_ID      "esp32-red-chair"

#define TOPIC_CMD           "room/Room101/chair/red/command"
#define TOPIC_STATUS        "room/Room101/chair/red/status"

#define CHAIR_ID            "redChair"
#define CHAIR_SIDE          "red"
#define ROOM_ID             "Room101"

#define MOTOR1_PIN1         12
#define MOTOR1_PIN2         14
#define ENABLE1_PIN         13
#define MOTOR2_PIN1         27
#define MOTOR2_PIN2         26
#define ENABLE2_PIN         25

#define MOTOR_FREQ          30000
#define MOTOR_RESOLUTION    8
#define MOTOR_SPEED         240
#define GYRO_THRESHOLD      1.5

// Historical targets: lecture/exam = 0 degrees; group/red = 90 degrees.
