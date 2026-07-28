/*
  ════════════════════════════════════════════════════════════
  motor_test.ino
  ملف تيست مستقل لموتورات الكرسي - بناءً على config.h تبعك
  بيجرب: قدام / خلف / لف يمين / لف يسار (بزاوية دقيقة عن طريق MPU6050)
         / حركة يمين ويسار (strafe مركّبة)

  ⚠️ ملاحظة مهمة:
  الشاسي عندك Differential Drive (موتورين فقط، يمين وشمال).
  هاد التصميم فيزيائياً ما بيقدر يتحرك "يمين/يسار" مباشرة (مثل
  Mecanum أو Omni wheels). "يمين/يسار" هون معناها لف 90 درجة
  + قدام + لف رجوع، يعني حركة مركّبة مش حركة طبيعية حقيقية.

  ⚠️ مهم جداً عند الرفع:
  لازم الكرسي يكون ثابت تماماً وقت ما يشتغل (مرحلة المعايرة 300
  قراءة بالبداية). إذا تحرك أثناء المعايرة، الـ gyroBiasX رح يكون
  غلط وكل الزوايا بعدها رح تنحرف.

  رفع الكود: افصل الموتورات شوي عن الأرض أول مرة (الكرسي معلّق)
  للتأكد إنه الاتجاهات صحيحة قبل ما تجربه على الأرض فعلياً.
  ════════════════════════════════════════════════════════════
*/

#include <Arduino.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <ThreeWire.h>
#include <RtcDS1302.h>
#include <Wire.h>
#include <hd44780.h>
#include <hd44780ioClass/hd44780_I2Cexp.h>

Adafruit_MPU6050 mpu;

// I2C LCD on the same Wire bus as the MPU6050. Scanner confirmed 0x27.
const uint8_t LCD_ADDRESS = 0x27;
const uint8_t LCD_COLS = 20;
const uint8_t LCD_ROWS = 4;
hd44780_I2Cexp lcd(LCD_ADDRESS);
static bool lcdReady = false;

// ─── نفس البنّات من config.h تبعك ────────────────
#define MOTOR1_PIN1         12
#define MOTOR1_PIN2         14
#define ENABLE1_PIN         13
#define MOTOR2_PIN1         27
#define MOTOR2_PIN2         26
#define ENABLE2_PIN         25
#define PUMP_PIN            23
#define MOTOR1_PWM_CHANNEL   0
#define MOTOR2_PWM_CHANNEL   1

const int ULTRASONIC_TRIG_PIN = 18;
const int ULTRASONIC_ECHO_PIN = 34;
const unsigned long ULTRASONIC_TIMEOUT_US = 30000;
const int IR_SENSOR_PIN = 16;
const int IR_DETECTED_LEVEL = LOW;
const unsigned long IR_DEBOUNCE_MS = 100;
const int LINE_OUT1_PIN = 35;
const int LINE_OUT2_PIN = 36;
const int LINE_OUT3_PIN = 39;
const int LINE_OUT4_PIN = 17;
const int LINE_OUT5_PIN = 4;
const unsigned long LINE_SAMPLE_INTERVAL_MS = 20;
const unsigned long LINE_STABLE_DURATION_MS = 50;

// MH Real Time Clock Module 2 / DS1302-style 3-wire RTC wiring:
// VCC -> ESP32 3V3, GND -> GND, CLK -> GPIO33, DAT -> GPIO32, RST -> GPIO19.
const int RTC_CLK_PIN = 33;
const int RTC_DAT_PIN = 32;
const int RTC_RST_PIN = 19;
const unsigned long RTC_PRINT_INTERVAL_MS = 1000;

ThreeWire rtcWire(RTC_DAT_PIN, RTC_CLK_PIN, RTC_RST_PIN); // IO, SCLK, CE
RtcDS1302<ThreeWire> rtc(rtcWire);
static unsigned long lastRTCPrintMs = 0;

// غيّرها إلى false فقط إذا كان Relay يعمل بمستوى HIGH.
const bool PUMP_ACTIVE_LOW = true;

// ─── نفس إعدادات الموتور ──────────────────────────
#define MOTOR_FREQ          30000
#define MOTOR_RESOLUTION    8
#define DRIVE_SPEED         240    // سرعة القيادة للأمام والخلف
#define TURN_SPEED          240    // سرعة الدوران الجيروسكوبي يمينًا ويسارًا
#define GYRO_THRESHOLD       1.5   // تجاهل ضجيج الـ gyro
#define ROTATION_TIMEOUT_MS 10000  // حد أمان أقصى لأي دوران
#define ROTATION_PRINT_MS    200   // تقليل رسائل Serial أثناء الدوران
#define PUMP_RUN_MS          2000   // مدة اختبار المضخة بالأمر P

// ─── مدة كل حركة بالتيست (ms) ─────────────────────
#define TEST_MOVE_MS        1000   // مدة المشي قدام/خلف
#define PAUSE_MS             800   // وقفة بين كل حركة وحركة

// ─── متغيرات الجيروسكوب ───────────────────────────
static float gyroBiasX = 0;

const float OBSTACLE_DISTANCE_CM = 25.0f;
const uint8_t AUTO_FORWARD_SPEED = 230;
const uint8_t AUTO_REVERSE_SPEED = 210;
const uint8_t AUTO_TURN_SPEED = 220;
const unsigned long REVERSE_DURATION_MS = 500;
const unsigned long TURN_DURATION_MS = 750;
const unsigned long AUTO_STOP_DURATION_MS = 200;
const unsigned long SENSOR_INTERVAL_MS = 100;
const unsigned long SENSOR_RETRY_INTERVAL_MS = 150;
const unsigned long DISTANCE_PRINT_INTERVAL_MS = 400;
const uint8_t MAX_ULTRASONIC_FAILED_READS = 20;

enum AutoState {
  AUTO_DISABLED,
  AUTO_FORWARD,
  AUTO_STOP_BEFORE_REVERSE,
  AUTO_REVERSE,
  AUTO_STOP_BEFORE_TURN,
  AUTO_TURN_LEFT,
  AUTO_TURN_RIGHT,
  AUTO_STOP_AFTER_TURN,
  AUTO_SENSOR_RETRY
};

static bool autoModeEnabled = false;
static AutoState autoState = AUTO_DISABLED;
static unsigned long autoStateStartedMs = 0;
static unsigned long lastAutoSensorMs = 0;
static unsigned long lastAutoDistancePrintMs = 0;
static uint8_t consecutiveObstacleReadings = 0;
static uint8_t failedUltrasonicReadings = 0;
static bool nextAutoTurnRight = true;
static float lastAutoDistanceCm = -1.0f;

static bool irCurrentRawDetected = false;
static bool irLastRawDetected = false;
static bool irStableDetected = false;
static bool irDetectionLatched = false;
static unsigned long irDebounceStartedMs = 0;

static uint8_t lineCandidatePattern = 0;
static uint8_t lineStablePattern = 0;
static unsigned long lastLineSampleMs = 0;
static unsigned long lineCandidateStartedMs = 0;
static bool lineStablePatternReady = false;

const size_t SERIAL_COMMAND_BUFFER_SIZE = 64;
const unsigned long SERIAL_PENDING_P_TIMEOUT_MS = 125;
static char serialCommandBuffer[SERIAL_COMMAND_BUFFER_SIZE];
static size_t serialCommandLength = 0;
static bool serialCommandOverflow = false;
static bool serialTextMode = false;
static bool serialPendingP = false;
static unsigned long serialPendingPStartedMs = 0;

enum SerialInputResult {
  SERIAL_INPUT_INCOMPLETE,
  SERIAL_INPUT_LEGACY_READY,
  SERIAL_INPUT_LINE_READY,
  SERIAL_INPUT_OVERFLOW
};

void stopMotors();
void pumpOn();
void pumpOff();
void stopAllOutputs();
void setupUltrasonic();
float readUltrasonicCm();
void testUltrasonicOnce();
void updateIrSensor();
uint8_t readLineSensorPattern();
void updateLineSensorTest();
void setupRTC();
void printRTC();
void setupLCD();
void lcdShowStatus(String line1, String line2 = "", String line3 = "", String line4 = "");
void lcdShowReady();
void lcdShowError(String message);
void showRTCOnce();
void startAutonomousMode();
void stopAutonomousMode(const char* reason, char command);
void updateAutonomousMode();
void handleLegacyCommand(char command);
void handleTextCommand(const String& command);
static bool isLegacyCommand(char command);

// Hardware keys execute immediately. Text commands remain newline-terminated,
// while P is held briefly so a fast PING line is not mistaken for the pump key.
static SerialInputResult readSerialInput(char& legacyCommand, String& line) {
  while (Serial.available() > 0) {
    char incoming = (char)Serial.read();

    if (serialCommandOverflow) {
      if (incoming == '\n') {
        serialCommandLength = 0;
        serialCommandBuffer[0] = '\0';
        serialCommandOverflow = false;
        serialTextMode = false;
        return SERIAL_INPUT_OVERFLOW;
      }
      continue;
    }

    if (serialTextMode) {
      if (incoming == '\r') {
        continue;
      }

      if (incoming == '\n') {
        serialCommandBuffer[serialCommandLength] = '\0';
        line = serialCommandBuffer;
        serialCommandLength = 0;
        serialCommandBuffer[0] = '\0';
        serialTextMode = false;
        return SERIAL_INPUT_LINE_READY;
      }

      if (serialCommandLength < SERIAL_COMMAND_BUFFER_SIZE - 1) {
        serialCommandBuffer[serialCommandLength++] = incoming;
      } else {
        serialCommandLength = 0;
        serialCommandBuffer[0] = '\0';
        serialCommandOverflow = true;
      }
      continue;
    }

    if (serialPendingP) {
      if (incoming == '\r' || incoming == '\n') {
        serialPendingP = false;
        legacyCommand = 'P';
        return SERIAL_INPUT_LEGACY_READY;
      }

      if (isLegacyCommand(incoming)) {
        serialPendingP = false;
        legacyCommand = incoming;
        return SERIAL_INPUT_LEGACY_READY;
      }

      serialPendingP = false;
      serialTextMode = true;
      serialCommandLength = 0;
      serialCommandBuffer[serialCommandLength++] = 'P';
      serialCommandBuffer[serialCommandLength++] = incoming;
      continue;
    }

    if (incoming == '\r' || incoming == '\n' || incoming == ' ' || incoming == '\t') {
      continue;
    }

    if ((char)toupper((unsigned char)incoming) == 'P') {
      serialPendingP = true;
      serialPendingPStartedMs = millis();
      continue;
    }

    if (isLegacyCommand(incoming)) {
      legacyCommand = incoming;
      return SERIAL_INPUT_LEGACY_READY;
    }

    serialTextMode = true;
    serialCommandLength = 0;
    serialCommandBuffer[serialCommandLength++] = incoming;
  }

  if (serialPendingP && millis() - serialPendingPStartedMs >= SERIAL_PENDING_P_TIMEOUT_MS) {
    serialPendingP = false;
    legacyCommand = 'P';
    return SERIAL_INPUT_LEGACY_READY;
  }

  return SERIAL_INPUT_INCOMPLETE;
}

// أثناء عملية حاجبة (دوران أو Demo)، أي أمر جديد يوقف الحركة.
// الأمر S يعمل كتوقف طارئ، وباقي الأوامر تُعاد بعد عودة البرنامج للحلقة الرئيسية.
static bool interruptionRequested() {
  while (true) {
    char legacyCommand = '\0';
    String receivedLine;
    SerialInputResult result = readSerialInput(legacyCommand, receivedLine);

    if (result == SERIAL_INPUT_INCOMPLETE) {
      return false;
    }

    if (result == SERIAL_INPUT_OVERFLOW) {
      stopAllOutputs();
      lcdShowStatus("Action Cancelled", "Outputs Off");
      Serial.println("ERROR|COMMAND_TOO_LONG");
      Serial.println("Action cancelled by an overlong Serial command.");
      return true;
    }

    if (result == SERIAL_INPUT_LEGACY_READY) {
      receivedLine = String(legacyCommand);
    } else {
      receivedLine.trim();
      if (receivedLine.length() == 0) {
        continue;
      }
    }

    char command = (char)toupper((unsigned char)receivedLine.charAt(0));
    stopAllOutputs();
    if (receivedLine.length() == 1 && command == 'S') {
      lcdShowStatus("STOP", "All Outputs Off");
      Serial.println("ACK|STOP");
      Serial.println("Emergency stop received. Action cancelled.");
    } else {
      lcdShowStatus("Action Cancelled", "Outputs Off");
      Serial.print("Action cancelled by command \"");
      Serial.print(receivedLine);
      Serial.println("\". Send the command again when ready.");
    }
    return true;
  }
}

static bool waitSafely(unsigned long durationMs) {
  unsigned long startTime = millis();
  while (millis() - startTime < durationMs) {
    if (interruptionRequested()) return false;
    delay(5);
  }
  return true;
}

// ════════════════════════════════════════════════════════════
//  دوال التحكم الأساسية
// ════════════════════════════════════════════════════════════

void stopMotors() {
  digitalWrite(MOTOR1_PIN1, LOW);
  digitalWrite(MOTOR1_PIN2, LOW);
  digitalWrite(MOTOR2_PIN1, LOW);
  digitalWrite(MOTOR2_PIN2, LOW);
  ledcWrite(MOTOR1_PWM_CHANNEL, 0);
  ledcWrite(MOTOR2_PWM_CHANNEL, 0);
  Serial.println("STOP");
}

void pumpOn() {
  digitalWrite(PUMP_PIN, PUMP_ACTIVE_LOW ? LOW : HIGH);
}

void pumpOff() {
  digitalWrite(PUMP_PIN, PUMP_ACTIVE_LOW ? HIGH : LOW);
}

void stopAllOutputs() {
  stopMotors();
  pumpOff();
}

static void applyMotorSpeed(uint8_t speed) {
  ledcWrite(MOTOR1_PWM_CHANNEL, speed);
  ledcWrite(MOTOR2_PWM_CHANNEL, speed);
}

static void driveForwardAt(uint8_t speed) {
  digitalWrite(MOTOR1_PIN1, LOW);  digitalWrite(MOTOR1_PIN2, HIGH);
  digitalWrite(MOTOR2_PIN1, LOW);  digitalWrite(MOTOR2_PIN2, HIGH);
  applyMotorSpeed(speed);
}

static void driveBackwardAt(uint8_t speed) {
  digitalWrite(MOTOR1_PIN1, HIGH); digitalWrite(MOTOR1_PIN2, LOW);
  digitalWrite(MOTOR2_PIN1, HIGH); digitalWrite(MOTOR2_PIN2, LOW);
  applyMotorSpeed(speed);
}

static void turnLeftInPlaceAt(uint8_t speed) {
  digitalWrite(MOTOR1_PIN1, LOW);  digitalWrite(MOTOR1_PIN2, HIGH);
  digitalWrite(MOTOR2_PIN1, HIGH); digitalWrite(MOTOR2_PIN2, LOW);
  applyMotorSpeed(speed);
}

static void turnRightInPlaceAt(uint8_t speed) {
  digitalWrite(MOTOR1_PIN1, HIGH); digitalWrite(MOTOR1_PIN2, LOW);
  digitalWrite(MOTOR2_PIN1, LOW);  digitalWrite(MOTOR2_PIN2, HIGH);
  applyMotorSpeed(speed);
}

void setupUltrasonic() {
  pinMode(ULTRASONIC_TRIG_PIN, OUTPUT);
  pinMode(ULTRASONIC_ECHO_PIN, INPUT);
  digitalWrite(ULTRASONIC_TRIG_PIN, LOW);
  delay(50);
}

float readUltrasonicCm() {
  digitalWrite(ULTRASONIC_TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(ULTRASONIC_TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(ULTRASONIC_TRIG_PIN, LOW);

  unsigned long duration = pulseIn(
    ULTRASONIC_ECHO_PIN,
    HIGH,
    ULTRASONIC_TIMEOUT_US
  );

  if (duration == 0) return -1.0f;

  float distanceCm = duration * 0.0343f / 2.0f;
  if (distanceCm < 2.0f || distanceCm > 400.0f) return -1.0f;

  return distanceCm;
}

void testUltrasonicOnce() {
  stopAllOutputs();
  lcdShowStatus("Ultrasonic", "Reading...");
  float distance = readUltrasonicCm();

  if (distance < 0) {
    lcdShowStatus("Ultrasonic", "Read Failed");
    Serial.println("Ultrasonic read failed");
  } else {
    lcdShowStatus("Distance:", String(distance, 1) + " cm");
    Serial.print("Ultrasonic distance: ");
    Serial.print(distance, 1);
    Serial.println(" cm");
  }
}

void updateIrSensor() {
  irCurrentRawDetected = digitalRead(IR_SENSOR_PIN) == IR_DETECTED_LEVEL;
  unsigned long now = millis();

  if (irCurrentRawDetected != irLastRawDetected) {
    irLastRawDetected = irCurrentRawDetected;
    irDebounceStartedMs = now;
    return;
  }

  if (irCurrentRawDetected == irStableDetected || now - irDebounceStartedMs < IR_DEBOUNCE_MS) {
    return;
  }

  irStableDetected = irCurrentRawDetected;
  if (irStableDetected) {
    if (!irDetectionLatched) {
      irDetectionLatched = true;
      Serial.println("IR|HAND_DETECTED");
      lcdShowStatus("IR Sensor", "Hand Detected");
    }
  } else {
    irDetectionLatched = false;
  }
}

uint8_t readLineSensorPattern() {
  uint8_t out1 = digitalRead(LINE_OUT1_PIN) == HIGH ? 1 : 0;
  uint8_t out2 = digitalRead(LINE_OUT2_PIN) == HIGH ? 1 : 0;
  uint8_t out3 = digitalRead(LINE_OUT3_PIN) == HIGH ? 1 : 0;
  uint8_t out4 = digitalRead(LINE_OUT4_PIN) == HIGH ? 1 : 0;
  uint8_t out5 = digitalRead(LINE_OUT5_PIN) == HIGH ? 1 : 0;

  return (out1 << 4) | (out2 << 3) | (out3 << 2) | (out4 << 1) | out5;
}

static void printLineSensorPattern(uint8_t pattern) {
  Serial.print("LINE|O1=");
  Serial.print((pattern >> 4) & 1);
  Serial.print("|O2=");
  Serial.print((pattern >> 3) & 1);
  Serial.print("|O3=");
  Serial.print((pattern >> 2) & 1);
  Serial.print("|O4=");
  Serial.print((pattern >> 1) & 1);
  Serial.print("|O5=");
  Serial.print(pattern & 1);
  Serial.print("|PATTERN=");
  for (int8_t bit = 4; bit >= 0; bit--) {
    Serial.print((pattern >> bit) & 1);
  }
  Serial.println();
}

void updateLineSensorTest() {
  unsigned long now = millis();
  if (now - lastLineSampleMs < LINE_SAMPLE_INTERVAL_MS) return;

  lastLineSampleMs = now;
  uint8_t pattern = readLineSensorPattern();

  if (pattern != lineCandidatePattern) {
    lineCandidatePattern = pattern;
    lineCandidateStartedMs = now;
    return;
  }

  if (now - lineCandidateStartedMs < LINE_STABLE_DURATION_MS) return;

  if (!lineStablePatternReady || lineStablePattern != lineCandidatePattern) {
    lineStablePattern = lineCandidatePattern;
    lineStablePatternReady = true;
    printLineSensorPattern(lineStablePattern);
  }
}

static void printRTCDateTime(const RtcDateTime& dt) {
  if (!dt.IsValid()) {
    Serial.println("RTC Time: invalid");
    return;
  }

  char dateTimeString[20];
  snprintf(
    dateTimeString,
    sizeof(dateTimeString),
    "%04u/%02u/%02u %02u:%02u:%02u",
    dt.Year(),
    dt.Month(),
    dt.Day(),
    dt.Hour(),
    dt.Minute(),
    dt.Second()
  );

  //Serial.print("RTC Time: ");
  //Serial.println(dateTimeString);
}

void setupRTC() {
  rtc.Begin();
  Serial.println("RTC initialized");

  RtcDateTime compiled(__DATE__, __TIME__);
  bool timeSetFromCompile = false;

  if (rtc.GetIsWriteProtected()) {
    Serial.println("RTC write protected");
    rtc.SetIsWriteProtected(false);
    Serial.println("RTC write protection disabled");
  }

  if (rtc.IsDateTimeValid()) {
    Serial.println("RTC time valid");
  } else {
    Serial.println("RTC time invalid");
    rtc.SetDateTime(compiled);
    timeSetFromCompile = true;
  }

  if (rtc.GetIsRunning()) {
    Serial.println("RTC running");
  } else {
    Serial.println("RTC stopped");
    rtc.SetIsRunning(true);
    Serial.println("RTC started");
  }

  RtcDateTime now = rtc.GetDateTime();
  if (!timeSetFromCompile && now.IsValid() && now < compiled) {
    Serial.println("RTC time older than compile time");
    rtc.SetDateTime(compiled);
    timeSetFromCompile = true;
  }

  Serial.print("RTC time set from compile time: ");
  Serial.println(timeSetFromCompile ? "yes" : "no");
  printRTCDateTime(rtc.GetDateTime());
}

void printRTC() {
  unsigned long nowMs = millis();
  if (nowMs - lastRTCPrintMs < RTC_PRINT_INTERVAL_MS) {
    return;
  }

  lastRTCPrintMs = nowMs;
  printRTCDateTime(rtc.GetDateTime());
}

static void lcdPrintLine(uint8_t row, String text) {
  if (!lcdReady || row >= LCD_ROWS) return;

  if (text.length() > LCD_COLS) {
    text.remove(LCD_COLS);
  }

  lcd.setCursor(0, row);
  lcd.print(text);
  for (uint8_t i = text.length(); i < LCD_COLS; i++) {
    lcd.print(' ');
  }
}

void lcdShowStatus(String line1, String line2, String line3, String line4) {
  if (!lcdReady) return;

  lcdPrintLine(0, line1);
  if (LCD_ROWS > 1) lcdPrintLine(1, line2);
  if (LCD_ROWS > 2) lcdPrintLine(2, line3);
  if (LCD_ROWS > 3) lcdPrintLine(3, line4);
}

void lcdShowReady() {
  lcdShowStatus(
    "Smart Med Robot",
    "Test Mode",
    "RTC/LCD Ready",
    "Press H for Help"
  );
}

void lcdShowError(String message) {
  lcdShowStatus("Error", message);
}

void setupLCD() {
  Serial.println("Initializing LCD using hd44780_I2Cexp...");
  int status = lcd.begin(LCD_COLS, LCD_ROWS);

  if (status != 0) {
    lcdReady = false;
    Serial.print("LCD initialization failed. Status: ");
    Serial.println(status);
    return;
  }

  lcd.backlight();
  lcd.clear();
  lcdReady = true;
  Serial.println("LCD initialized successfully at 0x27 as 20x4.");

  for (uint8_t i = 0; i < 2; i++) {
    lcd.noBacklight();
    delay(200);
    lcd.backlight();
    delay(200);
  }

  lcdShowStatus("LCD Test", "Address 0x27", "Size 20x4", "ESP32 I2C OK");
  delay(2000);
  lcdShowReady();
}

void showRTCOnce() {
  RtcDateTime now = rtc.GetDateTime();
  printRTCDateTime(now);

  if (!now.IsValid()) {
    lcdShowError("RTC invalid");
    return;
  }

  char timeString[9];
  char dateString[11];
  snprintf(
    timeString,
    sizeof(timeString),
    "%02u:%02u:%02u",
    now.Hour(),
    now.Minute(),
    now.Second()
  );
  snprintf(
    dateString,
    sizeof(dateString),
    "%04u/%02u/%02u",
    now.Year(),
    now.Month(),
    now.Day()
  );

  lcdShowStatus("RTC Time", timeString, dateString);
}

void runPumpForTwoSeconds() {
  stopAllOutputs();
  lcdShowStatus("Pump Test", "Running 2 sec");
  Serial.println(">> Pump ON for 2 seconds (send S to cancel)");
  pumpOn();

  bool completed = waitSafely(PUMP_RUN_MS);
  pumpOff();

  if (completed) {
    Serial.println("Pump test complete. Pump OFF.");
  } else {
    Serial.println("Pump test interrupted. Pump OFF.");
  }
  lcdShowStatus("Pump", "OFF");
}

// قدام باستمرار حتى وصول أمر آخر
void moveForward() {
  Serial.println(">> Forward");
  driveForwardAt(DRIVE_SPEED);
}

// خلف باستمرار حتى وصول أمر آخر
void moveBackward() {
  Serial.println(">> Backward");
  driveBackwardAt(DRIVE_SPEED);
}

// نسخ محددة المدة تُستخدم فقط داخل العرض القديم.
static bool moveForward(unsigned long durationMs) {
  moveForward();
  bool completed = waitSafely(durationMs);
  stopMotors();
  return completed;
}

static bool moveBackward(unsigned long durationMs) {
  moveBackward();
  bool completed = waitSafely(durationMs);
  stopMotors();
  return completed;
}

// ════════════════════════════════════════════════════════════
//  لف بزاوية دقيقة معتمد على MPU6050 (نفس منطق rotateSmart
//  بـ chair_control.cpp تبعك)
//
//  angle > 0  → لف يسار (عكس عقارب الساعة)
//  angle < 0  → لف يمين (مع عقارب الساعة)
// ════════════════════════════════════════════════════════════
static bool rotateSmart(int angle) {
  if (angle == 0) {
    stopMotors();
    return true;
  }

  float rotated = 0;
  float target  = abs(angle);
  unsigned long lastTime = millis();
  unsigned long startTime = lastTime;
  unsigned long lastPrintTime = lastTime;

  Serial.print("Rotating "); Serial.print(angle); Serial.println(" degrees...");

  if (angle > 0) {
    // عكس عقارب الساعة (يسار)
    turnLeftInPlaceAt(TURN_SPEED);
  } else {
    // مع عقارب الساعة (يمين)
    turnRightInPlaceAt(TURN_SPEED);
  }

  while (rotated < target) {
    if (interruptionRequested()) {
      stopMotors();
      return false;
    }

    if (millis() - startTime >= ROTATION_TIMEOUT_MS) {
      stopMotors();
      Serial.println("ERROR: Rotation timeout after 5 seconds.");
      return false;
    }

    sensors_event_t a, g, temp;
    if (!mpu.getEvent(&a, &g, &temp)) {
      stopMotors();
      Serial.println("ERROR: Failed to read MPU6050 during rotation.");
      return false;
    }

    unsigned long now = millis();
    float dt = (now - lastTime) / 1000.0;
    lastTime = now;

    // نستخدم محور gyro.x للدوران حاليًا؛ إذا بقيت الزاوية غير دقيقة سنختبر gyro.z لاحقًا.
    float speed = (g.gyro.x - gyroBiasX) * (180.0 / PI);
    if (abs(speed) > GYRO_THRESHOLD) {
      rotated += abs(speed) * dt;
    }

    if (now - lastPrintTime >= ROTATION_PRINT_MS) {
      Serial.print("Rotated: "); Serial.println(rotated);
      lastPrintTime = now;
    }
    delay(10);
  }

  stopMotors();
  Serial.println("Rotation done!");
  return true;
}

bool turnRight90() {
  stopMotors();
  Serial.println(">> Turn RIGHT 90 (gyro-based)");
  bool completed = rotateSmart(-90);
  stopMotors();
  return completed;
}

bool turnLeft90() {
  stopMotors();
  Serial.println(">> Turn LEFT 90 (gyro-based)");
  bool completed = rotateSmart(90);
  stopMotors();
  return completed;
}

// ════════════════════════════════════════════════════════════
//  حركة مركّبة: "يمين" = لف يمين 90° + قدام + لف رجوع لليسار 90°
//  (مش strafe حقيقي، الشاسي ما بيدعمها)
// ════════════════════════════════════════════════════════════
static const char* autoStateName(AutoState state) {
  switch (state) {
    case AUTO_DISABLED: return "AUTO_DISABLED";
    case AUTO_FORWARD: return "AUTO_FORWARD";
    case AUTO_STOP_BEFORE_REVERSE: return "AUTO_STOP_BEFORE_REVERSE";
    case AUTO_REVERSE: return "AUTO_REVERSE";
    case AUTO_STOP_BEFORE_TURN: return "AUTO_STOP_BEFORE_TURN";
    case AUTO_TURN_LEFT: return "AUTO_TURN_LEFT";
    case AUTO_TURN_RIGHT: return "AUTO_TURN_RIGHT";
    case AUTO_STOP_AFTER_TURN: return "AUTO_STOP_AFTER_TURN";
    case AUTO_SENSOR_RETRY: return "AUTO_SENSOR_RETRY";
  }
  return "AUTO_UNKNOWN";
}

static void printSerialCharacter(char command) {
  uint8_t ascii = (uint8_t)command;
  if (ascii >= 32 && ascii <= 126) {
    Serial.print(command);
  } else {
    Serial.print("0x");
    if (ascii < 16) Serial.print('0');
    Serial.print(ascii, HEX);
  }
}

static void printIgnoredSerialCharacter(char command) {
  Serial.print("[SERIAL] Ignored character: ");
  printSerialCharacter(command);
  Serial.print(" ASCII: ");
  Serial.println((uint8_t)command);
}

static void printAutonomousDisableDebug(
  const char* reason,
  char command,
  AutoState stateAtDisable,
  float distanceAtDisable,
  uint8_t invalidCount
) {
  Serial.println("[AUTO] Disabled");
  Serial.print("Reason: ");
  Serial.println(reason);
  Serial.print("Character: ");
  printSerialCharacter(command);
  Serial.println();
  Serial.print("ASCII: ");
  Serial.println((uint8_t)command);
  Serial.print("State: ");
  Serial.println(autoStateName(stateAtDisable));
  Serial.print("Last distance: ");
  if (distanceAtDisable >= 0) {
    Serial.print(distanceAtDisable, 1);
    Serial.println(" cm");
  } else {
    Serial.println("invalid");
  }
  Serial.print("Invalid count: ");
  Serial.println(invalidCount);
}

static void enterAutonomousState(AutoState newState) {
  autoState = newState;
  autoStateStartedMs = millis();

  switch (autoState) {
    case AUTO_DISABLED:
      autoModeEnabled = false;
      stopMotors();
      lcdShowStatus("AUTO STOP");
      break;

    case AUTO_FORWARD:
      autoModeEnabled = true;
      consecutiveObstacleReadings = 0;
      failedUltrasonicReadings = 0;
      driveForwardAt(AUTO_FORWARD_SPEED);
      Serial.println("[AUTO] Moving forward");
      lcdShowStatus("AUTO FORWARD");
      break;

    case AUTO_STOP_BEFORE_REVERSE:
      stopMotors();
      break;

    case AUTO_REVERSE:
      driveBackwardAt(AUTO_REVERSE_SPEED);
      Serial.println("[AUTO] Reversing");
      lcdShowStatus("REVERSING");
      break;

    case AUTO_STOP_BEFORE_TURN:
      stopMotors();
      break;

    case AUTO_TURN_LEFT:
      turnLeftInPlaceAt(AUTO_TURN_SPEED);
      Serial.println("[AUTO] Turning left");
      lcdShowStatus("TURN LEFT");
      break;

    case AUTO_TURN_RIGHT:
      turnRightInPlaceAt(AUTO_TURN_SPEED);
      Serial.println("[AUTO] Turning right");
      lcdShowStatus("TURN RIGHT");
      break;

    case AUTO_STOP_AFTER_TURN:
      stopMotors();
      break;

    case AUTO_SENSOR_RETRY:
      stopMotors();
      Serial.println("[ULTRASONIC] Sensor retry mode");
      lcdShowStatus("SENSOR RETRY");
      break;
  }
}

void startAutonomousMode() {
  stopAllOutputs();
  autoModeEnabled = true;
  nextAutoTurnRight = true;
  consecutiveObstacleReadings = 0;
  failedUltrasonicReadings = 0;
  lastAutoSensorMs = 0;
  lastAutoDistancePrintMs = 0;
  lastAutoDistanceCm = -1.0f;
  Serial.println("[AUTO] Started");
  enterAutonomousState(AUTO_FORWARD);
}

void stopAutonomousMode(const char* reason, char command) {
  AutoState stateAtDisable = autoState;
  float distanceAtDisable = lastAutoDistanceCm;
  uint8_t invalidCountAtDisable = failedUltrasonicReadings;

  autoModeEnabled = false;
  autoState = AUTO_DISABLED;
  consecutiveObstacleReadings = 0;
  failedUltrasonicReadings = 0;
  stopMotors();
  lcdShowStatus("AUTO STOP");

  Serial.print("[AUTO] Disabled by ");
  Serial.println(reason);
  printAutonomousDisableDebug(
    reason,
    command,
    stateAtDisable,
    distanceAtDisable,
    invalidCountAtDisable
  );
}

static bool isValidAutonomousDistance(float distance) {
  return distance >= 2.0f && distance <= 400.0f;
}

static void recordInvalidUltrasonicReading() {
  if (failedUltrasonicReadings < 255) {
    failedUltrasonicReadings++;
  }
  consecutiveObstacleReadings = 0;

  Serial.print("[ULTRASONIC] Invalid reading count: ");
  Serial.println(failedUltrasonicReadings);
}

static void checkAutonomousSensor() {
  unsigned long now = millis();
  if (now - lastAutoSensorMs < SENSOR_INTERVAL_MS) {
    return;
  }

  lastAutoSensorMs = now;
  float distance = readUltrasonicCm();
  lastAutoDistanceCm = distance;

  if (!isValidAutonomousDistance(distance)) {
    recordInvalidUltrasonicReading();

    if (failedUltrasonicReadings >= MAX_ULTRASONIC_FAILED_READS) {
      enterAutonomousState(AUTO_SENSOR_RETRY);
    }
    return;
  }

  failedUltrasonicReadings = 0;

  if (now - lastAutoDistancePrintMs >= DISTANCE_PRINT_INTERVAL_MS) {
    Serial.print("[ULTRASONIC] Distance: ");
    Serial.print(distance, 1);
    Serial.println(" cm");
    lastAutoDistancePrintMs = now;
  }

  if (distance <= OBSTACLE_DISTANCE_CM) {
    consecutiveObstacleReadings++;
    if (consecutiveObstacleReadings >= 2) {
      Serial.print("[ULTRASONIC] Distance: ");
      Serial.print(distance, 1);
      Serial.println(" cm");
      Serial.println("[AUTO] Obstacle detected");
      lcdShowStatus(String("OBSTACLE ") + String((int)(distance + 0.5f)) + "cm");
      consecutiveObstacleReadings = 0;
      enterAutonomousState(AUTO_STOP_BEFORE_REVERSE);
    }
  } else {
    consecutiveObstacleReadings = 0;
  }
}

static void checkAutonomousSensorRetry() {
  unsigned long now = millis();
  if (now - lastAutoSensorMs < SENSOR_RETRY_INTERVAL_MS) {
    return;
  }

  lastAutoSensorMs = now;
  float distance = readUltrasonicCm();
  lastAutoDistanceCm = distance;

  if (!isValidAutonomousDistance(distance)) {
    recordInvalidUltrasonicReading();
    return;
  }

  Serial.print("[ULTRASONIC] Sensor recovered. Distance: ");
  Serial.print(distance, 1);
  Serial.println(" cm");
  failedUltrasonicReadings = 0;
  consecutiveObstacleReadings = 0;
  enterAutonomousState(AUTO_FORWARD);
}

void updateAutonomousMode() {
  if (!autoModeEnabled || autoState == AUTO_DISABLED) {
    return;
  }

  unsigned long elapsedMs = millis() - autoStateStartedMs;

  switch (autoState) {
    case AUTO_FORWARD:
      checkAutonomousSensor();
      break;

    case AUTO_STOP_BEFORE_REVERSE:
      if (elapsedMs >= AUTO_STOP_DURATION_MS) {
        enterAutonomousState(AUTO_REVERSE);
      }
      break;

    case AUTO_REVERSE:
      if (elapsedMs >= REVERSE_DURATION_MS) {
        enterAutonomousState(AUTO_STOP_BEFORE_TURN);
      }
      break;

    case AUTO_STOP_BEFORE_TURN:
      if (elapsedMs >= AUTO_STOP_DURATION_MS) {
        if (nextAutoTurnRight) {
          nextAutoTurnRight = false;
          enterAutonomousState(AUTO_TURN_RIGHT);
        } else {
          nextAutoTurnRight = true;
          enterAutonomousState(AUTO_TURN_LEFT);
        }
      }
      break;

    case AUTO_TURN_LEFT:
    case AUTO_TURN_RIGHT:
      if (elapsedMs >= TURN_DURATION_MS) {
        enterAutonomousState(AUTO_STOP_AFTER_TURN);
      }
      break;

    case AUTO_STOP_AFTER_TURN:
      if (elapsedMs >= AUTO_STOP_DURATION_MS) {
        enterAutonomousState(AUTO_FORWARD);
      }
      break;

    case AUTO_SENSOR_RETRY:
      checkAutonomousSensorRetry();
      break;

    case AUTO_DISABLED:
      break;
  }
}

static bool strafeRight(unsigned long sideMs) {
  Serial.println(">> Strafe RIGHT (composite: turn+forward+turn back)");
  if (!turnRight90()) return false;
  if (!waitSafely(300)) return false;
  if (!moveForward(sideMs)) return false;
  if (!waitSafely(300)) return false;
  return turnLeft90();
}

static bool strafeLeft(unsigned long sideMs) {
  Serial.println(">> Strafe LEFT (composite: turn+forward+turn back)");
  if (!turnLeft90()) return false;
  if (!waitSafely(300)) return false;
  if (!moveForward(sideMs)) return false;
  if (!waitSafely(300)) return false;
  return turnRight90();
}

// ════════════════════════════════════════════════════════════
//  معايرة الـ Gyro (لازم الكرسي يكون ثابت تماماً!)
// ════════════════════════════════════════════════════════════
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

static bool continueDemo(bool stepCompleted) {
  if (!stepCompleted) {
    stopAllOutputs();
    lcdShowStatus("Demo Mode", "Cancelled");
    Serial.println("Demo cancelled safely.");
  }
  return stepCompleted;
}

// العرض التلقائي القديم محفوظ هنا، ويعمل مرة واحدة فقط عند الأمر D.
void runDemoOnce() {
  stopAllOutputs();
  Serial.println("\n=== Running automatic demo once ===");

  Serial.println("\n--- Forward ---");
  if (!continueDemo(moveForward(TEST_MOVE_MS))) return;
  if (!continueDemo(waitSafely(PAUSE_MS))) return;

  Serial.println("\n--- Backward ---");
  if (!continueDemo(moveBackward(TEST_MOVE_MS))) return;
  if (!continueDemo(waitSafely(PAUSE_MS))) return;

  Serial.println("\n--- Turn Right 90 (gyro) ---");
  if (!continueDemo(turnRight90())) return;
  if (!continueDemo(waitSafely(PAUSE_MS))) return;

  Serial.println("\n--- Turn Left 90 (gyro) ---");
  if (!continueDemo(turnLeft90())) return;
  if (!continueDemo(waitSafely(PAUSE_MS))) return;

  Serial.println("\n--- Strafe Right (composite) ---");
  if (!continueDemo(strafeRight(TEST_MOVE_MS))) return;
  if (!continueDemo(waitSafely(PAUSE_MS))) return;

  Serial.println("\n--- Strafe Left (composite) ---");
  if (!continueDemo(strafeLeft(TEST_MOVE_MS))) return;
  if (!continueDemo(waitSafely(PAUSE_MS))) return;

  stopAllOutputs();
  lcdShowStatus("Demo Mode", "Complete");
  Serial.println("\n=== Demo complete. It will not repeat automatically. ===");
}

void printHelp() {
  Serial.println("\n========== SERIAL MOTOR CONTROL ==========");
  Serial.println("A : Start autonomous obstacle avoidance");
  Serial.println("F : Move forward continuously");
  Serial.println("B : Move backward continuously");
  Serial.println("R : Stop, then turn right 90 degrees");
  Serial.println("L : Stop, then turn left 90 degrees");
  Serial.println("S : Stop immediately");
  Serial.println("D : Run the old automatic demo once");
  Serial.println("H : Stop and print this help menu");
  Serial.println("P : Run pump for 2 seconds");
  Serial.println("O : Turn pump ON continuously");
  Serial.println("X : Turn pump OFF and stop motors");
  Serial.println("U - Ultrasonic distance test");
  Serial.println("T : Show RTC time once on Serial and LCD");
  Serial.println("Commands are case-insensitive.");
  Serial.println("==========================================");
}

static void scanI2CBus() {
  Serial.println("Scanning I2C...");
  uint8_t deviceCount = 0;

  for (uint8_t address = 1; address <= 126; address++) {
    Wire.beginTransmission(address);
    uint8_t error = Wire.endTransmission();

    if (error == 0) {
      Serial.print("Found I2C device at 0x");
      if (address < 0x10) Serial.print('0');
      Serial.println(address, HEX);
      deviceCount++;
    }
  }

  if (deviceCount == 0) {
    Serial.println("No I2C devices found");
  }
}

// ════════════════════════════════════════════════════════════
//  Setup / Loop
// ════════════════════════════════════════════════════════════

static bool isLegacyCommand(char command) {
  switch ((char)toupper((unsigned char)command)) {
    case 'A':
    case 'F':
    case 'B':
    case 'R':
    case 'L':
    case 'S':
    case 'D':
    case 'H':
    case 'P':
    case 'O':
    case 'X':
    case 'U':
    case 'T':
      return true;

    default:
      return false;
  }
}

void handleLegacyCommand(char rawCommand) {
  char command = (char)toupper((unsigned char)rawCommand);

  switch (command) {
    case 'A':
      startAutonomousMode();
      break;

    case 'F':
      Serial.println("ACK|FORWARD");
      if (autoModeEnabled) {
        stopAutonomousMode("manual command", rawCommand);
      }
      stopAllOutputs();
      delay(50);
      lcdShowStatus("Motors", "Forward");
      moveForward();
      break;

    case 'B':
      Serial.println("ACK|BACKWARD");
      if (autoModeEnabled) {
        stopAutonomousMode("manual command", rawCommand);
      }
      stopAllOutputs();
      delay(50);
      lcdShowStatus("Motors", "Backward");
      moveBackward();
      break;

    case 'R':
      Serial.println("ACK|RIGHT");
      if (autoModeEnabled) {
        stopAutonomousMode("manual command", rawCommand);
      }
      stopAllOutputs();
      lcdShowStatus("Motors", "Turning Right");
      turnRight90();
      break;

    case 'L':
      Serial.println("ACK|LEFT");
      if (autoModeEnabled) {
        stopAutonomousMode("manual command", rawCommand);
      }
      stopAllOutputs();
      lcdShowStatus("Motors", "Turning Left");
      turnLeft90();
      break;

    case 'S':
      if (autoModeEnabled) {
        stopAutonomousMode("S command", rawCommand);
      }
      stopAllOutputs();
      lcdShowStatus("STOP", "All Outputs Off");
      Serial.println("ACK|STOP");
      Serial.println("Immediate stop command received. Motors and pump OFF.");
      break;

    case 'X':
      if (autoModeEnabled) {
        stopAutonomousMode("X command", rawCommand);
      }
      stopAllOutputs();
      lcdShowStatus("Pump", "OFF");
      Serial.println("Pump OFF. Motors stopped.");
      break;

    case 'D':
      if (autoModeEnabled) {
        Serial.println("[SERIAL] Command D ignored while autonomous mode is active. Send S or X first.");
        break;
      }
      stopAllOutputs();
      lcdShowStatus("Demo Mode", "Running...");
      runDemoOnce();
      break;

    case 'H':
      if (autoModeEnabled) {
        Serial.println("[SERIAL] Command H ignored while autonomous mode is active. Send S or X first.");
        break;
      }
      stopAllOutputs();
      printHelp();
      lcdShowStatus("Test Mode", "Press Serial Cmd");
      break;

    case 'U':
      if (autoModeEnabled) {
        Serial.println("[SERIAL] Command U ignored while autonomous mode is active. Send S or X first.");
        break;
      }
      testUltrasonicOnce();
      break;

    case 'P':
      if (autoModeEnabled) {
        Serial.println("[SERIAL] Command P ignored while autonomous mode is active. Send S or X first.");
        break;
      }
      runPumpForTwoSeconds();
      break;

    case 'O':
      if (autoModeEnabled) {
        Serial.println("[SERIAL] Command O ignored while autonomous mode is active. Send S or X first.");
        break;
      }
      stopAllOutputs();
      pumpOn();
      lcdShowStatus("Pump", "ON");
      Serial.println("Pump ON continuously. Send X or S to stop.");
      break;

    case 'T':
      if (autoModeEnabled) {
        Serial.println("[SERIAL] Command T ignored while autonomous mode is active. Send S or X first.");
        break;
      }
      showRTCOnce();
      break;

    default:
      printIgnoredSerialCharacter(rawCommand);
      break;
  }
}

void handleTextCommand(const String& command) {
  String normalizedCommand = command;
  normalizedCommand.trim();
  normalizedCommand.toUpperCase();

  if (normalizedCommand == "PING") {
    Serial.println("ACK|PING");
  } else if (normalizedCommand == "GET_STATUS") {
    Serial.println("STATUS|IDLE");
  } else {
    Serial.println("ERROR|UNKNOWN_COMMAND");
  }
}

static void processSerialInput() {
  while (true) {
    char legacyCommand = '\0';
    String receivedLine;
    SerialInputResult result = readSerialInput(legacyCommand, receivedLine);

    if (result == SERIAL_INPUT_INCOMPLETE) {
      return;
    }

    if (result == SERIAL_INPUT_OVERFLOW) {
      Serial.println("ERROR|COMMAND_TOO_LONG");
      continue;
    }

    if (result == SERIAL_INPUT_LEGACY_READY) {
      handleLegacyCommand(legacyCommand);
      continue;
    }

    receivedLine.trim();
    if (receivedLine.length() == 0) {
      continue;
    }

    if (receivedLine.length() == 1 && isLegacyCommand(receivedLine.charAt(0))) {
      handleLegacyCommand(receivedLine.charAt(0));
    } else {
      handleTextCommand(receivedLine);
    }
  }
}

void setup() {
  pinMode(PUMP_PIN, OUTPUT);
  digitalWrite(PUMP_PIN, HIGH); // OFF for active-low relay.
  pinMode(IR_SENSOR_PIN, INPUT);
  pinMode(LINE_OUT1_PIN, INPUT);
  pinMode(LINE_OUT2_PIN, INPUT);
  pinMode(LINE_OUT3_PIN, INPUT);
  pinMode(LINE_OUT4_PIN, INPUT);
  pinMode(LINE_OUT5_PIN, INPUT);
  irCurrentRawDetected = digitalRead(IR_SENSOR_PIN) == IR_DETECTED_LEVEL;
  irLastRawDetected = irCurrentRawDetected;
  irDebounceStartedMs = millis();

  Serial.begin(115200);
  delay(500);
  Serial.println("=== Safe Serial Motor Control (with MPU6050) ===");
  setupRTC();

  pinMode(MOTOR1_PIN1, OUTPUT);
  pinMode(MOTOR1_PIN2, OUTPUT);
  pinMode(MOTOR2_PIN1, OUTPUT);
  pinMode(MOTOR2_PIN2, OUTPUT);

  ledcSetup(MOTOR1_PWM_CHANNEL, MOTOR_FREQ, MOTOR_RESOLUTION);
  ledcAttachPin(ENABLE1_PIN, MOTOR1_PWM_CHANNEL);
  ledcSetup(MOTOR2_PWM_CHANNEL, MOTOR_FREQ, MOTOR_RESOLUTION);
  ledcAttachPin(ENABLE2_PIN, MOTOR2_PWM_CHANNEL);

  stopMotors();

  setupUltrasonic();
  Serial.print("Ultrasonic ready: TRIG=");
  Serial.print(ULTRASONIC_TRIG_PIN);
  Serial.print(" ECHO=");
  Serial.println(ULTRASONIC_ECHO_PIN);

  Wire.begin(21, 22);
  Wire.setClock(100000);
  Wire.setTimeOut(50);
  scanI2CBus();
  setupLCD();

  bool mpuFound = false;
  if (mpu.begin(0x68, &Wire)) {
    Serial.println("MPU6050 found at 0x68");
    mpuFound = true;
  } else if (mpu.begin(0x69, &Wire)) {
    Serial.println("MPU6050 found at 0x69");
    mpuFound = true;
  }

  if (!mpuFound) {
    lcdShowStatus("MPU6050", "Not Found", "Check Wiring", "SDA/SCL");
    Serial.println("MPU6050 not found at 0x68 or 0x69! Check wiring (SDA/SCL).");
    while (1) delay(10);
  }

  calibrateGyro();

  stopAllOutputs();
  Serial.println("Ready. Motors will not move until a command is received.");
  lcdShowReady();
  printHelp();

  lineCandidatePattern = readLineSensorPattern();
  unsigned long lineMonitorStartedMs = millis();
  lastLineSampleMs = lineMonitorStartedMs;
  lineCandidateStartedMs = lineMonitorStartedMs;
  lineStablePatternReady = false;
  Serial.println("LINE|MONITOR_READY|PINS=35,36,39,17,4");
}

void loop() {
  printRTC();

  processSerialInput();

  updateIrSensor();
  updateLineSensorTest();
  updateAutonomousMode();
  delay(5);
}
