#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

APP = Path("app.py")
text = APP.read_text(encoding="utf-8")

if "STAGE43_DIRECTOR_MODE" in text:
    print("Stage 4.3 already applied.")
    raise SystemExit(0)

old_scenes_anchor = '''                "--source",
                str(video),
            ],
            cwd="/app",
            timeout=600,
'''
new_scenes_anchor = '''                "--source",
                str(video),
                "--scenes",
                str(job / "scenes.json"),
            ],
            cwd="/app",
            timeout=600,
'''
if text.count(old_scenes_anchor) != 1:
    raise RuntimeError(
        f"Expected one smart-crop source anchor, found {text.count(old_scenes_anchor)}"
    )
text = text.replace(old_scenes_anchor, new_scenes_anchor, 1)

new_render_block = r'''# STAGE43_DIRECTOR_MODE
def fallback_intervals_of(crop_item: dict, duration: float) -> list[tuple[float, float]]:
    intervals = []
    for item in crop_item.get("fallback_intervals", []) or []:
        if isinstance(item, dict):
            start = float(item.get("start", 0.0))
            end = float(item.get("end", start))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            start = float(item[0])
            end = float(item[1])
        else:
            continue
        start = max(0.0, min(duration, start))
        end = max(start, min(duration, end))
        if end - start >= 0.05:
            intervals.append((start, end))

    merged = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1] + 0.05:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(float(start), float(end)) for start, end in merged]


def blur_full_frame_complex(ass_path: Path | None = None) -> str:
    chain = (
        "[0:v]setpts=PTS-STARTPTS,split=2[bg_in][fg_in];"
        "[bg_in]scale=720:1280:force_original_aspect_ratio=increase,"
        "crop=720:1280,gblur=sigma=24[bg];"
        "[fg_in]scale=720:1280:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[mixed]"
    )
    if ass_path and ass_path.is_file():
        chain += f";[mixed]ass='{filter_path(ass_path)}'[vout]"
    else:
        chain += ";[mixed]null[vout]"
    return chain


def director_filter_complex(
    crop_w: int,
    crop_h: int,
    initial_x: int,
    command_path: Path,
    intervals: list[tuple[float, float]],
    ass_path: Path | None,
) -> str:
    enable_expr = "+".join(
        f"between(t,{start:.3f},{end:.3f})" for start, end in intervals
    )
    chain = (
        "[0:v]setpts=PTS-STARTPTS,split=3[focus_in][bg_in][fg_in];"
        f"[focus_in]sendcmd=f='{filter_path(command_path)}',"
        f"crop@track={crop_w}:{crop_h}:{initial_x}:0,"
        "scale=720:1280[focus];"
        "[bg_in]scale=720:1280:force_original_aspect_ratio=increase,"
        "crop=720:1280,gblur=sigma=24[bg];"
        "[fg_in]scale=720:1280:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[full];"
        f"[focus][full]overlay=0:0:enable='{enable_expr}'[mixed]"
    )
    if ass_path and ass_path.is_file():
        chain += f";[mixed]ass='{filter_path(ass_path)}'[vout]"
    else:
        chain += ";[mixed]null[vout]"
    return chain


def render_all(
    video: Path,
    meta: dict,
    clips: dict,
    crop_path: Path | None,
    captions: Path,
    job: Path,
):
    output_dir = job / "outputs"
    output_dir.mkdir(exist_ok=True)
    crop_data = (
        json.loads(crop_path.read_text(encoding="utf-8"))
        if crop_path and crop_path.is_file()
        else None
    )
    outputs = []
    animated_count = 0
    fallback_count = 0

    default_w, default_h, default_x = crop_dimensions(meta)

    for clip in clips["clips"]:
        safe_title = re.sub(r"[^A-Za-z0-9_.-]+", "_", clip["title"][:30])
        output = output_dir / f"{clip['id']}_{safe_title}.mp4"
        ass_path = captions / f"{clip['id']}.ass"
        crop_item = (
            crop_data.get("clips", {}).get(clip["id"], {}) if crop_data else {}
        )
        crop_w = int(crop_item.get("crop_w") or default_w)
        crop_h = int(crop_item.get("crop_h") or default_h)
        crop_w = min(crop_w, meta["width"])
        crop_h = min(crop_h, meta["height"])

        command_path = job / f"crop_commands_{clip['id']}.txt"
        initial_x = smooth_commands(clip, crop_item, command_path)
        animated = initial_x is not None and command_path.is_file()
        intervals = fallback_intervals_of(crop_item, float(clip["duration"]))

        command = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-ss",
            str(clip["start"]),
            "-i",
            str(video),
            "-t",
            str(clip["duration"]),
        ]

        uses_complex = False
        if animated and intervals:
            uses_complex = True
            filter_value = director_filter_complex(
                crop_w,
                crop_h,
                int(initial_x),
                command_path,
                intervals,
                ass_path,
            )
        elif animated:
            filter_value = (
                "setpts=PTS-STARTPTS,"
                f"sendcmd=f='{filter_path(command_path)}',"
                f"crop@track={crop_w}:{crop_h}:{initial_x}:0,"
                "scale=720:1280"
            )
            if ass_path.is_file():
                filter_value += f",ass='{filter_path(ass_path)}'"
        else:
            uses_complex = True
            filter_value = blur_full_frame_complex(ass_path)

        if uses_complex:
            command.extend(
                [
                    "-filter_complex",
                    filter_value,
                    "-map",
                    "[vout]",
                    "-map",
                    "0:a?",
                ]
            )
        else:
            command.extend(["-vf", filter_value])

        command.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "21",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                str(output),
            ]
        )

        try:
            run(command, timeout=1800)
            if animated:
                animated_count += 1
            else:
                fallback_count += 1
        except Exception as exc:
            (job / f"render_director_error_{clip['id']}.txt").write_text(
                f"{type(exc).__name__}: {exc}", encoding="utf-8"
            )
            fallback_command = [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-ss",
                str(clip["start"]),
                "-i",
                str(video),
                "-t",
                str(clip["duration"]),
                "-filter_complex",
                blur_full_frame_complex(ass_path),
                "-map",
                "[vout]",
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "21",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                str(output),
            ]
            run(fallback_command, timeout=1800)
            fallback_count += 1

        if output.is_file() and output.stat().st_size > 0:
            outputs.append(output)

    if not outputs:
        raise RuntimeError("Semua render gagal.")
    return outputs, animated_count, fallback_count
'''

pattern = re.compile(r"def render_all\([\s\S]*?\n\ndef make_zip", re.MULTILINE)
matches = pattern.findall(text)
if len(matches) != 1:
    raise RuntimeError(f"Expected one render_all block, found {len(matches)}")
text = pattern.sub(new_render_block + "\n\ndef make_zip", text, count=1)

replacements = {
    'else f"{face_note} | Render akan memakai center crop."':
        'else f"{face_note} | Render akan memakai full-frame blur fallback."',
    'yield snap("FFmpeg merender smart crop bergerak 720×1280...")':
        'yield snap("FFmpeg merender Director Mode 720×1280...")',
    'f"{fallback_count} center-crop fallback."':
        'f"{fallback_count} blur fallback penuh."',
    'debug_files.extend(job.glob("render_animated_error_*.txt"))':
        'debug_files.extend(job.glob("render_animated_error_*.txt"))\n'
        '        debug_files.extend(job.glob("render_director_error_*.txt"))',
    'yield snap("🎉 Tahap 4 selesai: campaign match score, requirement results, dan pipeline clipping aktif.")':
        'yield snap("🎬 Stage 4.3 selesai: Director Mode, speaker lock, scene reset, dan blur fallback aktif.")',
}

for old, new in replacements.items():
    if old not in text:
        raise RuntimeError(f"Missing app.py anchor: {old}")
    text = text.replace(old, new, 1)

APP.write_text(text, encoding="utf-8")
print("Stage 4.3 app.py patch applied.")
