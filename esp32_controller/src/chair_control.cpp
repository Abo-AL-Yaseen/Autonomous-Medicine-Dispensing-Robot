#include "chair_control.h"
#include "config.h"
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <Wire.h>

Adafruit_MPU6050 mpu;

static float       gyroBiasX    = 0;
static int         currentAngle = 0;
static ChairStatus chairStatus  = STATUS_IDLE;
static String      currentMode  = "lecture";

void setCurrentAngle(int angle) {
  currentAngle = angle;
  Serial.print("Angle set to: "); Serial.println(angle);
}

// ─── حساب الزاوية المطلوبة حسب المود ────────────
static int getTargetAngle(String mode) {
  if (mode == "lecture" || mode == "exam") return 0;
  if (mode == "group") return 90;   // red → 90°
  return 0;
}

// ─── حساب أقصر مسار للدوران ─────────────────────
static int calculateDelta(int from, int to) {
  int diff = to - from;
  if (diff >  180) diff -= 360;
  if (diff < -180) diff += 360;
  return diff;
}

// ─── إيقاف الموتورات ─────────────────────────────
static void stopMotors() {
  digitalWrite(MOTOR1_PIN1, LOW);
  digitalWrite(MOTOR1_PIN2, LOW);
  digitalWrite(MOTOR2_PIN1, LOW);
  digitalWrite(MOTOR2_PIN2, LOW);
  ledcWrite(0, 0);
  ledcWrite(1, 0);
}

// ─── دوران ذكي باستخدام MPU6050 ──────────────────
static void rotateSmart(int angle) {
  if (angle == 0) return;

  float rotated = 0;
  float target  = abs(angle);
  unsigned long lastTime = millis();

  Serial.print("Rotating "); Serial.print(angle); Serial.println(" degrees...");

  if (angle > 0) {
    // عكس عقارب الساعة
    digitalWrite(MOTOR1_PIN1, LOW);  digitalWrite(MOTOR1_PIN2, HIGH);
    digitalWrite(MOTOR2_PIN1, HIGH); digitalWrite(MOTOR2_PIN2, LOW);
  } else {
    // مع عقارب الساعة
    digitalWrite(MOTOR1_PIN1, HIGH); digitalWrite(MOTOR1_PIN2, LOW);
    digitalWrite(MOTOR2_PIN1, LOW);  digitalWrite(MOTOR2_PIN2, HIGH);
  }

  ledcWrite(0, MOTOR_SPEED);
  ledcWrite(1, MOTOR_SPEED);

  while (rotated < target) {
    sensors_event_t a, g, temp;
    mpu.getEvent(&a, &g, &temp);

    unsigned long now = millis();
    float dt = (now - lastTime) / 1000.0;
    lastTime = now;

    float speed = (g.gyro.x - gyroBiasX) * (180.0 / PI);
    if (abs(speed) > GYRO_THRESHOLD) {
      rotated += abs(speed) * dt;
    }

    Serial.print("Rotated: "); Serial.println(rotated);
    delay(10);
  }

  stopMotors();
  Serial.println("Rotation done!");
}

// ─── تهيئة ───────────────────────────────────────
void initChair() {
  pinMode(MOTOR1_PIN1, OUTPUT);
  pinMode(MOTOR1_PIN2, OUTPUT);
  pinMode(MOTOR2_PIN1, OUTPUT);
  pinMode(MOTOR2_PIN2, OUTPUT);
  ledcSetup(0, MOTOR_FREQ, MOTOR_RESOLUTION);
  ledcAttachPin(ENABLE1_PIN, 0);
  ledcSetup(1, MOTOR_FREQ, MOTOR_RESOLUTION);
  ledcAttachPin(ENABLE2_PIN, 1);

  stopMotors();

  Wire.begin();
  if (!mpu.begin()) {
    Serial.println("MPU6050 not found!");
    while (1) delay(10);
  }

  Serial.println("Chair hardware initialized!");
}

// ─── معايرة الـ Gyro ──────────────────────────────
void calibrateGyro() {
  Serial.println("Calibrating... Keep chair STILL!");
  float sum = 0;
  for (int i = 0; i < 300; i++) {
    sensors_event_t a, g, temp;
    mpu.getEvent(&a, &g, &temp);
    sum += g.gyro.x;
    delay(5);
  }
  gyroBiasX = sum / 300.0;
  Serial.print("Calibration done. Offset: ");
  Serial.println(gyroBiasX);
}

// ─── تحريك الكرسي للمود المطلوب ──────────────────
void moveToMode(String mode) {
  int targetAngle = getTargetAngle(mode);
  int delta       = calculateDelta(currentAngle, targetAngle);

  Serial.print("Mode: ");          Serial.println(mode);
  Serial.print("Current angle: "); Serial.println(currentAngle);
  Serial.print("Target angle: ");  Serial.println(targetAngle);
  Serial.print("Delta: ");         Serial.println(delta);

  if (delta == 0) {
    Serial.println("Already at target!");
    chairStatus = STATUS_DONE;
    currentMode = mode;
    return;
  }

  chairStatus = STATUS_MOVING;

  if (mode == "group" && currentMode == "lecture") {
    // قادم من exam → بس لف 90 يسار بدون delay
    rotateSmart(-90);
    delay(3000);  } else {
    // قادم من lecture → نفس السلوك مع delay
    delay(3000);
    rotateSmart(delta);
  }

  if (mode == "group" && currentMode == "exam") {
    // قادم من exam → بس لف 90 يسار بدون delay
    rotateSmart(90);
  } else {
    // قادم من lecture → نفس السلوك مع delay
    delay(3000);
    rotateSmart(delta);
  }

 if (mode == "lecture" && currentMode == "exam") {
    // قادم من exam → بس لف 90 يسار بدون delay
   // rotateSmart(90);
  } else {
    // قادم من lecture → نفس السلوك مع delay
    rotateSmart(90);
    delay(3000);
    rotateSmart(delta);
  }

  currentAngle = targetAngle;
  currentMode  = mode;
  chairStatus  = STATUS_DONE;

  Serial.println("Chair reached target position!");
}

// ─── Getters ─────────────────────────────────────
int         getCurrentAngle()  { return currentAngle; }
ChairStatus getChairStatus()   { return chairStatus;  }
String      getCurrentMode()   { return currentMode;  }