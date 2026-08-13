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
};

SensorTransitionTracker pillSensor1Capture = {false, false, false, 0};
SensorTransitionTracker pillSensor2Capture = {false, false, false, 0};

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
  if (now - capture->lowStartedAtMicros >= PILL_MIN_PULSE_US) {
    capture->pulseLatched = true;
    capture->armed = false;
  }
}

ISR(PCINT0_vect) {
  capturePillSensorTransition(
    &pillSensor1Capture,
    (PINB & _BV(PB4)) == LOW
  );
}

ISR(PCINT2_vect) {
  capturePillSensorTransition(
    &pillSensor2Capture,
    (PIND & _BV(PD3)) == LOW
  );
}

void armPillSensorCapture(byte pin) {
  SensorTransitionTracker *capture = captureForSensor(pin);
  noInterrupts();
  capture->armed = true;
  capture->lowActive = false;
  capture->pulseLatched = false;
  capture->lowStartedAtMicros = 0;
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
  } else if (strcmp(command, "MONITOR_PILL_SENSORS") == 0) {
    monitorPillSensors();
  } else if (strcmp(command, "DISPENSE_1") == 0) {
    Serial.println(F("ACK|DISPENSE_1"));
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
