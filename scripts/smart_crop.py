#!/usr/bin/env python3
"""Convert MediaPipe face positions into smooth animated 9:16 crop keyframes."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np


def probe_resolution(source: str) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0", source,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-1000:])
    parts = result.stdout.strip().split(",")
    if len(parts) != 2:
        raise RuntimeError("Resolusi video tidak terbaca.")
    return int(parts[0]), int(parts[1])


def interpolate_missing(values: list[float | None]) -> np.ndarray:
    arr = np.array([np.nan if value is None else float(value) for value in values])
    valid = np.where(~np.isnan(arr))[0]
    if valid.size == 0:
        return np.full(arr.shape, 0.5, dtype=np.float64)
    if valid.size == 1:
        return np.full(arr.shape, arr[valid[0]], dtype=np.float64)
    indexes = np.arange(len(arr))
    return np.interp(indexes, valid, arr[valid])


def ema(values: np.ndarray, alpha: float = 0.28) -> np.ndarray:
    if values.size == 0:
        return values
    output = np.empty_like(values, dtype=np.float64)
    output[0] = values[0]
    for i in range(1, values.size):
        output[i] = alpha * values[i] + (1.0 - alpha) * output[i - 1]
    # Forward/backward smoothing reduces delay while staying CPU-cheap.
    reverse = np.empty_like(output)
    reverse[-1] = output[-1]
    for i in range(output.size - 2, -1, -1):
        reverse[i] = alpha * output[i] + (1.0 - alpha) * reverse[i + 1]
    return (output + reverse) / 2.0


def limit_velocity(values: np.ndarray, max_delta: float) -> np.ndarray:
    if values.size == 0:
        return values
    output = values.copy()
    for i in range(1, output.size):
        delta = float(output[i] - output[i - 1])
        output[i] = output[i - 1] + float(np.clip(delta, -max_delta, max_delta))
    return output


def build_clip_crop(face_info: dict, src_w: int, src_h: int) -> dict:
    frames = face_info.get("frames", [])
    crop_h = src_h
    crop_w = int(round(src_h * 9 / 16))
    if crop_w > src_w:
        crop_w = src_w
        crop_h = int(round(src_w * 16 / 9))

    center_x = max(0, (src_w - crop_w) // 2)
    detected_count = sum(1 for frame in frames if frame.get("detected"))

    if not frames or detected_count == 0:
        return {
            "strategy": "center",
            "crop_w": crop_w,
            "crop_h": crop_h,
            "keyframes": [{"time": 0.0, "crop_x": center_x}],
            "detected_frames": 0,
            "total_frames": len(frames),
        }

    times = np.array([float(frame.get("time", 0.0)) for frame in frames])
    raw_x = [
        float(frame.get("face_x", 0.5)) if frame.get("detected") else None
        for frame in frames
    ]
    face_x = ema(interpolate_missing(raw_x), alpha=0.28)

    # Keep the face near 43% of the vertical frame, leaving more visual room
    # in the direction of the rest of the source frame.
    target_ratio = 0.43
    crop_x = face_x * src_w - target_ratio * crop_w
    crop_x = np.clip(crop_x, 0, max(0, src_w - crop_w))

    # Dead-zone + speed limit avoids nervous camera movement.
    max_delta = max(6.0, crop_w * 0.045)
    crop_x = limit_velocity(crop_x, max_delta=max_delta)

    keyframes = []
    previous = None
    for timestamp, x_value in zip(times, crop_x):
        x_int = int(round(float(x_value)))
        if previous is None or abs(x_int - previous) >= 3:
            keyframes.append({"time": round(float(timestamp), 3), "crop_x": x_int})
            previous = x_int

    if not keyframes:
        keyframes = [{"time": round(float(times[0]), 3), "crop_x": center_x}]
    elif keyframes[-1]["time"] != round(float(times[-1]), 3):
        keyframes.append({"time": round(float(times[-1]), 3), "crop_x": int(round(float(crop_x[-1])))})

    strategy = "face_track"
    if face_info.get("split_screen"):
        strategy = "face_track_multi_face"

    return {
        "strategy": strategy,
        "crop_w": crop_w,
        "crop_h": crop_h,
        "keyframes": keyframes,
        "detected_frames": detected_count,
        "total_frames": len(frames),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--face-data", required=True)
    parser.add_argument("--clips", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--smooth", type=int, default=5)  # kept for compatibility
    args = parser.parse_args()

    src_w, src_h = probe_resolution(args.source)
    face_payload = json.loads(Path(args.face_data).read_text(encoding="utf-8"))
    clips_payload = json.loads(Path(args.clips).read_text(encoding="utf-8"))

    output = {
        "clips": {},
        "metadata": {
            "src_w": src_w,
            "src_h": src_h,
            "engine": "animated-face-crop-v2",
        },
    }

    for clip in clips_payload.get("clips", []):
        clip_id = str(clip.get("id", "01"))
        face_info = face_payload.get("clips", {}).get(clip_id, {})
        crop_info = build_clip_crop(face_info, src_w, src_h)
        output["clips"][clip_id] = crop_info
        print(
            f"Clip {clip_id}: {crop_info['strategy']}, "
            f"{len(crop_info['keyframes'])} keyframes",
            flush=True,
        )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Smart crop written to {out_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"SMART_CROP_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
