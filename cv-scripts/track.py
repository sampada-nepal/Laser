#!/usr/bin/env python3
"""
track.py -- open-vocabulary object tracking proof-of-concept.

Point a webcam (or video file) at a scene, give it a text prompt like
"green apple" or "wine bottle", and it will:

  1. Run YOLO-World periodically to *find* the object from your text prompt
     (open-vocabulary detection -- no training needed).
  2. Hand off to a fast OpenCV tracker (CSRT) to *follow* it frame-to-frame,
     which is much cheaper than running the detector on every frame.
  3. Re-run detection automatically if the tracker loses the object, or on
     a fixed interval to correct drift.
  4. Draw a crosshair at the object's center -- this is the pixel coordinate
     you'd eventually feed into pan-tilt/servo calibration.

No servo/laser control here -- this is just the CV loop, so you can validate
detection + tracking quality before wiring up hardware.

Usage:
    python track.py --prompts "green apple,wine bottle" --source 0
    python track.py --prompts "coffee mug" --source video.mp4 --show-fps

Keys while running:
    q        quit
    r        force re-detection this frame
    n        cycle to the next prompt class (if multiple given)
"""

import argparse
import queue
import threading
import time

import cv2
import numpy as np
from ultralytics import YOLO


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--prompts", type=str, required=True,
                    help="Comma-separated text prompts, e.g. 'green apple,wine bottle'")
    p.add_argument("--source", type=str, default="0",
                    help="Camera index (e.g. 0) or path to a video file (default: 0)")
    p.add_argument("--model", type=str, default="yolov8s-worldv2.pt",
                    help="YOLO-World checkpoint (auto-downloaded by ultralytics). "
                         "Try yolov8x-worldv2.pt for higher accuracy / lower speed.")
    p.add_argument("--conf", type=float, default=0.15,
                    help="Detection confidence threshold (open-vocab models often need this lower than usual)")
    p.add_argument("--redetect-interval", type=int, default=30,
                    help="Force a fresh detection every N frames even if tracking is fine (corrects drift)")
    p.add_argument("--device", type=str, default=None,
                    help="'cpu', 'cuda:0', 'mps', etc. Defaults to ultralytics auto-select.")
    p.add_argument("--show-fps", action="store_true", help="Overlay FPS counter")
    return p.parse_args()


def make_tracker():
    """CSRT: slower than KCF but much more robust to scale/rotation changes,
    which matters more here than raw speed since we only track between
    periodic re-detections."""
    if hasattr(cv2, "legacy"):
        return cv2.legacy.TrackerCSRT_create()
    return cv2.TrackerCSRT_create()


def detect_target(model, frame, prompt_idx, conf):
    """Run YOLO-World on the frame, return the best box (xyxy) for the
    currently-selected prompt class, or None if not found."""
    results = model.predict(frame, conf=conf, verbose=False)[0]
    if results.boxes is None or len(results.boxes) == 0:
        return None

    boxes = results.boxes
    cls_ids = boxes.cls.cpu().numpy().astype(int)
    confs = boxes.conf.cpu().numpy()
    xyxy = boxes.xyxy.cpu().numpy()

    # keep only detections matching the class we're currently hunting for
    mask = cls_ids == prompt_idx
    if not mask.any():
        return None

    # pick the highest-confidence match
    best = np.argmax(confs[mask])
    return xyxy[mask][best]


def stdin_listener(prompt_queue, stop_event):
    """Runs in a background thread: blocks on terminal input so you can type
    a new search target at any time without pausing the video loop. Click
    back into the terminal window to type -- the cv2 window won't see these
    keystrokes."""
    print("[input] type an object name + Enter to search for it (or 'quit' to exit)")
    while not stop_event.is_set():
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if not line:
            continue
        prompt_queue.put(line)
        if line.lower() in ("quit", "exit"):
            stop_event.set()
            break


def clamp_box(box, w, h):
    x1, y1, x2, y2 = box
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w - 1, x2), min(h - 1, y2)
    return x1, y1, x2, y2


def main():
    args = parse_args()
    prompts = [p.strip() for p in args.prompts.split(",") if p.strip()]
    if not prompts:
        raise SystemExit("Give at least one prompt via --prompts")

    print(f"[setup] loading {args.model} ...")
    model = YOLO(args.model)
    model.set_classes(prompts)  # this is the open-vocabulary part
    if args.device:
        model.to(args.device)

    source = int(args.source) if args.source.isdigit() else args.source
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit(f"Could not open video source: {args.source}")

    prompt_idx = 0
    tracker = None
    tracking = False
    frame_idx = 0
    last_fps_t = time.time()
    fps = 0.0

    # background thread lets you type new search targets without blocking the video loop
    prompt_queue = queue.Queue()
    stop_event = threading.Event()
    threading.Thread(target=stdin_listener, args=(prompt_queue, stop_event), daemon=True).start()

    print(f"[run] hunting for: {prompts[prompt_idx]!r}  "
          f"(keys in video window: q=quit, r=redetect, n=next prompt)")

    while True:
        # pick up any new target typed into the terminal since the last frame
        while not prompt_queue.empty():
            new_prompt = prompt_queue.get()
            if new_prompt.lower() in ("quit", "exit"):
                stop_event.set()
                break
            prompts = [new_prompt]
            prompt_idx = 0
            model.set_classes(prompts)
            tracking = False
            print(f"[run] switched target to: {prompts[0]!r}")
        if stop_event.is_set():
            break

        ok, frame = cap.read()
        if not ok:
            print("[run] end of stream / camera read failed")
            break
        h, w = frame.shape[:2]
        frame_idx += 1

        need_detect = (
            not tracking
            or frame_idx % args.redetect_interval == 0
        )

        if need_detect:
            box = detect_target(model, frame, prompt_idx, args.conf)
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

        # -- draw overlay --
        if tracking:
            x1, y1, x2, y2 = map(int, (x1, y1, x2, y2))
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.drawMarker(frame, (cx, cy), (0, 0, 255),
                            markerType=cv2.MARKER_CROSS, markerSize=20, thickness=2)
            cv2.putText(frame, f"{prompts[prompt_idx]} ({cx},{cy})", (x1, max(0, y1 - 10)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        cv2.putText(frame, status, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)

        if args.show_fps:
            now = time.time()
            fps = 0.9 * fps + 0.1 * (1.0 / max(1e-6, now - last_fps_t))
            last_fps_t = now
            cv2.putText(frame, f"FPS: {fps:.1f}", (10, h - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        cv2.imshow("laser-cv proof of concept", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        elif key == ord("r"):
            tracking = False  # forces redetect next loop
        elif key == ord("n") and len(prompts) > 1:
            prompt_idx = (prompt_idx + 1) % len(prompts)
            tracking = False
            print(f"[run] switched target to: {prompts[prompt_idx]!r}")

    stop_event.set()
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
