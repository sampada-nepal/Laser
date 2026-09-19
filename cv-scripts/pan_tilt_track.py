#!/usr/bin/env python3
"""
pan_tilt_track.py -- webcam object tracking -> Arduino pan/tilt servos.

Same detect (YOLO-World) + track (CSRT) loop as track.py, but instead of just
drawing a crosshair, it turns the object's offset from the frame center into
incremental pan/tilt servo angles and streams them to the Arduino sketch at
arduino/servo_controller/servo_controller.ino over serial.

Serial protocol (matches the .ino, and servo_gui.py): "<channel>,<angle>\n"
  channel 1 = pan  (servo1, pin 9)
  channel 2 = tilt (servo2, pin 10)

Usage:
    python pan_tilt_track.py --prompts "green apple" --port /dev/cu.usbmodem14101
    python pan_tilt_track.py --prompts "face" --dry-run   # CV only, no serial

Keys while running:
    q        quit
    r        force re-detection this frame
    c        re-center pan/tilt to 90/90

Tuning:
    --gain           max degrees moved per frame when the object is at the
                      frame edge (higher = snappier, more overshoot/jitter)
    --deadzone       fraction of half-frame the object can drift within
                      before servos react at all (kills jitter when centered)
    --invert-pan / --invert-tilt
                      flip direction if the mount moves the wrong way
    --swap-axes      swap which detected axis drives channel 1 vs 2, if pan
                      and tilt servos are wired opposite to pin 9/10
"""

import argparse
import time

import cv2
import numpy as np
from ultralytics import YOLO

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--prompts", type=str, required=True,
                    help="Comma-separated text prompts, e.g. 'green apple,wine bottle'")
    p.add_argument("--source", type=str, default="0",
                    help="Camera index (e.g. 0) or path to a video file (default: 0)")
    p.add_argument("--model", type=str, default="yolov8s-worldv2.pt",
                    help="YOLO-World checkpoint (auto-downloaded by ultralytics)")
    p.add_argument("--conf", type=float, default=0.15, help="Detection confidence threshold")
    p.add_argument("--redetect-interval", type=int, default=30,
                    help="Force a fresh detection every N frames even if tracking is fine")
    p.add_argument("--device", type=str, default=None, help="'cpu', 'cuda:0', 'mps', etc.")

    p.add_argument("--port", type=str, default=None,
                    help="Arduino serial port (e.g. /dev/cu.usbmodem14101). Auto-detected if omitted.")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--dry-run", action="store_true",
                    help="Run the CV loop and print target angles without opening serial")

    p.add_argument("--gain", type=float, default=3.0,
                    help="Max degrees/frame moved when the object is at the frame edge")
    p.add_argument("--deadzone", type=float, default=0.03,
                    help="Fraction of half-frame the object can drift within before reacting")
    p.add_argument("--pan-min", type=float, default=0.0)
    p.add_argument("--pan-max", type=float, default=180.0)
    p.add_argument("--tilt-min", type=float, default=0.0)
    p.add_argument("--tilt-max", type=float, default=180.0)
    p.add_argument("--invert-pan", action="store_true")
    p.add_argument("--invert-tilt", action="store_true")
    p.add_argument("--swap-axes", action="store_true",
                    help="Swap which detected axis (x/y) drives channel 1 vs channel 2")

    p.add_argument("--show-fps", action="store_true")
    return p.parse_args()


def make_tracker():
    if hasattr(cv2, "legacy"):
        return cv2.legacy.TrackerCSRT_create()
    return cv2.TrackerCSRT_create()


def detect_target(model, frame, conf):
    """Run YOLO-World, return the highest-confidence box (xyxy) for any of
    the currently active prompts, or None."""
    results = model.predict(frame, conf=conf, verbose=False)[0]
    if results.boxes is None or len(results.boxes) == 0:
        return None
    boxes = results.boxes
    confs = boxes.conf.cpu().numpy()
    xyxy = boxes.xyxy.cpu().numpy()
    best = np.argmax(confs)
    return xyxy[best]


def clamp_box(box, w, h):
    x1, y1, x2, y2 = box
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w - 1, x2), min(h - 1, y2)
    return x1, y1, x2, y2


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def find_arduino_port():
    if serial is None:
        return None
    ports = [port.device for port in list_ports.comports()]
    return next((p for p in ports if "usb" in p.lower()), ports[0] if ports else None)


class ServoLink:
    """Thin wrapper around the serial connection to servo_controller.ino.
    In --dry-run mode (or if pyserial/the port isn't available), this just
    prints what it would have sent."""

    def __init__(self, port, baud, dry_run):
        self.conn = None
        self.dry_run = dry_run or serial is None
        self.last_sent = {1: None, 2: None}
        if self.dry_run:
            if serial is None:
                print("[serial] pyserial not installed -- running dry (no hardware)")
            else:
                print("[serial] --dry-run: printing angles instead of sending")
            return
        if not port:
            raise SystemExit("No serial port given and none could be auto-detected. "
                              "Pass --port, or use --dry-run to test without hardware.")
        self.conn = serial.Serial(port, baud, timeout=0, write_timeout=1)
        time.sleep(2.0)  # let the Arduino finish its reset-on-connect
        print(f"[serial] connected to {port} @ {baud}")

    def send(self, channel, angle):
        angle = int(round(angle))
        if self.last_sent[channel] == angle:
            return  # nothing changed, don't spam the serial line
        self.last_sent[channel] = angle
        if self.dry_run:
            print(f"[dry-run] channel {channel} -> {angle} deg")
            return
        try:
            self.conn.write(f"{channel},{angle}\n".encode("ascii"))
        except serial.SerialException as exc:
            print(f"[serial] write failed: {exc}")

    def close(self):
        if self.conn:
            self.conn.close()


def main():
    args = parse_args()
    prompts = [p.strip() for p in args.prompts.split(",") if p.strip()]
    if not prompts:
        raise SystemExit("Give at least one prompt via --prompts")

    print(f"[setup] loading {args.model} ...")
    model = YOLO(args.model)
    model.set_classes(prompts)
    if args.device:
        model.to(args.device)

    source = int(args.source) if args.source.isdigit() else args.source
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit(f"Could not open video source: {args.source}")

    port = args.port or find_arduino_port()
    link = ServoLink(port, args.baud, args.dry_run)

    pan, tilt = 90.0, 90.0
    link.send(1, pan)
    link.send(2, tilt)

    tracker = None
    tracking = False
    frame_idx = 0
    last_fps_t = time.time()
    fps = 0.0

    print(f"[run] hunting for: {prompts}  (keys: q=quit, r=redetect, c=recenter)")

    while True:
        ok, frame = cap.read()
        if not ok:
            print("[run] end of stream / camera read failed")
            break
        h, w = frame.shape[:2]
        frame_idx += 1

        need_detect = not tracking or frame_idx % args.redetect_interval == 0

        if need_detect:
            box = detect_target(model, frame, args.conf)
            if box is not None:
                x1, y1, x2, y2 = clamp_box(box, w, h)
                tracker = make_tracker()
                tracker.init(frame, (x1, y1, x2 - x1, y2 - y1))
                tracking = True
                status = "detected"
            else:
                tracking = False
                status = "searching..."
        else:
            ok_t, bbox = tracker.update(frame)
            if ok_t:
                x1, y1, wd, ht = bbox
                x2, y2 = x1 + wd, y1 + ht
                status = "tracking"
            else:
                tracking = False
                status = "lost -> redetecting"

        if tracking:
            x1, y1, x2, y2 = map(int, (x1, y1, x2, y2))
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

            err_x = (cx - w / 2) / (w / 2)   # -1 (left) .. +1 (right)
            err_y = (cy - h / 2) / (h / 2)   # -1 (top)  .. +1 (bottom)
            if abs(err_x) < args.deadzone:
                err_x = 0.0
            if abs(err_y) < args.deadzone:
                err_y = 0.0

            if args.swap_axes:
                err_x, err_y = err_y, err_x

            pan_delta = err_x * args.gain * (-1 if args.invert_pan else 1)
            tilt_delta = err_y * args.gain * (-1 if args.invert_tilt else 1)
            pan = clamp(pan + pan_delta, args.pan_min, args.pan_max)
            tilt = clamp(tilt + tilt_delta, args.tilt_min, args.tilt_max)
            link.send(1, pan)
            link.send(2, tilt)

            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.drawMarker(frame, (cx, cy), (0, 0, 255),
                            markerType=cv2.MARKER_CROSS, markerSize=20, thickness=2)

        cv2.putText(frame, f"{status}  pan={pan:.0f} tilt={tilt:.0f}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)

        if args.show_fps:
            now = time.time()
            fps = 0.9 * fps + 0.1 * (1.0 / max(1e-6, now - last_fps_t))
            last_fps_t = now
            cv2.putText(frame, f"FPS: {fps:.1f}", (10, h - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        cv2.imshow("laser-cv pan/tilt tracking", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        elif key == ord("r"):
            tracking = False
        elif key == ord("c"):
            pan, tilt = 90.0, 90.0
            link.send(1, pan)
            link.send(2, tilt)

    cap.release()
    cv2.destroyAllWindows()
    link.close()


if __name__ == "__main__":
    main()
