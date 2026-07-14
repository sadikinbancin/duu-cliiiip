#!/usr/bin/env python3
"""Build Director Mode crop locks and no-face blur intervals for 9:16 clips."""

from __future__ import annotations

import argparse
import bisect
import json
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


def load_scenes(path: str | None) -> list[dict]:
    if not path:
        return []
    source = Path(path)
    if not source.is_file():
        return []
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        scenes = payload.get("scenes", [])
        return sorted(
            [
                {
                    "start": float(item.get("start", 0.0)),
                    "end": float(item.get("end", item.get("start", 0.0))),
                }
                for item in scenes
                if float(item.get("end", item.get("start", 0.0)))
                > float(item.get("start", 0.0))
            ],
            key=lambda item: item["start"],
        )
    except Exception:
        return []


def scene_index(timestamp: float, scenes: list[dict], starts: list[float]) -> int:
    if not scenes:
        return 0
    index = max(0, bisect.bisect_right(starts, timestamp) - 1)
    if index < len(scenes) and timestamp <= scenes[index]["end"] + 0.05:
        return index
    return min(index, len(scenes) - 1)


def merge_intervals(intervals: list[tuple[float, float]], gap: float = 0.18):
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if not merged or start > merged[-1][1] + gap:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(item[0], item[1]) for item in merged]


def no_face_intervals(
    frames: list[dict],
    clip_start: float,
    clip_end: float,
    minimum_seconds: float = 1.0,
) -> list[dict]:
    if not frames:
        return [{"start": 0.0, "end": round(clip_end - clip_start, 3)}]

    times = sorted(float(frame.get("time", clip_start)) for frame in frames)
    steps = np.diff(times)
    sample_step = float(np.median(steps)) if steps.size else 1.0 / 3.0
    half_step = max(0.05, sample_step / 2.0)

    intervals: list[tuple[float, float]] = []
    run_start = None
    run_end = None

    for frame in sorted(frames, key=lambda item: float(item.get("time", 0.0))):
        timestamp = float(frame.get("time", clip_start))
        if not frame.get("detected"):
            if run_start is None:
                run_start = timestamp - half_step
            run_end = timestamp + half_step
        elif run_start is not None:
            if run_end is not None and run_end - run_start >= minimum_seconds:
                intervals.append((run_start, run_end))
            run_start = None
            run_end = None

    if run_start is not None and run_end is not None:
        if run_end - run_start >= minimum_seconds:
            intervals.append((run_start, run_end))

    clipped = []
    for start, end in merge_intervals(intervals):
        start = max(clip_start, start - 0.10)
        end = min(clip_end, end + 0.10)
        if end - start >= minimum_seconds:
            clipped.append(
                {
                    "start": round(start - clip_start, 3),
                    "end": round(end - clip_start, 3),
                }
            )
    return clipped


def director_segments(
    frames: list[dict],
    scenes: list[dict],
    clip_start: float,
    clip_end: float,
) -> list[dict]:
    starts = [item["start"] for item in scenes]
    segments: list[dict] = []
    current = None
    last_detected_time = None

    for frame in sorted(frames, key=lambda item: float(item.get("time", 0.0))):
        if not frame.get("detected"):
            continue

        timestamp = float(frame.get("time", clip_start))
        if timestamp < clip_start - 0.1 or timestamp > clip_end + 0.1:
            continue

        track_id = frame.get("active_track_id")
        if track_id is None:
            track_id = "unknown"

        current_scene = scene_index(timestamp, scenes, starts)
        long_gap = (
            last_detected_time is not None and timestamp - last_detected_time > 1.0
        )
        key = (current_scene, str(track_id))

        if current is None or current["key"] != key or long_gap:
            if current is not None:
                segments.append(current)
            current = {
                "key": key,
                "scene_id": current_scene,
                "track_id": track_id,
                "start": timestamp,
                "end": timestamp,
                "xs": [float(frame.get("face_x", 0.5))],
            }
        else:
            current["end"] = timestamp
            current["xs"].append(float(frame.get("face_x", 0.5)))

        last_detected_time = timestamp

    if current is not None:
        segments.append(current)

    for segment in segments:
        xs = np.array(segment.pop("xs"), dtype=np.float64)
        segment["face_x"] = float(np.median(xs))
    return segments


def crop_x_for_face(face_x: float, src_w: int, crop_w: int) -> int:
    value = face_x * src_w - 0.50 * crop_w
    return int(round(float(np.clip(value, 0, max(0, src_w - crop_w)))))


def append_keyframe(keyframes: list[dict], timestamp: float, crop_x: int):
    timestamp = round(float(timestamp), 3)
    crop_x = int(crop_x)
    if keyframes and abs(timestamp - keyframes[-1]["time"]) < 0.001:
        keyframes[-1] = {"time": timestamp, "crop_x": crop_x}
        return
    keyframes.append({"time": timestamp, "crop_x": crop_x})


def build_locked_keyframes(
    segments: list[dict],
    src_w: int,
    crop_w: int,
    clip_start: float,
    clip_end: float,
) -> tuple[list[dict], int]:
    if not segments:
        center_x = max(0, (src_w - crop_w) // 2)
        return [{"time": round(clip_start, 3), "crop_x": center_x}], 0

    keyframes: list[dict] = []
    positions = [
        crop_x_for_face(segment["face_x"], src_w, crop_w) for segment in segments
    ]

    first_time = max(clip_start, float(segments[0]["start"]))
    append_keyframe(keyframes, clip_start, positions[0])
    if first_time > clip_start:
        append_keyframe(keyframes, first_time, positions[0])

    switches = 0
    previous_x = positions[0]
    previous_scene = segments[0]["scene_id"]

    for segment, next_x in zip(segments[1:], positions[1:]):
        switch_time = max(clip_start, min(clip_end, float(segment["start"])))
        scene_changed = segment["scene_id"] != previous_scene
        transition = 0.18 if scene_changed else 0.80
        transition_start = max(clip_start, switch_time - transition)

        append_keyframe(keyframes, transition_start, previous_x)
        append_keyframe(keyframes, switch_time, next_x)

        if next_x != previous_x:
            switches += 1
        previous_x = next_x
        previous_scene = segment["scene_id"]

    append_keyframe(keyframes, clip_end, previous_x)
    return keyframes, switches


def build_clip_crop(
    face_info: dict,
    src_w: int,
    src_h: int,
    clip: dict,
    scenes: list[dict],
) -> dict:
    clip_start = float(clip.get("start", 0.0))
    clip_end = float(clip.get("end", clip_start))
    duration = max(0.0, clip_end - clip_start)
    frames = face_info.get("frames", [])

    crop_h = src_h
    crop_w = int(round(src_h * 9 / 16))
    if crop_w > src_w:
        crop_w = src_w
        crop_h = int(round(src_w * 16 / 9))

    detected_count = sum(1 for frame in frames if frame.get("detected"))
    fallback_intervals = no_face_intervals(frames, clip_start, clip_end)
    segments = director_segments(frames, scenes, clip_start, clip_end)
    keyframes, switches = build_locked_keyframes(
        segments, src_w, crop_w, clip_start, clip_end
    )

    if not segments:
        fallback_intervals = [{"start": 0.0, "end": round(duration, 3)}]
        strategy = "blur_full_frame"
    else:
        strategy = "director_active_speaker_lock"

    return {
        "strategy": strategy,
        "director_mode": True,
        "crop_w": crop_w,
        "crop_h": crop_h,
        "keyframes": keyframes,
        "fallback_intervals": fallback_intervals,
        "detected_frames": detected_count,
        "total_frames": len(frames),
        "speaker_locks": len(segments),
        "active_speaker_switches": switches,
        "scene_resets": max(
            0,
            sum(
                1
                for previous, current in zip(segments, segments[1:])
                if previous["scene_id"] != current["scene_id"]
            ),
        ),
        "multi_face_ratio": float(face_info.get("multi_face_ratio", 0.0)),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--face-data", required=True)
    parser.add_argument("--clips", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--scenes")
    parser.add_argument("--smooth", type=int, default=5)  # compatibility
    args = parser.parse_args()

    src_w, src_h = probe_resolution(args.source)
    face_payload = json.loads(Path(args.face_data).read_text(encoding="utf-8"))
    clips_payload = json.loads(Path(args.clips).read_text(encoding="utf-8"))
    scenes = load_scenes(args.scenes)

    output = {
        "clips": {},
        "metadata": {
            "src_w": src_w,
            "src_h": src_h,
            "engine": "director-mode-v1",
            "layout": "single-speaker-fullscreen",
            "transition_seconds": 0.8,
            "no_face_fallback": "blurred-full-frame",
            "scene_reset": True,
        },
    }

    for clip in clips_payload.get("clips", []):
        clip_id = str(clip.get("id", "01"))
        face_info = face_payload.get("clips", {}).get(clip_id, {})
        crop_info = build_clip_crop(face_info, src_w, src_h, clip, scenes)
        output["clips"][clip_id] = crop_info
        print(
            f"Clip {clip_id}: {crop_info['strategy']}, "
            f"{crop_info['speaker_locks']} locks, "
            f"{crop_info['active_speaker_switches']} switches, "
            f"{len(crop_info['fallback_intervals'])} blur intervals",
            flush=True,
        )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Director crop written to {out_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"SMART_CROP_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
