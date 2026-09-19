#include <Servo.h>

Servo servo1;
Servo servo2;

void setup() {
  Serial.begin(115200);
  servo1.attach(9);
  servo2.attach(10);
  servo1.write(90);
  servo2.write(90);
}

void loop() {
  if (!Serial.available()) return;

  int channel = Serial.parseInt();
  if (Serial.read() != ',') {
    while (Serial.available()) Serial.read();
    return;
  }
  int angle = Serial.parseInt();
  if (Serial.read() != '\n') {
    while (Serial.available()) Serial.read();
    return;
  }
  if (angle < 0 || angle > 180) return;

  if (channel == 1) servo1.write(angle);
  if (channel == 2) servo2.write(angle);
}
