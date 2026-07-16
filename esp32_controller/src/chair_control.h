#pragma once
#include <Arduino.h>

// أوضاع الكرسي
enum ChairMode { MODE_LECTURE, MODE_EXAM, MODE_GROUP };
enum ChairStatus { STATUS_IDLE, STATUS_MOVING, STATUS_DONE };

void initChair();
void calibrateGyro();
void moveToMode(String mode);
void setCurrentAngle(int angle);

// Getters
int         getCurrentAngle();
ChairStatus getChairStatus();
String      getCurrentMode();