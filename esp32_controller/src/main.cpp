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
const uint8_t LINE_LOST_CONFIRM_READINGS = 3;
const unsigned long RECOVERY_BRAKE_MS = 80;
const unsigned long RECOVERY_BACKTRACK_MS = 250;
const uint8_t RECOVERY_BACKTRACK_PWM = 165;
const uint8_t RECOVERY_SEARCH_PWM = 170;
const unsigned long RECOVERY_TOTAL_TIMEOUT_MS = 12000;
const uint8_t RECOVERY_MAX_SCAN_CYCLES = 2;
const unsigned long RECOVERY_SECOND_BACKTRACK_MS = 200;
const float RECOVERY_PRIMARY_HEADING_DEG = 35.0f;
const float RECOVERY_OPPOSITE_HEADING_DEG = 60.0f;
const float RECOVERY_EXPANDED_HEADING_DEG = 85.0f;
const float RECOVERY_HEADING_TOLERANCE_DEG = 2.0f;
const unsigned long RECOVERY_FALLBACK_SWEEP_MS[4] = {
  800,
  1600,
  2400,
  2800
};
const uint8_t RECOVERY_TRACK_BASE_PWM = 180;
const uint8_t RECOVERY_TRACK_PIVOT_PWM = 165;
const uint8_t RECOVERY_TRACK_PROPORTIONAL_GAIN = 25;
const uint8_t RECOVERY_TRACK_MAX_CORRECTION = 35;
const uint8_t RECOVERY_MIN_MOVING_PWM = 160;
const unsigned long RECOVERY_CONTACT_VERIFY_TIMEOUT_MS = 700;
const unsigned long RECOVERY_CONTACT_LOSS_GRACE_MS = 250;
const uint8_t RECOVERY_WIDE_VERIFY_READINGS = 10;
const unsigned long RECOVERY_WIDE_VERIFY_TIMEOUT_MS = 300;
const uint8_t RECOVERY_WIDE_FORWARD_PWM = 165;
const unsigned long RECOVERY_LINE_LOCK_MS = 450;
const unsigned long RECOVERY_LOCK_LOSS_GRACE_MS = 150;
const unsigned long RECOVERY_SAMPLE_INTERVAL_MS = 10;
const unsigned long RECOVERY_DIAGNOSTIC_INTERVAL_MS = 250;

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
// physical-right pivot must clear the original line before sensor reacquisition
// is allowed, then the existing alignment and line-lock controllers take over.
const uint8_t UTURN_PIVOT_PWM = 180;
const float UTURN_SENSOR_SEARCH_MIN_ANGLE_DEG = 170.0f;
const float UTURN_MAX_ANGLE_DEG = 320.0f;
const unsigned long UTURN_PIVOT_TIMEOUT_MS = 22000;
const uint8_t UTURN_SENSOR_ALIGN_PWM = 160;
const unsigned long UTURN_SENSOR_ALIGN_TIMEOUT_MS = 6000;
const unsigned long UTURN_SENSOR_LOSS_GRACE_MS = 500;
const unsigned long UTURN_TOTAL_TIMEOUT_MS = 35000;
const uint8_t UTURN_ORIGINAL_LINE_CLEAR_READINGS = 3;
const uint8_t UTURN_LINE_CONFIRM_READINGS = 3;
const unsigned long UTURN_DIAGNOSTIC_INTERVAL_MS = 250;

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
const uint8_t MANUAL_STRAIGHT_PWM = DRIVE_SPEED;
const uint8_t MANUAL_STEERING_INNER_PWM = 150;
const uint8_t MANUAL_PIVOT_PWM = TURN_SPEED;
#define GYRO_THRESHOLD       1.5   // تجاهل ضجيج الـ gyro
#define ROTATION_TIMEOUT_MS 10000  // حد أمان أقصى لأي دوران
#define ROTATION_PRINT_MS    200   // تقليل رسائل Serial أثناء الدوران
#define PUMP_RUN_MS          2000   // مدة اختبار المضخة بالأمر P
const unsigned long WATER_MIN_DURATION_MS = 100;
const unsigned long WATER_MAX_DURATION_MS = 60000;
const float WATER_FULL_DISTANCE_CM = 2.3f;
const float WATER_EMPTY_DISTANCE_CM = 6.9f;
const uint8_t WATER_LEVEL_SAMPLE_COUNT = 2;
const uint8_t WATER_LEVEL_MAX_ATTEMPTS = 4;
const unsigned long WATER_LEVEL_PING_INTERVAL_MS = 60;
const uint8_t WATER_LOW_PERCENT = 20;
const uint8_t WATER_EMPTY_PERCENT = 5;

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

enum LineRecoveryState {
  LINE_RECOVERY_INACTIVE,
  LINE_RECOVERY_LOST_CONFIRM,
  LINE_RECOVERY_BRAKE,
  LINE_RECOVERY_BACKTRACK,
  LINE_RECOVERY_GYRO_SEARCH,
  LINE_RECOVERY_CONTACT_TRACK,
  LINE_RECOVERY_WIDE_BLACK_VERIFY,
  LINE_RECOVERY_LINE_LOCK,
  LINE_RECOVERY_RETURN_TO_ORIGIN,
  LINE_RECOVERY_FAILED
};

enum LineRecoverySide {
  LINE_RECOVERY_SIDE_NONE,
  LINE_RECOVERY_SIDE_LEFT,
  LINE_RECOVERY_SIDE_RIGHT
};

enum LineRecoveryContactMotion {
  LINE_RECOVERY_CONTACT_STOPPED,
  LINE_RECOVERY_CONTACT_DIFFERENTIAL,
  LINE_RECOVERY_CONTACT_PIVOT_LEFT,
  LINE_RECOVERY_CONTACT_PIVOT_RIGHT
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
static LineRecoveryState lineRecoveryState = LINE_RECOVERY_INACTIVE;
static LineRecoverySide lastNonZeroLineSide = LINE_RECOVERY_SIDE_NONE;
static LineRecoverySide previousFailedRecoveryFirstSide =
  LINE_RECOVERY_SIDE_NONE;
static bool recoveryAlternatingDefaultLeft = true;
static uint8_t recoveryLostReadings = 0;
static LineRecoverySide recoveryPrimarySide = LINE_RECOVERY_SIDE_NONE;
static LineRecoverySide recoveryCommandedTurnSide = LINE_RECOVERY_SIDE_NONE;
static unsigned long recoveryStartedMs = 0;
static unsigned long lastRecoverySampleMs = 0;
static unsigned long recoveryPhaseStartedMs = 0;
static unsigned long recoveryBacktrackDurationMs = 0;
static uint8_t recoveryScanCycle = 0;
static uint8_t recoverySearchStage = 0;
static unsigned long recoverySearchStageStartedMs = 0;
static float recoveryRelativeHeadingDeg = 0.0f;
static float recoveryTargetHeadingDeg = 0.0f;
static unsigned long recoveryLastGyroUpdateMs = 0;
static bool recoveryGyroInitialized = false;
static bool recoveryGyroAvailable = true;
static LineRecoveryState recoveryInterruptedState = LINE_RECOVERY_INACTIVE;
static unsigned long recoveryInterruptedPhaseRemainingMs = 0;
static unsigned long recoveryInterruptedSearchElapsedMs = 0;
static unsigned long recoveryContactStartedMs = 0;
static unsigned long recoveryContactLastSeenMs = 0;
static uint8_t recoveryFirstContactMask = 0;
static uint8_t recoveryContactSeenMask = 0;
static float recoveryBestAbsoluteError = 0.0f;
static bool recoveryContactProgress = false;
static LineRecoveryContactMotion recoveryLastContactMotion =
  LINE_RECOVERY_CONTACT_STOPPED;
static uint8_t recoveryLastContactLeftPwm = 0;
static uint8_t recoveryLastContactRightPwm = 0;
static uint8_t recoveryWideConsecutiveReadings = 0;
static unsigned long recoveryLineLockStartedMs = 0;
static bool recoveryLineLockSawInnerSensor = false;
static unsigned long recoveryLastDiagnosticMs = 0;
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
static bool uturnOriginalLineCleared = false;
static uint8_t uturnConsecutiveAllWhiteReadings = 0;
static uint8_t uturnConsecutiveValidLineReadings = 0;
static unsigned long uturnLastDiagnosticMs = 0;
static unsigned long uturnPivotElapsedMs = 0;

static bool irCurrentRawDetected = false;
static bool irLastRawDetected = false;
static bool irStableDetected = false;
static bool irDetectionLatched = false;
static unsigned long irDebounceStartedMs = 0;

const size_t SERIAL_COMMAND_BUFFER_SIZE = 64;
static char serialCommandBuffer[SERIAL_COMMAND_BUFFER_SIZE];
static size_t serialCommandLength = 0;
static bool serialCommandOverflow = false;

enum SerialInputResult {
  SERIAL_INPUT_INCOMPLETE,
  SERIAL_INPUT_LINE_READY,
  SERIAL_INPUT_OVERFLOW
};

void stopMotors();
void pumpOn();
void pumpOff();
void stopAllOutputs();
void setupUltrasonic();
float readUltrasonicCm();
float readWaterLevelDistanceCm();
int waterLevelPercentForDistance(float distanceCm);
const char* waterLevelStatusForPercent(int percent);
void printWaterLevel();
void testUltrasonicOnce();
void updateIrSensor();
void sampleLineSensors();
void updateLineFollowing();
void updateIntersectionNavigation();
void startLineFollowing();
void stopLineFollowing();
void setupRTC();
void printRTC();
void printRTCMachineReadable();
void handleSetRTCCommand(const String& command);
void setupLCD();
void lcdShowStatus(String line1, String line2 = "", String line3 = "", String line4 = "");
void showMedicineWorkflowStatus(const String& state);
void lcdShowReady();
void lcdShowError(String message);
void showRTCOnce();
void runPumpForDuration(unsigned long durationMs);
void startAutonomousMode();
void stopAutonomousMode(const char* reason, char command);
void updateAutonomousMode();
void handleLegacyCommand(char command);
void handleTextCommand(const String& command);
static bool isLegacyCommand(char command);
static void disableLineFollowing(LineFollowState nextState);
static void cancelIntersectionNavigation();
static void startUturnNavigation();

// Every command is newline-terminated. Dispatch happens only after the full
// line is available, so a structured command beginning with a legacy letter
// (for example LCD|STATE=...) can never trigger motor movement.
static SerialInputResult readSerialInput(String& line) {
  while (Serial.available() > 0) {
    char incoming = (char)Serial.read();

    if (serialCommandOverflow) {
      if (incoming == '\n') {
        serialCommandLength = 0;
        serialCommandBuffer[0] = '\0';
        serialCommandOverflow = false;
        return SERIAL_INPUT_OVERFLOW;
      }
      continue;
    }

    if (incoming == '\r') {
      continue;
    }

    if (incoming == '\n') {
      serialCommandBuffer[serialCommandLength] = '\0';
      line = serialCommandBuffer;
      serialCommandLength = 0;
      serialCommandBuffer[0] = '\0';
      return SERIAL_INPUT_LINE_READY;
    }

    if (serialCommandLength < SERIAL_COMMAND_BUFFER_SIZE - 1) {
      serialCommandBuffer[serialCommandLength++] = incoming;
    } else {
      serialCommandLength = 0;
      serialCommandBuffer[0] = '\0';
      serialCommandOverflow = true;
    }
  }

  return SERIAL_INPUT_INCOMPLETE;
}

// أثناء عملية حاجبة (دوران أو Demo)، أي أمر جديد يوقف الحركة.
// الأمر S يعمل كتوقف طارئ، وباقي الأوامر تُعاد بعد عودة البرنامج للحلقة الرئيسية.
static bool interruptionRequested() {
  while (true) {
    String receivedLine;
    SerialInputResult result = readSerialInput(receivedLine);

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

    receivedLine.trim();
    if (receivedLine.length() == 0) {
      continue;
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

static void driveBackwardDifferential(uint8_t leftSpeed, uint8_t rightSpeed) {
  digitalWrite(MOTOR1_PIN1, HIGH); digitalWrite(MOTOR1_PIN2, LOW);
  digitalWrite(MOTOR2_PIN1, HIGH); digitalWrite(MOTOR2_PIN2, LOW);
  ledcWrite(MOTOR1_PWM_CHANNEL, leftSpeed);
  ledcWrite(MOTOR2_PWM_CHANNEL, rightSpeed);
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

float readWaterLevelDistanceCm() {
  float readings[WATER_LEVEL_SAMPLE_COUNT];
  uint8_t validReadings = 0;

  for (uint8_t attempt = 0; attempt < WATER_LEVEL_MAX_ATTEMPTS; attempt++) {
    if (attempt > 0) {
      delay(WATER_LEVEL_PING_INTERVAL_MS);
    }

    float distance = readUltrasonicCm();
    if (distance >= 0.0f) {
      readings[validReadings++] = distance;
      if (validReadings == WATER_LEVEL_SAMPLE_COUNT) {
        break;
      }
    }
  }

  if (validReadings != WATER_LEVEL_SAMPLE_COUNT) {
    return -1.0f;
  }

  return (readings[0] + readings[1]) / 2.0f;
}

int waterLevelPercentForDistance(float distanceCm) {
  if (distanceCm <= WATER_FULL_DISTANCE_CM) return 100;
  if (distanceCm >= WATER_EMPTY_DISTANCE_CM) return 0;

  float percent = 100.0f *
    (WATER_EMPTY_DISTANCE_CM - distanceCm) /
    (WATER_EMPTY_DISTANCE_CM - WATER_FULL_DISTANCE_CM);
  int roundedPercent = (int)(percent + 0.5f);
  return constrain(roundedPercent, 0, 100);
}

const char* waterLevelStatusForPercent(int percent) {
  if (percent <= WATER_EMPTY_PERCENT) return "EMPTY";
  if (percent <= WATER_LOW_PERCENT) return "LOW";
  return "OK";
}

void printWaterLevel() {
  float distance = readWaterLevelDistanceCm();
  if (distance < 0.0f) {
    Serial.println("WATER_LEVEL|DISTANCE_CM=NA|PERCENT=NA|STATUS=SENSOR_ERROR");
    return;
  }

  int percent = waterLevelPercentForDistance(distance);
  Serial.print("WATER_LEVEL|DISTANCE_CM=");
  Serial.print(distance, 1);
  Serial.print("|PERCENT=");
  Serial.print(percent);
  Serial.print("|STATUS=");
  Serial.println(waterLevelStatusForPercent(percent));
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
  lineRecoveryState = LINE_RECOVERY_INACTIVE;
  recoveryLostReadings = 0;
  recoveryPrimarySide = LINE_RECOVERY_SIDE_NONE;
  recoveryCommandedTurnSide = LINE_RECOVERY_SIDE_NONE;
  recoveryStartedMs = 0;
  lastRecoverySampleMs = 0;
  recoveryPhaseStartedMs = 0;
  recoveryBacktrackDurationMs = 0;
  recoveryScanCycle = 0;
  recoverySearchStage = 0;
  recoverySearchStageStartedMs = 0;
  recoveryRelativeHeadingDeg = 0.0f;
  recoveryTargetHeadingDeg = 0.0f;
  recoveryLastGyroUpdateMs = 0;
  recoveryGyroInitialized = false;
  recoveryGyroAvailable = true;
  recoveryInterruptedState = LINE_RECOVERY_INACTIVE;
  recoveryInterruptedPhaseRemainingMs = 0;
  recoveryInterruptedSearchElapsedMs = 0;
  recoveryContactStartedMs = 0;
  recoveryContactLastSeenMs = 0;
  recoveryFirstContactMask = 0;
  recoveryContactSeenMask = 0;
  recoveryBestAbsoluteError = 0.0f;
  recoveryContactProgress = false;
  recoveryLastContactMotion = LINE_RECOVERY_CONTACT_STOPPED;
  recoveryLastContactLeftPwm = 0;
  recoveryLastContactRightPwm = 0;
  recoveryWideConsecutiveReadings = 0;
  recoveryLineLockStartedMs = 0;
  recoveryLineLockSawInnerSensor = false;
  recoveryLastDiagnosticMs = 0;
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
  uturnOriginalLineCleared = false;
  uturnConsecutiveAllWhiteReadings = 0;
  uturnConsecutiveValidLineReadings = 0;
  uturnLastDiagnosticMs = 0;
  uturnPivotElapsedMs = 0;
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
  if (lastValidLinePositionError < -0.25f) {
    lastNonZeroLineSide = LINE_RECOVERY_SIDE_LEFT;
  } else if (lastValidLinePositionError > 0.25f) {
    lastNonZeroLineSide = LINE_RECOVERY_SIDE_RIGHT;
  }
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
  if (latestLinePositionError < -0.25f) {
    lastNonZeroLineSide = LINE_RECOVERY_SIDE_LEFT;
  } else if (latestLinePositionError > 0.25f) {
    lastNonZeroLineSide = LINE_RECOVERY_SIDE_RIGHT;
  }
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

static const char* lineRecoveryStateName() {
  switch (lineRecoveryState) {
    case LINE_RECOVERY_INACTIVE: return "INACTIVE";
    case LINE_RECOVERY_LOST_CONFIRM: return "LOST_CONFIRM";
    case LINE_RECOVERY_BRAKE: return "BRAKE";
    case LINE_RECOVERY_BACKTRACK: return "BACKTRACK";
    case LINE_RECOVERY_GYRO_SEARCH: return "GYRO_SEARCH";
    case LINE_RECOVERY_CONTACT_TRACK: return "CONTACT_TRACK";
    case LINE_RECOVERY_WIDE_BLACK_VERIFY: return "WIDE_BLACK_VERIFY";
    case LINE_RECOVERY_LINE_LOCK: return "LINE_LOCK";
    case LINE_RECOVERY_RETURN_TO_ORIGIN: return "RETURN_TO_ORIGIN";
    case LINE_RECOVERY_FAILED: return "FAILED";
  }
  return "UNKNOWN";
}

static uint8_t currentLineContactMask() {
  uint8_t mask = 0;
  for (uint8_t i = 0; i < LINE_SENSOR_COUNT; i++) {
    if (lineDetected[i]) mask |= (uint8_t)(1U << i);
  }
  return mask;
}

static LineRecoverySide oppositeRecoverySide(LineRecoverySide side) {
  if (side == LINE_RECOVERY_SIDE_LEFT) return LINE_RECOVERY_SIDE_RIGHT;
  if (side == LINE_RECOVERY_SIDE_RIGHT) return LINE_RECOVERY_SIDE_LEFT;
  return LINE_RECOVERY_SIDE_NONE;
}

static LineRecoverySide chooseRecoveryPrimarySide() {
  if (lastNonZeroLineSide != LINE_RECOVERY_SIDE_NONE) {
    return lastNonZeroLineSide;
  }
  if (previousFailedRecoveryFirstSide != LINE_RECOVERY_SIDE_NONE) {
    return oppositeRecoverySide(previousFailedRecoveryFirstSide);
  }

  LineRecoverySide selected = recoveryAlternatingDefaultLeft
    ? LINE_RECOVERY_SIDE_LEFT
    : LINE_RECOVERY_SIDE_RIGHT;
  recoveryAlternatingDefaultLeft = !recoveryAlternatingDefaultLeft;
  return selected;
}

static void printLineRecoveryDiagnostic(unsigned long now) {
  if (
    recoveryLastDiagnosticMs != 0 &&
    now - recoveryLastDiagnosticMs < RECOVERY_DIAGNOSTIC_INTERVAL_MS
  ) {
    return;
  }

  recoveryLastDiagnosticMs = now;
  Serial.print("LINE|RECOVERY|STATE=");
  Serial.print(lineRecoveryStateName());
  Serial.print("|PATTERN=");
  printLinePatternBits(latestLinePattern);
  Serial.print("|ERROR=");
  Serial.print(latestLinePositionError, 2);
  Serial.print("|ANGLE=");
  Serial.print(recoveryRelativeHeadingDeg, 1);
  Serial.print("|CYCLE=");
  Serial.println((unsigned int)recoveryScanCycle + 1U);
}

static void updateRecoveryHeading(unsigned long now) {
  if (!recoveryGyroInitialized) return;

  if (recoveryLastGyroUpdateMs == 0) {
    recoveryLastGyroUpdateMs = now;
    return;
  }

  float deltaSeconds = (now - recoveryLastGyroUpdateMs) / 1000.0f;
  recoveryLastGyroUpdateMs = now;
  if (
    recoveryCommandedTurnSide == LINE_RECOVERY_SIDE_NONE ||
    !recoveryGyroAvailable
  ) {
    return;
  }

  sensors_event_t acceleration, gyro, temperature;
  if (!mpu.getEvent(&acceleration, &gyro, &temperature)) {
    recoveryGyroAvailable = false;
    return;
  }

  float angularSpeedDegPerSecond =
    (gyro.gyro.x - gyroBiasX) * (180.0f / PI);
  if (abs(angularSpeedDegPerSecond) <= GYRO_THRESHOLD) return;

  float deltaAngle = abs(angularSpeedDegPerSecond) * deltaSeconds;
  if (recoveryCommandedTurnSide == LINE_RECOVERY_SIDE_LEFT) {
    recoveryRelativeHeadingDeg -= deltaAngle;
  } else {
    recoveryRelativeHeadingDeg += deltaAngle;
  }
}

static void failLineRecovery() {
  lineRecoveryState = LINE_RECOVERY_FAILED;
  if (recoveryPrimarySide != LINE_RECOVERY_SIDE_NONE) {
    previousFailedRecoveryFirstSide = recoveryPrimarySide;
  }
  stopLineFollowingForEvent(LINE_FOLLOW_LINE_LOST, "LINE_LOST");
}

static void captureInterruptedRecovery(unsigned long now) {
  recoveryInterruptedState = lineRecoveryState;
  recoveryInterruptedPhaseRemainingMs = 0;
  recoveryInterruptedSearchElapsedMs = 0;

  if (lineRecoveryState == LINE_RECOVERY_BRAKE) {
    unsigned long elapsed = now - recoveryPhaseStartedMs;
    recoveryInterruptedPhaseRemainingMs = elapsed >= RECOVERY_BRAKE_MS
      ? 0
      : RECOVERY_BRAKE_MS - elapsed;
  } else if (lineRecoveryState == LINE_RECOVERY_BACKTRACK) {
    unsigned long elapsed = now - recoveryPhaseStartedMs;
    recoveryInterruptedPhaseRemainingMs =
      elapsed >= recoveryBacktrackDurationMs
        ? 0
        : recoveryBacktrackDurationMs - elapsed;
  } else if (
    lineRecoveryState == LINE_RECOVERY_GYRO_SEARCH ||
    lineRecoveryState == LINE_RECOVERY_RETURN_TO_ORIGIN
  ) {
    recoveryInterruptedSearchElapsedMs = now - recoverySearchStageStartedMs;
  }
}

static void setRecoveryContactDifferential(uint8_t leftPwm, uint8_t rightPwm) {
  recoveryLastContactMotion = LINE_RECOVERY_CONTACT_DIFFERENTIAL;
  recoveryLastContactLeftPwm = leftPwm;
  recoveryLastContactRightPwm = rightPwm;
  driveForwardDifferential(leftPwm, rightPwm);
}

static void setRecoveryContactPivot(LineRecoverySide physicalSide) {
  recoveryLastContactLeftPwm = RECOVERY_TRACK_PIVOT_PWM;
  recoveryLastContactRightPwm = RECOVERY_TRACK_PIVOT_PWM;
  recoveryCommandedTurnSide = physicalSide;
  if (physicalSide == LINE_RECOVERY_SIDE_LEFT) {
    recoveryLastContactMotion = LINE_RECOVERY_CONTACT_PIVOT_LEFT;
    lineFollowState = LINE_FOLLOW_CORRECTING_LEFT;
    // On this chassis the helper name is inverted relative to physical motion.
    turnRightInPlaceAt(RECOVERY_TRACK_PIVOT_PWM);
  } else {
    recoveryLastContactMotion = LINE_RECOVERY_CONTACT_PIVOT_RIGHT;
    lineFollowState = LINE_FOLLOW_CORRECTING_RIGHT;
    // On this chassis the helper name is inverted relative to physical motion.
    turnLeftInPlaceAt(RECOVERY_TRACK_PIVOT_PWM);
  }
}

static void applyRecoveryContactSteering() {
  uint8_t contactMask = currentLineContactMask();
  if (contactMask == 0x01) {
    setRecoveryContactPivot(LINE_RECOVERY_SIDE_LEFT);
    return;
  }
  if (contactMask == 0x10) {
    setRecoveryContactPivot(LINE_RECOVERY_SIDE_RIGHT);
    return;
  }

  if (latestLinePositionError <= -1.5f) {
    setRecoveryContactPivot(LINE_RECOVERY_SIDE_LEFT);
    return;
  }
  if (latestLinePositionError >= 1.5f) {
    setRecoveryContactPivot(LINE_RECOVERY_SIDE_RIGHT);
    return;
  }

  int correction = (int)roundf(
    latestLinePositionError * RECOVERY_TRACK_PROPORTIONAL_GAIN
  );
  correction = constrain(
    correction,
    -(int)RECOVERY_TRACK_MAX_CORRECTION,
    (int)RECOVERY_TRACK_MAX_CORRECTION
  );
  int leftPwm = constrain((int)RECOVERY_TRACK_BASE_PWM + correction, 0, 255);
  int rightPwm = constrain((int)RECOVERY_TRACK_BASE_PWM - correction, 0, 255);
  if (leftPwm > 0 && leftPwm < RECOVERY_MIN_MOVING_PWM) {
    leftPwm = RECOVERY_MIN_MOVING_PWM;
  }
  if (rightPwm > 0 && rightPwm < RECOVERY_MIN_MOVING_PWM) {
    rightPwm = RECOVERY_MIN_MOVING_PWM;
  }

  recoveryCommandedTurnSide = latestLinePositionError < -0.1f
    ? LINE_RECOVERY_SIDE_LEFT
    : (
      latestLinePositionError > 0.1f
        ? LINE_RECOVERY_SIDE_RIGHT
        : LINE_RECOVERY_SIDE_NONE
    );
  lineFollowState = latestLinePositionError < -0.1f
    ? LINE_FOLLOW_CORRECTING_LEFT
    : (
      latestLinePositionError > 0.1f
        ? LINE_FOLLOW_CORRECTING_RIGHT
        : LINE_FOLLOW_CENTERED
    );
  setRecoveryContactDifferential((uint8_t)leftPwm, (uint8_t)rightPwm);
}

static void applyLastRecoveryContactSteering() {
  switch (recoveryLastContactMotion) {
    case LINE_RECOVERY_CONTACT_DIFFERENTIAL:
      driveForwardDifferential(
        recoveryLastContactLeftPwm,
        recoveryLastContactRightPwm
      );
      break;
    case LINE_RECOVERY_CONTACT_PIVOT_LEFT:
      recoveryCommandedTurnSide = LINE_RECOVERY_SIDE_LEFT;
      turnRightInPlaceAt(RECOVERY_TRACK_PIVOT_PWM);
      break;
    case LINE_RECOVERY_CONTACT_PIVOT_RIGHT:
      recoveryCommandedTurnSide = LINE_RECOVERY_SIDE_RIGHT;
      turnLeftInPlaceAt(RECOVERY_TRACK_PIVOT_PWM);
      break;
    case LINE_RECOVERY_CONTACT_STOPPED:
      recoveryCommandedTurnSide = LINE_RECOVERY_SIDE_NONE;
      stopMotorOutputs();
      break;
  }
}

static float recoverySearchTargetForStage(uint8_t stage) {
  float primarySign = recoveryPrimarySide == LINE_RECOVERY_SIDE_LEFT
    ? -1.0f
    : 1.0f;
  switch (stage) {
    case 0: return primarySign * RECOVERY_PRIMARY_HEADING_DEG;
    case 1: return -primarySign * RECOVERY_OPPOSITE_HEADING_DEG;
    case 2: return primarySign * RECOVERY_EXPANDED_HEADING_DEG;
    case 3: return -primarySign * RECOVERY_EXPANDED_HEADING_DEG;
    default: return 0.0f;
  }
}

static void commandRecoverySearchMotion() {
  if (recoveryGyroAvailable) {
    float remaining = recoveryTargetHeadingDeg - recoveryRelativeHeadingDeg;
    if (abs(remaining) <= RECOVERY_HEADING_TOLERANCE_DEG) {
      recoveryCommandedTurnSide = LINE_RECOVERY_SIDE_NONE;
      stopMotorOutputs();
      return;
    }
    recoveryCommandedTurnSide = remaining < 0.0f
      ? LINE_RECOVERY_SIDE_LEFT
      : LINE_RECOVERY_SIDE_RIGHT;
  } else {
    bool primaryStage =
      recoverySearchStage == 0 ||
      recoverySearchStage == 2 ||
      recoverySearchStage >= 4;
    recoveryCommandedTurnSide = primaryStage
      ? recoveryPrimarySide
      : oppositeRecoverySide(recoveryPrimarySide);
  }

  if (recoveryCommandedTurnSide == LINE_RECOVERY_SIDE_LEFT) {
    lineFollowState = LINE_FOLLOW_SEARCHING_LEFT;
    // Physical LEFT uses the right-named helper on this motor wiring.
    turnRightInPlaceAt(RECOVERY_SEARCH_PWM);
  } else {
    lineFollowState = LINE_FOLLOW_SEARCHING_RIGHT;
    // Physical RIGHT uses the left-named helper on this motor wiring.
    turnLeftInPlaceAt(RECOVERY_SEARCH_PWM);
  }
}

static void startRecoverySearchStage(unsigned long now, uint8_t stage) {
  recoverySearchStage = stage;
  recoveryTargetHeadingDeg = recoverySearchTargetForStage(stage);
  recoverySearchStageStartedMs = now;
  recoveryLastGyroUpdateMs = now;
  lineRecoveryState = stage >= 4
    ? LINE_RECOVERY_RETURN_TO_ORIGIN
    : LINE_RECOVERY_GYRO_SEARCH;
  commandRecoverySearchMotion();
}

static void startRecoveryBacktrack(unsigned long now, unsigned long durationMs) {
  lineRecoveryState = LINE_RECOVERY_BACKTRACK;
  recoveryPhaseStartedMs = now;
  recoveryBacktrackDurationMs = durationMs;
  recoveryCommandedTurnSide = LINE_RECOVERY_SIDE_NONE;
  lineFollowState = LINE_FOLLOW_ACQUIRING;
  driveBackwardAt(RECOVERY_BACKTRACK_PWM);
}

static void resumeInterruptedRecovery(unsigned long now) {
  LineRecoveryState resumeState = recoveryInterruptedState;
  unsigned long remainingMs = recoveryInterruptedPhaseRemainingMs;
  unsigned long searchElapsedMs = recoveryInterruptedSearchElapsedMs;
  recoveryInterruptedState = LINE_RECOVERY_INACTIVE;
  recoveryInterruptedPhaseRemainingMs = 0;
  recoveryInterruptedSearchElapsedMs = 0;
  recoveryLastGyroUpdateMs = now;

  switch (resumeState) {
    case LINE_RECOVERY_LOST_CONFIRM:
      lineRecoveryState = LINE_RECOVERY_LOST_CONFIRM;
      recoveryCommandedTurnSide = LINE_RECOVERY_SIDE_NONE;
      stopMotorOutputs();
      break;
    case LINE_RECOVERY_BRAKE:
      lineRecoveryState = LINE_RECOVERY_BRAKE;
      recoveryPhaseStartedMs = now - (RECOVERY_BRAKE_MS - remainingMs);
      recoveryCommandedTurnSide = LINE_RECOVERY_SIDE_NONE;
      stopMotorOutputs();
      break;
    case LINE_RECOVERY_BACKTRACK:
      startRecoveryBacktrack(now, remainingMs);
      break;
    case LINE_RECOVERY_GYRO_SEARCH:
    case LINE_RECOVERY_RETURN_TO_ORIGIN:
      lineRecoveryState = resumeState;
      recoverySearchStageStartedMs = now - searchElapsedMs;
      commandRecoverySearchMotion();
      break;
    default:
      if (recoveryPrimarySide != LINE_RECOVERY_SIDE_NONE) {
        startRecoverySearchStage(now, recoverySearchStage);
      } else {
        lineRecoveryState = LINE_RECOVERY_LOST_CONFIRM;
        recoveryCommandedTurnSide = LINE_RECOVERY_SIDE_NONE;
        stopMotorOutputs();
      }
      break;
  }
}

static void startRecoveryContactTrack(unsigned long now, bool preserveResume) {
  if (!preserveResume) captureInterruptedRecovery(now);
  lineRecoveryState = LINE_RECOVERY_CONTACT_TRACK;
  recoveryContactStartedMs = now;
  recoveryContactLastSeenMs = now;
  recoveryFirstContactMask = currentLineContactMask();
  recoveryContactSeenMask = recoveryFirstContactMask;
  recoveryBestAbsoluteError = abs(latestLinePositionError);
  recoveryContactProgress = lineDetected[2];
  applyRecoveryContactSteering();
}

static void startRecoveryWideBlackVerify(unsigned long now, bool preserveResume) {
  if (!preserveResume) captureInterruptedRecovery(now);
  lineRecoveryState = LINE_RECOVERY_WIDE_BLACK_VERIFY;
  recoveryPhaseStartedMs = now;
  recoveryWideConsecutiveReadings = lineDetected[2] ? 1 : 0;
  recoveryCommandedTurnSide = LINE_RECOVERY_SIDE_NONE;
  stopMotorOutputs();
  driveForwardAt(RECOVERY_WIDE_FORWARD_PWM);
}

static void startRecoveryLineLock(unsigned long now) {
  lineRecoveryState = LINE_RECOVERY_LINE_LOCK;
  recoveryLineLockStartedMs = now;
  recoveryContactLastSeenMs = now;
  recoveryLineLockSawInnerSensor =
    lineDetected[1] || lineDetected[2] || lineDetected[3];
  applyRecoveryContactSteering();
}

static void updateRecoveryContactEvidence() {
  uint8_t currentMask = currentLineContactMask();
  recoveryContactSeenMask |= currentMask;

  uint8_t adjacentMask = 0;
  for (uint8_t i = 0; i < LINE_SENSOR_COUNT; i++) {
    if ((recoveryFirstContactMask & (uint8_t)(1U << i)) == 0) continue;
    if (i > 0) adjacentMask |= (uint8_t)(1U << (i - 1));
    if (i + 1 < LINE_SENSOR_COUNT) {
      adjacentMask |= (uint8_t)(1U << (i + 1));
    }
  }
  adjacentMask &= (uint8_t)~recoveryFirstContactMask;
  if ((recoveryContactSeenMask & adjacentMask) != 0) {
    recoveryContactProgress = true;
  }

  float absoluteError = abs(latestLinePositionError);
  if (absoluteError + 0.05f < recoveryBestAbsoluteError) {
    recoveryContactProgress = true;
  }
  if (absoluteError < recoveryBestAbsoluteError) {
    recoveryBestAbsoluteError = absoluteError;
  }
  if (lineDetected[2]) recoveryContactProgress = true;
  if (
    (recoveryFirstContactMask & 0x01) != 0 &&
    (recoveryContactSeenMask & 0x06) != 0
  ) {
    recoveryContactProgress = true;
  }
  if (
    (recoveryFirstContactMask & 0x10) != 0 &&
    (recoveryContactSeenMask & 0x0C) != 0
  ) {
    recoveryContactProgress = true;
  }
}

static bool handleImmediateRecoveryContact(unsigned long now) {
  if (latestLineActiveCount >= LINE_INTERSECTION_MIN_SENSORS) {
    startRecoveryWideBlackVerify(now, false);
    return true;
  }
  if (latestLineActiveCount > 0) {
    startRecoveryContactTrack(now, false);
    return true;
  }
  return false;
}

static void updateRecoveryLostConfirmation(unsigned long now) {
  if (latestLineActiveCount >= LINE_INTERSECTION_MIN_SENSORS) {
    startRecoveryWideBlackVerify(now, false);
    return;
  }
  if (latestLineActiveCount > 0) {
    resetLineSearch();
    consecutiveIntersectionReadings = 0;
    lastLineFollowUpdateMs = now;
    applyProportionalLineControl();
    return;
  }

  if (recoveryLostReadings < 255) recoveryLostReadings++;
  if (recoveryLostReadings < LINE_LOST_CONFIRM_READINGS) return;

  recoveryPrimarySide = chooseRecoveryPrimarySide();
  recoveryRelativeHeadingDeg = 0.0f;
  recoveryTargetHeadingDeg = 0.0f;
  recoveryGyroInitialized = true;
  recoveryGyroAvailable = true;
  recoveryLastGyroUpdateMs = now;
  recoveryCommandedTurnSide = LINE_RECOVERY_SIDE_NONE;
  recoveryScanCycle = 0;
  recoverySearchStage = 0;
  lineRecoveryState = LINE_RECOVERY_BRAKE;
  recoveryPhaseStartedMs = now;
  lineFollowState = LINE_FOLLOW_ACQUIRING;
  stopMotorOutputs();
}

static void updateRecoveryBrake(unsigned long now) {
  if (handleImmediateRecoveryContact(now)) return;
  if (now - recoveryPhaseStartedMs >= RECOVERY_BRAKE_MS) {
    startRecoveryBacktrack(now, RECOVERY_BACKTRACK_MS);
  } else {
    recoveryCommandedTurnSide = LINE_RECOVERY_SIDE_NONE;
    stopMotorOutputs();
  }
}

static void updateRecoveryBacktrack(unsigned long now) {
  if (handleImmediateRecoveryContact(now)) return;
  if (now - recoveryPhaseStartedMs >= recoveryBacktrackDurationMs) {
    startRecoverySearchStage(now, 0);
  } else {
    recoveryCommandedTurnSide = LINE_RECOVERY_SIDE_NONE;
    driveBackwardAt(RECOVERY_BACKTRACK_PWM);
  }
}

static bool recoverySearchTargetReached(unsigned long now) {
  if (recoveryGyroAvailable) {
    float remaining = recoveryTargetHeadingDeg - recoveryRelativeHeadingDeg;
    if (abs(remaining) <= RECOVERY_HEADING_TOLERANCE_DEG) return true;
    if (
      recoveryCommandedTurnSide == LINE_RECOVERY_SIDE_LEFT &&
      recoveryRelativeHeadingDeg <= recoveryTargetHeadingDeg
    ) {
      return true;
    }
    if (
      recoveryCommandedTurnSide == LINE_RECOVERY_SIDE_RIGHT &&
      recoveryRelativeHeadingDeg >= recoveryTargetHeadingDeg
    ) {
      return true;
    }
    return false;
  }

  uint8_t fallbackIndex = recoverySearchStage < 4
    ? recoverySearchStage
    : 3;
  return now - recoverySearchStageStartedMs >=
    RECOVERY_FALLBACK_SWEEP_MS[fallbackIndex];
}

static void finishRecoveryScanCycle(unsigned long now) {
  if (recoveryScanCycle + 1U < RECOVERY_MAX_SCAN_CYCLES) {
    recoveryScanCycle++;
    startRecoveryBacktrack(now, RECOVERY_SECOND_BACKTRACK_MS);
  } else {
    failLineRecovery();
  }
}

static void updateRecoverySearch(unsigned long now) {
  if (handleImmediateRecoveryContact(now)) return;

  if (!recoverySearchTargetReached(now)) {
    commandRecoverySearchMotion();
    return;
  }

  stopMotorOutputs();
  recoveryCommandedTurnSide = LINE_RECOVERY_SIDE_NONE;
  if (lineRecoveryState == LINE_RECOVERY_RETURN_TO_ORIGIN) {
    finishRecoveryScanCycle(now);
  } else if (recoverySearchStage < 3) {
    startRecoverySearchStage(now, recoverySearchStage + 1U);
  } else {
    startRecoverySearchStage(now, 4);
  }
}

static void updateRecoveryContactTrack(unsigned long now) {
  if (latestLineActiveCount >= LINE_INTERSECTION_MIN_SENSORS) {
    startRecoveryWideBlackVerify(now, true);
    return;
  }

  if (latestLineActiveCount == 0) {
    if (
      now - recoveryContactLastSeenMs > RECOVERY_CONTACT_LOSS_GRACE_MS ||
      now - recoveryContactStartedMs >= RECOVERY_CONTACT_VERIFY_TIMEOUT_MS
    ) {
      resumeInterruptedRecovery(now);
    } else {
      applyLastRecoveryContactSteering();
    }
    return;
  }

  recoveryContactLastSeenMs = now;
  updateRecoveryContactEvidence();
  applyRecoveryContactSteering();
  if (recoveryContactProgress) {
    startRecoveryLineLock(now);
  } else if (
    now - recoveryContactStartedMs >= RECOVERY_CONTACT_VERIFY_TIMEOUT_MS
  ) {
    resumeInterruptedRecovery(now);
  }
}

static void updateRecoveryWideBlackVerify(unsigned long now) {
  if (latestLineActiveCount == 0) {
    resumeInterruptedRecovery(now);
    return;
  }
  if (latestLineActiveCount < LINE_INTERSECTION_MIN_SENSORS) {
    startRecoveryContactTrack(now, true);
    return;
  }

  if (lineDetected[2]) {
    if (recoveryWideConsecutiveReadings < 255) {
      recoveryWideConsecutiveReadings++;
    }
    if (
      recoveryWideConsecutiveReadings >= RECOVERY_WIDE_VERIFY_READINGS
    ) {
      stopLineFollowingForEvent(LINE_FOLLOW_INTERSECTION, "INTERSECTION");
      return;
    }
  } else {
    recoveryWideConsecutiveReadings = 0;
  }

  if (now - recoveryPhaseStartedMs >= RECOVERY_WIDE_VERIFY_TIMEOUT_MS) {
    resumeInterruptedRecovery(now);
    return;
  }

  recoveryCommandedTurnSide = LINE_RECOVERY_SIDE_NONE;
  driveForwardAt(RECOVERY_WIDE_FORWARD_PWM);
}

static void completeLineRecovery(unsigned long now) {
  resetLineSearch();
  consecutiveIntersectionReadings = 0;
  lastLineFollowUpdateMs = now;
  applyProportionalLineControl();
}

static void updateRecoveryLineLock(unsigned long now) {
  if (latestLineActiveCount >= LINE_INTERSECTION_MIN_SENSORS) {
    startRecoveryWideBlackVerify(now, true);
    return;
  }

  if (latestLineActiveCount == 0) {
    // A brief dropout keeps the last steering command, but it does not count
    // toward the required continuous low-speed lock interval.
    recoveryLineLockStartedMs = now;
    if (
      now - recoveryContactLastSeenMs > RECOVERY_LOCK_LOSS_GRACE_MS
    ) {
      resumeInterruptedRecovery(now);
    } else {
      applyLastRecoveryContactSteering();
    }
    return;
  }

  recoveryContactLastSeenMs = now;
  recoveryLineLockSawInnerSensor =
    recoveryLineLockSawInnerSensor ||
    lineDetected[1] || lineDetected[2] || lineDetected[3];
  applyRecoveryContactSteering();
  if (now - recoveryLineLockStartedMs >= RECOVERY_LINE_LOCK_MS) {
    if (recoveryLineLockSawInnerSensor) {
      completeLineRecovery(now);
    } else {
      resumeInterruptedRecovery(now);
    }
  }
}

static void updateLineRecovery(unsigned long now) {
  updateRecoveryHeading(now);
  printLineRecoveryDiagnostic(now);

  if (
    recoveryStartedMs != 0 &&
    now - recoveryStartedMs >= RECOVERY_TOTAL_TIMEOUT_MS
  ) {
    failLineRecovery();
    return;
  }

  switch (lineRecoveryState) {
    case LINE_RECOVERY_LOST_CONFIRM:
      updateRecoveryLostConfirmation(now);
      break;
    case LINE_RECOVERY_BRAKE:
      updateRecoveryBrake(now);
      break;
    case LINE_RECOVERY_BACKTRACK:
      updateRecoveryBacktrack(now);
      break;
    case LINE_RECOVERY_GYRO_SEARCH:
    case LINE_RECOVERY_RETURN_TO_ORIGIN:
      updateRecoverySearch(now);
      break;
    case LINE_RECOVERY_CONTACT_TRACK:
      updateRecoveryContactTrack(now);
      break;
    case LINE_RECOVERY_WIDE_BLACK_VERIFY:
      updateRecoveryWideBlackVerify(now);
      break;
    case LINE_RECOVERY_LINE_LOCK:
      updateRecoveryLineLock(now);
      break;
    case LINE_RECOVERY_FAILED:
      failLineRecovery();
      break;
    case LINE_RECOVERY_INACTIVE:
      break;
  }
}

static void startLineLostConfirmation(unsigned long now) {
  resetLineSearch();
  lineRecoveryState = LINE_RECOVERY_LOST_CONFIRM;
  recoveryLostReadings = 1;
  recoveryStartedMs = now;
  lastRecoverySampleMs = now;
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
  uturnOriginalLineCleared = false;
  uturnConsecutiveAllWhiteReadings = 0;
  uturnConsecutiveValidLineReadings = 0;
  uturnLastDiagnosticMs = 0;
  uturnPivotElapsedMs = 0;
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

static void failIntersectionNavigationWithUturnReason(const char* reason) {
  if (intersectionDirection == INTERSECTION_DIRECTION_U_TURN) {
    Serial.print("UTURN|FAILURE=");
    Serial.println(reason);
  }
  failIntersectionNavigation();
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
  uturnOriginalLineCleared = false;
  uturnConsecutiveAllWhiteReadings = 0;
  uturnConsecutiveValidLineReadings = 0;
  uturnLastDiagnosticMs = 0;
  uturnPivotElapsedMs = 0;
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
  uturnOriginalLineCleared = false;
  uturnConsecutiveAllWhiteReadings = 0;
  uturnConsecutiveValidLineReadings = 0;
  uturnLastDiagnosticMs = 0;
  uturnPivotElapsedMs = 0;
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
      failIntersectionNavigationWithUturnReason("ALIGN_LINE_LOST");
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
    failIntersectionNavigationWithUturnReason("ALIGN_TIMEOUT");
    return;
  }

  if (!updateIntersectionTurnAngle(now, intersectionAlignmentPivotLeft)) {
    failIntersectionNavigationWithUturnReason("GYRO_READ");
    return;
  }

  if (intersectionTurnAngleDeg > maxAngleDeg) {
    failIntersectionNavigationWithUturnReason("MAX_ANGLE");
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
    failIntersectionNavigationWithUturnReason("LOCK_TIMEOUT");
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

static void updateUturnOriginalLineClearance() {
  if (uturnOriginalLineCleared) return;

  if (latestLinePattern == 0x1F) {
    if (uturnConsecutiveAllWhiteReadings < 255) {
      uturnConsecutiveAllWhiteReadings++;
    }
    if (
      uturnConsecutiveAllWhiteReadings >=
      UTURN_ORIGINAL_LINE_CLEAR_READINGS
    ) {
      uturnOriginalLineCleared = true;
    }
  } else {
    uturnConsecutiveAllWhiteReadings = 0;
  }
}

static void printUturnDiagnostic(unsigned long now) {
  if (
    uturnLastDiagnosticMs != 0 &&
    now - uturnLastDiagnosticMs < UTURN_DIAGNOSTIC_INTERVAL_MS
  ) {
    return;
  }

  uturnLastDiagnosticMs = now;
  Serial.print("UTURN|STATE=");
  Serial.print(intersectionNavigationStateName());
  Serial.print("|ANGLE_DEG=");
  Serial.print(intersectionTurnAngleDeg, 1);
  Serial.print("|PATTERN=");
  printLinePatternBits(latestLinePattern);
  Serial.print("|ACTIVE_COUNT=");
  Serial.print(latestLineActiveCount);
  Serial.print("|ORIGINAL_LINE_CLEARED=");
  Serial.print(uturnOriginalLineCleared ? 1 : 0);
  Serial.print("|VALID_LINE=");
  Serial.print(isValidUturnSearchPattern() ? 1 : 0);
  Serial.print("|CONFIRM_COUNT=");
  Serial.print(uturnConsecutiveValidLineReadings);
  Serial.print("|PIVOT_ELAPSED_MS=");
  Serial.println(uturnPivotElapsedMs);
}

static void updateUturnNavigation(unsigned long now) {
  if (now - uTurnStartedMs >= UTURN_TOTAL_TIMEOUT_MS) {
    failIntersectionNavigationWithUturnReason("TOTAL_TIMEOUT");
    return;
  }

  if (intersectionNavigationState == INTERSECTION_UTURN_PIVOT_SEARCH) {
    uturnPivotElapsedMs = now - intersectionPhaseStartedMs;
    // The initial U-turn always pivots physical RIGHT. The original line must
    // first clear for three all-white readings, and reacquisition remains
    // disabled until the gyro reaches the minimum search angle.
    if (!updateIntersectionTurnAngle(now, false)) {
      failIntersectionNavigationWithUturnReason("GYRO_READ");
      return;
    }

    updateUturnOriginalLineClearance();

    bool validLineContact =
      uturnOriginalLineCleared &&
      intersectionTurnAngleDeg >= UTURN_SENSOR_SEARCH_MIN_ANGLE_DEG &&
      isValidUturnSearchPattern();
    if (validLineContact) {
      bool firstContact = uturnConsecutiveValidLineReadings == 0;
      if (uturnConsecutiveValidLineReadings < 255) {
        uturnConsecutiveValidLineReadings++;
      }

      // Remove fast-pivot torque on the first eligible contact. The remaining
      // temporal confirmation samples are collected while stationary so the
      // sensor array cannot be driven past O5/O4 at PWM 180.
      stopMotorOutputs();
      if (firstContact) {
        Serial.print("UTURN|CONTACT=FIRST|ANGLE_DEG=");
        Serial.print(intersectionTurnAngleDeg, 1);
        Serial.print("|PATTERN=");
        printLinePatternBits(latestLinePattern);
        Serial.print("|ACTIVE_COUNT=");
        Serial.print(latestLineActiveCount);
        Serial.println(
          "|EXPECTED_FIRST_SENSOR=O5|ACTION=STOP_CONFIRM"
        );
      } else {
        Serial.print("UTURN|CONTACT_CONFIRM|COUNT=");
        Serial.print(uturnConsecutiveValidLineReadings);
        Serial.print("|PATTERN=");
        printLinePatternBits(latestLinePattern);
        Serial.println("|MOTION=STOPPED");
      }
    } else if (uturnConsecutiveValidLineReadings > 0) {
      uint8_t previousConfirmationCount =
        uturnConsecutiveValidLineReadings;
      uturnConsecutiveValidLineReadings = 0;
      Serial.print("UTURN|CONTACT=REJECTED|PREVIOUS_COUNT=");
      Serial.print(previousConfirmationCount);
      Serial.print("|PATTERN=");
      printLinePatternBits(latestLinePattern);
      Serial.println("|ACTION=RESUME_FAST_PIVOT");
    }

    printUturnDiagnostic(now);

    if (
      uturnConsecutiveValidLineReadings >= UTURN_LINE_CONFIRM_READINGS
    ) {
      Serial.print(
        "UTURN|TRANSITION=PIVOT_SEARCH_TO_SENSOR_ALIGN|"
        "REASON=LINE_CONFIRMED|ANGLE_DEG="
      );
      Serial.print(intersectionTurnAngleDeg, 1);
      Serial.print("|PATTERN=");
      printLinePatternBits(latestLinePattern);
      Serial.print("|CONFIRM_COUNT=");
      Serial.println(uturnConsecutiveValidLineReadings);
      uturnConsecutiveValidLineReadings = 0;
      startSensorGuidedPivotAlignment(now);
      return;
    }

    if (uturnPivotElapsedMs >= UTURN_PIVOT_TIMEOUT_MS) {
      failIntersectionNavigationWithUturnReason("PIVOT_TIMEOUT");
      return;
    }

    if (intersectionTurnAngleDeg >= UTURN_MAX_ANGLE_DEG) {
      failIntersectionNavigationWithUturnReason("MAX_ANGLE");
      return;
    }

    if (uturnConsecutiveValidLineReadings > 0) {
      // Hold motor output off until the temporal contact confirmation finishes.
      return;
    }

    driveIntersectionManeuver();
    return;
  }

  if (intersectionNavigationState == INTERSECTION_UTURN_SENSOR_ALIGN) {
    printUturnDiagnostic(now);
    updateSensorGuidedPivotAlignment(now);
    return;
  }

  if (intersectionNavigationState == INTERSECTION_UTURN_LINE_LOCK) {
    printUturnDiagnostic(now);
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
  if (lineRecoveryState != LINE_RECOVERY_INACTIVE) {
    unsigned long recoveryIntervalMs =
      lineRecoveryState == LINE_RECOVERY_LOST_CONFIRM
        ? LINE_FOLLOW_INTERVAL_MS
        : RECOVERY_SAMPLE_INTERVAL_MS;
    if (now - lastRecoverySampleMs < recoveryIntervalMs) return;
    lastRecoverySampleMs = now;
    sampleLineSensors();
    updateLineRecovery(now);
    return;
  }

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
    startLineLostConfirmation(now);
    return;
  }

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

  Serial.print("RTC Time: ");
  Serial.println(dateTimeString);
}

void showMedicineWorkflowStatus(const String& state) {
  if (state == "HAND_WAITING") {
    lcdShowStatus("Take a cup", "Place under water", "Place hand below", "Waiting...");
  } else if (state == "HAND_DETECTED") {
    lcdShowStatus("Hand detected");
  } else if (state == "DISPENSING") {
    lcdShowStatus("Dispensing medicine", "Please wait");
  } else if (state == "WATER_DISPENSING") {
    lcdShowStatus("Dispensing water", "Please wait");
  } else if (state == "MEDICINE_READY") {
    lcdShowStatus("Medicine & water", "ready");
  } else if (state == "NO_HAND") {
    lcdShowStatus("No hand detected");
  } else if (state == "DISPENSE_FAILED") {
    lcdShowStatus("Dispense failed");
  }
}

void showPickupCountdown(unsigned int secondsRemaining) {
  lcdShowStatus(
    "Take med & water",
    String("Returning in: ") + String(secondsRemaining)
  );
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

void printRTCMachineReadable() {
  RtcDateTime now = rtc.GetDateTime();
  if (!now.IsValid()) {
    Serial.println("ERROR|RTC_INVALID");
    return;
  }

  char response[64];
  snprintf(
    response,
    sizeof(response),
    "RTC|YYYY=%04u|MM=%02u|DD=%02u|HH=%02u|MIN=%02u|SEC=%02u",
    now.Year(),
    now.Month(),
    now.Day(),
    now.Hour(),
    now.Minute(),
    now.Second()
  );
  Serial.println(response);
}

static bool parseRTCDigits(
  const String& command,
  size_t start,
  size_t width,
  uint16_t& value
) {
  value = 0;
  for (size_t index = start; index < start + width; index++) {
    char character = command.charAt(index);
    if (!isDigit(character)) {
      return false;
    }
    value = (value * 10) + (character - '0');
  }
  return true;
}

static bool isRTCLeapYear(uint16_t year) {
  return (year % 4 == 0) && ((year % 100 != 0) || (year % 400 == 0));
}

static uint8_t rtcDaysInMonth(uint16_t year, uint8_t month) {
  static const uint8_t daysByMonth[] = {
    31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31
  };
  if (month < 1 || month > 12) {
    return 0;
  }
  if (month == 2 && isRTCLeapYear(year)) {
    return 29;
  }
  return daysByMonth[month - 1];
}

void handleSetRTCCommand(const String& command) {
  // Exact grammar:
  // SET_RTC|YYYY=2026|MM=08|DD=23|HH=13|MIN=30|SEC=00
  if (
    command.length() != 49 ||
    !command.startsWith("SET_RTC|YYYY=") ||
    command.substring(18, 21) != "MM=" ||
    command.substring(24, 27) != "DD=" ||
    command.substring(30, 33) != "HH=" ||
    command.substring(36, 40) != "MIN=" ||
    command.substring(43, 47) != "SEC=" ||
    command.charAt(17) != '|' ||
    command.charAt(23) != '|' ||
    command.charAt(29) != '|' ||
    command.charAt(35) != '|' ||
    command.charAt(42) != '|'
  ) {
    Serial.println("ERROR|SET_RTC|INVALID_FORMAT");
    return;
  }

  uint16_t year;
  uint16_t month;
  uint16_t day;
  uint16_t hour;
  uint16_t minute;
  uint16_t second;
  if (
    !parseRTCDigits(command, 13, 4, year) ||
    !parseRTCDigits(command, 21, 2, month) ||
    !parseRTCDigits(command, 27, 2, day) ||
    !parseRTCDigits(command, 33, 2, hour) ||
    !parseRTCDigits(command, 40, 2, minute) ||
    !parseRTCDigits(command, 47, 2, second)
  ) {
    Serial.println("ERROR|SET_RTC|INVALID_FORMAT");
    return;
  }

  if (
    year < 2000 || year > 2099 ||
    month < 1 || month > 12 ||
    day < 1 || day > rtcDaysInMonth(year, month) ||
    hour > 23 || minute > 59 || second > 59
  ) {
    Serial.println("ERROR|SET_RTC|INVALID_DATETIME");
    return;
  }

  if (rtc.GetIsWriteProtected()) {
    rtc.SetIsWriteProtected(false);
  }
  if (rtc.GetIsWriteProtected()) {
    Serial.println("ERROR|SET_RTC|WRITE_FAILED");
    return;
  }

  RtcDateTime requested(year, month, day, hour, minute, second);
  if (!requested.IsValid()) {
    Serial.println("ERROR|SET_RTC|INVALID_DATETIME");
    return;
  }

  rtc.SetDateTime(requested);
  if (!rtc.GetIsRunning()) {
    rtc.SetIsRunning(true);
  }

  RtcDateTime confirmed = rtc.GetDateTime();
  if (
    !confirmed.IsValid() ||
    confirmed.Year() != year ||
    confirmed.Month() != month ||
    confirmed.Day() != day ||
    confirmed.Hour() != hour ||
    confirmed.Minute() != minute ||
    confirmed.Second() != second
  ) {
    Serial.println("ERROR|SET_RTC|WRITE_FAILED");
    return;
  }

  char response[72];
  snprintf(
    response,
    sizeof(response),
    "ACK|SET_RTC|YYYY=%04u|MM=%02u|DD=%02u|HH=%02u|MIN=%02u|SEC=%02u",
    confirmed.Year(),
    confirmed.Month(),
    confirmed.Day(),
    confirmed.Hour(),
    confirmed.Minute(),
    confirmed.Second()
  );
  Serial.println(response);
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

void runPumpForDuration(unsigned long durationMs) {
  if (durationMs < WATER_MIN_DURATION_MS || durationMs > WATER_MAX_DURATION_MS) {
    Serial.println("ERROR|INVALID_WATER_DURATION");
    return;
  }

  if (
    autoModeEnabled ||
    lineFollowEnabled ||
    intersectionNavigationActive ||
    manualMovementActive
  ) {
    Serial.println("ERROR|ROBOT_BUSY");
    return;
  }

  stopAllOutputs();
  Serial.print("ACK|WATER|DURATION_MS=");
  Serial.println(durationMs);
  lcdShowStatus("Dispensing water", "Please wait");
  pumpOn();

  bool completed = waitSafely(durationMs);
  pumpOff();
  lcdShowStatus("Water", "OFF");

  if (!completed) {
    Serial.println("ERROR|WATER_INTERRUPTED");
    return;
  }

  Serial.print("DONE|WATER|DURATION_MS=");
  Serial.println(durationMs);
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
      // The HC-SR04 is now mounted over the water tank. The legacy obstacle
      // avoidance mode must not drive using a water-surface distance.
      Serial.println("ERROR|AUTONOMOUS_MODE_DISABLED");
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
      Serial.println("ACK|PUMP|STATE=OFF");
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
      Serial.println("ACK|PUMP|STATE=ON");
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

static void prepareManualDrive() {
  if (autoModeEnabled) {
    stopAutonomousMode("manual drive command", 'M');
  }
  cancelIntersectionNavigation();
  disableLineFollowing(LINE_FOLLOW_IDLE);
  stopMotorOutputs();
  manualMovementActive = false;
}

static void handleManualDriveCommand(const String& command) {
  prepareManualDrive();

  if (command == "MANUAL_FORWARD") {
    driveForwardAt(MANUAL_STRAIGHT_PWM);
  } else if (command == "MANUAL_BACKWARD") {
    driveBackwardAt(MANUAL_STRAIGHT_PWM);
  } else if (command == "MANUAL_LEFT") {
    turnRightInPlaceAt(MANUAL_PIVOT_PWM);
  } else if (command == "MANUAL_RIGHT") {
    turnLeftInPlaceAt(MANUAL_PIVOT_PWM);
  } else if (command == "MANUAL_FORWARD_LEFT") {
    driveForwardDifferential(
      MANUAL_STRAIGHT_PWM,
      MANUAL_STEERING_INNER_PWM
    );
  } else if (command == "MANUAL_FORWARD_RIGHT") {
    driveForwardDifferential(
      MANUAL_STEERING_INNER_PWM,
      MANUAL_STRAIGHT_PWM
    );
  } else if (command == "MANUAL_BACKWARD_LEFT") {
    driveBackwardDifferential(
      MANUAL_STRAIGHT_PWM,
      MANUAL_STEERING_INNER_PWM
    );
  } else if (command == "MANUAL_BACKWARD_RIGHT") {
    driveBackwardDifferential(
      MANUAL_STEERING_INNER_PWM,
      MANUAL_STRAIGHT_PWM
    );
  } else if (command == "MANUAL_STOP") {
    lcdShowStatus("Manual Drive", "Stopped");
    Serial.println("ACK|MANUAL_STOP");
    return;
  } else {
    Serial.println("ERROR|UNKNOWN_MANUAL_COMMAND");
    return;
  }

  manualMovementActive = true;
  lcdShowStatus("Manual Drive", command.substring(7));
  Serial.print("ACK|");
  Serial.println(command);
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
  } else if (normalizedCommand == "GET_WATER_LEVEL") {
    printWaterLevel();
  } else if (normalizedCommand == "GET_HAND") {
    Serial.println(irStableDetected ? "HAND|DETECTED" : "HAND|WAITING");
  } else if (normalizedCommand.startsWith("LCD|STATE=PICKUP_WAITING|SECONDS=")) {
    String secondsText = normalizedCommand.substring(33);
    if (secondsText.length() == 0) {
      Serial.println("ERROR|INVALID_PICKUP_SECONDS");
      return;
    }
    for (size_t i = 0; i < secondsText.length(); i++) {
      if (!isDigit(secondsText.charAt(i))) {
        Serial.println("ERROR|INVALID_PICKUP_SECONDS");
        return;
      }
    }
    unsigned long seconds = strtoul(secondsText.c_str(), nullptr, 10);
    if (seconds > 30) {
      Serial.println("ERROR|INVALID_PICKUP_SECONDS");
      return;
    }
    showPickupCountdown((unsigned int)seconds);
    Serial.print("ACK|LCD|STATE=PICKUP_WAITING|SECONDS=");
    Serial.println(seconds);
  } else if (normalizedCommand.startsWith("LCD|STATE=")) {
    String state = normalizedCommand.substring(10);
    if (
      state != "HAND_WAITING" &&
      state != "HAND_DETECTED" &&
      state != "DISPENSING" &&
      state != "WATER_DISPENSING" &&
      state != "MEDICINE_READY" &&
      state != "NO_HAND" &&
      state != "DISPENSE_FAILED"
    ) {
      Serial.println("ERROR|INVALID_LCD_STATE");
      return;
    }
    showMedicineWorkflowStatus(state);
    Serial.print("ACK|LCD|STATE=");
    Serial.println(state);
  } else if (normalizedCommand == "GET_RTC") {
    printRTCMachineReadable();
  } else if (normalizedCommand.startsWith("SET_RTC")) {
    handleSetRTCCommand(normalizedCommand);
  } else if (normalizedCommand.startsWith("MANUAL_")) {
    handleManualDriveCommand(normalizedCommand);
  } else if (normalizedCommand.startsWith("WATER_DISPENSE|MS=")) {
    String durationText = normalizedCommand.substring(18);
    if (durationText.length() == 0) {
      Serial.println("ERROR|INVALID_WATER_DURATION");
      return;
    }

    for (size_t i = 0; i < durationText.length(); i++) {
      if (!isDigit(durationText.charAt(i))) {
        Serial.println("ERROR|INVALID_WATER_DURATION");
        return;
      }
    }

    runPumpForDuration(strtoul(durationText.c_str(), nullptr, 10));
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
    String receivedLine;
    SerialInputResult result = readSerialInput(receivedLine);

    if (result == SERIAL_INPUT_INCOMPLETE) {
      return;
    }

    if (result == SERIAL_INPUT_OVERFLOW) {
      Serial.println("ERROR|COMMAND_TOO_LONG");
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
  processSerialInput();

  updateIrSensor();
  updateIntersectionNavigation();
  updateLineFollowing();
  updateAutonomousMode();
  delay(5);
}
