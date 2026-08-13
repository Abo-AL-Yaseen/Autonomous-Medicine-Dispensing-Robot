#include <Stepper.h>
#include <avr/interrupt.h>
#include <string.h>

#define STEPS_PER_REV 2048
#define PILL_STEPS 256

// Pill-drop IR sensors. Most LM393-style obstacle modules assert LOW when a
// pill blocks the beam. Change this one value to HIGH after workshop testing
// if the installed sensors report the opposite polarity.
const byte PILL_SENSOR_1_PIN = 12;
const byte PILL_SENSOR_2_PIN = 3;
const byte PILL_SENSOR_ACTIVE_STATE = LOW;

// A pill can create a very short LOW pulse. The pin-change ISR records both
// edges even while Stepper.step() is waiting for the next motor step.
const unsigned long PILL_MIN_PULSE_US = 200;
const unsigned long PILL_CLEAR_DEBOUNCE_MS = 10;
const unsigned long PILL_SENSOR_CLEAR_TIMEOUT_MS = 100;
const unsigned long PILL_DETECTION_TIMEOUT_MS = 2000;
const unsigned long PILL_SENSOR_MONITOR_MS = 5000;

// Keep these pin orders matched to the ULN2003 wiring.
Stepper motor1(STEPS_PER_REV, 4, 6, 5, 7);
Stepper motor2(STEPS_PER_REV, 8, 10, 9, 11);

const byte COMMAND_BUFFER_SIZE = 24;
char commandBuffer[COMMAND_BUFFER_SIZE];
byte commandLength = 0;
bool discardingLongCommand = false;

enum ControllerState {
  IDLE,
  DISPENSING_1,
  DISPENSING_2,
  DISPENSING_BOTH
};

ControllerState controllerState = IDLE;

// These types must appear before the first function definition. Arduino's
// preprocessor inserts function prototypes there, and those prototypes use
// both types below.
enum DispenseResult {
  DISPENSE_CONFIRMED,
  DISPENSE_SENSOR_STUCK,
  DISPENSE_PILL_TIMEOUT
};

struct SensorTransitionTracker {
  volatile bool armed;
  volatile bool lowActive;
  volatile bool pulseLatched;
  volatile unsigned long lowStartedAtMicros;
  volatile unsigned long lastPulseWidthMicros;
};

SensorTransitionTracker pillSensor1Capture = {false, false, false, 0, 0};
SensorTransitionTracker pillSensor2Capture = {false, false, false, 0, 0};

// Temporary PCINT diagnostics. These are intentionally recorded in the ISR
// but printed only from normal foreground code.
volatile unsigned long pcint0InvocationCount = 0;
volatile unsigned long pcint2InvocationCount = 0;
volatile unsigned long pillSensor1FallingEdgeCount = 0;
volatile unsigned long pillSensor1RisingEdgeCount = 0;
volatile unsigned long pillSensor2FallingEdgeCount = 0;
volatile unsigned long pillSensor2RisingEdgeCount = 0;
volatile bool pillSensor1ArmedDuringCommand = false;
volatile bool pillSensor2ArmedDuringCommand = false;

void printStatus() {
  switch (controllerState) {
    case DISPENSING_1:
      Serial.println(F("STATUS|DISPENSING_1"));
      break;
    case DISPENSING_2:
      Serial.println(F("STATUS|DISPENSING_2"));
      break;
    case DISPENSING_BOTH:
      Serial.println(F("STATUS|DISPENSING_BOTH"));
      break;
    default:
      Serial.println(F("STATUS|IDLE"));
      break;
  }
}

void runMotor1(int steps) {
  controllerState = DISPENSING_1;
  motor1.step(steps);
  controllerState = IDLE;
}

void runMotor2(int steps) {
  controllerState = DISPENSING_2;
  motor2.step(steps);
  controllerState = IDLE;
}

void runBothMotors(int steps) {
  controllerState = DISPENSING_BOTH;
  motor1.step(steps);
  delay(500);
  motor2.step(steps);
  controllerState = IDLE;
}

bool pillSensorDetected(byte pin) {
  return digitalRead(pin) == PILL_SENSOR_ACTIVE_STATE;
}

bool waitForStableSensorState(
  byte pin,
  bool expectedDetected,
  unsigned long stableMs,
  unsigned long timeoutMs
) {
  bool lastDetected = pillSensorDetected(pin);
  unsigned long changedAt = millis();
  unsigned long startedAt = changedAt;

  while (millis() - startedAt < timeoutMs) {
    bool detected = pillSensorDetected(pin);
    unsigned long now = millis();
    if (detected != lastDetected) {
      lastDetected = detected;
      changedAt = now;
    }
    if (detected == expectedDetected && now - changedAt >= stableMs) {
      return true;
    }
    delay(1);
  }
  return false;
}

SensorTransitionTracker *captureForSensor(byte pin) {
  return pin == PILL_SENSOR_1_PIN
    ? &pillSensor1Capture
    : &pillSensor2Capture;
}

void capturePillSensorTransition(
  SensorTransitionTracker *capture,
  bool detected
) {
  if (!capture->armed || capture->pulseLatched) {
    return;
  }

  unsigned long now = micros();
  if (detected) {
    if (!capture->lowActive) {
      capture->lowActive = true;
      capture->lowStartedAtMicros = now;
    }
    return;
  }

  if (!capture->lowActive) {
    return;
  }

  capture->lowActive = false;
  unsigned long pulseWidth = now - capture->lowStartedAtMicros;
  capture->lastPulseWidthMicros = pulseWidth;
  if (pulseWidth >= PILL_MIN_PULSE_US) {
    capture->pulseLatched = true;
    capture->armed = false;
  }
}

ISR(PCINT0_vect) {
  pcint0InvocationCount++;
  bool detected = (PINB & _BV(PB4)) == LOW;
  if (detected) {
    pillSensor1FallingEdgeCount++;
  } else {
    pillSensor1RisingEdgeCount++;
  }
  capturePillSensorTransition(
    &pillSensor1Capture,
    detected
  );
}

ISR(PCINT2_vect) {
  pcint2InvocationCount++;
  bool detected = (PIND & _BV(PD3)) == LOW;
  if (detected) {
    pillSensor2FallingEdgeCount++;
  } else {
    pillSensor2RisingEdgeCount++;
  }
  capturePillSensorTransition(
    &pillSensor2Capture,
    detected
  );
}

void resetPillIrqDebug() {
  noInterrupts();
  pcint0InvocationCount = 0;
  pcint2InvocationCount = 0;
  pillSensor1FallingEdgeCount = 0;
  pillSensor1RisingEdgeCount = 0;
  pillSensor2FallingEdgeCount = 0;
  pillSensor2RisingEdgeCount = 0;
  pillSensor1Capture.lastPulseWidthMicros = 0;
  pillSensor2Capture.lastPulseWidthMicros = 0;
  pillSensor1ArmedDuringCommand = false;
  pillSensor2ArmedDuringCommand = false;
  interrupts();
}

void printPillIrqDebug() {
  unsigned long pcint0Count;
  unsigned long pcint2Count;
  unsigned long sensor1FallingCount;
  unsigned long sensor1RisingCount;
  unsigned long sensor2FallingCount;
  unsigned long sensor2RisingCount;
  bool sensor1Armed;
  bool sensor2Armed;
  bool sensor1Latched;
  bool sensor2Latched;
  bool sensor1ArmedDuringCommand;
  bool sensor2ArmedDuringCommand;
  unsigned long sensor1LastPulseWidth;
  unsigned long sensor2LastPulseWidth;

  noInterrupts();
  pcint0Count = pcint0InvocationCount;
  pcint2Count = pcint2InvocationCount;
  sensor1FallingCount = pillSensor1FallingEdgeCount;
  sensor1RisingCount = pillSensor1RisingEdgeCount;
  sensor2FallingCount = pillSensor2FallingEdgeCount;
  sensor2RisingCount = pillSensor2RisingEdgeCount;
  sensor1Armed = pillSensor1Capture.armed;
  sensor2Armed = pillSensor2Capture.armed;
  sensor1Latched = pillSensor1Capture.pulseLatched;
  sensor2Latched = pillSensor2Capture.pulseLatched;
  sensor1ArmedDuringCommand = pillSensor1ArmedDuringCommand;
  sensor2ArmedDuringCommand = pillSensor2ArmedDuringCommand;
  sensor1LastPulseWidth = pillSensor1Capture.lastPulseWidthMicros;
  sensor2LastPulseWidth = pillSensor2Capture.lastPulseWidthMicros;
  interrupts();

  Serial.print(F("PILL_IRQ_DEBUG|PCINT0="));
  Serial.print(pcint0Count);
  Serial.print(F("|PCINT2="));
  Serial.print(pcint2Count);
  Serial.print(F("|D12_FALL="));
  Serial.print(sensor1FallingCount);
  Serial.print(F("|D12_RISE="));
  Serial.print(sensor1RisingCount);
  Serial.print(F("|D3_FALL="));
  Serial.print(sensor2FallingCount);
  Serial.print(F("|D3_RISE="));
  Serial.print(sensor2RisingCount);
  Serial.print(F("|ARM1="));
  Serial.print(sensor1Armed ? 1 : 0);
  Serial.print(F("|ARM2="));
  Serial.print(sensor2Armed ? 1 : 0);
  Serial.print(F("|ARMED1="));
  Serial.print(sensor1ArmedDuringCommand ? 1 : 0);
  Serial.print(F("|ARMED2="));
  Serial.print(sensor2ArmedDuringCommand ? 1 : 0);
  Serial.print(F("|LATCH1="));
  Serial.print(sensor1Latched ? 1 : 0);
  Serial.print(F("|LATCH2="));
  Serial.print(sensor2Latched ? 1 : 0);
  Serial.print(F("|LAST_US1="));
  Serial.print(sensor1LastPulseWidth);
  Serial.print(F("|LAST_US2="));
  Serial.println(sensor2LastPulseWidth);
}

void armPillSensorCapture(byte pin) {
  SensorTransitionTracker *capture = captureForSensor(pin);
  noInterrupts();
  capture->armed = true;
  capture->lowActive = false;
  capture->pulseLatched = false;
  capture->lowStartedAtMicros = 0;
  if (pin == PILL_SENSOR_1_PIN) {
    pillSensor1ArmedDuringCommand = true;
  } else {
    pillSensor2ArmedDuringCommand = true;
  }
  interrupts();
}

void disarmPillSensorCapture(byte pin) {
  SensorTransitionTracker *capture = captureForSensor(pin);
  noInterrupts();
  capture->armed = false;
  capture->lowActive = false;
  interrupts();
}

bool pillPulseLatched(byte pin) {
  SensorTransitionTracker *capture = captureForSensor(pin);
  noInterrupts();
  bool latched = capture->pulseLatched;
  interrupts();
  return latched;
}

DispenseResult runConfirmedPill(
  Stepper *motor,
  byte sensorPin,
  ControllerState dispensingState
) {
  // A blocked sensor before movement is unsafe: do not rotate the disk.
  if (pillSensorDetected(sensorPin)) {
    return DISPENSE_SENSOR_STUCK;
  }
  if (!waitForStableSensorState(
        sensorPin,
        false,
        PILL_CLEAR_DEBOUNCE_MS,
        PILL_SENSOR_CLEAR_TIMEOUT_MS
      )) {
    return DISPENSE_SENSOR_STUCK;
  }

  armPillSensorCapture(sensorPin);
  controllerState = dispensingState;
  unsigned long startedAt = millis();

  // The ISR latch, not polling, captures the matching sensor pulse during
  // the complete existing 256-step dispense motion.
  for (int step = 0; step < PILL_STEPS; step++) {
    motor->step(1);
  }

  // A pill can leave the disk just after the final step. Wait only for the
  // ISR's one-pulse latch until the existing bounded per-pill deadline.
  while (!pillPulseLatched(sensorPin) && millis() - startedAt < PILL_DETECTION_TIMEOUT_MS) {
    delay(1);
  }

  if (!pillPulseLatched(sensorPin)) {
    disarmPillSensorCapture(sensorPin);
    controllerState = IDLE;
    return DISPENSE_PILL_TIMEOUT;
  }

  // Re-arm requires a stable clear sensor so the next command cannot count
  // the same pill or a sensor that has remained blocked.
  if (!waitForStableSensorState(
        sensorPin,
        false,
        PILL_CLEAR_DEBOUNCE_MS,
        PILL_SENSOR_CLEAR_TIMEOUT_MS
      )) {
    disarmPillSensorCapture(sensorPin);
    controllerState = IDLE;
    return DISPENSE_SENSOR_STUCK;
  }

  disarmPillSensorCapture(sensorPin);
  controllerState = IDLE;
  return DISPENSE_CONFIRMED;
}

void printDispenseError(const char *command, DispenseResult result) {
  Serial.print(F("ERROR|"));
  Serial.print(command);
  Serial.print(F("|CODE="));
  if (result == DISPENSE_SENSOR_STUCK) {
    Serial.println(F("SENSOR_STUCK"));
  } else {
    Serial.println(F("PILL_TIMEOUT"));
  }
}

void printDispenseBothError(byte box, DispenseResult result) {
  Serial.print(F("ERROR|DISPENSE_BOTH|BOX="));
  Serial.print(box);
  Serial.print(F("|CODE="));
  if (result == DISPENSE_SENSOR_STUCK) {
    Serial.println(F("SENSOR_STUCK"));
  } else {
    Serial.println(F("PILL_TIMEOUT"));
  }
}

// Temporary diagnostics: these report raw digital inputs only and never move
// either dispenser. They intentionally do not apply active-state logic or
// debounce so workshop testing can determine the electrical polarity/pulse.
void printPillSensors() {
  Serial.print(F("PILL_SENSORS|D12="));
  Serial.print(digitalRead(PILL_SENSOR_1_PIN));
  Serial.print(F("|D3="));
  Serial.println(digitalRead(PILL_SENSOR_2_PIN));
}

void printPillSensorChange(byte pin, int state) {
  Serial.print(F("PILL_SENSOR|PIN="));
  Serial.print(pin);
  Serial.print(F("|STATE="));
  Serial.println(state);
}

void monitorPillSensors() {
  int sensor1State = digitalRead(PILL_SENSOR_1_PIN);
  int sensor2State = digitalRead(PILL_SENSOR_2_PIN);
  unsigned long startedAt = millis();

  while (millis() - startedAt < PILL_SENSOR_MONITOR_MS) {
    int currentSensor1State = digitalRead(PILL_SENSOR_1_PIN);
    int currentSensor2State = digitalRead(PILL_SENSOR_2_PIN);

    if (currentSensor1State != sensor1State) {
      sensor1State = currentSensor1State;
      printPillSensorChange(PILL_SENSOR_1_PIN, sensor1State);
    }
    if (currentSensor2State != sensor2State) {
      sensor2State = currentSensor2State;
      printPillSensorChange(PILL_SENSOR_2_PIN, sensor2State);
    }
  }
}

void executeCommand(const char *command) {
  if (strcmp(command, "PING") == 0) {
    Serial.println(F("ACK|PING"));
  } else if (strcmp(command, "GET_STATUS") == 0) {
    printStatus();
  } else if (strcmp(command, "GET_PILL_SENSORS") == 0) {
    printPillSensors();
  } else if (strcmp(command, "GET_PILL_IRQ_DEBUG") == 0) {
    printPillIrqDebug();
  } else if (strcmp(command, "MONITOR_PILL_SENSORS") == 0) {
    monitorPillSensors();
  } else if (strcmp(command, "DISPENSE_1") == 0) {
    Serial.println(F("ACK|DISPENSE_1"));
    resetPillIrqDebug();
    DispenseResult result = runConfirmedPill(
      &motor1,
      PILL_SENSOR_1_PIN,
      DISPENSING_1
    );
    if (result == DISPENSE_CONFIRMED) {
      Serial.println(F("DONE|DISPENSE_1"));
    } else {
      printDispenseError("DISPENSE_1", result);
    }
  } else if (strcmp(command, "DISPENSE_2") == 0) {
    Serial.println(F("ACK|DISPENSE_2"));
    resetPillIrqDebug();
    DispenseResult result = runConfirmedPill(
      &motor2,
      PILL_SENSOR_2_PIN,
      DISPENSING_2
    );
    if (result == DISPENSE_CONFIRMED) {
      Serial.println(F("DONE|DISPENSE_2"));
    } else {
      printDispenseError("DISPENSE_2", result);
    }
  } else if (strcmp(command, "DISPENSE_BOTH") == 0) {
    Serial.println(F("ACK|DISPENSE_BOTH"));
    resetPillIrqDebug();
    DispenseResult firstResult = runConfirmedPill(
      &motor1,
      PILL_SENSOR_1_PIN,
      DISPENSING_BOTH
    );
    if (firstResult != DISPENSE_CONFIRMED) {
      printDispenseBothError(1, firstResult);
      return;
    }
    delay(500);
    DispenseResult secondResult = runConfirmedPill(
      &motor2,
      PILL_SENSOR_2_PIN,
      DISPENSING_BOTH
    );
    if (secondResult != DISPENSE_CONFIRMED) {
      printDispenseBothError(2, secondResult);
      return;
    }
    Serial.println(F("DONE|DISPENSE_BOTH"));
  } else if (strcmp(command, "1") == 0) {
    Serial.println(F("ACK|1"));
    runMotor1(STEPS_PER_REV);
    Serial.println(F("DONE|1"));
  } else if (strcmp(command, "2") == 0) {
    Serial.println(F("ACK|2"));
    runMotor2(STEPS_PER_REV);
    Serial.println(F("DONE|2"));
  } else if (strcmp(command, "3") == 0) {
    Serial.println(F("ACK|3"));
    runMotor1(-STEPS_PER_REV);
    Serial.println(F("DONE|3"));
  } else if (strcmp(command, "4") == 0) {
    Serial.println(F("ACK|4"));
    runMotor2(-STEPS_PER_REV);
    Serial.println(F("DONE|4"));
  } else if (strcmp(command, "5") == 0) {
    Serial.println(F("ACK|5"));
    runBothMotors(STEPS_PER_REV);
    Serial.println(F("DONE|5"));
  } else if (strcmp(command, "6") == 0) {
    Serial.println(F("ACK|6"));
    runMotor1(PILL_STEPS);
    Serial.println(F("DONE|6"));
  } else if (strcmp(command, "7") == 0) {
    Serial.println(F("ACK|7"));
    runMotor2(PILL_STEPS);
    Serial.println(F("DONE|7"));
  } else {
    Serial.println(F("ERROR|UNKNOWN_COMMAND"));
  }
}

void processCommandLine() {
  if (discardingLongCommand) {
    Serial.println(F("ERROR|COMMAND_TOO_LONG"));
    discardingLongCommand = false;
    commandLength = 0;
    return;
  }

  // Trim spaces/tabs and normalize ASCII letters without using Arduino String.
  byte first = 0;
  while (first < commandLength &&
         (commandBuffer[first] == ' ' || commandBuffer[first] == '\t')) {
    first++;
  }

  byte last = commandLength;
  while (last > first &&
         (commandBuffer[last - 1] == ' ' || commandBuffer[last - 1] == '\t')) {
    last--;
  }

  byte outputLength = 0;
  for (byte i = first; i < last; i++) {
    char value = commandBuffer[i];
    if (value >= 'a' && value <= 'z') {
      value -= ('a' - 'A');
    }
    commandBuffer[outputLength++] = value;
  }
  commandBuffer[outputLength] = '\0';
  commandLength = 0;

  // Empty lines are harmless and produce no response.
  if (outputLength > 0) {
    executeCommand(commandBuffer);
  }
}

void setup() {
  Serial.begin(9600);

  motor1.setSpeed(12);
  motor2.setSpeed(12);
  pinMode(PILL_SENSOR_1_PIN, INPUT);
  pinMode(PILL_SENSOR_2_PIN, INPUT);

  // D12 = PB4 = PCINT4 (PCINT0_vect); D3 = PD3 = PCINT19
  // (PCINT2_vect). Keep both groups enabled because each box has its own
  // physical sensor, while the active dispense command arms only one latch.
  PCMSK0 |= _BV(PCINT4);
  PCMSK2 |= _BV(PCINT19);
  PCIFR |= _BV(PCIF0) | _BV(PCIF2);
  PCICR |= _BV(PCIE0) | _BV(PCIE2);

  Serial.println(F("CONTROLLER|ARDUINO_UNO"));
  Serial.println(F("BAUD|9600"));
  Serial.println(F("STATUS|IDLE"));
  Serial.println(F("READY"));
}

void loop() {
  while (Serial.available() > 0) {
    char incoming = Serial.read();

    if (incoming == '\r') {
      continue;
    }

    if (incoming == '\n') {
      processCommandLine();
      continue;
    }

    if (discardingLongCommand) {
      continue;
    }

    if (commandLength < COMMAND_BUFFER_SIZE - 1) {
      commandBuffer[commandLength++] = incoming;
    } else {
      // Discard the rest of this line, then report one error at its newline.
      discardingLongCommand = true;
    }
  }
}
