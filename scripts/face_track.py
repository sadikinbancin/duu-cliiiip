#!/usr/bin/env python3
"""CPU-friendly MediaPipe face tracking for selected clips.

Reads clips.json and samples only the selected clip ranges. For continuity it
chooses the face closest to the previous tracked face, falling back to the
largest face when tracking starts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python.core import base_options
from mediapipe.tasks.python.vision import (
    FaceLandmarker,
    FaceLandmarkerOptions,
    RunningMode,
)


DEFAULT_MODEL = "/app/models/face_landmarker.task"


def choose_face(face_sets, previous_x: float | None):
    """Return (landmarks, center_x, center_y, width, height) for best face."""
    candidates = []
    for landmarks in face_sets:
        xs = np.array([float(p.x) for p in landmarks], dtype=np.float32)
        ys = np.array([float(p.y) for p in landmarks], dtype=np.float32)
        x0, x1 = float(xs.min()), float(xs.max())
        y0, y1 = float(ys.min()), float(ys.max())
        width = max(0.0, x1 - x0)
        height = max(0.0, y1 - y0)
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0
        area = width * height
        candidates.append((landmarks, cx, cy, width, height, area))

    if not candidates:
        return None

    if previous_x is None:
        return max(candidates, key=lambda item: item[5])[:5]

    # Keep the same person whenever possible; area is a small tie-breaker.
    return min(
        candidates,
        key=lambda item: abs(item[1] - previous_x) - min(item[5], 0.25) * 0.12,
    )[:5]


def track_clip(cap, landmarker, clip, fps: float):
    start = float(clip["start"])
    end = float(clip["end"])
    step = 1.0 / max(0.5, fps)
    t = start
    previous_x = None
    rows = []

    while t <= end + 1e-6:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            rows.append({
                "time": round(t, 3),
                "detected": False,
                "face_x": previous_x if previous_x is not None else 0.5,
                "face_y": 0.38,
                "face_width": 0.0,
                "face_height": 0.0,
                "num_faces": 0,
                "confidence": 0.0,
            })
            t += step
            continue

        # Downscale only for detection. Coordinates remain normalized.
        h, w = frame.shape[:2]
        if w > 640:
            new_h = max(2, int(h * 640 / w))
            frame = cv2.resize(frame, (640, new_h), interpolation=cv2.INTER_AREA)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = landmarker.detect(mp_image)
        face_sets = result.face_landmarks or []
        selected = choose_face(face_sets, previous_x)

        if selected is None:
            rows.append({
                "time": round(t, 3),
                "detected": False,
                "face_x": previous_x if previous_x is not None else 0.5,
                "face_y": 0.38,
                "face_width": 0.0,
                "face_height": 0.0,
                "num_faces": 0,
                "confidence": 0.0,
            })
        else:
            _, cx, cy, fw, fh = selected
            previous_x = float(np.clip(cx, 0.0, 1.0))
            rows.append({
                "time": round(t, 3),
                "detected": True,
                "face_x": round(previous_x, 5),
                "face_y": round(float(np.clip(cy, 0.0, 1.0)), 5),
                "face_width": round(float(np.clip(fw, 0.0, 1.0)), 5),
                "face_height": round(float(np.clip(fh, 0.0, 1.0)), 5),
                "num_faces": len(face_sets),
                "confidence": 1.0,
            })

        t += step

    detected = [row for row in rows if row["detected"]]
    multi_ratio = (
        sum(1 for row in detected if row.get("num_faces", 0) >= 2) / len(detected)
        if detected else 0.0
    )
    median_x = float(np.median([row["face_x"] for row in detected])) if detected else 0.5

    if median_x < 0.38:
        dominant_side = "left"
    elif median_x > 0.62:
        dominant_side = "right"
    else:
        dominant_side = "center"

    return {
        "frames": rows,
        "detected_frames": len(detected),
        "total_frames": len(rows),
        "split_screen": multi_ratio >= 0.35,
        "dominant_side": dominant_side,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--clips", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default=os.getenv("MEDIAPIPE_MODEL_PATH", DEFAULT_MODEL))
    parser.add_argument("--fps", type=float, default=3.0)
    parser.add_argument("--num-faces", type=int, default=4)
    args = parser.parse_args()

    if not Path(args.source).is_file():
        raise FileNotFoundError(args.source)
    if not Path(args.model).is_file():
        raise FileNotFoundError(f"MediaPipe model not found: {args.model}")

    clips_payload = json.loads(Path(args.clips).read_text(encoding="utf-8"))
    clips = clips_payload.get("clips", [])
    if not clips:
        raise RuntimeError("clips.json tidak memiliki clip.")

    cap = cv2.VideoCapture(args.source)
    if not cap.isOpened():
        raise RuntimeError("OpenCV gagal membuka video.")

    options = FaceLandmarkerOptions(
        base_options=base_options.BaseOptions(model_asset_path=args.model),
        running_mode=RunningMode.IMAGE,
        num_faces=max(1, args.num_faces),
        min_face_detection_confidence=0.35,
        min_face_presence_confidence=0.35,
        min_tracking_confidence=0.35,
        output_face_blendshapes=False,
        output_facial_transformation_matrixes=False,
    )

    started = time.time()
    output = {
        "clips": {},
        "metadata": {
            "fps": args.fps,
            "model": args.model,
            "engine": "MediaPipe FaceLandmarker",
        },
    }

    try:
        with FaceLandmarker.create_from_options(options) as landmarker:
            for clip in clips:
                clip_id = str(clip.get("id", "01"))
                result = track_clip(cap, landmarker, clip, args.fps)
                output["clips"][clip_id] = result
                print(
                    f"Clip {clip_id}: {result['detected_frames']}/"
                    f"{result['total_frames']} sampled frames detected",
                    flush=True,
                )
    finally:
        cap.release()

    output["metadata"]["processing_time_sec"] = round(time.time() - started, 2)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Face tracking written to {out_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FACE_TRACK_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
