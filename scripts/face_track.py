#!/usr/bin/env python3
"""Track face position in video clips using MediaPipe FaceLandmarker.

Uses the MediaPipe Tasks API (v0.10+) FaceLandmarker to detect face position
per-frame, outputting normalized coordinates for smart crop computation.

Usage:
    python3 face_track.py --source source.mp4 --clips clips.json --output face_data.json
    python3 face_track.py --source source.mp4 --clips clips.json --output face_data.json --model face_landmarker_v2.task

Output JSON:
{
  "clips": {
    "01": {
      "frames": [
        {"time": 0.0, "face_x": 0.5, "face_y": 0.3, "confidence": 0.98, "detected": true},
        ...
      ],
      "split_screen": false,
      "dominant_side": "center"  // "left", "right", "center"
    }
  }
}
"""

import argparse
import json
import os
import subprocess
import sys
import time

import cv2
import numpy as np

# MediaPipe Tasks API (v0.10+)
from mediapipe.tasks.python.vision import (
    FaceLandmarker,
    FaceLandmarkerOptions,
    RunningMode,
)
from mediapipe.tasks.python.core import base_options


# Face landmark indices for crop tracking
NOSE_TIP = 1
LEFT_EYE_OUTER = 33
RIGHT_EYE_OUTER = 263
CHIN = 152
FOREHEAD = 10
LEFT_FACE_EDGE = 234
RIGHT_FACE_EDGE = 454

# Default model bundled with MediaPipe (auto-downloaded on first run)
DEFAULT_MODEL_PATH = os.path.expanduser(
    "~/.mediapipe/face_landmarker_v2_with_blendshapes.task"
)

# Fallback: download URL for the model
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)


def ensure_model(model_path: str) -> str:
    """Ensure the FaceLandmarker model exists, download if needed."""
    if os.path.exists(model_path):
        return model_path

    # Try the default path
    if os.path.exists(DEFAULT_MODEL_PATH):
        return DEFAULT_MODEL_PATH

    # Download
    os.makedirs(os.path.dirname(model_path) or DEFAULT_MODEL_PATH.rsplit("/", 1)[0], exist_ok=True)
    target = model_path if model_path else DEFAULT_MODEL_PATH
    print(f"Downloading FaceLandmarker model to {target}...")
    import urllib.request
    urllib.request.urlretrieve(MODEL_URL, target)
    return target


def extract_clip_frames(
    source: str, start: float, end: float, fps: float = 10.0
) -> list:
    """Extract frames from a video segment at specified FPS using ffmpeg.

    Returns list of (timestamp, numpy_array) tuples.
    """
    duration = end - start
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", source,
        "-t", str(duration),
        "-vf", f"fps={fps},scale=480:-1",
        "-pix_fmt", "rgb24",
        "-f", "rawvideo",
        "-"
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        print(f"  WARNING: ffmpeg frame extraction failed: {result.stderr[-200:]}")
        return []

    raw = result.stdout
    # Determine frame dimensions from the scaled output (480 width, maintain aspect)
    # We need to know the actual height - probe it
    probe_cmd = [
        "ffprobe", "-v", "quiet",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0", source
    ]
    probe = subprocess.run(probe_cmd, capture_output=True, text=True)
    parts = probe.stdout.strip().split(",")
    if len(parts) == 2:
        src_w, src_h = int(parts[0]), int(parts[1])
    else:
        src_w, src_h = 1920, 1080  # fallback

    scaled_w = 480
    scaled_h = int(src_h * (scaled_w / src_w))
    frame_size = scaled_w * scaled_h * 3

    frames = []
    num_frames = len(raw) // frame_size
    for i in range(num_frames):
        offset = i * frame_size
        frame = np.frombuffer(raw[offset:offset + frame_size], dtype=np.uint8)
        frame = frame.reshape((scaled_h, scaled_w, 3))
        timestamp = start + (i / fps)
        frames.append((timestamp, frame))

    return frames


def track_faces_in_frames(
    frames: list, model_path: str, num_faces: int = 2
) -> list:
    """Run MediaPipe FaceLandmarker on extracted frames.

    Returns list of dicts with face position data per frame.
    """
    model_path = ensure_model(model_path)

    options = FaceLandmarkerOptions(
        base_options=base_options.BaseOptions(model_asset_path=model_path),
        running_mode=RunningMode.IMAGE,
        num_faces=num_faces,
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
        min_tracking_confidence=0.5,
        output_face_blendshapes=False,
        output_facial_transformation_matrixes=False,
    )

    results = []
    with FaceLandmarker.create_from_options(options) as landmarker:
        for timestamp, frame_bgr in frames:
            # Convert BGR (from ffmpeg) to RGB for MediaPipe
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

            # Create MediaPipe Image
            import mediapipe as mp
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)

            # Detect
            detection_result = landmarker.detect(mp_image)

            frame_data = {
                "time": round(timestamp, 3),
                "detected": False,
                "face_x": 0.5,
                "face_y": 0.35,
                "confidence": 0.0,
                "face_width": 0.0,
                "num_faces": 0,
            }

            if detection_result.face_landmarks:
                # Use the first (largest/most confident) face
                landmarks = detection_result.face_landmarks[0]
                frame_data["num_faces"] = len(detection_result.face_landmarks)

                # Get nose tip as primary center reference
                nose = landmarks[NOSE_TIP]
                frame_data["face_x"] = round(nose.x, 4)
                frame_data["face_y"] = round(nose.y, 4)
                frame_data["detected"] = True

                # Compute face width from eye positions
                left_eye = landmarks[LEFT_EYE_OUTER]
                right_eye = landmarks[RIGHT_EYE_OUTER]
                face_w = abs(right_eye.x - left_eye.x) * 3.0  # ~3x inter-eye distance
                frame_data["face_width"] = round(min(face_w, 1.0), 4)

                # Confidence proxy: use presence of key landmarks
                frame_data["confidence"] = round(
                    max(nose.presence or 0.5, left_eye.presence or 0.5, right_eye.presence or 0.5),
                    4,
                )

            results.append(frame_data)

    return results


def detect_split_screen(face_data: list) -> tuple:
    """Detect if the video has a split-screen layout.

    Returns (is_split: bool, dominant_side: str).
    dominant_side is "left", "right", or "center".
    """
    detected = [f for f in face_data if f["detected"]]
    if len(detected) < 5:
        return False, "center"

    xs = [f["face_x"] for f in detected]
    median_x = sorted(xs)[len(xs) // 2]

    # If the median face position is significantly off-center
    if median_x < 0.35:
        return False, "left"
    elif median_x > 0.65:
        return False, "right"

    # Check for bimodal distribution (two faces, split screen)
    left_count = sum(1 for x in xs if x < 0.4)
    right_count = sum(1 for x in xs if x > 0.6)
    total = len(xs)

    if left_count > total * 0.3 and right_count > total * 0.3:
        # Split screen detected - determine which side is the guest
        # (usually the side with more consistent/single face)
        return True, "right"  # Default: guest on right

    return False, "center"


def main():
    parser = argparse.ArgumentParser(description="Track face position in clips")
    parser.add_argument("--source", required=True, help="Source video file")
    parser.add_argument("--clips", required=True, help="Clips JSON file")
    parser.add_argument("--output", required=True, help="Output face data JSON")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL_PATH,
        help=f"FaceLandmarker model path (default: {DEFAULT_MODEL_PATH})",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=10.0,
        help="Frame sampling rate for face detection (default: 10 fps)",
    )
    parser.add_argument(
        "--num-faces",
        type=int,
        default=2,
        help="Max faces to detect per frame (default: 2)",
    )

    args = parser.parse_args()

    if not os.path.isfile(args.source):
        print(f"ERROR: Source file not found: {args.source}")
        sys.exit(1)

    with open(args.clips) as f:
        clips_data = json.load(f)

    clips = clips_data.get("clips", [])
    print(f"Tracking faces in {len(clips)} clips at {args.fps} fps...")

    all_data = {"clips": {}, "metadata": {"fps": args.fps, "model": args.model}}
    start_time = time.time()

    for clip in clips:
        clip_id = clip.get("id", "01")
        clip_start = clip["start"]
        clip_end = clip["end"]
        duration = clip_end - clip_start

        print(f"  Clip {clip_id} ({clip_start:.1f}s -> {clip_end:.1f}s, {duration:.1f}s)...", end=" ", flush=True)

        # Extract frames
        frames = extract_clip_frames(args.source, clip_start, clip_end, args.fps)
        if not frames:
            print("NO FRAMES")
            all_data["clips"][clip_id] = {
                "frames": [],
                "split_screen": False,
                "dominant_side": "center",
            }
            continue

        # Track faces
        face_results = track_faces_in_frames(frames, args.model, args.num_faces)

        # Detect layout
        is_split, dominant_side = detect_split_screen(face_results)

        detected_count = sum(1 for f in face_results if f["detected"])
        print(
            f"{len(frames)} frames, {detected_count} detected"
            + (f", SPLIT ({dominant_side})" if is_split else "")
        )

        all_data["clips"][clip_id] = {
            "frames": face_results,
            "split_screen": is_split,
            "dominant_side": dominant_side,
        }

    elapsed = time.time() - start_time
    all_data["metadata"]["processing_time_sec"] = round(elapsed, 1)

    # Write output
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(all_data, f, indent=2)

    print(f"\nFace data written to {args.output} ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
