#!/usr/bin/env python3
"""CPU-friendly MediaPipe active-speaker tracking for selected clips.

The tracker samples only selected clip ranges. It keeps stable face identities,
measures mouth movement, and uses hysteresis so the virtual camera follows the
current speaker instead of jumping between people.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import defaultdict, deque
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
UPPER_INNER_LIP = 13
LOWER_INNER_LIP = 14
LEFT_MOUTH_CORNER = 61
RIGHT_MOUTH_CORNER = 291


def point_distance(a, b) -> float:
    return math.hypot(float(a.x) - float(b.x), float(a.y) - float(b.y))


def describe_faces(face_sets) -> list[dict]:
    """Convert MediaPipe landmarks into compact face and mouth metrics."""
    faces = []
    for landmarks in face_sets:
        if len(landmarks) <= RIGHT_MOUTH_CORNER:
            continue
        xs = np.array([float(p.x) for p in landmarks], dtype=np.float32)
        ys = np.array([float(p.y) for p in landmarks], dtype=np.float32)
        x0, x1 = float(xs.min()), float(xs.max())
        y0, y1 = float(ys.min()), float(ys.max())
        width = max(1e-5, x1 - x0)
        height = max(1e-5, y1 - y0)
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0
        area = width * height

        lip_gap = point_distance(
            landmarks[UPPER_INNER_LIP], landmarks[LOWER_INNER_LIP]
        )
        mouth_width = point_distance(
            landmarks[LEFT_MOUTH_CORNER], landmarks[RIGHT_MOUTH_CORNER]
        )
        mouth_open = float(np.clip(lip_gap / max(mouth_width, 1e-4), 0.0, 1.5))

        faces.append(
            {
                "cx": cx,
                "cy": cy,
                "width": width,
                "height": height,
                "area": area,
                "mouth_open": mouth_open,
            }
        )
    return faces


def assign_tracks(
    faces: list[dict],
    tracks: dict[int, dict],
    next_track_id: int,
    frame_index: int,
) -> tuple[list[dict], int]:
    """Assign stable face IDs using nearest position and area."""
    assigned_tracks: set[int] = set()
    ordered_faces = sorted(faces, key=lambda item: item["area"], reverse=True)

    for face in ordered_faces:
        best_id = None
        best_cost = float("inf")
        for track_id, track in tracks.items():
            if track_id in assigned_tracks:
                continue
            if frame_index - int(track.get("last_frame", -999)) > 8:
                continue
            distance = math.hypot(
                face["cx"] - float(track["cx"]),
                face["cy"] - float(track["cy"]),
            )
            if distance > 0.28:
                continue
            area_delta = abs(face["area"] - float(track.get("area", face["area"])))
            cost = distance + area_delta * 0.15
            if cost < best_cost:
                best_cost = cost
                best_id = track_id

        if best_id is None:
            best_id = next_track_id
            next_track_id += 1

        face["track_id"] = best_id
        assigned_tracks.add(best_id)
        tracks[best_id] = {
            "cx": face["cx"],
            "cy": face["cy"],
            "area": face["area"],
            "last_frame": frame_index,
        }

    stale_ids = [
        track_id
        for track_id, track in tracks.items()
        if frame_index - int(track.get("last_frame", -999)) > 24
    ]
    for track_id in stale_ids:
        tracks.pop(track_id, None)

    return ordered_faces, next_track_id


def choose_active_speaker(
    faces: list[dict],
    tracks: dict[int, dict],
    activity_history: dict[int, deque],
    previous_mouth: dict[int, float],
    active_track_id: int | None,
    challenger_track_id: int | None,
    challenger_frames: int,
    frames_since_switch: int,
    fps: float,
) -> tuple[int | None, int | None, int, int, dict[int, float]]:
    """Choose the current speaker using mouth movement and hysteresis."""
    visible_ids = {int(face["track_id"]) for face in faces}
    scores: dict[int, float] = {}

    for face in faces:
        track_id = int(face["track_id"])
        mouth_open = float(face["mouth_open"])
        previous = previous_mouth.get(track_id, mouth_open)
        delta = abs(mouth_open - previous)
        previous_mouth[track_id] = mouth_open

        raw_activity = delta * 2.8 + mouth_open * 0.22
        activity_history[track_id].append(raw_activity)
        scores[track_id] = float(np.mean(activity_history[track_id]))

    if not faces:
        return active_track_id, None, 0, frames_since_switch + 1, scores

    if len(faces) == 1:
        only_id = int(faces[0]["track_id"])
        if active_track_id != only_id:
            active_track_id = only_id
            frames_since_switch = 0
        return active_track_id, None, 0, frames_since_switch + 1, scores

    best_id = max(
        visible_ids,
        key=lambda track_id: (
            scores.get(track_id, 0.0),
            float(tracks.get(track_id, {}).get("area", 0.0)),
        ),
    )

    if active_track_id not in visible_ids:
        return best_id, None, 0, 1, scores

    if best_id == active_track_id:
        return active_track_id, None, 0, frames_since_switch + 1, scores

    active_score = scores.get(active_track_id, 0.0)
    best_score = scores.get(best_id, 0.0)
    min_hold_frames = max(3, int(round(fps * 1.5)))
    required_challenge_frames = max(2, int(round(fps * 0.7)))

    is_clear_challenger = best_score > active_score * 1.18 + 0.006
    if frames_since_switch >= min_hold_frames and is_clear_challenger:
        if challenger_track_id == best_id:
            challenger_frames += 1
        else:
            challenger_track_id = best_id
            challenger_frames = 1

        if challenger_frames >= required_challenge_frames:
            active_track_id = best_id
            challenger_track_id = None
            challenger_frames = 0
            frames_since_switch = 0
    else:
        challenger_track_id = None
        challenger_frames = 0

    return (
        active_track_id,
        challenger_track_id,
        challenger_frames,
        frames_since_switch + 1,
        scores,
    )


def track_clip(cap, landmarker, clip, fps: float):
    start = float(clip["start"])
    end = float(clip["end"])
    step = 1.0 / max(0.5, fps)
    t = start
    rows = []
    frame_index = 0

    tracks: dict[int, dict] = {}
    next_track_id = 1
    previous_mouth: dict[int, float] = {}
    activity_history: dict[int, deque] = defaultdict(lambda: deque(maxlen=5))
    active_track_id: int | None = None
    challenger_track_id: int | None = None
    challenger_frames = 0
    frames_since_switch = 999
    last_active_face_x = 0.5

    while t <= end + 1e-6:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            rows.append(
                {
                    "time": round(t, 3),
                    "detected": False,
                    "face_x": last_active_face_x,
                    "face_y": 0.38,
                    "face_width": 0.0,
                    "face_height": 0.0,
                    "num_faces": 0,
                    "active_track_id": active_track_id,
                    "active_score": 0.0,
                    "confidence": 0.0,
                    "faces": [],
                }
            )
            t += step
            frame_index += 1
            continue

        h, w = frame.shape[:2]
        if w > 640:
            new_h = max(2, int(h * 640 / w))
            frame = cv2.resize(frame, (640, new_h), interpolation=cv2.INTER_AREA)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = landmarker.detect(mp_image)
        faces = describe_faces(result.face_landmarks or [])
        faces, next_track_id = assign_tracks(
            faces, tracks, next_track_id, frame_index
        )

        (
            active_track_id,
            challenger_track_id,
            challenger_frames,
            frames_since_switch,
            scores,
        ) = choose_active_speaker(
            faces,
            tracks,
            activity_history,
            previous_mouth,
            active_track_id,
            challenger_track_id,
            challenger_frames,
            frames_since_switch,
            fps,
        )

        active_face = next(
            (
                face
                for face in faces
                if int(face["track_id"]) == active_track_id
            ),
            None,
        )

        if active_face is None:
            rows.append(
                {
                    "time": round(t, 3),
                    "detected": False,
                    "face_x": last_active_face_x,
                    "face_y": 0.38,
                    "face_width": 0.0,
                    "face_height": 0.0,
                    "num_faces": len(faces),
                    "active_track_id": active_track_id,
                    "active_score": round(scores.get(active_track_id, 0.0), 6),
                    "confidence": 0.0,
                    "faces": [],
                }
            )
        else:
            last_active_face_x = float(np.clip(active_face["cx"], 0.0, 1.0))
            debug_faces = [
                {
                    "track_id": int(face["track_id"]),
                    "face_x": round(float(face["cx"]), 5),
                    "face_y": round(float(face["cy"]), 5),
                    "face_width": round(float(face["width"]), 5),
                    "face_height": round(float(face["height"]), 5),
                    "mouth_open": round(float(face["mouth_open"]), 6),
                    "activity": round(scores.get(int(face["track_id"]), 0.0), 6),
                }
                for face in sorted(faces, key=lambda item: item["cx"])
            ]
            rows.append(
                {
                    "time": round(t, 3),
                    "detected": True,
                    "face_x": round(last_active_face_x, 5),
                    "face_y": round(float(np.clip(active_face["cy"], 0.0, 1.0)), 5),
                    "face_width": round(float(np.clip(active_face["width"], 0.0, 1.0)), 5),
                    "face_height": round(float(np.clip(active_face["height"], 0.0, 1.0)), 5),
                    "num_faces": len(faces),
                    "active_track_id": active_track_id,
                    "active_score": round(scores.get(active_track_id, 0.0), 6),
                    "confidence": 1.0,
                    "faces": debug_faces,
                }
            )

        t += step
        frame_index += 1

    detected = [row for row in rows if row["detected"]]
    multi_ratio = (
        sum(1 for row in detected if row.get("num_faces", 0) >= 2) / len(detected)
        if detected
        else 0.0
    )
    median_x = (
        float(np.median([row["face_x"] for row in detected])) if detected else 0.5
    )

    if median_x < 0.38:
        dominant_side = "left"
    elif median_x > 0.62:
        dominant_side = "right"
    else:
        dominant_side = "center"

    switches = 0
    previous_id = None
    for row in detected:
        current_id = row.get("active_track_id")
        if previous_id is not None and current_id != previous_id:
            switches += 1
        previous_id = current_id

    return {
        "frames": rows,
        "detected_frames": len(detected),
        "total_frames": len(rows),
        "multi_face_ratio": round(multi_ratio, 4),
        "active_speaker_switches": switches,
        "dominant_side": dominant_side,
        "strategy": "active_speaker",
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
            "engine": "MediaPipe Active Speaker Tracker v1",
            "layout": "single-speaker-fullscreen",
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
                    f"{result['total_frames']} frames, "
                    f"{result['active_speaker_switches']} speaker switches",
                    flush=True,
                )
    finally:
        cap.release()

    output["metadata"]["processing_time_sec"] = round(time.time() - started, 2)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Active-speaker tracking written to {out_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FACE_TRACK_ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
