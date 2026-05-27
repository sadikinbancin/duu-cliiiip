#!/usr/bin/env python3
"""Render vertical clips from source video using ffmpeg.

Supports:
- Static center crop (original behavior)
- Face-tracked animated crop (via smart_crop.py output)
- Remotion caption overlay compositing

Usage:
    python3 render.py --source source.mp4 --clips clips.json --output-dir exports/vertical/
    python3 render.py --source source.mp4 --clips clips.json --output-dir exports/vertical/ --crf 23
    python3 render.py --source source.mp4 --clips clips.json --output-dir exports/vertical/ --crop-data crop_data.json
    python3 render.py --source source.mp4 --clips clips.json --output-dir exports/vertical/ --captions-dir captions_remotion/
"""

import argparse
import json
import os
import subprocess
import sys
import time


def get_video_info(path):
    """Get video width, height, and duration."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-show_format", "-select_streams", "v:0", path],
        capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    fmt = data.get("format", {})
    return int(stream["width"]), int(stream["height"]), float(fmt.get("duration", 0))


def compute_crop(src_w, src_h, x_offset=None, y_offset=0):
    """Compute 9:16 crop parameters."""
    crop_h = src_h - y_offset
    crop_w = int(crop_h * 9 / 16)
    if crop_w > src_w:
        crop_w = src_w
        crop_h = int(crop_w * 16 / 9)

    if x_offset is None:
        x_offset = (src_w - crop_w) // 2

    # Clamp
    x_offset = max(0, min(x_offset, src_w - crop_w))
    y_offset = max(0, min(y_offset, src_h - crop_h))

    return crop_w, crop_h, x_offset, y_offset


def build_animated_crop_filter(crop_keyframes, crop_w, crop_h, src_w, src_h):
    """Build an ffmpeg filter string for animated crop using sendcmd.

    Uses the crop filter with 'enable' expressions driven by sendcmd keyframes
    for smooth face-tracked panning.

    For simplicity and reliability, we use the 'zoompan' filter approach:
    - Generate a crop_x expression that interpolates between keyframes
    - Use the crop filter with a time-based expression
    """
    if len(crop_keyframes) <= 1:
        # Static crop
        cx = crop_keyframes[0]["crop_x"] if crop_keyframes else (src_w - crop_w) // 2
        return f"crop={crop_w}:{crop_h}:{cx}:0"

    # Build a smooth interpolation using linear segments between keyframes
    # ffmpeg's crop filter supports expressions with 'between' and 'lerp'
    # We'll use the geq approach or the simpler: crop with sendcmd

    # Simpler approach: use the crop filter with a time-varying x expression
    # ffmpeg supports conditional expressions in filter params
    # We build a chain of between() conditions

    # For reliability, use the 'sendcmd' approach with crop
    # First, build the static crop filter
    filter_str = f"crop={crop_w}:{crop_h}"

    # Build the x position expression
    # Use a piecewise linear interpolation between keyframes
    expr_parts = []
    for i, kf in enumerate(crop_keyframes):
        t = kf["time"]
        cx = kf["crop_x"]
        if i == 0:
            expr_parts.append(f"if(lte(t,{t}),{cx}")
        elif i == len(crop_keyframes) - 1:
            expr_parts.append(f",{cx})")
        else:
            next_t = crop_keyframes[i + 1]["time"]
            next_cx = crop_keyframes[i + 1]["crop_x"]
            # Linear interpolation between this keyframe and next
            expr_parts.append(
                f",if(lte(t,{next_t}),"
                f"lerp({cx},{next_cx},(t-{t})/({next_t}-{t}))"
            )

    # Close all the parentheses
    x_expr = "".join(expr_parts)

    # Clamp the expression
    max_x = src_w - crop_w
    x_expr = f"min(max({x_expr},0),{max_x})"

    return f"crop={crop_w}:{crop_h}:'{x_expr}':0"


def render_clip(source, clip, output_path, crf=23, crop_x=None, crop_y=0,
                src_w=None, src_h=None, captions_path=None,
                crop_keyframes=None):
    """Render a single vertical clip.

    Args:
        crop_keyframes: If provided, enables face-tracked animated crop.
            List of {"time": float, "crop_x": int} dicts.
    """
    duration = clip["end"] - clip["start"]

    if src_w is None or src_h is None:
        src_w, src_h, _ = get_video_info(source)

    # Build video filter chain
    if crop_keyframes and len(crop_keyframes) > 0:
        # Face-tracked animated crop
        crop_w = crop_keyframes[0].get("crop_w", int(src_h * 9 / 16))
        crop_h = crop_keyframes[0].get("crop_h", src_h)
        # Adjust keyframes to be clip-relative
        clip_start = clip["start"]
        rel_keyframes = [
            {"time": round(kf["time"] - clip_start, 3), "crop_x": kf["crop_x"]}
            for kf in crop_keyframes
            if clip_start <= kf["time"] <= clip["end"]
        ]
        if not rel_keyframes:
            rel_keyframes = [{"time": 0.0, "crop_x": crop_x or (src_w - crop_w) // 2}]

        vf = build_animated_crop_filter(rel_keyframes, crop_w, crop_h, src_w, src_h)
        vf += ",scale=1080:1920"
    else:
        # Static crop (original behavior)
        crop_w, crop_h, cx, cy = compute_crop(src_w, src_h, crop_x, crop_y)
        vf = f"crop={crop_w}:{crop_h}:{cx}:{cy},scale=1080:1920"

    # Add captions if provided (ASS subtitles burned in)
    if captions_path and os.path.exists(captions_path):
        vf = f"subtitles={captions_path},{vf}"

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(clip["start"]),
        "-i", source,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR rendering clip {clip.get('id', '?')}: {result.stderr[-300:]}")
        return False

    return True


def composite_caption_overlay(clip_path, caption_overlay_path, output_path, crf=23):
    """Composite a Remotion-rendered caption overlay (WebM with alpha) onto a clip.

    The caption overlay should be a WebM with transparency (VP8/VP9 alpha channel)
    at 1080x1920 resolution, matching the clip duration.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", clip_path,
        "-i", caption_overlay_path,
        "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR compositing captions: {result.stderr[-300:]}")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Render vertical clips")
    parser.add_argument("--source", required=True, help="Source video file")
    parser.add_argument("--clips", required=True, help="Clips JSON file")
    parser.add_argument("--output-dir", default="exports/vertical/", help="Output directory")
    parser.add_argument("--crf", type=int, default=23, help="CRF quality (default: 23)")
    parser.add_argument("--crop-x", type=int, default=None,
                        help="X offset for static crop (default: center)")
    parser.add_argument("--crop-y", type=int, default=0,
                        help="Y offset for crop (default: 0)")
    parser.add_argument("--crop-data", default=None,
                        help="Crop data JSON from smart_crop.py (enables face-tracked crop)")
    parser.add_argument("--captions-dir", default=None,
                        help="Directory containing .ass caption files (named <id>.ass)")
    parser.add_argument("--captions-remotion-dir", default=None,
                        help="Directory containing Remotion-rendered caption overlays (named <id>_captions.webm)")
    parser.add_argument("--horizontal", action="store_true",
                        help="Also render horizontal (source resolution) clips)")

    args = parser.parse_args()

    if not os.path.isfile(args.source):
        print(f"ERROR: Source file not found: {args.source}")
        sys.exit(1)

    with open(args.clips) as f:
        clips_data = json.load(f)

    clips = clips_data.get("clips", [])
    src_w, src_h, duration = get_video_info(args.source)
    print(f"Source: {src_w}x{src_h}, {duration:.1f}s")
    print(f"Clips: {len(clips)}, CRF: {args.crf}")

    # Load crop data if provided
    crop_data = None
    if args.crop_data and os.path.isfile(args.crop_data):
        with open(args.crop_data) as f:
            crop_data = json.load(f)
        print(f"Face-tracked crop: ENABLED ({len(crop_data.get('clips', {}))} clips)")
    else:
        print(f"Face-tracked crop: DISABLED (using static crop)")

    os.makedirs(args.output_dir, exist_ok=True)
    if args.horizontal:
        h_dir = args.output_dir.replace("/vertical/", "/horizontal/")
        os.makedirs(h_dir, exist_ok=True)

    success = 0
    start = time.time()

    for clip in clips:
        clip_id = clip.get("id", "01")
        output_path = os.path.join(args.output_dir, f"{clip_id}_v.mp4")

        # Determine crop keyframes for this clip
        clip_crop_keyframes = None
        if crop_data and clip_id in crop_data.get("clips", {}):
            clip_crop_keyframes = crop_data["clips"][clip_id].get("keyframes", None)

        # Determine ASS caption path
        captions_path = None
        if args.captions_dir:
            candidate = os.path.join(args.captions_dir, f"{clip_id}.ass")
            if os.path.exists(candidate):
                captions_path = candidate

        print(f"  Rendering clip {clip_id} ({clip['start']:.1f}s -> {clip['end']:.1f}s, "
              f"{clip['duration']:.1f}s)...", end=" ", flush=True)

        ok = render_clip(
            args.source, clip, output_path, args.crf,
            args.crop_x, args.crop_y, src_w, src_h, captions_path,
            crop_keyframes=clip_crop_keyframes,
        )

        if ok:
            size_mb = os.path.getsize(output_path) / 1024 / 1024
            print(f"OK ({size_mb:.1f}MB)")
            success += 1

            # Composite Remotion caption overlay if provided
            if args.captions_remotion_dir:
                overlay_path = os.path.join(args.captions_remotion_dir, f"{clip_id}_captions.webm")
                if os.path.exists(overlay_path):
                    captioned_path = os.path.join(args.output_dir, f"{clip_id}_v_captions.mp4")
                    print(f"    Compositing Remotion captions...", end=" ", flush=True)
                    if composite_caption_overlay(output_path, overlay_path, captioned_path, args.crf):
                        cap_size = os.path.getsize(captioned_path) / 1024 / 1024
                        print(f"OK ({cap_size:.1f}MB)")
                    else:
                        print("FAILED")

            # Horizontal
            if args.horizontal:
                h_path = os.path.join(h_dir, f"{clip_id}_h.mp4")
                dur = clip["end"] - clip["start"]
                cmd = [
                    "ffmpeg", "-y", "-ss", str(clip["start"]), "-i", args.source,
                    "-t", str(dur),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-c:a", "aac", "-b:a", "128k",
                    "-movflags", "+faststart", h_path
                ]
                subprocess.run(cmd, capture_output=True)

    elapsed = time.time() - start
    print(f"\nRendered {success}/{len(clips)} clips in {elapsed:.1f}s -> {args.output_dir}")


if __name__ == "__main__":
    main()
