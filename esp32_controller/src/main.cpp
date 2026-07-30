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
const uint8_t LINE_SENSOR_COUNT = 5;
const int LINE_SENSOR_PINS[LINE_SENSOR_COUNT] = {
  LINE_OUT1_PIN,
  LINE_OUT2_PIN,
  LINE_OUT3_PIN,
  LINE_OUT4_PIN,
  LINE_OUT5_PIN
};
const int8_t LINE_SENSOR_WEIGHTS[LINE_SENSOR_COUNT] = {-2, -1, 0, 1, 2};

// Real-hardware tuning; these motors need about PWM 160 to move reliably.
const uint8_t LINE_FOLLOW_BASE_PWM = 210;
const uint8_t LINE_FOLLOW_PROPORTIONAL_GAIN = 25;
const uint8_t LINE_FOLLOW_MAX_CORRECTION = 50;
const unsigned long LINE_FOLLOW_INTERVAL_MS = 25;
const uint8_t LINE_INTERSECTION_MIN_SENSORS = 4;
const uint8_t LINE_INTERSECTION_CONFIRM_READINGS = 3;
const unsigned long LINE_SEARCH_PRIMARY_MS = 300;
const unsigned long LINE_SEARCH_OPPOSITE_MS = 600;
const uint8_t LINE_SEARCH_OUTER_PWM = 180;
const uint8_t LINE_SEARCH_INNER_PWM = 0;

// Conservative starting values for physical intersection tuning. Each phase
// has its own deadline so a maneuver can never turn or drive indefinitely.
const uint8_t INTERSECTION_STRAIGHT_PWM = 180;
const uint8_t INTERSECTION_CENTER_PWM = 210;
// Time-based estimate for the approximately 20 cm sensor-to-rotation-center
// offset. Calibrate physically in 100 ms increments.
const unsigned long INTERSECTION_CENTER_MS = 1750;
const uint8_t INTERSECTION_PIVOT_SEARCH_PWM = 170;
const float INTERSECTION_SENSOR_SEARCH_MIN_ANGLE_DEG = 50.0f;
const float INTERSECTION_PIVOT_MAX_ANGLE_DEG = 320.0f;
const unsigned long INTERSECTION_PIVOT_TIMEOUT_MS = 10500;
const uint8_t INTERSECTION_SENSOR_ALIGN_PWM = 170;
const unsigned long INTERSECTION_SENSOR_ALIGN_TIMEOUT_MS = 5000;
const unsigned long INTERSECTION_SENSOR_LOSS_GRACE_MS = 500;
const uint8_t INTERSECTION_WIDE_CLEAR_CONFIRM_READINGS = 3;
const uint8_t INTERSECTION_SENSOR_CENTER_CONFIRM_READINGS = 5;
const uint8_t INTERSECTION_LOCK_PWM = 110;
const uint8_t INTERSECTION_LOCK_PROPORTIONAL_GAIN = 35;
const uint8_t INTERSECTION_LOCK_MAX_CORRECTION = 70;
const unsigned long INTERSECTION_LOCK_MS = 500;
const unsigned long INTERSECTION_LOCK_TIMEOUT_MS = 2000;
const uint8_t INTERSECTION_REACQUIRE_PWM = 140;
const unsigned long INTERSECTION_REACQUIRE_MS = 1200;
const unsigned long INTERSECTION_CLEAR_TIMEOUT_MS = 1500;
const unsigned long INTERSECTION_ACQUIRE_TIMEOUT_MS = 2500;
const uint8_t INTERSECTION_LINE_CONFIRM_READINGS = 3;

// Initial bounded calibration for a manually requested U-turn. The fast
// physical-right pivot ignores the original line until 120 degrees, then the
// existing sensor-guided alignment and line-lock controllers take over.
const uint8_t UTURN_PIVOT_PWM = 170;
const float UTURN_SENSOR_SEARCH_MIN_ANGLE_DEG = 120.0f;
const float UTURN_MAX_ANGLE_DEG = 260.0f;
const unsigned long UTURN_PIVOT_TIMEOUT_MS = 15000;
const uint8_t UTURN_SENSOR_ALIGN_PWM = 160;
const unsigned long UTURN_SENSOR_ALIGN_TIMEOUT_MS = 6000;
const unsigned long UTURN_SENSOR_LOSS_GRACE_MS = 500;
const unsigned long UTURN_MANEUVER_TIMEOUT_MS = 24000;

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

enum LineFollowState {
  LINE_FOLLOW_IDLE,
  LINE_FOLLOW_ACQUIRING,
  LINE_FOLLOW_CENTERED,
  LINE_FOLLOW_CORRECTING_LEFT,
  LINE_FOLLOW_CORRECTING_RIGHT,
  LINE_FOLLOW_SEARCHING_LEFT,
  LINE_FOLLOW_SEARCHING_RIGHT,
  LINE_FOLLOW_INTERSECTION,
  LINE_FOLLOW_LINE_LOST,
  LINE_FOLLOW_NAVIGATION_FAILED
};

enum LineSearchPhase {
  LINE_SEARCH_INACTIVE,
  LINE_SEARCH_PRIMARY,
  LINE_SEARCH_OPPOSITE
};

enum IntersectionDirection {
  INTERSECTION_DIRECTION_NONE,
  INTERSECTION_DIRECTION_LEFT,
  INTERSECTION_DIRECTION_RIGHT,
  INTERSECTION_DIRECTION_STRAIGHT,
  INTERSECTION_DIRECTION_U_TURN
};

enum IntersectionNavigationState {
  INTERSECTION_NAVIGATION_INACTIVE,
  INTERSECTION_GOING_STRAIGHT,
  INTERSECTION_CENTERING_LEFT,
  INTERSECTION_CENTERING_RIGHT,
  INTERSECTION_PIVOT_SEARCH_LEFT,
  INTERSECTION_PIVOT_SEARCH_RIGHT,
  INTERSECTION_SENSOR_ALIGN_LEFT,
  INTERSECTION_SENSOR_ALIGN_RIGHT,
  INTERSECTION_LOCKING_LINE_LEFT,
  INTERSECTION_LOCKING_LINE_RIGHT,
  INTERSECTION_REACQUIRING_LEFT,
  INTERSECTION_REACQUIRING_RIGHT,
  INTERSECTION_ACQUIRING_LINE,
  INTERSECTION_UTURN_PIVOT_SEARCH,
  INTERSECTION_UTURN_SENSOR_ALIGN,
  INTERSECTION_UTURN_LINE_LOCK
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
static bool manualMovementActive = false;

static bool lineFollowEnabled = false;
static LineFollowState lineFollowState = LINE_FOLLOW_IDLE;
static uint8_t lineRawValues[LINE_SENSOR_COUNT] = {1, 1, 1, 1, 1};
static bool lineDetected[LINE_SENSOR_COUNT] = {false, false, false, false, false};
static uint8_t latestLinePattern = 0x1F;
static uint8_t latestLineActiveCount = 0;
static float latestLinePositionError = 0.0f;
static float lastValidLinePositionError = 0.0f;
static uint8_t consecutiveIntersectionReadings = 0;
static LineSearchPhase lineSearchPhase = LINE_SEARCH_INACTIVE;
static bool lineSearchPrimaryLeft = false;
static unsigned long lineSearchPhaseStartedMs = 0;
static unsigned long lastLineFollowUpdateMs = 0;
static bool intersectionNavigationActive = false;
static bool intersectionCleared = false;
static IntersectionDirection intersectionDirection = INTERSECTION_DIRECTION_NONE;
static IntersectionNavigationState intersectionNavigationState =
  INTERSECTION_NAVIGATION_INACTIVE;
static unsigned long intersectionPhaseStartedMs = 0;
static uint8_t consecutiveOutgoingLineReadings = 0;
static float intersectionTurnAngleDeg = 0.0f;
static unsigned long intersectionLastGyroUpdateMs = 0;
static bool intersectionAlignmentPivotLeft = false;
static unsigned long intersectionLastLineSeenMs = 0;
static bool intersectionWideBlackCleared = false;
static uint8_t consecutiveIntersectionWideClearReadings = 0;
static unsigned long intersectionLockStableStartedMs = 0;
static float intersectionLastLockError = 0.0f;
static unsigned long uTurnStartedMs = 0;

static bool irCurrentRawDetected = false;
static bool irLastRawDetected = false;
static bool irStableDetected = false;
static bool irDetectionLatched = false;
static unsigned long irDebounceStartedMs = 0;

const size_t SERIAL_COMMAND_BUFFER_SIZE = 64;
const unsigned long SERIAL_PENDING_P_TIMEOUT_MS = 125;
const unsigned long SERIAL_PENDING_S_TIMEOUT_MS = 20;
const unsigned long SERIAL_PENDING_U_TIMEOUT_MS = 20;
static char serialCommandBuffer[SERIAL_COMMAND_BUFFER_SIZE];
static size_t serialCommandLength = 0;
static bool serialCommandOverflow = false;
static bool serialTextMode = false;
static bool serialPendingP = false;
static unsigned long serialPendingPStartedMs = 0;
static bool serialPendingS = false;
static unsigned long serialPendingSStartedMs = 0;
static bool serialPendingU = false;
static unsigned long serialPendingUStartedMs = 0;

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
void sampleLineSensors();
void updateLineFollowing();
void updateIntersectionNavigation();
void startLineFollowing();
void stopLineFollowing();
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
static void disableLineFollowing(LineFollowState nextState);
static void cancelIntersectionNavigation();
static void startUturnNavigation();

// Hardware keys execute immediately. Text commands remain newline-terminated,
// while P/S/U are held briefly so PING, ST..., and U_TURN text lines are not
// mistaken for the pump, emergency-stop, or ultrasonic legacy keys.
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

    if (serialPendingS) {
      if (incoming == '\r' || incoming == '\n') {
        serialPendingS = false;
        legacyCommand = 'S';
        return SERIAL_INPUT_LEGACY_READY;
      }

      if ((char)toupper((unsigned char)incoming) == 'T') {
        serialPendingS = false;
        serialTextMode = true;
        serialCommandLength = 0;
        serialCommandBuffer[serialCommandLength++] = 'S';
        serialCommandBuffer[serialCommandLength++] = incoming;
        continue;
      }

      // A non-text character following S still prioritizes emergency stop.
      serialPendingS = false;
      legacyCommand = 'S';
      return SERIAL_INPUT_LEGACY_READY;
    }

    if (serialPendingU) {
      if (incoming == '\r' || incoming == '\n') {
        serialPendingU = false;
        legacyCommand = 'U';
        return SERIAL_INPUT_LEGACY_READY;
      }

      if (incoming == '_') {
        serialPendingU = false;
        serialTextMode = true;
        serialCommandLength = 0;
        serialCommandBuffer[serialCommandLength++] = 'U';
        serialCommandBuffer[serialCommandLength++] = incoming;
        continue;
      }

      // A non-text character following U preserves the ultrasonic shortcut.
      serialPendingU = false;
      legacyCommand = 'U';
      return SERIAL_INPUT_LEGACY_READY;
    }

    if (incoming == '\r' || incoming == '\n' || incoming == ' ' || incoming == '\t') {
      continue;
    }

    if ((char)toupper((unsigned char)incoming) == 'P') {
      serialPendingP = true;
      serialPendingPStartedMs = millis();
      continue;
    }

    if ((char)toupper((unsigned char)incoming) == 'S') {
      serialPendingS = true;
      serialPendingSStartedMs = millis();
      continue;
    }

    if ((char)toupper((unsigned char)incoming) == 'U') {
      serialPendingU = true;
      serialPendingUStartedMs = millis();
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

  if (serialPendingS && millis() - serialPendingSStartedMs >= SERIAL_PENDING_S_TIMEOUT_MS) {
    serialPendingS = false;
    legacyCommand = 'S';
    return SERIAL_INPUT_LEGACY_READY;
  }

  if (serialPendingU && millis() - serialPendingUStartedMs >= SERIAL_PENDING_U_TIMEOUT_MS) {
    serialPendingU = false;
    legacyCommand = 'U';
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

    receivedLine.trim();
    receivedLine.toUpperCase();
    char command = (char)toupper((unsigned char)receivedLine.charAt(0));
    bool startLineFollowCommand = receivedLine == "START_LINE_FOLLOW";
    bool stopLineFollowCommand = receivedLine == "STOP_LINE_FOLLOW";
    bool uTurnCommand = receivedLine == "U_TURN";
    stopAllOutputs();
    cancelIntersectionNavigation();
    disableLineFollowing(LINE_FOLLOW_IDLE);
    if (receivedLine.length() == 1 && command == 'S') {
      lcdShowStatus("STOP", "All Outputs Off");
      Serial.println("ACK|STOP");
      Serial.println("Emergency stop received. Action cancelled.");
    } else if (stopLineFollowCommand) {
      lcdShowStatus("Line Follow", "Stopped");
      Serial.println("ACK|LINE_FOLLOW_STOPPED");
    } else if (startLineFollowCommand) {
      startLineFollowing();
      lcdShowStatus("Line Follow", "Started");
    } else if (uTurnCommand) {
      lcdShowStatus("Action Active", "U-turn Rejected");
      Serial.println("ERROR|MANEUVER_ACTIVE");
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

static void stopMotorOutputs() {
  digitalWrite(MOTOR1_PIN1, LOW);
  digitalWrite(MOTOR1_PIN2, LOW);
  digitalWrite(MOTOR2_PIN1, LOW);
  digitalWrite(MOTOR2_PIN2, LOW);
  ledcWrite(MOTOR1_PWM_CHANNEL, 0);
  ledcWrite(MOTOR2_PWM_CHANNEL, 0);
}

void stopMotors() {
  stopMotorOutputs();
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
  manualMovementActive = false;
}

static void applyMotorSpeed(uint8_t speed) {
  ledcWrite(MOTOR1_PWM_CHANNEL, speed);
  ledcWrite(MOTOR2_PWM_CHANNEL, speed);
}

static void setForwardMotorDirection() {
  digitalWrite(MOTOR1_PIN1, LOW);  digitalWrite(MOTOR1_PIN2, HIGH);
  digitalWrite(MOTOR2_PIN1, LOW);  digitalWrite(MOTOR2_PIN2, HIGH);
}

static void driveForwardAt(uint8_t speed) {
  setForwardMotorDirection();
  applyMotorSpeed(speed);
}

static void driveForwardDifferential(uint8_t leftSpeed, uint8_t rightSpeed) {
  setForwardMotorDirection();
  ledcWrite(MOTOR1_PWM_CHANNEL, leftSpeed);
  ledcWrite(MOTOR2_PWM_CHANNEL, rightSpeed);
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

void sampleLineSensors() {
  latestLinePattern = 0;
  latestLineActiveCount = 0;
  int weightedPositionSum = 0;

  for (uint8_t i = 0; i < LINE_SENSOR_COUNT; i++) {
    lineRawValues[i] = digitalRead(LINE_SENSOR_PINS[i]) == HIGH ? 1 : 0;
    lineDetected[i] = lineRawValues[i] == 0; // Active-low: true means black line.
    latestLinePattern = (latestLinePattern << 1) | lineRawValues[i];

    if (lineDetected[i]) {
      latestLineActiveCount++;
      weightedPositionSum += LINE_SENSOR_WEIGHTS[i];
    }
  }

  if (latestLineActiveCount > 0) {
    latestLinePositionError =
      weightedPositionSum / (float)latestLineActiveCount;
  } else {
    latestLinePositionError = 0.0f;
  }
}

static void printLinePatternBits(uint8_t pattern) {
  for (int8_t bit = LINE_SENSOR_COUNT - 1; bit >= 0; bit--) {
    Serial.print((pattern >> bit) & 1);
  }
}

static void printLineSensorReading() {
  Serial.print("LINE|O1=");
  Serial.print(lineRawValues[0]);
  Serial.print("|O2=");
  Serial.print(lineRawValues[1]);
  Serial.print("|O3=");
  Serial.print(lineRawValues[2]);
  Serial.print("|O4=");
  Serial.print(lineRawValues[3]);
  Serial.print("|O5=");
  Serial.print(lineRawValues[4]);
  Serial.print("|PATTERN=");
  printLinePatternBits(latestLinePattern);
  Serial.println();
}

static const char* lineFollowStateName(LineFollowState state) {
  switch (state) {
    case LINE_FOLLOW_IDLE: return "IDLE";
    case LINE_FOLLOW_ACQUIRING: return "ACQUIRING";
    case LINE_FOLLOW_CENTERED: return "CENTERED";
    case LINE_FOLLOW_CORRECTING_LEFT: return "CORRECTING_LEFT";
    case LINE_FOLLOW_CORRECTING_RIGHT: return "CORRECTING_RIGHT";
    case LINE_FOLLOW_SEARCHING_LEFT: return "SEARCHING_LEFT";
    case LINE_FOLLOW_SEARCHING_RIGHT: return "SEARCHING_RIGHT";
    case LINE_FOLLOW_INTERSECTION: return "INTERSECTION";
    case LINE_FOLLOW_LINE_LOST: return "LINE_LOST";
    case LINE_FOLLOW_NAVIGATION_FAILED: return "NAVIGATION_FAILED";
  }
  return "UNKNOWN";
}

static const char* intersectionDirectionName(IntersectionDirection direction) {
  switch (direction) {
    case INTERSECTION_DIRECTION_LEFT: return "LEFT";
    case INTERSECTION_DIRECTION_RIGHT: return "RIGHT";
    case INTERSECTION_DIRECTION_STRAIGHT: return "STRAIGHT";
    case INTERSECTION_DIRECTION_U_TURN: return "U_TURN";
    case INTERSECTION_DIRECTION_NONE: return "NONE";
  }
  return "NONE";
}

static const char* intersectionNavigationStateName() {
  switch (intersectionNavigationState) {
    case INTERSECTION_GOING_STRAIGHT: return "GOING_STRAIGHT";
    case INTERSECTION_CENTERING_LEFT: return "CENTERING_LEFT";
    case INTERSECTION_CENTERING_RIGHT: return "CENTERING_RIGHT";
    case INTERSECTION_PIVOT_SEARCH_LEFT: return "PIVOT_SEARCH_LEFT";
    case INTERSECTION_PIVOT_SEARCH_RIGHT: return "PIVOT_SEARCH_RIGHT";
    case INTERSECTION_SENSOR_ALIGN_LEFT: return "SENSOR_ALIGN_LEFT";
    case INTERSECTION_SENSOR_ALIGN_RIGHT: return "SENSOR_ALIGN_RIGHT";
    case INTERSECTION_LOCKING_LINE_LEFT: return "LOCKING_LINE_LEFT";
    case INTERSECTION_LOCKING_LINE_RIGHT: return "LOCKING_LINE_RIGHT";
    case INTERSECTION_REACQUIRING_LEFT: return "REACQUIRING_LEFT";
    case INTERSECTION_REACQUIRING_RIGHT: return "REACQUIRING_RIGHT";
    case INTERSECTION_UTURN_PIVOT_SEARCH: return "UTURN_PIVOT_SEARCH";
    case INTERSECTION_UTURN_SENSOR_ALIGN: return "UTURN_SENSOR_ALIGN";
    case INTERSECTION_UTURN_LINE_LOCK: return "UTURN_LINE_LOCK";
    case INTERSECTION_ACQUIRING_LINE:
      switch (intersectionDirection) {
        case INTERSECTION_DIRECTION_LEFT: return "ACQUIRING_LEFT";
        case INTERSECTION_DIRECTION_RIGHT: return "ACQUIRING_RIGHT";
        case INTERSECTION_DIRECTION_STRAIGHT: return "ACQUIRING_STRAIGHT";
        case INTERSECTION_DIRECTION_U_TURN: return "UTURN_PIVOT_SEARCH";
        case INTERSECTION_DIRECTION_NONE: return "ACQUIRING_LINE";
      }
    case INTERSECTION_NAVIGATION_INACTIVE: return "INACTIVE";
  }
  return "UNKNOWN";
}

static void printLineFollowStatus() {
  Serial.print("LINE_STATUS|MODE=");
  if (intersectionNavigationActive) {
    Serial.print("NAVIGATION");
  } else {
    Serial.print(lineFollowEnabled ? "FOLLOWING" : "STOPPED");
  }
  Serial.print("|STATE=");
  Serial.print(
    intersectionNavigationActive
      ? intersectionNavigationStateName()
      : lineFollowStateName(lineFollowState)
  );
  Serial.print("|PATTERN=");
  printLinePatternBits(latestLinePattern);
  Serial.println();
}

static void resetLineSearch() {
  lineSearchPhase = LINE_SEARCH_INACTIVE;
  lineSearchPrimaryLeft = false;
  lineSearchPhaseStartedMs = 0;
}

static void resetLineFollowConfirmation() {
  consecutiveIntersectionReadings = 0;
  resetLineSearch();
}

static void cancelIntersectionNavigation() {
  intersectionNavigationActive = false;
  intersectionCleared = false;
  intersectionDirection = INTERSECTION_DIRECTION_NONE;
  intersectionNavigationState = INTERSECTION_NAVIGATION_INACTIVE;
  intersectionPhaseStartedMs = 0;
  consecutiveOutgoingLineReadings = 0;
  intersectionTurnAngleDeg = 0.0f;
  intersectionLastGyroUpdateMs = 0;
  intersectionAlignmentPivotLeft = false;
  intersectionLastLineSeenMs = 0;
  intersectionWideBlackCleared = false;
  consecutiveIntersectionWideClearReadings = 0;
  intersectionLockStableStartedMs = 0;
  intersectionLastLockError = 0.0f;
  uTurnStartedMs = 0;
}

static void disableLineFollowing(LineFollowState nextState) {
  lineFollowEnabled = false;
  lineFollowState = nextState;
  resetLineFollowConfirmation();
}

static void stopLineFollowingForEvent(
  LineFollowState eventState,
  const char* eventName
) {
  disableLineFollowing(eventState);
  manualMovementActive = false;
  stopMotorOutputs();
  Serial.print("EVENT|");
  Serial.print(eventName);
  Serial.print("|PATTERN=");
  printLinePatternBits(latestLinePattern);
  Serial.println();
}

void startLineFollowing() {
  if (intersectionNavigationActive) {
    Serial.println("ERROR|NAVIGATION_IN_PROGRESS");
    return;
  }

  if (autoModeEnabled) {
    stopAutonomousMode("line-follow command", 'S');
  }

  manualMovementActive = false;
  stopMotorOutputs();
  sampleLineSensors();
  if (
    lineFollowState == LINE_FOLLOW_INTERSECTION ||
    lineFollowState == LINE_FOLLOW_NAVIGATION_FAILED ||
    latestLineActiveCount >= LINE_INTERSECTION_MIN_SENSORS
  ) {
    Serial.println("ERROR|INTERSECTION_UNRESOLVED");
    return;
  }

  resetLineFollowConfirmation();
  lastValidLinePositionError =
    latestLineActiveCount > 0 &&
    latestLineActiveCount < LINE_INTERSECTION_MIN_SENSORS
      ? latestLinePositionError
      : 0.0f;
  lineFollowState = LINE_FOLLOW_ACQUIRING;
  lineFollowEnabled = true;
  lastLineFollowUpdateMs = 0;
  Serial.println("ACK|LINE_FOLLOW_STARTED");
}

void stopLineFollowing() {
  cancelIntersectionNavigation();
  disableLineFollowing(LINE_FOLLOW_IDLE);
  manualMovementActive = false;
  stopMotorOutputs();
  Serial.println("ACK|LINE_FOLLOW_STOPPED");
}

static void driveProportionalErrorAt(
  float positionError,
  uint8_t basePwm,
  uint8_t proportionalGain,
  uint8_t maxCorrection
) {
  int correction = (int)roundf(
    positionError * proportionalGain
  );
  correction = constrain(
    correction,
    -(int)maxCorrection,
    (int)maxCorrection
  );

  int leftPwm = constrain(
    (int)basePwm + correction,
    0,
    255
  );
  int rightPwm = constrain(
    (int)basePwm - correction,
    0,
    255
  );

  driveForwardDifferential((uint8_t)leftPwm, (uint8_t)rightPwm);
}

static void driveProportionalLineAt(
  uint8_t basePwm,
  uint8_t proportionalGain,
  uint8_t maxCorrection
) {
  driveProportionalErrorAt(
    latestLinePositionError,
    basePwm,
    proportionalGain,
    maxCorrection
  );
}

static void applyProportionalLineControl() {
  lastValidLinePositionError = latestLinePositionError;
  if (latestLinePositionError < -0.1f) {
    lineFollowState = LINE_FOLLOW_CORRECTING_LEFT;
  } else if (latestLinePositionError > 0.1f) {
    lineFollowState = LINE_FOLLOW_CORRECTING_RIGHT;
  } else {
    lineFollowState = LINE_FOLLOW_CENTERED;
  }

  driveProportionalLineAt(
    LINE_FOLLOW_BASE_PWM,
    LINE_FOLLOW_PROPORTIONAL_GAIN,
    LINE_FOLLOW_MAX_CORRECTION
  );
}

static void driveIntersectionManeuver() {
  switch (intersectionNavigationState) {
    case INTERSECTION_GOING_STRAIGHT:
      driveForwardDifferential(
        INTERSECTION_STRAIGHT_PWM,
        INTERSECTION_STRAIGHT_PWM
      );
      break;
    case INTERSECTION_CENTERING_LEFT:
    case INTERSECTION_CENTERING_RIGHT:
      driveForwardAt(INTERSECTION_CENTER_PWM);
      break;
    case INTERSECTION_PIVOT_SEARCH_LEFT:
      // Physical intersection LEFT is the opposite of the manual helper name.
      turnRightInPlaceAt(INTERSECTION_PIVOT_SEARCH_PWM);
      break;
    case INTERSECTION_PIVOT_SEARCH_RIGHT:
      // Physical intersection RIGHT is the opposite of the manual helper name.
      turnLeftInPlaceAt(INTERSECTION_PIVOT_SEARCH_PWM);
      break;
    case INTERSECTION_UTURN_PIVOT_SEARCH:
      // The first U-turn calibration consistently pivots physical RIGHT.
      turnLeftInPlaceAt(UTURN_PIVOT_PWM);
      break;
    case INTERSECTION_SENSOR_ALIGN_LEFT:
    case INTERSECTION_SENSOR_ALIGN_RIGHT:
    case INTERSECTION_UTURN_SENSOR_ALIGN:
      if (intersectionAlignmentPivotLeft) {
        turnRightInPlaceAt(
          intersectionDirection == INTERSECTION_DIRECTION_U_TURN
            ? UTURN_SENSOR_ALIGN_PWM
            : INTERSECTION_SENSOR_ALIGN_PWM
        );
      } else {
        turnLeftInPlaceAt(
          intersectionDirection == INTERSECTION_DIRECTION_U_TURN
            ? UTURN_SENSOR_ALIGN_PWM
            : INTERSECTION_SENSOR_ALIGN_PWM
        );
      }
      break;
    case INTERSECTION_LOCKING_LINE_LEFT:
    case INTERSECTION_LOCKING_LINE_RIGHT:
    case INTERSECTION_UTURN_LINE_LOCK:
      driveForwardAt(INTERSECTION_LOCK_PWM);
      break;
    case INTERSECTION_REACQUIRING_LEFT:
    case INTERSECTION_REACQUIRING_RIGHT:
      driveForwardAt(INTERSECTION_REACQUIRE_PWM);
      break;
    case INTERSECTION_ACQUIRING_LINE:
      driveForwardDifferential(
        INTERSECTION_STRAIGHT_PWM,
        INTERSECTION_STRAIGHT_PWM
      );
      break;
    case INTERSECTION_NAVIGATION_INACTIVE:
      stopMotorOutputs();
      break;
  }
}

static void failIntersectionNavigation() {
  bool uTurn = intersectionDirection == INTERSECTION_DIRECTION_U_TURN;
  const char* direction = intersectionDirectionName(intersectionDirection);
  intersectionNavigationActive = false;
  intersectionCleared = false;
  intersectionNavigationState = INTERSECTION_NAVIGATION_INACTIVE;
  consecutiveOutgoingLineReadings = 0;
  intersectionTurnAngleDeg = 0.0f;
  intersectionLastGyroUpdateMs = 0;
  intersectionAlignmentPivotLeft = false;
  intersectionLastLineSeenMs = 0;
  intersectionWideBlackCleared = false;
  consecutiveIntersectionWideClearReadings = 0;
  intersectionLockStableStartedMs = 0;
  intersectionLastLockError = 0.0f;
  uTurnStartedMs = 0;
  lineFollowEnabled = false;
  lineFollowState = LINE_FOLLOW_NAVIGATION_FAILED;
  manualMovementActive = false;
  stopMotorOutputs();
  if (uTurn) {
    Serial.println("EVENT|U_TURN_FAILED");
  } else {
    Serial.print("EVENT|INTERSECTION_FAILED|DIRECTION=");
    Serial.println(direction);
  }
  intersectionDirection = INTERSECTION_DIRECTION_NONE;
}

static void completeIntersectionNavigation() {
  bool uTurn = intersectionDirection == INTERSECTION_DIRECTION_U_TURN;
  const char* direction = intersectionDirectionName(intersectionDirection);
  intersectionNavigationActive = false;
  intersectionCleared = false;
  intersectionNavigationState = INTERSECTION_NAVIGATION_INACTIVE;
  intersectionDirection = INTERSECTION_DIRECTION_NONE;
  consecutiveOutgoingLineReadings = 0;
  intersectionTurnAngleDeg = 0.0f;
  intersectionLastGyroUpdateMs = 0;
  intersectionAlignmentPivotLeft = false;
  intersectionLastLineSeenMs = 0;
  intersectionWideBlackCleared = false;
  consecutiveIntersectionWideClearReadings = 0;
  intersectionLockStableStartedMs = 0;
  intersectionLastLockError = 0.0f;
  uTurnStartedMs = 0;
  resetLineFollowConfirmation();
  lineFollowEnabled = true;
  manualMovementActive = false;
  lastLineFollowUpdateMs = millis();
  applyProportionalLineControl();
  if (uTurn) {
    Serial.print("EVENT|U_TURN_COMPLETE|PATTERN=");
  } else {
    Serial.print("EVENT|INTERSECTION_COMPLETE|DIRECTION=");
    Serial.print(direction);
    Serial.print("|PATTERN=");
  }
  printLinePatternBits(latestLinePattern);
  Serial.println();
}

static void startUturnNavigation() {
  if (
    intersectionNavigationActive ||
    lineFollowEnabled ||
    manualMovementActive ||
    autoModeEnabled
  ) {
    Serial.println("ERROR|MANEUVER_ACTIVE");
    return;
  }

  stopMotorOutputs();
  sampleLineSensors();
  intersectionDirection = INTERSECTION_DIRECTION_U_TURN;
  intersectionCleared = false;
  consecutiveOutgoingLineReadings = 0;
  intersectionPhaseStartedMs = millis();
  uTurnStartedMs = intersectionPhaseStartedMs;
  intersectionTurnAngleDeg = 0.0f;
  intersectionLastGyroUpdateMs = intersectionPhaseStartedMs;
  intersectionAlignmentPivotLeft = false;
  intersectionLastLineSeenMs = 0;
  intersectionWideBlackCleared = false;
  consecutiveIntersectionWideClearReadings = 0;
  intersectionLockStableStartedMs = 0;
  intersectionLastLockError = 0.0f;
  lineFollowEnabled = false;
  manualMovementActive = false;
  resetLineFollowConfirmation();
  intersectionNavigationState = INTERSECTION_UTURN_PIVOT_SEARCH;
  intersectionNavigationActive = true;
  Serial.println("ACK|U_TURN_STARTED");
  driveIntersectionManeuver();
}

static void startIntersectionNavigation(IntersectionDirection direction) {
  if (
    intersectionNavigationActive ||
    lineFollowState != LINE_FOLLOW_INTERSECTION
  ) {
    Serial.println("ERROR|NOT_AT_INTERSECTION");
    return;
  }

  intersectionDirection = direction;
  intersectionCleared = false;
  consecutiveOutgoingLineReadings = 0;
  intersectionPhaseStartedMs = millis();
  intersectionTurnAngleDeg = 0.0f;
  intersectionLastGyroUpdateMs = 0;
  intersectionAlignmentPivotLeft = direction == INTERSECTION_DIRECTION_LEFT;
  intersectionLastLineSeenMs = 0;
  intersectionWideBlackCleared = false;
  consecutiveIntersectionWideClearReadings = 0;
  intersectionLockStableStartedMs = 0;
  intersectionLastLockError = 0.0f;
  lineFollowEnabled = false;
  manualMovementActive = false;
  resetLineFollowConfirmation();

  switch (direction) {
    case INTERSECTION_DIRECTION_LEFT:
      intersectionNavigationState = INTERSECTION_CENTERING_LEFT;
      Serial.println("ACK|INTERSECTION_LEFT_STARTED");
      break;
    case INTERSECTION_DIRECTION_RIGHT:
      intersectionNavigationState = INTERSECTION_CENTERING_RIGHT;
      Serial.println("ACK|INTERSECTION_RIGHT_STARTED");
      break;
    case INTERSECTION_DIRECTION_STRAIGHT:
      intersectionNavigationState = INTERSECTION_GOING_STRAIGHT;
      Serial.println("ACK|INTERSECTION_STRAIGHT_STARTED");
      break;
    case INTERSECTION_DIRECTION_U_TURN:
      Serial.println("ERROR|NOT_AT_INTERSECTION");
      return;
    case INTERSECTION_DIRECTION_NONE:
      Serial.println("ERROR|NOT_AT_INTERSECTION");
      return;
  }

  intersectionNavigationActive = true;
  driveIntersectionManeuver();
}

static bool isValidOutgoingIntersectionLine() {
  return
    latestLineActiveCount > 0 &&
    latestLineActiveCount < LINE_INTERSECTION_MIN_SENSORS;
}

static bool confirmOutgoingIntersectionLine() {
  if (isValidOutgoingIntersectionLine()) {
    if (consecutiveOutgoingLineReadings < 255) {
      consecutiveOutgoingLineReadings++;
    }
    if (
      consecutiveOutgoingLineReadings >=
      INTERSECTION_LINE_CONFIRM_READINGS
    ) {
      completeIntersectionNavigation();
      return true;
    }
  } else {
    consecutiveOutgoingLineReadings = 0;
  }
  return false;
}

static void updateStraightIntersectionNavigation(unsigned long now) {
  if (!intersectionCleared) {
    if (now - intersectionPhaseStartedMs >= INTERSECTION_CLEAR_TIMEOUT_MS) {
      failIntersectionNavigation();
      return;
    }

    // The original wide black area is cleared only after fewer than the
    // normal intersection threshold of sensors remain on black.
    if (latestLineActiveCount < LINE_INTERSECTION_MIN_SENSORS) {
      intersectionCleared = true;
      intersectionNavigationState = INTERSECTION_ACQUIRING_LINE;
      intersectionPhaseStartedMs = now;
      consecutiveOutgoingLineReadings = 0;
    }
  } else if (
    now - intersectionPhaseStartedMs >= INTERSECTION_ACQUIRE_TIMEOUT_MS
  ) {
    failIntersectionNavigation();
    return;
  }

  if (intersectionCleared) {
    if (confirmOutgoingIntersectionLine()) return;
  }

  driveIntersectionManeuver();
}

static void startIntersectionPivot(unsigned long now) {
  stopMotorOutputs();
  intersectionTurnAngleDeg = 0.0f;
  intersectionLastGyroUpdateMs = now;
  intersectionPhaseStartedMs = now;
  consecutiveOutgoingLineReadings = 0;
  intersectionNavigationState =
    intersectionDirection == INTERSECTION_DIRECTION_LEFT
      ? INTERSECTION_PIVOT_SEARCH_LEFT
      : INTERSECTION_PIVOT_SEARCH_RIGHT;
  driveIntersectionManeuver();
}

static void updateIntersectionWideBlackClearance() {
  if (intersectionWideBlackCleared) return;

  if (latestLineActiveCount <= 2) {
    if (consecutiveIntersectionWideClearReadings < 255) {
      consecutiveIntersectionWideClearReadings++;
    }
    if (
      consecutiveIntersectionWideClearReadings >=
      INTERSECTION_WIDE_CLEAR_CONFIRM_READINGS
    ) {
      intersectionWideBlackCleared = true;
    }
  } else {
    consecutiveIntersectionWideClearReadings = 0;
  }
}

static bool isExpectedTurnEdgeDetected() {
  if (
    !intersectionWideBlackCleared ||
    latestLineActiveCount == 0 ||
    latestLineActiveCount > 3 ||
    lineDetected[2]
  ) {
    return false;
  }

  if (intersectionDirection == INTERSECTION_DIRECTION_LEFT) {
    return lineDetected[0] || lineDetected[1]; // O1/O2, physical left.
  }
  return lineDetected[3] || lineDetected[4]; // O4/O5, physical right.
}

static bool isFallbackTurnLineDetected() {
  return
    intersectionWideBlackCleared &&
    latestLineActiveCount > 0 &&
    latestLineActiveCount <= 3;
}

static bool updateIntersectionTurnAngle(
  unsigned long now,
  bool pivotTowardPhysicalLeft
) {
  sensors_event_t acceleration, gyro, temperature;
  if (!mpu.getEvent(&acceleration, &gyro, &temperature)) {
    return false;
  }

  float deltaSeconds = (now - intersectionLastGyroUpdateMs) / 1000.0f;
  intersectionLastGyroUpdateMs = now;
  float angularSpeedDegPerSecond =
    (gyro.gyro.x - gyroBiasX) * (180.0f / PI);
  if (abs(angularSpeedDegPerSecond) <= GYRO_THRESHOLD) {
    return true;
  }

  float deltaAngle = abs(angularSpeedDegPerSecond) * deltaSeconds;
  bool originalPivotIsLeft =
    intersectionDirection == INTERSECTION_DIRECTION_LEFT;
  if (pivotTowardPhysicalLeft == originalPivotIsLeft) {
    intersectionTurnAngleDeg += deltaAngle;
  } else {
    intersectionTurnAngleDeg = max(0.0f, intersectionTurnAngleDeg - deltaAngle);
  }
  return true;
}

static void startLowSpeedLineLock(unsigned long now) {
  bool uTurn = intersectionDirection == INTERSECTION_DIRECTION_U_TURN;
  if (!uTurn) {
    stopMotorOutputs();
  }
  intersectionNavigationState = uTurn
    ? INTERSECTION_UTURN_LINE_LOCK
    : (
      intersectionDirection == INTERSECTION_DIRECTION_LEFT
        ? INTERSECTION_LOCKING_LINE_LEFT
        : INTERSECTION_LOCKING_LINE_RIGHT
    );
  intersectionPhaseStartedMs = now;
  intersectionLockStableStartedMs = now;
  intersectionLastLineSeenMs = now;
  intersectionLastLockError = latestLinePositionError;
  consecutiveOutgoingLineReadings = 0;
  driveProportionalLineAt(
    INTERSECTION_LOCK_PWM,
    INTERSECTION_LOCK_PROPORTIONAL_GAIN,
    INTERSECTION_LOCK_MAX_CORRECTION
  );
}

static void applySensorGuidedPivotAlignment(unsigned long now) {
  bool anyBlackDetected = latestLineActiveCount > 0;
  if (!anyBlackDetected) {
    consecutiveOutgoingLineReadings = 0;
    if (
      now - intersectionLastLineSeenMs <=
      (
        intersectionDirection == INTERSECTION_DIRECTION_U_TURN
          ? UTURN_SENSOR_LOSS_GRACE_MS
          : INTERSECTION_SENSOR_LOSS_GRACE_MS
      )
    ) {
      // Continue the last low-speed pivot direction through brief line loss.
      driveIntersectionManeuver();
    } else {
      // The outgoing line was already detected, so forward fallback is unsafe.
      failIntersectionNavigation();
    }
    return;
  }

  intersectionLastLineSeenMs = now;
  if (latestLineActiveCount >= 4) {
    // A broad pattern can mean the board is parallel over the branch. Keep the
    // current pivot direction until the pattern narrows; never complete here.
    consecutiveOutgoingLineReadings = 0;
    driveIntersectionManeuver();
    return;
  }

  bool centerConfirmedBySensors =
    lineDetected[2] &&
    !lineDetected[0] &&
    !lineDetected[4] &&
    latestLineActiveCount >= 1 &&
    latestLineActiveCount <= 3;
  if (centerConfirmedBySensors) {
    if (consecutiveOutgoingLineReadings < 255) {
      consecutiveOutgoingLineReadings++;
    }
    if (
      consecutiveOutgoingLineReadings >=
      INTERSECTION_SENSOR_CENTER_CONFIRM_READINGS
    ) {
      startLowSpeedLineLock(now);
      return;
    }
    // Hold the approximate heading while O3 confirmation accumulates.
    stopMotorOutputs();
    return;
  }

  consecutiveOutgoingLineReadings = 0;
  bool blackOnLeft = lineDetected[0] || lineDetected[1];
  bool blackOnRight = lineDetected[3] || lineDetected[4];
  if (blackOnLeft && !blackOnRight) {
    intersectionAlignmentPivotLeft = true;
  } else if (blackOnRight && !blackOnLeft) {
    intersectionAlignmentPivotLeft = false;
  } else if (latestLinePositionError < -0.1f) {
    intersectionAlignmentPivotLeft = true;
  } else if (latestLinePositionError > 0.1f) {
    intersectionAlignmentPivotLeft = false;
  }
  driveIntersectionManeuver();
}

static void startSensorGuidedPivotAlignment(unsigned long now) {
  intersectionNavigationState =
    intersectionDirection == INTERSECTION_DIRECTION_U_TURN
      ? INTERSECTION_UTURN_SENSOR_ALIGN
      : (
        intersectionDirection == INTERSECTION_DIRECTION_LEFT
          ? INTERSECTION_SENSOR_ALIGN_LEFT
          : INTERSECTION_SENSOR_ALIGN_RIGHT
      );
  intersectionPhaseStartedMs = now;
  intersectionLastLineSeenMs = now;
  intersectionLastGyroUpdateMs = now;
  intersectionAlignmentPivotLeft =
    intersectionDirection == INTERSECTION_DIRECTION_LEFT;
  consecutiveOutgoingLineReadings = 0;
  // The first expected edge reading changes the low-speed pivot immediately.
  applySensorGuidedPivotAlignment(now);
}

static void startTurningForwardReacquisition(unsigned long now) {
  stopMotorOutputs();
  if (intersectionTurnAngleDeg > INTERSECTION_PIVOT_MAX_ANGLE_DEG) {
    intersectionTurnAngleDeg = INTERSECTION_PIVOT_MAX_ANGLE_DEG;
  }
  intersectionNavigationState =
    intersectionDirection == INTERSECTION_DIRECTION_LEFT
      ? INTERSECTION_REACQUIRING_LEFT
      : INTERSECTION_REACQUIRING_RIGHT;
  intersectionPhaseStartedMs = now;
  consecutiveOutgoingLineReadings = 0;
  driveIntersectionManeuver();
}

static void updateSensorGuidedPivotAlignment(unsigned long now) {
  unsigned long alignTimeoutMs =
    intersectionDirection == INTERSECTION_DIRECTION_U_TURN
      ? UTURN_SENSOR_ALIGN_TIMEOUT_MS
      : INTERSECTION_SENSOR_ALIGN_TIMEOUT_MS;
  float maxAngleDeg =
    intersectionDirection == INTERSECTION_DIRECTION_U_TURN
      ? UTURN_MAX_ANGLE_DEG
      : INTERSECTION_PIVOT_MAX_ANGLE_DEG;
  if (
    now - intersectionPhaseStartedMs >=
    alignTimeoutMs
  ) {
    failIntersectionNavigation();
    return;
  }

  if (
    !updateIntersectionTurnAngle(
      now,
      intersectionAlignmentPivotLeft
    ) ||
    intersectionTurnAngleDeg > maxAngleDeg
  ) {
    failIntersectionNavigation();
    return;
  }

  applySensorGuidedPivotAlignment(now);
}

static bool isLineWithinInnerLockSensors() {
  return
    latestLineActiveCount > 0 &&
    !lineDetected[0] &&
    !lineDetected[4] &&
    (lineDetected[1] || lineDetected[2] || lineDetected[3]);
}

static void returnLockToSensorGuidedPivot(unsigned long now) {
  stopMotorOutputs();
  intersectionNavigationState =
    intersectionDirection == INTERSECTION_DIRECTION_U_TURN
      ? INTERSECTION_UTURN_SENSOR_ALIGN
      : (
        intersectionDirection == INTERSECTION_DIRECTION_LEFT
          ? INTERSECTION_SENSOR_ALIGN_LEFT
          : INTERSECTION_SENSOR_ALIGN_RIGHT
      );
  intersectionPhaseStartedMs = now;
  intersectionLastGyroUpdateMs = now;
  intersectionLastLineSeenMs = now;
  intersectionLockStableStartedMs = 0;
  consecutiveOutgoingLineReadings = 0;
  driveIntersectionManeuver();
}

static void updateLowSpeedLineLock(unsigned long now) {
  if (now - intersectionPhaseStartedMs >= INTERSECTION_LOCK_TIMEOUT_MS) {
    failIntersectionNavigation();
    return;
  }

  if (latestLineActiveCount == 0) {
    intersectionLockStableStartedMs = 0;
    if (
      now - intersectionLastLineSeenMs <=
      (
        intersectionDirection == INTERSECTION_DIRECTION_U_TURN
          ? UTURN_SENSOR_LOSS_GRACE_MS
          : INTERSECTION_SENSOR_LOSS_GRACE_MS
      )
    ) {
      // Keep the last low-speed correction output through a short dropout.
      return;
    }

    // The branch was already found, so recover by pivoting rather than using
    // the never-detected forward fallback.
    returnLockToSensorGuidedPivot(now);
    return;
  }

  intersectionLastLineSeenMs = now;
  float controlError = latestLinePositionError;
  if (abs(controlError) > 0.1f) {
    intersectionLastLockError = controlError;
  } else if (lineDetected[0] || lineDetected[4]) {
    // A broad/ambiguous outer pattern must still produce a strong correction.
    controlError = abs(intersectionLastLockError) > 0.1f
      ? intersectionLastLockError
      : (intersectionAlignmentPivotLeft ? -2.0f : 2.0f);
  }

  if (controlError < -0.1f) {
    intersectionAlignmentPivotLeft = true;
  } else if (controlError > 0.1f) {
    intersectionAlignmentPivotLeft = false;
  }

  driveProportionalErrorAt(
    controlError,
    INTERSECTION_LOCK_PWM,
    INTERSECTION_LOCK_PROPORTIONAL_GAIN,
    INTERSECTION_LOCK_MAX_CORRECTION
  );

  if (isLineWithinInnerLockSensors()) {
    if (intersectionLockStableStartedMs == 0) {
      intersectionLockStableStartedMs = now;
    }
    if (now - intersectionLockStableStartedMs >= INTERSECTION_LOCK_MS) {
      completeIntersectionNavigation();
    }
  } else {
    // The line is still detected and correction continues, but the complete
    // 500 ms inner-sensor stability interval must start again.
    intersectionLockStableStartedMs = 0;
  }
}

static void updateTurningForwardReacquisition(unsigned long now) {
  if (now - intersectionPhaseStartedMs >= INTERSECTION_REACQUIRE_MS) {
    failIntersectionNavigation();
    return;
  }

  if (isFallbackTurnLineDetected()) {
    startSensorGuidedPivotAlignment(now);
    return;
  }

  // The fallback deliberately ignores both 11111 and 00000 until its bounded
  // deadline, while normal intersection detection remains disabled.
  driveIntersectionManeuver();
}

static void updateTurningIntersectionNavigation(unsigned long now) {
  if (
    intersectionNavigationState == INTERSECTION_CENTERING_LEFT ||
    intersectionNavigationState == INTERSECTION_CENTERING_RIGHT
  ) {
    // All sensor patterns are intentionally ignored until the complete
    // centering interval places the wheel axis near the middle of the '+'.
    if (now - intersectionPhaseStartedMs >= INTERSECTION_CENTER_MS) {
      startIntersectionPivot(now);
    } else {
      driveIntersectionManeuver();
    }
    return;
  }

  if (
    intersectionNavigationState == INTERSECTION_PIVOT_SEARCH_LEFT ||
    intersectionNavigationState == INTERSECTION_PIVOT_SEARCH_RIGHT
  ) {
    updateIntersectionWideBlackClearance();
    // The starting all-black pattern and early line crossings are ignored
    // until the calibrated minimum search angle has been reached.
    if (now - intersectionPhaseStartedMs >= INTERSECTION_PIVOT_TIMEOUT_MS) {
      startTurningForwardReacquisition(now);
      return;
    }

    bool pivotTowardPhysicalLeft =
      intersectionDirection == INTERSECTION_DIRECTION_LEFT;
    if (!updateIntersectionTurnAngle(now, pivotTowardPhysicalLeft)) {
      failIntersectionNavigation();
      return;
    }

    if (
      intersectionTurnAngleDeg >=
        INTERSECTION_SENSOR_SEARCH_MIN_ANGLE_DEG &&
      isExpectedTurnEdgeDetected()
    ) {
      startSensorGuidedPivotAlignment(now);
      return;
    }

    if (intersectionTurnAngleDeg >= INTERSECTION_PIVOT_MAX_ANGLE_DEG) {
      startTurningForwardReacquisition(now);
      return;
    }

    driveIntersectionManeuver();
    return;
  }

  if (
    intersectionNavigationState == INTERSECTION_SENSOR_ALIGN_LEFT ||
    intersectionNavigationState == INTERSECTION_SENSOR_ALIGN_RIGHT
  ) {
    updateSensorGuidedPivotAlignment(now);
    return;
  }

  if (
    intersectionNavigationState == INTERSECTION_LOCKING_LINE_LEFT ||
    intersectionNavigationState == INTERSECTION_LOCKING_LINE_RIGHT
  ) {
    updateLowSpeedLineLock(now);
    return;
  }

  if (
    intersectionNavigationState == INTERSECTION_REACQUIRING_LEFT ||
    intersectionNavigationState == INTERSECTION_REACQUIRING_RIGHT
  ) {
    updateTurningForwardReacquisition(now);
  }
}

static bool isValidUturnSearchPattern() {
  return latestLineActiveCount >= 1 && latestLineActiveCount <= 3;
}

static void updateUturnNavigation(unsigned long now) {
  if (now - uTurnStartedMs >= UTURN_MANEUVER_TIMEOUT_MS) {
    failIntersectionNavigation();
    return;
  }

  if (intersectionNavigationState == INTERSECTION_UTURN_PIVOT_SEARCH) {
    if (now - intersectionPhaseStartedMs >= UTURN_PIVOT_TIMEOUT_MS) {
      failIntersectionNavigation();
      return;
    }

    // The initial U-turn always pivots physical RIGHT. Sensor patterns are
    // deliberately ignored until the gyro reaches the minimum search angle.
    if (!updateIntersectionTurnAngle(now, false)) {
      failIntersectionNavigation();
      return;
    }

    if (
      intersectionTurnAngleDeg >= UTURN_SENSOR_SEARCH_MIN_ANGLE_DEG &&
      isValidUturnSearchPattern()
    ) {
      startSensorGuidedPivotAlignment(now);
      return;
    }

    if (intersectionTurnAngleDeg >= UTURN_MAX_ANGLE_DEG) {
      failIntersectionNavigation();
      return;
    }

    driveIntersectionManeuver();
    return;
  }

  if (intersectionNavigationState == INTERSECTION_UTURN_SENSOR_ALIGN) {
    updateSensorGuidedPivotAlignment(now);
    return;
  }

  if (intersectionNavigationState == INTERSECTION_UTURN_LINE_LOCK) {
    updateLowSpeedLineLock(now);
  }
}

void updateIntersectionNavigation() {
  if (!intersectionNavigationActive) return;

  unsigned long now = millis();
  if (now - lastLineFollowUpdateMs < LINE_FOLLOW_INTERVAL_MS) return;
  lastLineFollowUpdateMs = now;
  sampleLineSensors();

  if (intersectionDirection == INTERSECTION_DIRECTION_U_TURN) {
    updateUturnNavigation(now);
  } else if (intersectionDirection == INTERSECTION_DIRECTION_STRAIGHT) {
    updateStraightIntersectionNavigation(now);
  } else {
    updateTurningIntersectionNavigation(now);
  }
}

void updateLineFollowing() {
  if (!lineFollowEnabled) return;

  unsigned long now = millis();
  if (now - lastLineFollowUpdateMs < LINE_FOLLOW_INTERVAL_MS) return;
  lastLineFollowUpdateMs = now;

  sampleLineSensors();

  if (latestLineActiveCount >= LINE_INTERSECTION_MIN_SENSORS) {
    stopMotorOutputs();
    resetLineSearch();
    if (consecutiveIntersectionReadings < 255) {
      consecutiveIntersectionReadings++;
    }
    if (consecutiveIntersectionReadings >= LINE_INTERSECTION_CONFIRM_READINGS) {
      stopLineFollowingForEvent(LINE_FOLLOW_INTERSECTION, "INTERSECTION");
    }
    return;
  }

  consecutiveIntersectionReadings = 0;
  if (latestLineActiveCount == 0) {
    if (lineSearchPhase == LINE_SEARCH_INACTIVE) {
      lineSearchPrimaryLeft = lastValidLinePositionError < 0.0f;
      lineSearchPhase = LINE_SEARCH_PRIMARY;
      lineSearchPhaseStartedMs = now;
    }

    bool searchLeft = lineSearchPrimaryLeft;
    if (lineSearchPhase == LINE_SEARCH_PRIMARY) {
      if (now - lineSearchPhaseStartedMs >= LINE_SEARCH_PRIMARY_MS) {
        lineSearchPhase = LINE_SEARCH_OPPOSITE;
        lineSearchPhaseStartedMs = now;
        searchLeft = !lineSearchPrimaryLeft;
      }
    } else {
      searchLeft = !lineSearchPrimaryLeft;
      if (now - lineSearchPhaseStartedMs >= LINE_SEARCH_OPPOSITE_MS) {
        stopLineFollowingForEvent(LINE_FOLLOW_LINE_LOST, "LINE_LOST");
        return;
      }
    }

    // Both search phases are forward-only strong arcs; the opposite sweep is
    // longer so it crosses the original heading before checking the far side.
    if (searchLeft) {
      lineFollowState = LINE_FOLLOW_SEARCHING_LEFT;
      driveForwardDifferential(LINE_SEARCH_INNER_PWM, LINE_SEARCH_OUTER_PWM);
    } else {
      lineFollowState = LINE_FOLLOW_SEARCHING_RIGHT;
      driveForwardDifferential(LINE_SEARCH_OUTER_PWM, LINE_SEARCH_INNER_PWM);
    }
    return;
  }

  // Any reacquisition cancels both search phases and restores the
  // normal proportional controller on this same update.
  resetLineSearch();
  applyProportionalLineControl();
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
  disableLineFollowing(LINE_FOLLOW_IDLE);
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
  Serial.println("INTERSECTION_LEFT : acquire left branch after intersection stop");
  Serial.println("INTERSECTION_RIGHT : acquire right branch after intersection stop");
  Serial.println("INTERSECTION_STRAIGHT : acquire straight branch after intersection stop");
  Serial.println("U_TURN : start a bounded physical-right sensor-guided U-turn");
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

  // Any output-changing legacy command takes ownership from line following.
  if (command != 'T') {
    cancelIntersectionNavigation();
    disableLineFollowing(LINE_FOLLOW_IDLE);
  }

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
      manualMovementActive = true;
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
      manualMovementActive = true;
      break;

    case 'R':
      Serial.println("ACK|RIGHT");
      if (autoModeEnabled) {
        stopAutonomousMode("manual command", rawCommand);
      }
      stopAllOutputs();
      lcdShowStatus("Motors", "Turning Right");
      manualMovementActive = true;
      turnRight90();
      manualMovementActive = false;
      break;

    case 'L':
      Serial.println("ACK|LEFT");
      if (autoModeEnabled) {
        stopAutonomousMode("manual command", rawCommand);
      }
      stopAllOutputs();
      lcdShowStatus("Motors", "Turning Left");
      manualMovementActive = true;
      turnLeft90();
      manualMovementActive = false;
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

static void printControllerStatus() {
  if (intersectionNavigationActive) {
    Serial.println("STATUS|NAVIGATION");
  } else if (lineFollowEnabled) {
    Serial.println("STATUS|LINE_FOLLOWING");
  } else if (lineFollowState == LINE_FOLLOW_INTERSECTION) {
    Serial.println("STATUS|INTERSECTION");
  } else if (lineFollowState == LINE_FOLLOW_LINE_LOST) {
    Serial.println("STATUS|LINE_LOST");
  } else if (lineFollowState == LINE_FOLLOW_NAVIGATION_FAILED) {
    Serial.println("STATUS|NAVIGATION_FAILED");
  } else if (autoModeEnabled) {
    Serial.println("STATUS|AUTONOMOUS");
  } else if (manualMovementActive) {
    Serial.println("STATUS|MANUAL");
  } else {
    Serial.println("STATUS|IDLE");
  }
}

void handleTextCommand(const String& command) {
  String normalizedCommand = command;
  normalizedCommand.trim();
  normalizedCommand.toUpperCase();

  if (normalizedCommand == "PING") {
    Serial.println("ACK|PING");
  } else if (normalizedCommand == "GET_STATUS") {
    printControllerStatus();
  } else if (normalizedCommand == "GET_LINE") {
    sampleLineSensors();
    printLineSensorReading();
  } else if (normalizedCommand == "GET_LINE_STATUS") {
    sampleLineSensors();
    printLineFollowStatus();
  } else if (normalizedCommand == "START_LINE_FOLLOW") {
    startLineFollowing();
  } else if (normalizedCommand == "STOP_LINE_FOLLOW") {
    stopLineFollowing();
  } else if (normalizedCommand == "INTERSECTION_LEFT") {
    startIntersectionNavigation(INTERSECTION_DIRECTION_LEFT);
  } else if (normalizedCommand == "INTERSECTION_RIGHT") {
    startIntersectionNavigation(INTERSECTION_DIRECTION_RIGHT);
  } else if (normalizedCommand == "INTERSECTION_STRAIGHT") {
    startIntersectionNavigation(INTERSECTION_DIRECTION_STRAIGHT);
  } else if (normalizedCommand == "U_TURN") {
    startUturnNavigation();
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

  sampleLineSensors();
  Serial.println("LINE_READY|PINS=35,36,39,17,4|ACTIVE_LOW=1");
}

void loop() {
  printRTC();

  processSerialInput();

  updateIrSensor();
  updateIntersectionNavigation();
  updateLineFollowing();
  updateAutonomousMode();
  delay(5);
}
