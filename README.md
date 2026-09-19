# Two Servo Controller

A small desktop GUI for two servos connected to an Arduino Nano Every. The GUI
sends `servo,angle` lines over USB serial at 115200 baud. It needs the matching
Arduino sketch in `arduino/servo_controller/servo_controller.ino`.

## Wiring

The sketch uses digital pin 9 for servo 1 and pin 10 for servo 2. Connect each
servo's signal wire to its assigned pin. Use a suitable external 5 V servo
power supply and connect its ground to the Arduino ground. Do not power two
servos from the Arduino's 5 V pin.

If you have a separate servo controller board, confirm its model and protocol
before connecting it; this sketch assumes the Nano Every drives the servo
signals directly.

## Run

1. Upload the sketch with the Arduino IDE, selecting **Arduino Nano Every**.
2. From this folder, run:

   ```sh
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   .venv/bin/python servo_gui.py
   ```

3. Select the Arduino serial port (for example `/dev/cu.usbmodem101`) and click
   **Connect**. Move either slider or click **Center both (90°)**.

The servos start at 90 degrees when the Arduino boots. Connecting the GUI also
sends the current slider angles.
