#include <Stepper.h>

#define STEPS_PER_REV 2048

// Driver 1
Stepper motor1(STEPS_PER_REV, 4, 6, 5, 7);

// Driver 2
Stepper motor2(STEPS_PER_REV, 8, 10, 9, 11);

void setup() {
  Serial.begin(9600);

  motor1.setSpeed(12);
  motor2.setSpeed(12);

  Serial.println("=================================");
  Serial.println("Stepper Test");
  Serial.println("1 = Motor 1 CW");
  Serial.println("2 = Motor 2 CW");
  Serial.println("3 = Motor 1 CCW");
  Serial.println("4 = Motor 2 CCW");
  Serial.println("5 = Both Motors");
  Serial.println("6 = One Pill Motor 1");
  Serial.println("7 = One Pill Motor 2");
  Serial.println("=================================");
}

void loop() {

  if (!Serial.available())
    return;

  char cmd = Serial.read();

  switch (cmd) {

    case '1':
      Serial.println("Motor 1 Forward");
      motor1.step(STEPS_PER_REV);
      break;

    case '2':
      Serial.println("Motor 2 Forward");
      motor2.step(STEPS_PER_REV);
      break;

    case '3':
      Serial.println("Motor 1 Reverse");
      motor1.step(-STEPS_PER_REV);
      break;

    case '4':
      Serial.println("Motor 2 Reverse");
      motor2.step(-STEPS_PER_REV);
      break;

    case '5':
      Serial.println("Both Motors");

      motor1.step(STEPS_PER_REV);
      delay(500);

      motor2.step(STEPS_PER_REV);

      break;

    case '6':
      Serial.println("Motor 1 -> One Pill");
      motor1.step(256);      // 45 درجة تقريباً
      break;

    case '7':
      Serial.println("Motor 2 -> One Pill");
      motor2.step(256);
      break;

    default:
      Serial.println("Unknown Command");
      break;
  }
}