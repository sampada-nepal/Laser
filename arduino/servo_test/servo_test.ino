// Minimal servo sweep test -- no serial input needed.
// Flash this alone to check the servos/wiring/power are good, before
// testing them through servo_controller.ino + pan_tilt_track.py.
//
// Wiring: servo1 signal -> pin 9, servo2 signal -> pin 10, both servos'
// power/ground -> external 5V supply (not the Arduino's USB rail), grounds
// tied together with the Arduino's ground.
//
// Expected result: both servos sweep smoothly from 0 to 180 and back,
// forever. Check the Serial Monitor (9600 baud) for the angle log.

#include <Servo.h>

Servo servo1;
Servo servo2;

void setup() {
  Serial.begin(9600);
  servo1.attach(9);
  servo2.attach(10);
}

void loop() {
  for (int angle = 0; angle <= 180; angle += 1) {
    servo1.write(angle);
    servo2.write(angle);
    Serial.print("angle: ");
    Serial.println(angle);
    delay(15);
  }
  for (int angle = 180; angle >= 0; angle -= 1) {
    servo1.write(angle);
    servo2.write(angle);
    Serial.print("angle: ");
    Serial.println(angle);
    delay(15);
  }
}
