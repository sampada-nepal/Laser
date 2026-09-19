# laser-cv: open-vocabulary detect + track (proof of concept)

CV-only test rig for the laser-pointer project. No servo/hardware control yet --
this just proves out detection + tracking quality on your webcam.

## How it works

- **Detection**: [YOLO-World](https://docs.ultralytics.com/models/yolo-world/) via
  `ultralytics`. You give it plain-text prompts ("green apple", "wine bottle") and
  it detects them without any training -- this is what makes it "open-vocabulary."
- **Tracking**: OpenCV's CSRT tracker follows the detected box frame-to-frame, so
  you're not paying the cost of running the full detector on every frame. The
  detector re-runs automatically if tracking is lost, or every `--redetect-interval`
  frames to correct drift.
- The red crosshair marks the object's center in pixel coordinates -- that's the
  value you'll eventually map to pan/tilt angles once you add hardware.

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

First run will auto-download the YOLO-World weights (~50-100MB depending on model size).

## Run it

```bash
python track.py --prompts "green apple,wine bottle" --source 0 --show-fps
```

- `--source 0` uses your default webcam. Use a file path instead to test on a video.
- `--prompts` takes a comma-separated list. Press `n` while running to cycle
  between them if you gave more than one.
- Press `r` to force a re-detect, `q` to quit.

## Tuning notes

- **`--conf`** defaults to 0.15. Open-vocabulary models tend to be less confident
  than models trained on fixed classes, so you may need to go as low as 0.1, or
  as high as 0.3+ if you're getting false positives in a cluttered scene.
- **Model size**: `yolov8s-worldv2.pt` (default) is fast, good for a first test.
  If accuracy is the bottleneck rather than speed, try `yolov8m-worldv2.pt` or
  `yolov8x-worldv2.pt`.
- **Prompt phrasing matters.** "wine bottle" tends to work better than "bottle of
  wine" -- shorter, more object-detection-dataset-like phrases generally detect
  more reliably than natural-language descriptions. Worth A/B testing a few
  phrasings for your actual target objects.
- If CSRT tracking feels laggy on your machine, swap `make_tracker()` in
  `track.py` to `cv2.legacy.TrackerKCF_create()` -- faster, a bit less robust to
  the object changing scale/orientation.

## Next steps (once CV is validated)

1. Camera-to-servo calibration (map pixel coords -> pan/tilt angles).
2. Serial/PWM control loop to an Arduino or Pi driving the pan-tilt mount.
3. Optional: depth sensing (stereo or RealSense) if you need the laser to
   converge precisely rather than just aim in the object's general direction.
