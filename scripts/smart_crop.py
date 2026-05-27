#!/usr/bin/env python3
"""Compute smart crop coordinates from face tracking data.

Reads face position data from face_track.py and computes per-frame crop X offsets
that follow the speaker's face smoothly. Outputs crop keyframes compatible with
ffmpeg's animated crop filter.

Usage:
    python3 smart_crop.py --face-data face_data.json --clips clips.json --output crop_data.json
    python3 smart_crop.py --face-data face_data.json --clips clips.json --output crop_data.json --padding 0.15

Output JSON:
{
  "clips": {
    "01": {
      "keyframes": [
        {"time": 0.0, "crop_x": 656},
        {"time": 1.5, "crop_x": 620},
        ...
      ],
      "crop_w": 608,
      "crop_h": 1080,
      "strategy": "face_track"  // "face_track", "split_screen", "center"
    }
  }
}
"""

import argparse
import json
import os
import sys


def moving_average(data, window=5):
    """Apply smoothing to reduce jitter."""
    if len(data) < window:
        return data
    smoothed = []
    half = window // 2
    for i in range(len(data)):
        start = max(0, i - half)
        end = min(len(data), i + half + 1)
        window_vals = [data[j] for j in range(start, end) if data[j] is not None]
        if window_vals:
            smoothed.append(sum(window_vals) / len(window_vals))
        else:
            smoothed.append(data[i])
    return smoothed


def face_x_to_crop_x(
    face_x: float,
    face_width: float,
    src_w: int,
    src_h: int,
    crop_w: int,
    crop_h: int,
    padding: float = 0.15,
) -> int:
    """Convert normalized face X position to crop X offset in pixels.

    The crop window is positioned so the face is offset from center toward the
    direction the person is looking (like a rule-of-thirds composition).

    padding: extra space as fraction of crop width (0.15 = 15% on each side)
    """
    # Desired: face should be at about 1/3 from the left of the crop window
    # (leaving 2/3 for the direction the person faces, which is slightly right of center)
    target_face_pos_in_crop = 0.38 + padding  # slightly right of true 1/3

    # Crop X offset such that face_x in source maps to target_face_pos_in_crop in crop
    # face_x * src_w = crop_x + target_face_pos_in_crop * crop_w
    # crop_x = face_x * src_w - target_face_pos_in_crop * crop_w
    crop_x = int(face_x * src_w - target_face_pos_in_crop * crop_w)

    # Clamp to valid range
    crop_x = max(0, min(crop_x, src_w - crop_w))

    return crop_x


def compute_crop_for_clip(
    clip_id: str,
    face_data: dict,
    src_w: int,
    src_h: int,
    padding: float = 0.15,
    smooth_window: int = 5,
) -> dict:
    """Compute crop keyframes for a single clip."""
    frames = face_data.get("frames", [])
    is_split = face_data.get("split_screen", False)
    dominant_side = face_data.get("dominant_side", "center")

    # Compute crop dimensions (9:16)
    crop_h = src_h
    crop_w = int(crop_h * 9 / 16)
    if crop_w > src_w:
        crop_w = src_w
        crop_h = int(crop_w * 16 / 9)

    if not frames:
        # No face data, return center crop
        center_x = (src_w - crop_w) // 2
        return {
            "keyframes": [{"time": 0.0, "crop_x": center_x}],
            "crop_w": crop_w,
            "crop_h": crop_h,
            "strategy": "center",
        }

    # Extract face X positions
    face_xs = []
    face_detected = []
    timestamps = []
    for f in frames:
        timestamps.append(f["time"])
        if f["detected"] and f["confidence"] > 0.5:
            face_xs.append(f["face_x"])
            face_detected.append(True)
        else:
            face_xs.append(None)
            face_detected.append(False)

    # Handle split-screen: use fixed crop targeting the guest side
    if is_split:
        if dominant_side == "right":
            # Guest on right side of split: crop centered at 75% of source width
            target_x = src_w * 0.75
        else:
            target_x = src_w * 0.25
        crop_x = int(target_x - crop_w / 2)
        crop_x = max(0, min(crop_x, src_w - crop_w))
        return {
            "keyframes": [{"time": 0.0, "crop_x": crop_x}],
            "crop_w": crop_w,
            "crop_h": crop_h,
            "strategy": "split_screen",
        }

    # Fill gaps in face detection with interpolation
    filled_xs = []
    last_valid = None
    next_valid_idx = 0

    for i in range(len(face_xs)):
        if face_xs[i] is not None:
            filled_xs.append(face_xs[i])
            last_valid = face_xs[i]
        else:
            # Find next valid
            next_valid = None
            for j in range(i + 1, len(face_xs)):
                if face_xs[j] is not None:
                    next_valid = face_xs[j]
                    break
            if last_valid is not None and next_valid is not None:
                filled_xs.append((last_valid + next_valid) / 2)
            elif last_valid is not None:
                filled_xs.append(last_valid)
            elif next_valid is not None:
                filled_xs.append(next_valid)
            else:
                filled_xs.append(0.5)  # fallback to center

    # Smooth the face positions to remove jitter
    smoothed_xs = moving_average(filled_xs, window=smooth_window)

    # Convert to crop X offsets
    keyframes = []
    for i, (ts, fx) in enumerate(zip(timestamps, smoothed_xs)):
        # Approximate face width from the data (use default if unavailable)
        fw = 0.25  # default face width as fraction of frame
        cx = face_x_to_crop_x(fx, fw, src_w, src_h, crop_w, crop_h, padding)
        keyframes.append({"time": round(ts, 3), "crop_x": cx})

    # Deduplicate: only keep keyframes when crop_x changes significantly
    deduped = [keyframes[0]]
    for kf in keyframes[1:]:
        if abs(kf["crop_x"] - deduped[-1]["crop_x"]) >= 4:
            deduped.append(kf)

    # Always include last keyframe
    if len(deduped) > 1 and deduped[-1]["time"] != keyframes[-1]["time"]:
        deduped.append(keyframes[-1])

    strategy = "face_track" if any(face_detected) else "center"

    return {
        "keyframes": deduped,
        "crop_w": crop_w,
        "crop_h": crop_h,
        "strategy": strategy,
    }


def main():
    parser = argparse.ArgumentParser(description="Compute smart crop coordinates")
    parser.add_argument("--face-data", required=True, help="Face data JSON from face_track.py")
    parser.add_argument("--clips", required=True, help="Clips JSON file")
    parser.add_argument("--output", required=True, help="Output crop data JSON")
    parser.add_argument("--source", help="Source video (for resolution detection)")
    parser.add_argument(
        "--src-w", type=int, default=1920, help="Source width (default: 1920)"
    )
    parser.add_argument(
        "--src-h", type=int, default=1080, help="Source height (default: 1080)"
    )
    parser.add_argument(
        "--padding",
        type=float,
        default=0.15,
        help="Extra padding around face as fraction of crop width (default: 0.15)",
    )
    parser.add_argument(
        "--smooth",
        type=int,
        default=5,
        help="Smoothing window size in frames (default: 5)",
    )

    args = parser.parse_args()

    # Detect source resolution if source provided
    src_w, args.src_h = args.src_w, args.src_h
    if args.source and os.path.isfile(args.source):
        import subprocess
        probe = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0", args.source,
            ],
            capture_output=True, text=True,
        )
        parts = probe.stdout.strip().split(",")
        if len(parts) == 2:
            src_w, src_h = int(parts[0]), int(parts[1])
            print(f"Source resolution: {src_w}x{src_h}")

    with open(args.face_data) as f:
        face_json = json.load(f)

    with open(args.clips) as f:
        clips_json = json.load(f)

    clips = clips_json.get("clips", [])
    face_clips = face_json.get("clips", {})

    print(f"Computing smart crop for {len(clips)} clips...")

    all_data = {
        "clips": {},
        "metadata": {
            "src_w": src_w,
            "src_h": src_h,
            "padding": args.padding,
            "smooth_window": args.smooth,
        },
    }

    for clip in clips:
        clip_id = clip.get("id", "01")
        fd = face_clips.get(clip_id, {})

        crop_info = compute_crop_for_clip(
            clip_id, fd, src_w, src_h, args.padding, args.smooth
        )

        all_data["clips"][clip_id] = crop_info

        strategy = crop_info["strategy"]
        num_kf = len(crop_info["keyframes"])
        print(f"  Clip {clip_id}: {strategy}, {num_kf} keyframes, crop={crop_info['crop_w']}x{crop_info['crop_h']}")

    # Write output
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(all_data, f, indent=2)

    print(f"\nCrop data written to {args.output}")


if __name__ == "__main__":
    main()
