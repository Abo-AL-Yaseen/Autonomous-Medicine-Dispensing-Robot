#include <Stepper.h>
#include <string.h>

#define STEPS_PER_REV 2048
#define PILL_STEPS 256

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

void executeCommand(const char *command) {
  if (strcmp(command, "PING") == 0) {
    Serial.println(F("ACK|PING"));
  } else if (strcmp(command, "GET_STATUS") == 0) {
    printStatus();
  } else if (strcmp(command, "DISPENSE_1") == 0) {
    Serial.println(F("ACK|DISPENSE_1"));
    runMotor1(PILL_STEPS);
    Serial.println(F("DONE|DISPENSE_1"));
  } else if (strcmp(command, "DISPENSE_2") == 0) {
    Serial.println(F("ACK|DISPENSE_2"));
    runMotor2(PILL_STEPS);
    Serial.println(F("DONE|DISPENSE_2"));
  } else if (strcmp(command, "DISPENSE_BOTH") == 0) {
    Serial.println(F("ACK|DISPENSE_BOTH"));
    runBothMotors(PILL_STEPS);
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
