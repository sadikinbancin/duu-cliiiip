from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import cv2
import gdown
import gradio as gr
import numpy as np
import pytesseract
import requests
from scenedetect import SceneManager, open_video
from scenedetect.detectors import ContentDetector


STAGES = [
    "Input video",
    "FFmpeg/ffprobe",
    "Whisper",
    "PySceneDetect",
    "Audio dynamics",
    "OCR",
    "Gemini Vision scoring",
    "Groq Llama viral scoring",
    "MediaPipe",
    "Smart crop",
    "Subtitle",
    "Render",
    "Paket hasil",
]
ICON = {
    "pending": "⚪",
    "running": "🔵",
    "done": "✅",
    "warning": "🟡",
    "error": "❌",
}
ROOT = Path(tempfile.gettempdir()) / "clipping-lite-jobs"
MAX_BATCH_LINKS = max(1, int(os.getenv("MAX_BATCH_LINKS", "20")))


def env_config() -> dict:
    return {
        "groq_key_present": bool(os.getenv("GROQ_API_KEY", "").strip()),
        "groq_whisper_model": os.getenv(
            "GROQ_WHISPER_MODEL", "whisper-large-v3-turbo"
        ).strip(),
        "groq_llm_model": os.getenv(
            "GROQ_LLM_MODEL", "llama-3.3-70b-versatile"
        ).strip(),
        "google_key_present": bool(os.getenv("GOOGLE_API_KEY", "").strip()),
        "gemini_vision_model": os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash").strip(),
        "mediapipe_model": os.getenv(
            "MEDIAPIPE_MODEL_PATH", "/app/models/face_landmarker.task"
        ).strip(),
    }


def config_md() -> str:
    cfg = env_config()
    return (
        "### 🔐 Konfigurasi runtime\n"
        f"- Groq API: {'✅ aktif' if cfg['groq_key_present'] else '🟡 belum dipasang'}\n"
        f"- Whisper: `{cfg['groq_whisper_model']}`\n"
        f"- Viral scoring: `{cfg['groq_llm_model']}`\n"
        f"- Google API: {'✅ aktif untuk Gemini Vision' if cfg['google_key_present'] else '⚪ belum dipasang'}\n"
        f"- Gemini Vision: `{cfg['gemini_vision_model']}`\n"
        "- MediaPipe: lokal di CPU, tidak memakai API key"
    )


def status_md(states: dict, note: str = "") -> str:
    lines = ["## 🚦 Roadmap proses"]
    for i, stage in enumerate(STAGES, 1):
        lines.append(f"{ICON[states.get(stage, 'pending')]} **{i}. {stage}**")
    if note:
        lines.extend(["", f"**Log terakhir:** {note}"])
    return "\n".join(lines)


def run(cmd, timeout=1800, binary=False, cwd=None):
    process = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=not binary,
        timeout=timeout,
        check=False,
    )
    if process.returncode:
        if binary:
            error = process.stderr.decode("utf-8", "replace")
        else:
            error = process.stderr
        raise RuntimeError((error or "Command gagal")[-4000:])
    return process.stdout


def path_of(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("path", "video", "name"):
            if isinstance(value.get(key), str):
                return value[key]
    path = getattr(value, "path", None)
    return path if isinstance(path, str) else None


def cleanup_old_jobs(hours=6):
    ROOT.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - hours * 3600
    for path in ROOT.iterdir():
        try:
            if path.is_dir() and path.stat().st_mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


def prepare_source(upload, drive_url, job: Path) -> Path:
    destination = job / "source.mp4"
    upload_path = path_of(upload)
    if upload_path:
        shutil.copy2(upload_path, destination)
        return destination

    drive_url = (drive_url or "").strip()
    parsed = urlparse(drive_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname != "drive.google.com":
        raise ValueError("Upload video atau masukkan link Google Drive publik.")

    saved = gdown.download(url=drive_url, output=str(destination), quiet=False)
    destination = Path(saved or destination)
    if not destination.is_file() or destination.stat().st_size <= 0:
        raise RuntimeError(
            "Download Drive gagal. Set akses file: Anyone with the link → Viewer."
        )
    return destination


def probe_video(video: Path) -> dict:
    data = json.loads(
        run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(video),
            ],
            timeout=120,
        )
    )
    streams = data.get("streams", [])
    video_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "video"),
        None,
    )
    audio_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "audio"),
        None,
    )
    if video_stream is None:
        raise RuntimeError("Stream video tidak ditemukan.")

    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or video_stream.get("duration") or 0)
    if duration <= 0:
        raise RuntimeError("Durasi video tidak terbaca.")

    return {
        "duration": duration,
        "width": int(video_stream.get("width") or 0),
        "height": int(video_stream.get("height") or 0),
        "video_codec": video_stream.get("codec_name", "unknown"),
        "audio_codec": audio_stream.get("codec_name", "unknown") if audio_stream else None,
        "has_audio": bool(audio_stream),
        "size_mb": video.stat().st_size / 1024 / 1024,
    }



def normalize_source(video: Path, meta: dict, job: Path):
    """Convert fragile codecs such as AV1 to stable H.264 before seeking/cropping.

    Random seeking into AV1 can begin between sequence headers and produce green,
    gray, or blocky frames. Normalizing once from the beginning avoids that and
    gives OpenCV/MediaPipe a seek-friendly H.264 source.
    """
    codec = str(meta.get("video_codec") or "").lower()
    force = os.getenv("FORCE_NORMALIZE_VIDEO", "").strip().lower() in {
        "1", "true", "yes", "on"
    }
    needs_normalize = force or codec not in {"h264", "avc1"}

    if not needs_normalize:
        return video, meta, False, f"Codec {codec or 'unknown'} sudah aman; normalisasi dilewati."

    output = job / "source_normalized_h264.mp4"
    log_path = job / "normalization.log"
    attempts = []

    decoder_options = [["-c:v", "libdav1d"], []] if codec == "av1" else [[]]

    for decoder in decoder_options:
        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-fflags",
            "+genpts+discardcorrupt",
            "-err_detect",
            "ignore_err",
            *decoder,
            "-i",
            str(video),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-force_key_frames",
            "expr:gte(t,n_forced*2)",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            "-max_muxing_queue_size",
            "2048",
            str(output),
        ]

        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
        decoder_name = "libdav1d" if decoder else "FFmpeg default decoder"
        attempts.append(
            f"=== {decoder_name} | exit={process.returncode} ===\n"
            f"{process.stderr[-12000:]}\n"
        )

        if process.returncode == 0 and output.is_file() and output.stat().st_size > 0:
            log_path.write_text("\n".join(attempts), encoding="utf-8")
            normalized_meta = probe_video(output)
            return (
                output,
                normalized_meta,
                True,
                f"{codec.upper() or 'VIDEO'} dinormalisasi ke H.264/yuv420p.",
            )

        output.unlink(missing_ok=True)

    log_path.write_text("\n".join(attempts), encoding="utf-8")
    raise RuntimeError(
        f"Normalisasi codec {codec or 'unknown'} gagal. Lihat normalization.log."
    )


def extract_audio(video: Path, job: Path) -> Path:
    output = job / "audio.mp3"
    run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(video),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "48k",
            str(output),
        ],
        timeout=900,
    )
    if not output.is_file() or output.stat().st_size <= 0:
        raise RuntimeError("Audio tidak berhasil diekstrak.")
    return output


def normalize_transcript(data: dict, duration: float) -> dict:
    segments = []
    words = []

    for segment in data.get("segments") or []:
        if hasattr(segment, "model_dump"):
            segment = segment.model_dump()
        elif not isinstance(segment, dict):
            segment = vars(segment)

        start = float(segment.get("start") or 0)
        end = float(segment.get("end") or start)
        text = str(segment.get("text") or "").strip()
        segment_words = []

        for word in segment.get("words") or []:
            if hasattr(word, "model_dump"):
                word = word.model_dump()
            elif not isinstance(word, dict):
                word = vars(word)
            item = {
                "word": str(word.get("word") or "").strip(),
                "start": float(word.get("start") or start),
                "end": float(word.get("end") or end),
            }
            if item["word"]:
                segment_words.append(item)
                words.append(item)

        if text:
            segments.append(
                {
                    "start": start,
                    "end": end,
                    "text": text,
                    "words": segment_words,
                }
            )

    full_text = str(data.get("text") or "").strip()
    if not segments and full_text:
        segments = [
            {"start": 0.0, "end": duration, "text": full_text, "words": []}
        ]

    return {
        "language": data.get("language") or "unknown",
        "duration": float(data.get("duration") or duration),
        "text": full_text or " ".join(item["text"] for item in segments),
        "segments": segments,
        "words": words,
    }


def transcribe_groq(audio: Path, duration: float) -> tuple[dict, str]:
    cfg = env_config()
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY belum dipasang.")

    from groq import Groq

    client = Groq(api_key=key, timeout=240, max_retries=2)
    model = cfg["groq_whisper_model"]
    with audio.open("rb") as file_handle:
        try:
            response = client.audio.transcriptions.create(
                file=file_handle,
                model=model,
                response_format="verbose_json",
                temperature=0.0,
                timestamp_granularities=["segment", "word"],
            )
        except Exception:
            file_handle.seek(0)
            response = client.audio.transcriptions.create(
                file=file_handle,
                model=model,
                response_format="verbose_json",
                temperature=0.0,
            )

    data = (
        response.to_dict()
        if hasattr(response, "to_dict")
        else response.model_dump()
        if hasattr(response, "model_dump")
        else vars(response)
    )
    return normalize_transcript(data, duration), model


def transcribe_local(audio: Path, duration: float, model_name: str) -> dict:
    from faster_whisper import WhisperModel

    model = WhisperModel(
        model_name,
        device="cpu",
        compute_type="int8",
        cpu_threads=max(1, min(2, os.cpu_count() or 1)),
        num_workers=1,
    )
    segment_iterator, info = model.transcribe(
        str(audio),
        beam_size=1,
        vad_filter=True,
        word_timestamps=True,
    )

    segments = []
    words = []
    for segment in segment_iterator:
        segment_words = []
        for word in segment.words or []:
            item = {
                "word": word.word.strip(),
                "start": float(word.start),
                "end": float(word.end),
            }
            segment_words.append(item)
            words.append(item)
        segments.append(
            {
                "start": float(segment.start),
                "end": float(segment.end),
                "text": segment.text.strip(),
                "words": segment_words,
            }
        )

    return {
        "language": info.language,
        "duration": float(getattr(info, "duration", duration) or duration),
        "text": " ".join(item["text"] for item in segments),
        "segments": segments,
        "words": words,
    }


def transcribe(audio: Path, duration: float, mode: str):
    if mode.startswith("Groq"):
        try:
            transcript, model = transcribe_groq(audio, duration)
            return transcript, f"Groq Whisper ({model})", True
        except Exception as exc:
            transcript = transcribe_local(audio, duration, "tiny")
            return transcript, f"Groq gagal; fallback local tiny ({exc})", False

    model_name = "base" if "base" in mode.lower() else "tiny"
    return (
        transcribe_local(audio, duration, model_name),
        f"Local Whisper {model_name}",
        False,
    )


def scenes_of(video: Path, duration: float) -> list[dict]:
    manager = SceneManager()
    manager.add_detector(ContentDetector(threshold=27.0))
    manager.detect_scenes(video=open_video(str(video)), show_progress=False)
    scenes = [
        {"start": start.get_seconds(), "end": end.get_seconds()}
        for start, end in manager.get_scene_list()
    ]
    return scenes or [{"start": 0.0, "end": duration}]


def audio_energy(audio: Path) -> list[dict]:
    raw = run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(audio),
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            "8000",
            "pipe:1",
        ],
        timeout=900,
        binary=True,
    )
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    rate = 8000
    output = []
    for start_index in range(0, len(samples), rate):
        chunk = samples[start_index : start_index + rate]
        if chunk.size:
            output.append(
                {
                    "start": start_index / rate,
                    "end": min((start_index + rate) / rate, len(samples) / rate),
                    "rms": float(np.sqrt(np.mean(chunk * chunk) + 1e-12)),
                }
            )
    return output


def do_ocr(video: Path, scenes: list[dict], enabled: bool) -> list[dict]:
    if not enabled:
        return []
    times = sorted({round(scene["start"], 2) for scene in scenes[:20]})
    capture = cv2.VideoCapture(str(video))
    output = []
    try:
        for timestamp in times:
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, frame = capture.read()
            if not ok:
                continue
            height, width = frame.shape[:2]
            if width > 960:
                frame = cv2.resize(
                    frame,
                    (960, int(height * 960 / width)),
                    interpolation=cv2.INTER_AREA,
                )
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.threshold(
                gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )[1]
            text = re.sub(
                r"\s+",
                " ",
                pytesseract.image_to_string(gray, config="--psm 6"),
            ).strip()
            if len(text) >= 4:
                output.append({"time": timestamp, "text": text[:300]})
    finally:
        capture.release()
    return output


def text_window(transcript: dict, start: float, end: float) -> str:
    return " ".join(
        segment["text"]
        for segment in transcript["segments"]
        if segment["end"] > start and segment["start"] < end
    ).strip()


def mean_energy(items: list[dict], start: float, end: float) -> float:
    values = [
        item["rms"]
        for item in items
        if item["end"] > start and item["start"] < end
    ]
    return sum(values) / len(values) if values else 0.0


def candidates_of(
    transcript: dict,
    scenes: list[dict],
    energy: list[dict],
    ocr: list[dict],
    duration: float,
    target: int,
) -> list[dict]:
    window = float(target)
    step = max(10.0, window / 2)
    output = []
    start = 0.0
    index = 1

    while start < duration:
        end = min(duration, start + window)
        if end - start < min(12.0, window * 0.6):
            break
        text = text_window(transcript, start, end)
        word_count = len(text.split())
        if word_count >= 5:
            scene_changes = sum(
                1 for scene in scenes if start < scene["start"] < end
            )
            energy_value = mean_energy(energy, start, end)
            ocr_text = [
                item["text"]
                for item in ocr
                if start <= item["time"] <= end
            ][:3]
            preliminary = (
                word_count / max(1.0, end - start) * 0.45
                + math.log1p(scene_changes) * 0.30
                + energy_value * 2.5
            )
            output.append(
                {
                    "candidate_id": f"C{index:03d}",
                    "start": round(start, 2),
                    "end": round(end, 2),
                    "duration": round(end - start, 2),
                    "text": text[:1200],
                    "scene_changes": scene_changes,
                    "audio_energy": round(energy_value, 5),
                    "ocr": ocr_text,
                    "preliminary_score": round(preliminary, 4),
                }
            )
            index += 1
        start += step

    if not output:
        fallback_end = min(duration, window)
        output.append(
            {
                "candidate_id": "C001",
                "start": 0.0,
                "end": round(fallback_end, 2),
                "duration": round(fallback_end, 2),
                "text": transcript.get("text", "")[:1200],
                "scene_changes": 0,
                "audio_energy": mean_energy(energy, 0.0, fallback_end),
                "ocr": [],
                "preliminary_score": 0.0,
            }
        )

    return sorted(
        output,
        key=lambda item: item["preliminary_score"],
        reverse=True,
    )[:24]


def non_overlap(items: list[dict], count: int) -> list[dict]:
    selected = []
    for item in items:
        if not any(
            item["start"] < existing["end"]
            and item["end"] > existing["start"]
            for existing in selected
        ):
            selected.append(item)
        if len(selected) >= count:
            break
    return selected


def parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def make_candidate_sheet(video: Path, candidate: dict, output: Path) -> Path:
    """Create a small 3-frame contact sheet for Gemini Vision."""
    start = float(candidate["start"])
    end = float(candidate["end"])
    duration = max(0.1, end - start)
    times = [
        start + duration * 0.18,
        start + duration * 0.50,
        start + duration * 0.82,
    ]

    cap = cv2.VideoCapture(str(video))
    frames = []
    try:
        for index, t in enumerate(times, 1):
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            h, w = frame.shape[:2]
            target_w = 360
            target_h = max(1, int(h * target_w / max(1, w)))
            frame = cv2.resize(frame, (target_w, target_h))
            cv2.putText(
                frame,
                f"{candidate['candidate_id']} frame {index}",
                (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.75,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            frames.append(frame)
    finally:
        cap.release()

    if not frames:
        raise RuntimeError(f"Tidak bisa mengambil frame untuk {candidate['candidate_id']}.")

    max_h = max(frame.shape[0] for frame in frames)
    padded = []
    for frame in frames:
        h, w = frame.shape[:2]
        if h < max_h:
            pad = np.zeros((max_h - h, w, 3), dtype=np.uint8)
            frame = np.vstack([frame, pad])
        padded.append(frame)
    sheet = np.hstack(padded)
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), sheet, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
    return output


def gemini_vision_score(video: Path, candidates: list[dict], job: Path):
    """Use Google Gemini Vision to score visual hook/clarity for candidates."""
    cfg = env_config()
    key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not key:
        return candidates, "Gemini Vision dilewati: GOOGLE_API_KEY belum dipasang.", False

    # Keep it cheap and fast: analyze only the top candidates from heuristic pre-score.
    selected = candidates[: min(10, len(candidates))]
    if not selected:
        return candidates, "Gemini Vision dilewati: tidak ada kandidat.", False

    image_dir = job / "gemini_vision_frames"
    parts = [
        {
            "text": (
                "Anda adalah editor short-form video. Nilai kualitas visual setiap kandidat "
                "berdasarkan hook visual, wajah/ekspresi, gerakan, framing, kejernihan, "
                "dan apakah cocok jadi short viral. Balas JSON murni saja dengan format: "
                "{\"items\":[{\"candidate_id\":\"C001\",\"visual_score\":80,"
                "\"hook_visual\":\"...\",\"visual_summary\":\"...\","
                "\"risk\":\"...\"}]}"
            )
        }
    ]
    request_meta = {"model": cfg["gemini_vision_model"], "items": []}

    import base64

    for item in selected:
        sheet_path = make_candidate_sheet(video, item, image_dir / f"{item['candidate_id']}.jpg")
        image_b64 = base64.b64encode(sheet_path.read_bytes()).decode("utf-8")
        request_meta["items"].append(
            {
                "candidate_id": item["candidate_id"],
                "start": item["start"],
                "end": item["end"],
                "image": str(sheet_path),
                "text_preview": item.get("text", "")[:300],
            }
        )
        parts.append({"text": f"Kandidat {item['candidate_id']} | {item['start']}s-{item['end']}s | teks: {item.get('text','')[:500]}"})
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": image_b64}})

    (job / "gemini_vision_request.json").write_text(
        json.dumps(request_meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{cfg['gemini_vision_model']}:generateContent"
    )
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.2,
            "response_mime_type": "application/json",
        },
    }

    try:
        response = requests.post(
            endpoint,
            params={"key": key},
            json=payload,
            timeout=180,
        )
        response.raise_for_status()
        data = response.json()
        raw_text = ""
        for part in data.get("candidates", [{}])[0].get("content", {}).get("parts", []):
            raw_text += part.get("text", "")
        (job / "gemini_vision_response.txt").write_text(raw_text, encoding="utf-8")
        parsed = parse_json(raw_text)
        items = parsed.get("items", [])
    except Exception as exc:
        (job / "gemini_vision_error.txt").write_text(
            f"{type(exc).__name__}: {exc}", encoding="utf-8"
        )
        return candidates, f"Gemini Vision gagal, lanjut tanpa visual score: {type(exc).__name__}: {exc}", False

    visual_map = {}
    for item in items:
        cid = str(item.get("candidate_id") or "")
        if not cid:
            continue
        try:
            score = int(float(item.get("visual_score", 60)))
        except (TypeError, ValueError):
            score = 60
        visual_map[cid] = {
            "visual_score": int(clamp(score, 0, 100)),
            "hook_visual": str(item.get("hook_visual") or "")[:250],
            "visual_summary": str(item.get("visual_summary") or "")[:400],
            "visual_risk": str(item.get("risk") or "")[:250],
        }

    enriched = []
    for item in candidates:
        new_item = dict(item)
        visual = visual_map.get(item["candidate_id"])
        if visual:
            new_item.update(visual)
            # Blend visual score into pre-ranking so Llama sees better candidates higher.
            new_item["preliminary_score"] = round(
                float(new_item.get("preliminary_score", 0))
                + visual["visual_score"] / 100.0,
                4,
            )
        else:
            new_item.setdefault("visual_score", 0)
            new_item.setdefault("hook_visual", "")
            new_item.setdefault("visual_summary", "")
            new_item.setdefault("visual_risk", "")
        enriched.append(new_item)

    enriched.sort(key=lambda item: item.get("preliminary_score", 0), reverse=True)
    (job / "gemini_vision.json").write_text(
        json.dumps({"items": enriched}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return enriched, f"Gemini Vision aktif: {len(visual_map)}/{len(selected)} kandidat dianalisis.", True


def groq_rank(candidates: list[dict], count: int, job: Path):
    cfg = env_config()
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        return non_overlap(candidates, count), "heuristic tanpa GROQ_API_KEY", False

    from groq import Groq

    compact = [
        {
            "candidate_id": item["candidate_id"],
            "start": item["start"],
            "end": item["end"],
            "text": item["text"],
            "scene_changes": item["scene_changes"],
            "audio_energy": item["audio_energy"],
            "ocr": item["ocr"],
            "visual_score": item.get("visual_score", 0),
            "hook_visual": item.get("hook_visual", ""),
            "visual_summary": item.get("visual_summary", ""),
            "visual_risk": item.get("visual_risk", ""),
        }
        for item in candidates
    ]

    prompt = f"""
Anda adalah editor video short-form profesional.
Pilih tepat {count} kandidat terbaik untuk dijadikan clip viral.

Nilai setiap kandidat dari:
1. Hook 3 detik pertama.
2. Kejelasan konteks tanpa perlu menonton bagian sebelumnya.
3. Emotional arc, kejutan, humor, konflik, atau insight.
4. Payoff/penutup yang memuaskan.
5. Kepadatan informasi dan ritme bicara.
6. Scene change, energi audio, dan OCR sebagai sinyal pendukung.
7. Gemini Vision visual_score, hook_visual, visual_summary, dan visual_risk sebagai sinyal visual.

Hindari kandidat yang tumpang tindih. Balas JSON murni dengan format:
{{"clips":[{{"candidate_id":"C001","score":90,"title":"judul singkat","reason":"alasan pemilihan"}}]}}

Kandidat:
{json.dumps(compact, ensure_ascii=False)}
""".strip()

    (job / "groq_scoring_request.json").write_text(
        json.dumps({"model": cfg["groq_llm_model"], "candidates": compact}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    client = Groq(api_key=key, timeout=180, max_retries=2)
    kwargs = {
        "model": cfg["groq_llm_model"],
        "temperature": 0.15,
        "messages": [
            {"role": "system", "content": "Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        response = client.chat.completions.create(
            **kwargs,
            response_format={"type": "json_object"},
        )
    except Exception:
        response = client.chat.completions.create(**kwargs)

    raw_text = response.choices[0].message.content or ""
    (job / "groq_scoring_response.txt").write_text(raw_text, encoding="utf-8")
    data = parse_json(raw_text)
    candidate_map = {item["candidate_id"]: item for item in candidates}
    ranked = []

    for result in data.get("clips", []):
        candidate = candidate_map.get(str(result.get("candidate_id")))
        if candidate is None:
            continue
        candidate = dict(candidate)
        candidate["score"] = max(
            0, min(100, int(float(result.get("score", 70))))
        )
        candidate["title"] = str(result.get("title") or "Highlight")[:80]
        candidate["reason"] = str(result.get("reason") or "")[:300]
        ranked.append(candidate)

    ranked = non_overlap(ranked, count)
    if len(ranked) < count:
        used_ids = {item["candidate_id"] for item in ranked}
        extras = [
            item for item in candidates if item["candidate_id"] not in used_ids
        ]
        ranked.extend(non_overlap(extras, count - len(ranked)))

    return ranked[:count], f"Groq Llama ({cfg['groq_llm_model']})", True


def write_clips(selected: list[dict], job: Path):
    clips = []
    for index, item in enumerate(selected, 1):
        clips.append(
            {
                "id": f"{index:02d}",
                "start": float(item["start"]),
                "end": float(item["end"]),
                "duration": float(item["end"] - item["start"]),
                "title": item.get("title") or f"Highlight {index}",
                "score": int(item.get("score", 70)),
                "reason": item.get("reason") or "Heuristic selection",
                "visual_score": int(item.get("visual_score", 0) or 0),
                "hook_visual": item.get("hook_visual", ""),
                "visual_summary": item.get("visual_summary", ""),
                "visual_risk": item.get("visual_risk", ""),
            }
        )
    payload = {"clips": clips}
    path = job / "clips.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path, payload


def mediapipe_crop(video: Path, clips_path: Path, job: Path):
    face_path = job / "face_data.json"
    crop_path = job / "crop_data.json"
    model_path = Path(env_config()["mediapipe_model"])
    mediapipe_ok = False
    smart_crop_ok = False
    notes = []

    try:
        if not model_path.is_file() or model_path.stat().st_size < 100_000:
            raise RuntimeError(f"Model MediaPipe tidak ditemukan: {model_path}")

        stdout = run(
            [
                sys.executable,
                "scripts/face_track.py",
                "--source",
                str(video),
                "--clips",
                str(clips_path),
                "--output",
                str(face_path),
                "--fps",
                "3",
                "--model",
                str(model_path),
            ],
            cwd="/app",
            timeout=1800,
        )
        (job / "mediapipe_stdout.txt").write_text(
            stdout or "MediaPipe selesai tanpa stdout.", encoding="utf-8"
        )
        if not face_path.is_file():
            raise RuntimeError("face_data.json tidak dibuat.")

        face_data = json.loads(face_path.read_text(encoding="utf-8"))
        total = sum(
            int(item.get("total_frames", len(item.get("frames", []))))
            for item in face_data.get("clips", {}).values()
        )
        detected = sum(
            int(
                item.get(
                    "detected_frames",
                    sum(1 for frame in item.get("frames", []) if frame.get("detected")),
                )
            )
            for item in face_data.get("clips", {}).values()
        )
        mediapipe_ok = detected > 0
        if mediapipe_ok:
            notes.append(f"MediaPipe mendeteksi wajah pada {detected}/{total} frame sampel.")
        else:
            notes.append(f"MediaPipe berjalan, tetapi tidak menemukan wajah pada {total} frame sampel.")
    except Exception as exc:
        (job / "mediapipe_error.txt").write_text(
            f"{type(exc).__name__}: {exc}", encoding="utf-8"
        )
        notes.append(f"MediaPipe gagal: {type(exc).__name__}: {exc}")
        return None, False, False, " | ".join(notes)

    try:
        stdout = run(
            [
                sys.executable,
                "scripts/smart_crop.py",
                "--face-data",
                str(face_path),
                "--clips",
                str(clips_path),
                "--output",
                str(crop_path),
                "--source",
                str(video),
            ],
            cwd="/app",
            timeout=600,
        )
        (job / "smart_crop_stdout.txt").write_text(
            stdout or "Smart crop selesai tanpa stdout.", encoding="utf-8"
        )
        if not crop_path.is_file():
            raise RuntimeError("crop_data.json tidak dibuat.")
        crop_data = json.loads(crop_path.read_text(encoding="utf-8"))
        keyframes = sum(
            len(item.get("keyframes", []))
            for item in crop_data.get("clips", {}).values()
        )
        smart_crop_ok = bool(crop_data.get("clips"))
        notes.append(f"Smart crop menghasilkan {keyframes} keyframe tracking.")
    except Exception as exc:
        (job / "smart_crop_error.txt").write_text(
            f"{type(exc).__name__}: {exc}", encoding="utf-8"
        )
        notes.append(f"Smart crop gagal: {type(exc).__name__}: {exc}")

    return (
        crop_path if smart_crop_ok else None,
        mediapipe_ok,
        smart_crop_ok,
        " | ".join(notes),
    )


def ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    return (
        f"{int(seconds // 3600)}:"
        f"{int(seconds % 3600 // 60):02d}:"
        f"{seconds % 60:05.2f}"
    )


def captions_of(transcript: dict, clips: dict, job: Path) -> Path:
    folder = job / "captions"
    folder.mkdir(exist_ok=True)
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Main,DejaVu Sans,46,&H00FFFFFF,&H0000FFFF,&H00000000,&H78000000,1,0,0,0,100,100,0,0,1,4,1,2,55,55,110,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""

    for clip in clips["clips"]:
        rows = [header]
        clip_start = clip["start"]
        clip_end = clip["end"]
        for segment in transcript["segments"]:
            start = max(segment["start"], clip_start)
            end = min(segment["end"], clip_end)
            if end <= start or not segment["text"].strip():
                continue
            text = segment["text"].replace("{", "(").replace("}", ")")
            text = r"\N".join(textwrap.wrap(text, width=38)[:2])
            rows.append(
                f"Dialogue: 0,{ass_time(start-clip_start)},{ass_time(end-clip_start)},Main,,0,0,0,,{text}\n"
            )
        (folder / f"{clip['id']}.ass").write_text(
            "".join(rows), encoding="utf-8"
        )
    return folder


def filter_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def crop_dimensions(meta: dict) -> tuple[int, int, int]:
    crop_h = meta["height"]
    crop_w = int(round(crop_h * 9 / 16))
    if crop_w > meta["width"]:
        crop_w = meta["width"]
        crop_h = int(round(crop_w * 16 / 9))
    center_x = max(0, (meta["width"] - crop_w) // 2)
    return crop_w, crop_h, center_x


def smooth_commands(
    clip: dict,
    crop_item: dict,
    command_path: Path,
    sample_hz: float = 10.0,
):
    keyframes = sorted(
        crop_item.get("keyframes", []), key=lambda item: float(item.get("time", 0))
    )
    if not keyframes:
        return None

    clip_start = float(clip["start"])
    duration = float(clip["duration"])
    times = np.array(
        [float(item["time"]) - clip_start for item in keyframes], dtype=np.float64
    )
    xs = np.array([float(item["crop_x"]) for item in keyframes], dtype=np.float64)

    valid = (times >= -0.5) & (times <= duration + 0.5)
    times = times[valid]
    xs = xs[valid]
    if times.size == 0:
        return None

    order = np.argsort(times)
    times = times[order]
    xs = xs[order]
    times = np.clip(times, 0.0, duration)

    # Ensure a command exists from the first rendered frame.
    if times[0] > 0:
        times = np.insert(times, 0, 0.0)
        xs = np.insert(xs, 0, xs[0])
    if times[-1] < duration:
        times = np.append(times, duration)
        xs = np.append(xs, xs[-1])

    dense_times = np.arange(0.0, duration + 1e-6, 1.0 / sample_hz)
    dense_xs = np.interp(dense_times, times, xs)

    # Another small EMA makes 3-fps detections look fluid at render time.
    alpha = 0.30
    for index in range(1, len(dense_xs)):
        dense_xs[index] = (
            alpha * dense_xs[index] + (1.0 - alpha) * dense_xs[index - 1]
        )

    lines = []
    last_x = None
    for timestamp, x_value in zip(dense_times, dense_xs):
        x_int = int(round(float(x_value)))
        if last_x is None or x_int != last_x:
            lines.append(f"{timestamp:.3f} crop@track x {x_int};")
            last_x = x_int

    command_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return int(round(float(dense_xs[0])))


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
        center_x = max(0, (meta["width"] - crop_w) // 2)

        command_path = job / f"crop_commands_{clip['id']}.txt"
        initial_x = smooth_commands(clip, crop_item, command_path)
        animated = initial_x is not None and command_path.is_file()

        if animated:
            filter_chain = (
                "setpts=PTS-STARTPTS,"
                f"sendcmd=f={filter_path(command_path)},"
                f"crop@track={crop_w}:{crop_h}:{initial_x}:0,"
                "scale=720:1280"
            )
        else:
            filter_chain = (
                f"setpts=PTS-STARTPTS,crop={crop_w}:{crop_h}:{center_x}:0,"
                "scale=720:1280"
            )

        if ass_path.is_file():
            filter_chain += f",ass='{filter_path(ass_path)}'"

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
            "-vf",
            filter_chain,
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

        try:
            run(command, timeout=1800)
            if animated:
                animated_count += 1
            else:
                fallback_count += 1
        except Exception as exc:
            # Keep the pipeline alive if animated crop syntax fails on a specific FFmpeg build.
            (job / f"render_animated_error_{clip['id']}.txt").write_text(
                f"{type(exc).__name__}: {exc}", encoding="utf-8"
            )
            fallback_filter = (
                f"setpts=PTS-STARTPTS,crop={crop_w}:{crop_h}:{center_x}:0,"
                "scale=720:1280"
            )
            if ass_path.is_file():
                fallback_filter += f",ass='{filter_path(ass_path)}'"
            run(
                [
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
                    "-vf",
                    fallback_filter,
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
                ],
                timeout=1800,
            )
            fallback_count += 1

        if output.is_file() and output.stat().st_size > 0:
            outputs.append(output)

    if not outputs:
        raise RuntimeError("Semua render gagal.")
    return outputs, animated_count, fallback_count


def make_zip(job: Path, files: list[Path]) -> Path:
    output = job / "clipping_lite_results.zip"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in files:
            path = Path(file_path)
            if path.is_file():
                archive.write(path, arcname=path.name)
    return output


def pipeline(upload, drive_url, clip_count, clip_duration, whisper_mode, enable_ocr):
    cleanup_old_jobs()
    job = ROOT / uuid.uuid4().hex
    job.mkdir(parents=True, exist_ok=True)

    states = {stage: "pending" for stage in STAGES}
    preview = None
    transcript_text = ""
    clips_view = None
    files = []
    current = STAGES[0]

    cfg = env_config()
    (job / "runtime_config.json").write_text(
        json.dumps(cfg, indent=2), encoding="utf-8"
    )

    def snap(note):
        return status_md(states, note), preview, transcript_text, clips_view, files

    try:
        states[current] = "running"
        yield snap("Menyiapkan sumber video...")
        source_video = prepare_source(upload, drive_url, job)
        preview = str(source_video)
        states[current] = "done"
        yield snap(f"Video siap: {source_video.stat().st_size / 1024 / 1024:.1f} MB")

        current = STAGES[1]
        states[current] = "running"
        yield snap("Membaca codec dan menormalkan video bila diperlukan...")
        source_meta = probe_video(source_video)
        (job / "source_metadata.json").write_text(
            json.dumps(source_meta, indent=2), encoding="utf-8"
        )
        video, meta, normalized, normalize_note = normalize_source(
            source_video, source_meta, job
        )
        preview = str(video)
        if not meta["has_audio"]:
            raise RuntimeError("Video tidak memiliki audio.")
        audio = extract_audio(video, job)
        (job / "metadata.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
        states[current] = "done"
        yield snap(
            f"{normalize_note} {meta['width']}×{meta['height']}, "
            f"{meta['duration']:.1f} detik."
        )

        current = STAGES[2]
        states[current] = "running"
        yield snap(f"Menjalankan {whisper_mode}...")
        transcript, engine, used_groq_whisper = transcribe(
            audio, meta["duration"], whisper_mode
        )
        (job / "transcript.json").write_text(
            json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        transcript_text = transcript["text"][:20000]
        states[current] = "done" if used_groq_whisper or not whisper_mode.startswith("Groq") else "warning"
        yield snap(f"Transkripsi selesai: {engine}")

        current = STAGES[3]
        states[current] = "running"
        yield snap("Mendeteksi pergantian scene...")
        try:
            scenes = scenes_of(video, meta["duration"])
            states[current] = "done"
            note = f"{len(scenes)} scene ditemukan."
        except Exception as exc:
            scenes = [{"start": 0.0, "end": meta["duration"]}]
            states[current] = "warning"
            note = f"Fallback satu scene: {exc}"
        (job / "scenes.json").write_text(json.dumps({"scenes": scenes}, indent=2))
        yield snap(note)

        current = STAGES[4]
        states[current] = "running"
        yield snap("Mengukur energi audio...")
        energy = audio_energy(audio)
        (job / "audio_energy.json").write_text(json.dumps({"energy": energy}, indent=2))
        states[current] = "done"
        yield snap(f"{len(energy)} titik energi selesai.")

        current = STAGES[5]
        if enable_ocr:
            states[current] = "running"
            yield snap("OCR membaca teks pada frame...")
            try:
                ocr = do_ocr(video, scenes, True)
                states[current] = "done"
                note = f"OCR: {len(ocr)} frame berisi teks."
            except Exception as exc:
                ocr = []
                states[current] = "warning"
                note = f"OCR dilewati: {exc}"
        else:
            ocr = []
            states[current] = "done"
            note = "OCR dimatikan."
        (job / "ocr.json").write_text(
            json.dumps({"items": ocr}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        yield snap(note)

        current = STAGES[6]
        states[current] = "running"
        yield snap(f"Menganalisis visual kandidat dengan {cfg['gemini_vision_model']}...")
        candidates = candidates_of(
            transcript,
            scenes,
            energy,
            ocr,
            meta["duration"],
            int(clip_duration),
        )
        try:
            candidates, vision_note, used_gemini_vision = gemini_vision_score(
                video, candidates, job
            )
            states[current] = "done" if used_gemini_vision else "warning"
        except Exception as exc:
            vision_note = f"Gemini Vision fallback: {type(exc).__name__}: {exc}"
            states[current] = "warning"
        yield snap(vision_note)

        current = STAGES[7]
        states[current] = "running"
        yield snap(f"Menilai kandidat dengan {cfg['groq_llm_model']} + sinyal Gemini Vision...")
        try:
            selected, score_engine, used_groq_llm = groq_rank(
                candidates, int(clip_count), job
            )
            states[current] = "done" if used_groq_llm else "warning"
        except Exception as exc:
            selected = non_overlap(candidates, int(clip_count))
            score_engine = f"heuristic fallback ({exc})"
            states[current] = "warning"
        clips_path, clips = write_clips(selected, job)
        clips_view = clips
        yield snap(f"{len(clips['clips'])} clip dipilih: {score_engine}")

        current = STAGES[8]
        states[current] = "running"
        yield snap("MediaPipe melacak wajah pada clip terpilih...")
        crop_path, mediapipe_ok, smart_crop_ok, face_note = mediapipe_crop(
            video, clips_path, job
        )
        states[current] = "done" if mediapipe_ok else "warning"
        yield snap(face_note)

        current = STAGES[9]
        states[current] = "done" if smart_crop_ok else "warning"
        yield snap(
            face_note
            if smart_crop_ok
            else f"{face_note} | Render akan memakai center crop."
        )

        current = STAGES[10]
        states[current] = "running"
        yield snap("Membuat subtitle ASS...")
        captions = captions_of(transcript, clips, job)
        states[current] = "done"
        yield snap("Subtitle selesai.")

        current = STAGES[11]
        states[current] = "running"
        yield snap("FFmpeg merender smart crop bergerak 720×1280...")
        rendered, animated_count, fallback_count = render_all(
            video, meta, clips, crop_path, captions, job
        )
        files = [str(path) for path in rendered]
        states[current] = "done" if fallback_count == 0 else "warning"
        yield snap(
            f"{len(rendered)} clip selesai: {animated_count} animated crop, "
            f"{fallback_count} center-crop fallback."
        )

        current = STAGES[12]
        states[current] = "running"
        yield snap("Membuat ZIP hasil dan log debug...")
        debug_files = [
            job / "runtime_config.json",
            job / "source_metadata.json",
            job / "normalization.log",
            job / "metadata.json",
            job / "transcript.json",
            job / "scenes.json",
            job / "audio_energy.json",
            job / "ocr.json",
            job / "gemini_vision_request.json",
            job / "gemini_vision_response.txt",
            job / "gemini_vision_error.txt",
            job / "gemini_vision.json",
            job / "clips.json",
            job / "face_data.json",
            job / "crop_data.json",
            job / "groq_scoring_request.json",
            job / "groq_scoring_response.txt",
            job / "mediapipe_stdout.txt",
            job / "mediapipe_error.txt",
            job / "smart_crop_stdout.txt",
            job / "smart_crop_error.txt",
        ]
        debug_files.extend((job / "gemini_vision_frames").glob("*.jpg"))
        debug_files.extend(job.glob("crop_commands_*.txt"))
        debug_files.extend(job.glob("render_animated_error_*.txt"))
        archive = make_zip(job, rendered + debug_files)
        files.append(str(archive))
        states[current] = "done"
        yield snap("🎉 Tahap 3 selesai: Gemini Vision + Groq scoring + MediaPipe + animated smart crop aktif.")
        return {
            "ok": True,
            "job": str(job),
            "archive": str(archive),
            "rendered": [str(path) for path in rendered],
            "clips": clips,
            "final_stage": current,
        }

    except Exception as exc:
        states[current] = "error"
        error_path = job / "fatal_error.txt"
        error_path.write_text(
            f"Tahap: {current}\n{type(exc).__name__}: {exc}", encoding="utf-8"
        )
        yield snap(f"ERROR pada tahap **{current}**: {type(exc).__name__}: {exc}")
        return {
            "ok": False,
            "job": str(job),
            "error_log": str(error_path),
            "error": f"{type(exc).__name__}: {exc}",
            "final_stage": current,
        }


def parse_batch_links(raw_text: str) -> list[str]:
    links = []
    seen = set()
    for raw_line in (raw_text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line in seen:
            continue
        seen.add(line)
        links.append(line)
    if len(links) > MAX_BATCH_LINKS:
        raise gr.Error(
            f"Maksimal {MAX_BATCH_LINKS} link per batch supaya CPU Basic tetap stabil."
        )
    return links


def drive_file_id(url: str) -> str:
    patterns = [r"/d/([A-Za-z0-9_-]+)", r"[?&]id=([A-Za-z0-9_-]+)"]
    for pattern in patterns:
        match = re.search(pattern, url or "")
        if match:
            return match.group(1)[:24]
    return uuid.uuid5(uuid.NAMESPACE_URL, url or str(uuid.uuid4())).hex[:12]


def shorten_url(url: str, limit: int = 64) -> str:
    clean = (url or "").replace("|", "%7C")
    if len(clean) <= limit:
        return clean
    return clean[:34] + "…" + clean[-24:]


def stage_from_status(status_text: str) -> str:
    for line in (status_text or "").splitlines():
        if line.startswith("🔵") or line.startswith("❌"):
            return re.sub(r"[*#]", "", line).strip()
    for line in (status_text or "").splitlines():
        if line.startswith("🟡"):
            return re.sub(r"[*#]", "", line).strip()
    return "Memproses"


def note_from_status(status_text: str) -> str:
    marker = "**Log terakhir:**"
    for line in reversed((status_text or "").splitlines()):
        if marker in line:
            return line.split(marker, 1)[1].strip()
    return ""


def batch_status_md(items: list[dict], note: str = "") -> str:
    done = sum(1 for item in items if item["status"] == "done")
    failed = sum(1 for item in items if item["status"] == "error")
    running = sum(1 for item in items if item["status"] == "running")
    lines = [
        "## 📚 Antrian Batch",
        f"**Total:** {len(items)} · **Selesai:** {done} · **Gagal:** {failed} · **Berjalan:** {running}",
        "",
        "| # | Status | Tahap / keterangan | Link |",
        "|---:|:---:|---|---|",
    ]
    icons = {"pending": "⚪", "running": "🔵", "done": "✅", "error": "❌"}
    for item in items:
        detail = str(item.get("detail") or item.get("stage") or "Menunggu").replace("|", "/")
        if len(detail) > 115:
            detail = detail[:112] + "…"
        lines.append(
            f"| {item['index']} | {icons.get(item['status'], '⚪')} | "
            f"{detail} | `{shorten_url(item['url'])}` |"
        )
    if note:
        lines.extend(["", f"**Log batch:** {note}"])
    return "\n".join(lines)


def public_batch_summary(items: list[dict]) -> list[dict]:
    return [
        {
            "index": item["index"],
            "url": item["url"],
            "status": item["status"],
            "stage": item.get("stage"),
            "detail": item.get("detail"),
            "zip_file": Path(item["archive"]).name if item.get("archive") else None,
            "error_log": Path(item["error_log"]).name if item.get("error_log") else None,
        }
        for item in items
    ]


def write_batch_reports(batch_root: Path, items: list[dict]) -> tuple[Path, Path]:
    summary_json = batch_root / "batch_summary.json"
    summary_json.write_text(
        json.dumps({"items": public_batch_summary(items)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary_csv = batch_root / "batch_summary.csv"
    with summary_csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "index", "url", "status", "stage", "detail", "zip_file", "error_log"
            ],
        )
        writer.writeheader()
        writer.writerows(public_batch_summary(items))
    return summary_json, summary_csv


def make_batch_master_zip(batch_root: Path, files: list[Path]) -> Path:
    output = batch_root / "batch_all_results.zip"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in files:
            path = Path(file_path)
            if path.is_file() and path != output:
                archive.write(path, arcname=path.name)
    return output


def batch_pipeline(batch_links, clip_count, clip_duration, whisper_mode, enable_ocr):
    cleanup_old_jobs()
    links = parse_batch_links(batch_links)
    if not links:
        raise gr.Error("Masukkan minimal satu link Google Drive, satu link per baris.")

    batch_root = ROOT / f"batch_{uuid.uuid4().hex}"
    batch_root.mkdir(parents=True, exist_ok=True)
    items = [
        {
            "index": index,
            "url": url,
            "status": "pending",
            "stage": "Menunggu giliran",
            "detail": "Menunggu giliran",
            "archive": None,
            "error_log": None,
        }
        for index, url in enumerate(links, 1)
    ]
    downloadable = []
    current_preview = None
    current_roadmap = "Batch belum dimulai."

    yield (
        batch_status_md(items, "Antrian dibuat. Proses berjalan satu per satu."),
        current_preview,
        current_roadmap,
        public_batch_summary(items),
        downloadable,
    )

    for position, item in enumerate(items):
        item["status"] = "running"
        item["stage"] = "Memulai pipeline"
        item["detail"] = "Menyiapkan video"
        yield (
            batch_status_md(items, f"Memproses link {item['index']} dari {len(items)}."),
            current_preview,
            current_roadmap,
            public_batch_summary(items),
            downloadable,
        )

        generator = pipeline(
            None,
            item["url"],
            clip_count,
            clip_duration,
            whisper_mode,
            enable_ocr,
        )
        final_result = None
        while True:
            try:
                single_update = next(generator)
            except StopIteration as stop:
                final_result = stop.value
                break

            current_roadmap, current_preview, _transcript, _clips, _files = single_update
            item["stage"] = stage_from_status(current_roadmap)
            item["detail"] = note_from_status(current_roadmap) or item["stage"]
            yield (
                batch_status_md(
                    items,
                    f"Link {item['index']}/{len(items)} sedang berjalan — {item['detail']}",
                ),
                current_preview,
                current_roadmap,
                public_batch_summary(items),
                downloadable,
            )

        final_result = final_result or {
            "ok": False,
            "error": "Pipeline berhenti tanpa hasil akhir.",
            "final_stage": item.get("stage"),
        }
        short_id = drive_file_id(item["url"])

        if final_result.get("ok"):
            source_archive = Path(final_result["archive"])
            copied_archive = batch_root / f"{item['index']:02d}_{short_id}_results.zip"
            shutil.copy2(source_archive, copied_archive)
            item["status"] = "done"
            item["stage"] = "Selesai"
            item["detail"] = (
                f"Selesai — {len(final_result.get('rendered') or [])} clip dirender."
            )
            item["archive"] = str(copied_archive)
            downloadable.append(str(copied_archive))
        else:
            copied_error = batch_root / f"{item['index']:02d}_{short_id}_error.txt"
            original_error = Path(final_result.get("error_log") or "")
            body = [
                f"Link: {item['url']}",
                f"Tahap: {final_result.get('final_stage') or item.get('stage')}",
                f"Error: {final_result.get('error') or 'Unknown error'}",
            ]
            if original_error.is_file():
                body.extend(["", "--- fatal_error.txt asli ---", original_error.read_text(encoding="utf-8", errors="replace")])
            copied_error.write_text("\n".join(body), encoding="utf-8")
            item["status"] = "error"
            item["stage"] = final_result.get("final_stage") or "Gagal"
            item["detail"] = final_result.get("error") or "Unknown error"
            item["error_log"] = str(copied_error)
            downloadable.append(str(copied_error))

        yield (
            batch_status_md(
                items,
                f"Link {item['index']} selesai. Melanjutkan otomatis ke link berikutnya.",
            ),
            current_preview,
            current_roadmap,
            public_batch_summary(items),
            downloadable,
        )

    summary_json, summary_csv = write_batch_reports(batch_root, items)
    downloadable.extend([str(summary_json), str(summary_csv)])
    master_zip = make_batch_master_zip(
        batch_root, [Path(path) for path in downloadable]
    )
    downloadable.append(str(master_zip))
    done = sum(1 for item in items if item["status"] == "done")
    failed = sum(1 for item in items if item["status"] == "error")
    yield (
        batch_status_md(
            items,
            f"🎉 Batch selesai: {done} berhasil, {failed} gagal. Master ZIP sudah dibuat.",
        ),
        current_preview,
        "## ✅ Batch selesai\nSemua link sudah diproses secara berurutan.",
        public_batch_summary(items),
        downloadable,
    )


with gr.Blocks(title="Clipping Lite Stage 4") as demo:
    gr.Markdown(
        """
        # 🎬 Clipping Lite — Stage 4 Queue

        **Single video + Batch antrean link Drive berurutan.**  \n        Pipeline: AV1/H.265 Normalizer → Groq Whisper → Gemini Vision → Groq Llama →
        MediaPipe → Animated Smart Crop → Subtitle → Render.
        """
    )
    runtime_info = gr.Markdown(config_md())

    with gr.Tab("🎞️ Satu Video"):
        with gr.Row():
            with gr.Column():
                upload = gr.Video(label="Upload video — opsional")
                drive = gr.Textbox(
                    label="Link Google Drive publik",
                    placeholder="https://drive.google.com/file/d/FILE_ID/view?usp=sharing",
                    lines=2,
                )
                campaign_requirements = gr.Textbox(
                  label="📋 Campaign Requirements — opsional",
                  placeholder=(
                    "Tempel persyaratan kampanye di sini.\n\n"
                    "Contoh:\n"
                    "- Speaker harus berbicara di setiap clip\n"
                    "- Hook kuat pada 1–3 detik pertama\n"
                    "- Bukan pure lifestyle\n"
                    "- Edit clean, modern, dan tajam\n\n"
                    "Kosongkan untuk mode viral biasa."
                   ),
               lines=9,
               )
                whisper = gr.Dropdown(
                    [
                        "Groq Whisper (disarankan)",
                        "Local Whisper tiny",
                        "Local Whisper base",
                    ],
                    value="Groq Whisper (disarankan)",
                    label="Mesin transkripsi",
                )
                with gr.Row():
                    count = gr.Slider(1, 5, value=3, step=1, label="Jumlah clip")
                    duration = gr.Slider(20, 60, value=30, step=5, label="Durasi target")
                ocr_box = gr.Checkbox(False, label="Aktifkan OCR (lebih lambat)")
                button = gr.Button("🚀 Proses Satu Video", variant="primary")

            with gr.Column():
                preview = gr.Video(label="Preview sumber")
                status = gr.Markdown("Tekan tombol proses untuk mulai.")

        with gr.Tab("Transkrip"):
            transcript_out = gr.Textbox(lines=18, interactive=False)
        with gr.Tab("Clip terpilih"):
            clips_out = gr.JSON()
        with gr.Tab("Hasil"):
            files_out = gr.File(file_count="multiple")

        button.click(
            pipeline,
            [upload, drive, count, duration, whisper, ocr_box],
            [status, preview, transcript_out, clips_out, files_out],
            show_progress="full",
        )

    with gr.Tab("📚 Batch Link Drive"):
        gr.Markdown(
            f"""
            ### Tempel banyak link — satu link per baris
            Diproses **satu per satu**, bukan bersamaan, supaya CPU Basic stabil.  \n            Maksimal **{MAX_BATCH_LINKS} link per batch**. Biarkan tab tetap terbuka selama proses.
            """
        )
        with gr.Row():
            with gr.Column():
                batch_links = gr.Textbox(
                    label="Daftar link Google Drive publik",
                    placeholder=(
                        "https://drive.google.com/file/d/FILE_ID_1/view?usp=sharing\n"
                        "https://drive.google.com/file/d/FILE_ID_2/view?usp=sharing"
                    ),
                    lines=12,
                )
                batch_whisper = gr.Dropdown(
                    [
                        "Groq Whisper (disarankan)",
                        "Local Whisper tiny",
                        "Local Whisper base",
                    ],
                    value="Groq Whisper (disarankan)",
                    label="Mesin transkripsi batch",
                )
                with gr.Row():
                    batch_count = gr.Slider(1, 5, value=3, step=1, label="Clip per video")
                    batch_duration = gr.Slider(20, 60, value=30, step=5, label="Durasi target")
                batch_ocr = gr.Checkbox(False, label="Aktifkan OCR untuk semua video")
                batch_button = gr.Button("🚀 Jalankan Antrian Batch", variant="primary")

            with gr.Column():
                batch_preview = gr.Video(label="Video yang sedang diproses")
                batch_current = gr.Markdown("Antrian belum dijalankan.")

        batch_status = gr.Markdown("Masukkan link lalu jalankan batch.")
        with gr.Tab("Ringkasan Batch"):
            batch_results = gr.JSON()
        with gr.Tab("Download Batch"):
            batch_files = gr.File(file_count="multiple")

        batch_button.click(
            batch_pipeline,
            [
                batch_links,
                batch_count,
                batch_duration,
                batch_whisper,
                batch_ocr,
            ],
            [
                batch_status,
                batch_preview,
                batch_current,
                batch_results,
                batch_files,
            ],
            show_progress="full",
        )


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=1, max_size=8)
    demo.launch(server_name="0.0.0.0", server_port=7860)
