
from __future__ import annotations

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
from scenedetect import SceneManager, open_video
from scenedetect.detectors import ContentDetector


STAGES = [
    "Input video",
    "FFmpeg/ffprobe",
    "Whisper",
    "PySceneDetect",
    "Audio dynamics",
    "OCR",
    "Groq Llama viral scoring",
    "MediaPipe",
    "Smart crop",
    "Subtitle",
    "Render",
    "Paket hasil",
]
ICON = {"pending": "⚪", "running": "🔵", "done": "✅", "warning": "🟡", "error": "❌"}
ROOT = Path(tempfile.gettempdir()) / "clipping-lite-jobs"


def status_md(states, note=""):
    lines = ["## 🚦 Roadmap proses"]
    for i, stage in enumerate(STAGES, 1):
        lines.append(f"{ICON[states.get(stage, 'pending')]} **{i}. {stage}**")
    if note:
        lines += ["", f"**Log terakhir:** {note}"]
    return "\n".join(lines)


def run(cmd, timeout=1800, binary=False, cwd=None):
    p = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=not binary,
        timeout=timeout,
        check=False,
    )
    if p.returncode:
        err = p.stderr if not binary else p.stderr.decode("utf-8", "replace")
        raise RuntimeError((err or "Command gagal")[-2500:])
    return p.stdout


def path_of(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("path", "video", "name"):
            if isinstance(value.get(key), str):
                return value[key]
    value = getattr(value, "path", None)
    return value if isinstance(value, str) else None


def cleanup_old_jobs(hours=6):
    ROOT.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - hours * 3600
    for p in ROOT.iterdir():
        try:
            if p.is_dir() and p.stat().st_mtime < cutoff:
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass


def prepare_source(upload, drive_url, job):
    dst = job / "source.mp4"
    up = path_of(upload)
    if up:
        shutil.copy2(up, dst)
        return dst

    drive_url = (drive_url or "").strip()
    parsed = urlparse(drive_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname != "drive.google.com":
        raise ValueError("Upload video atau masukkan link Google Drive publik.")

    saved = gdown.download(url=drive_url, output=str(dst), quiet=False)
    dst = Path(saved or dst)
    if not dst.is_file() or dst.stat().st_size <= 0:
        raise RuntimeError("Download Drive gagal. Set akses: Anyone with the link → Viewer.")
    return dst


def probe_video(video):
    data = json.loads(
        run([
            "ffprobe", "-v", "error", "-show_streams", "-show_format",
            "-of", "json", str(video)
        ], timeout=120)
    )
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not v:
        raise RuntimeError("Stream video tidak ditemukan.")
    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or v.get("duration") or 0)
    if duration <= 0:
        raise RuntimeError("Durasi video tidak terbaca.")
    return {
        "duration": duration,
        "width": int(v.get("width") or 0),
        "height": int(v.get("height") or 0),
        "video_codec": v.get("codec_name", "?"),
        "audio_codec": a.get("codec_name", "?") if a else None,
        "has_audio": bool(a),
        "size_mb": video.stat().st_size / 1024 / 1024,
    }


def extract_audio(video, job):
    out = job / "audio.mp3"
    run([
        "ffmpeg", "-y", "-v", "error", "-i", str(video),
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(out)
    ], timeout=900)
    if not out.is_file():
        raise RuntimeError("Audio tidak berhasil diekstrak.")
    return out


def normalize_transcript(data, duration):
    segments, words = [], []
    for seg in data.get("segments") or []:
        if hasattr(seg, "model_dump"):
            seg = seg.model_dump()
        elif not isinstance(seg, dict):
            seg = vars(seg)
        start = float(seg.get("start") or 0)
        end = float(seg.get("end") or start)
        text = str(seg.get("text") or "").strip()
        sw = []
        for w in seg.get("words") or []:
            if hasattr(w, "model_dump"):
                w = w.model_dump()
            elif not isinstance(w, dict):
                w = vars(w)
            item = {
                "word": str(w.get("word") or "").strip(),
                "start": float(w.get("start") or start),
                "end": float(w.get("end") or end),
            }
            if item["word"]:
                sw.append(item)
                words.append(item)
        if text:
            segments.append({"start": start, "end": end, "text": text, "words": sw})
    text = str(data.get("text") or "").strip()
    if not segments and text:
        segments = [{"start": 0.0, "end": duration, "text": text, "words": []}]
    return {
        "language": data.get("language") or "unknown",
        "duration": float(data.get("duration") or duration),
        "text": text or " ".join(s["text"] for s in segments),
        "segments": segments,
        "words": words,
    }


def transcribe_groq(audio, duration):
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY belum dipasang.")
    from groq import Groq

    client = Groq(api_key=key, timeout=180, max_retries=2)
    model = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
    try:
        res = client.audio.transcriptions.create(
            file=audio,
            model=model,
            response_format="verbose_json",
            temperature=0.0,
            timestamp_granularities=["segment", "word"],
        )
    except Exception:
        res = client.audio.transcriptions.create(
            file=audio,
            model=model,
            response_format="verbose_json",
            temperature=0.0,
        )
    data = res.to_dict() if hasattr(res, "to_dict") else (
        res.model_dump() if hasattr(res, "model_dump") else vars(res)
    )
    return normalize_transcript(data, duration)


def transcribe_local(audio, duration, model_name):
    from faster_whisper import WhisperModel

    model = WhisperModel(
        model_name,
        device="cpu",
        compute_type="int8",
        cpu_threads=max(1, min(2, os.cpu_count() or 1)),
        num_workers=1,
    )
    segments, info = model.transcribe(
        str(audio), beam_size=1, vad_filter=True, word_timestamps=True
    )
    out, words = [], []
    for seg in segments:
        sw = []
        for w in seg.words or []:
            item = {"word": w.word.strip(), "start": float(w.start), "end": float(w.end)}
            sw.append(item)
            words.append(item)
        out.append({
            "start": float(seg.start),
            "end": float(seg.end),
            "text": seg.text.strip(),
            "words": sw,
        })
    return {
        "language": info.language,
        "duration": float(getattr(info, "duration", duration) or duration),
        "text": " ".join(s["text"] for s in out),
        "segments": out,
        "words": words,
    }


def transcribe(audio, duration, mode):
    if mode.startswith("Groq"):
        try:
            return transcribe_groq(audio, duration), "Groq Whisper"
        except Exception as exc:
            return transcribe_local(audio, duration, "tiny"), f"Groq gagal; fallback tiny ({exc})"
    model = "base" if "base" in mode.lower() else "tiny"
    return transcribe_local(audio, duration, model), f"Local Whisper {model}"


def scenes_of(video, duration):
    manager = SceneManager()
    manager.add_detector(ContentDetector(threshold=27.0))
    manager.detect_scenes(video=open_video(str(video)), show_progress=False)
    scenes = [
        {"start": s.get_seconds(), "end": e.get_seconds()}
        for s, e in manager.get_scene_list()
    ]
    return scenes or [{"start": 0.0, "end": duration}]


def audio_energy(audio):
    raw = run([
        "ffmpeg", "-v", "error", "-i", str(audio),
        "-f", "s16le", "-ac", "1", "-ar", "8000", "pipe:1"
    ], timeout=900, binary=True)
    arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    rate = 8000
    out = []
    for i in range(0, len(arr), rate):
        chunk = arr[i:i + rate]
        if chunk.size:
            out.append({
                "start": i / rate,
                "end": min((i + rate) / rate, len(arr) / rate),
                "rms": float(np.sqrt(np.mean(chunk * chunk) + 1e-12)),
            })
    return out


def do_ocr(video, scenes, enabled):
    if not enabled:
        return []
    times = sorted({round(s["start"], 2) for s in scenes[:20]})
    cap = cv2.VideoCapture(str(video))
    out = []
    try:
        for t in times:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            h, w = frame.shape[:2]
            if w > 960:
                frame = cv2.resize(frame, (960, int(h * 960 / w)))
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            text = re.sub(r"\s+", " ", pytesseract.image_to_string(gray, config="--psm 6")).strip()
            if len(text) >= 4:
                out.append({"time": t, "text": text[:300]})
    finally:
        cap.release()
    return out


def text_window(transcript, start, end):
    return " ".join(
        s["text"] for s in transcript["segments"]
        if s["end"] > start and s["start"] < end
    ).strip()


def mean_energy(items, start, end):
    vals = [x["rms"] for x in items if x["end"] > start and x["start"] < end]
    return sum(vals) / len(vals) if vals else 0.0


def candidates_of(transcript, scenes, energy, ocr, duration, target):
    window = float(target)
    step = max(10.0, window / 2)
    out, start, idx = [], 0.0, 1
    while start < duration:
        end = min(duration, start + window)
        if end - start < min(12.0, window * 0.6):
            break
        text = text_window(transcript, start, end)
        wc = len(text.split())
        if wc >= 5:
            sc = sum(1 for s in scenes if start < s["start"] < end)
            ae = mean_energy(energy, start, end)
            ocr_text = [x["text"] for x in ocr if start <= x["time"] <= end][:3]
            pre = (wc / max(1, end - start)) * 0.45 + math.log1p(sc) * 0.30 + ae * 2.5
            out.append({
                "candidate_id": f"C{idx:03d}",
                "start": round(start, 2),
                "end": round(end, 2),
                "duration": round(end - start, 2),
                "text": text[:1200],
                "scene_changes": sc,
                "audio_energy": round(ae, 5),
                "ocr": ocr_text,
                "preliminary_score": round(pre, 4),
            })
            idx += 1
        start += step
    return sorted(out, key=lambda x: x["preliminary_score"], reverse=True)[:24]


def non_overlap(items, count):
    picked = []
    for item in items:
        if not any(item["start"] < x["end"] and item["end"] > x["start"] for x in picked):
            picked.append(item)
        if len(picked) >= count:
            break
    return picked


def parse_json(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def groq_rank(candidates, count):
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        return non_overlap(candidates, count), "heuristic (tanpa GROQ_API_KEY)"

    from groq import Groq

    compact = [{
        "candidate_id": x["candidate_id"],
        "start": x["start"],
        "end": x["end"],
        "text": x["text"],
        "scene_changes": x["scene_changes"],
        "audio_energy": x["audio_energy"],
        "ocr": x["ocr"],
    } for x in candidates]

    prompt = f"""
Pilih tepat {count} kandidat short-form terbaik.
Nilai: hook, koherensi, visual, audio, informasi, emotional arc, payoff, cross-modal sync.
Hindari kandidat tumpang tindih. Balas JSON murni:
{{"clips":[{{"candidate_id":"C001","score":90,"title":"judul","reason":"alasan"}}]}}
Kandidat:
{json.dumps(compact, ensure_ascii=False)}
""".strip()

    model = os.getenv("GROQ_LLM_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
    client = Groq(api_key=key, timeout=120, max_retries=2)
    res = client.chat.completions.create(
        model=model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": "Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
    )
    data = parse_json(res.choices[0].message.content or "")
    cmap = {x["candidate_id"]: x for x in candidates}
    ranked = []
    for r in data.get("clips", []):
        c = cmap.get(str(r.get("candidate_id")))
        if not c:
            continue
        c = dict(c)
        c["score"] = max(0, min(100, int(float(r.get("score", 70)))))
        c["title"] = str(r.get("title") or "Highlight")[:80]
        c["reason"] = str(r.get("reason") or "")[:300]
        ranked.append(c)

    ranked = non_overlap(ranked, count)
    if len(ranked) < count:
        used = {x["candidate_id"] for x in ranked}
        ranked += non_overlap([x for x in candidates if x["candidate_id"] not in used], count - len(ranked))
    return ranked[:count], f"Groq Llama ({model})"


def write_clips(selected, job):
    clips = []
    for i, x in enumerate(selected, 1):
        clips.append({
            "id": f"{i:02d}",
            "start": float(x["start"]),
            "end": float(x["end"]),
            "duration": float(x["end"] - x["start"]),
            "title": x.get("title") or f"Highlight {i}",
            "score": int(x.get("score", 70)),
            "reason": x.get("reason") or "Heuristic selection",
        })
    payload = {"clips": clips}
    path = job / "clips.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path, payload


def mediapipe_crop(video, clips_path, job):
    """Run MediaPipe and Smart Crop separately so each stage has its own status."""
    face = job / "face_data.json"
    crop = job / "crop_data.json"
    model = Path(
        os.getenv(
            "MEDIAPIPE_MODEL_PATH",
            "/app/models/face_landmarker.task",
        )
    )

    mediapipe_ok = False
    smart_crop_ok = False
    detected_frames = 0
    total_frames = 0
    notes = []

    # Stage 8: MediaPipe
    try:
        if not model.is_file() or model.stat().st_size < 100_000:
            raise RuntimeError(
                f"Model MediaPipe tidak ditemukan atau rusak: {model}"
            )

        mp_stdout = run([
            sys.executable, "scripts/face_track.py",
            "--source", str(video),
            "--clips", str(clips_path),
            "--output", str(face),
            "--fps", "2",
            "--model", str(model),
        ], cwd="/app", timeout=1800)

        (job / "mediapipe_stdout.txt").write_text(
            mp_stdout or "MediaPipe selesai tanpa stdout.",
            encoding="utf-8",
        )

        if not face.is_file() or face.stat().st_size <= 2:
            raise RuntimeError("face_data.json tidak berhasil dibuat.")

        face_data = json.loads(face.read_text(encoding="utf-8"))
        for item in face_data.get("clips", {}).values():
            frames = item.get("frames", [])
            total_frames += len(frames)
            detected_frames += sum(
                1 for frame in frames if frame.get("detected")
            )

        mediapipe_ok = detected_frames > 0
        if mediapipe_ok:
            notes.append(
                f"MediaPipe: wajah terdeteksi pada "
                f"{detected_frames}/{total_frames} frame."
            )
        else:
            notes.append(
                f"MediaPipe berjalan, tetapi tidak menemukan wajah "
                f"pada {total_frames} frame."
            )

    except Exception as exc:
        error_text = (
            "MEDIA PIPE ERROR\n"
            f"{type(exc).__name__}: {exc}\n"
        )
        (job / "mediapipe_error.txt").write_text(
            error_text,
            encoding="utf-8",
        )
        notes.append(
            f"MediaPipe gagal: {type(exc).__name__}: {exc}"
        )
        return None, mediapipe_ok, smart_crop_ok, " | ".join(notes)

    # Stage 9: Smart Crop
    try:
        crop_stdout = run([
            sys.executable, "scripts/smart_crop.py",
            "--face-data", str(face),
            "--clips", str(clips_path),
            "--output", str(crop),
            "--source", str(video),
            "--smooth", "5",
        ], cwd="/app", timeout=600)

        (job / "smart_crop_stdout.txt").write_text(
            crop_stdout or "Smart Crop selesai tanpa stdout.",
            encoding="utf-8",
        )

        if not crop.is_file() or crop.stat().st_size <= 2:
            raise RuntimeError("crop_data.json tidak berhasil dibuat.")

        crop_data = json.loads(crop.read_text(encoding="utf-8"))
        clip_items = crop_data.get("clips", {})
        if not clip_items:
            raise RuntimeError("crop_data.json tidak memiliki data clip.")

        keyframes = sum(
            len(item.get("keyframes", []))
            for item in clip_items.values()
        )
        smart_crop_ok = True
        notes.append(
            f"Smart Crop: {keyframes} keyframe untuk "
            f"{len(clip_items)} clip."
        )

    except Exception as exc:
        error_text = (
            "SMART CROP ERROR\n"
            f"{type(exc).__name__}: {exc}\n"
        )
        (job / "smart_crop_error.txt").write_text(
            error_text,
            encoding="utf-8",
        )
        notes.append(
            f"Smart Crop gagal: {type(exc).__name__}: {exc}"
        )

    return (
        crop if smart_crop_ok else None,
        mediapipe_ok,
        smart_crop_ok,
        " | ".join(notes),
    )


def ass_time(sec):
    sec = max(0.0, sec)
    return f"{int(sec // 3600)}:{int(sec % 3600 // 60):02d}:{sec % 60:05.2f}"


def captions_of(transcript, clips, job):
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
        cs, ce = clip["start"], clip["end"]
        for seg in transcript["segments"]:
            start, end = max(seg["start"], cs), min(seg["end"], ce)
            if end <= start or not seg["text"].strip():
                continue
            text = seg["text"].replace("{", "(").replace("}", ")")
            text = r"\N".join(textwrap.wrap(text, width=38)[:2])
            rows.append(
                f"Dialogue: 0,{ass_time(start-cs)},{ass_time(end-cs)},Main,,0,0,0,,{text}\n"
            )
        (folder / f"{clip['id']}.ass").write_text("".join(rows), encoding="utf-8")
    return folder


def median_crop(crop_data, clip_id, width, height):
    dw = min(width, int(height * 9 / 16))
    dh = height
    dx = max(0, (width - dw) // 2)
    if not crop_data:
        return dw, dh, dx
    item = crop_data.get("clips", {}).get(clip_id, {})
    cw = int(item.get("crop_w") or dw)
    ch = int(item.get("crop_h") or dh)
    xs = [int(k["crop_x"]) for k in item.get("keyframes", []) if "crop_x" in k]
    cx = int(np.median(xs)) if xs else dx
    return cw, ch, max(0, min(cx, width - cw))


def filter_path(path):
    return str(path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def render_all(video, meta, clips, crop_path, captions, job):
    outdir = job / "outputs"
    outdir.mkdir(exist_ok=True)
    crop_data = json.loads(crop_path.read_text()) if crop_path and crop_path.is_file() else None
    outputs = []

    for clip in clips["clips"]:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", clip["title"][:30])
        out = outdir / f"{clip['id']}_{safe}.mp4"
        cw, ch, cx = median_crop(crop_data, clip["id"], meta["width"], meta["height"])
        vf = [f"crop={cw}:{ch}:{cx}:0", "scale=720:1280"]
        ass = captions / f"{clip['id']}.ass"
        if ass.is_file():
            vf.append(f"ass='{filter_path(ass)}'")
        run([
            "ffmpeg", "-y", "-v", "error",
            "-ss", str(clip["start"]), "-i", str(video),
            "-t", str(clip["duration"]),
            "-vf", ",".join(vf),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            str(out),
        ], timeout=1800)
        if out.is_file() and out.stat().st_size:
            outputs.append(out)
    if not outputs:
        raise RuntimeError("Semua render gagal.")
    return outputs


def make_zip(job, files):
    out = job / "clipping_lite_results.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            if f and Path(f).is_file():
                z.write(f, arcname=Path(f).name)
    return out


def pipeline(upload, drive_url, clip_count, clip_duration, whisper_mode, enable_ocr):
    cleanup_old_jobs()
    job = ROOT / uuid.uuid4().hex
    job.mkdir(parents=True, exist_ok=True)

    states = {s: "pending" for s in STAGES}
    preview, transcript_text, clips_view, files = None, "", None, []
    current = STAGES[0]

    def snap(note):
        return status_md(states, note), preview, transcript_text, clips_view, files

    try:
        states[current] = "running"
        yield snap("Menyiapkan sumber...")
        video = prepare_source(upload, drive_url, job)
        preview = str(video)
        states[current] = "done"
        yield snap(f"Video siap: {video.stat().st_size/1024/1024:.1f} MB")

        current = STAGES[1]
        states[current] = "running"
        yield snap("Membaca metadata dan mengekstrak audio...")
        meta = probe_video(video)
        if not meta["has_audio"]:
            raise RuntimeError("Video tidak punya audio.")
        audio = extract_audio(video, job)
        (job / "metadata.json").write_text(json.dumps(meta, indent=2))
        states[current] = "done"
        yield snap(f"{meta['width']}×{meta['height']}, {meta['duration']:.1f}s")

        current = STAGES[2]
        states[current] = "running"
        yield snap(f"Menjalankan {whisper_mode}...")
        transcript, engine = transcribe(audio, meta["duration"], whisper_mode)
        (job / "transcript.json").write_text(
            json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        transcript_text = transcript["text"][:20000]
        states[current] = "done"
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
            yield snap("OCR membaca teks frame...")
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
        (job / "ocr.json").write_text(json.dumps({"items": ocr}, ensure_ascii=False, indent=2))
        yield snap(note)

        current = STAGES[6]
        states[current] = "running"
        yield snap("Membuat kandidat dan menilai dengan Groq Llama...")
        cands = candidates_of(transcript, scenes, energy, ocr, meta["duration"], int(clip_duration))
        try:
            selected, score_engine = groq_rank(cands, int(clip_count))
            states[current] = "done"
        except Exception as exc:
            selected = non_overlap(cands, int(clip_count))
            score_engine = f"heuristic fallback ({exc})"
            states[current] = "warning"
        clips_path, clips = write_clips(selected, job)
        clips_view = clips
        yield snap(f"{len(clips['clips'])} clip dipilih: {score_engine}")

        current = STAGES[7]
        states[current] = "running"
        yield snap("MediaPipe melacak wajah...")
        (
            crop_path,
            mediapipe_ok,
            smart_crop_ok,
            face_note,
        ) = mediapipe_crop(video, clips_path, job)
        states[current] = "done" if mediapipe_ok else "warning"
        yield snap(face_note)

        current = STAGES[8]
        states[current] = "done" if smart_crop_ok else "warning"
        if smart_crop_ok:
            yield snap(face_note)
        else:
            yield snap(f"{face_note} | Render memakai center crop.")

        current = STAGES[9]
        states[current] = "running"
        yield snap("Membuat subtitle ASS...")
        capdir = captions_of(transcript, clips, job)
        states[current] = "done"
        yield snap("Subtitle selesai.")

        current = STAGES[10]
        states[current] = "running"
        yield snap("FFmpeg merender video 720×1280...")
        rendered = render_all(video, meta, clips, crop_path, capdir, job)
        files = [str(x) for x in rendered]
        states[current] = "done"
        yield snap(f"{len(rendered)} clip selesai.")

        current = STAGES[11]
        states[current] = "running"
        yield snap("Membuat ZIP debug...")
        debug = [
            job / "metadata.json", job / "transcript.json", job / "scenes.json",
            job / "audio_energy.json", job / "ocr.json", job / "clips.json",
            job / "face_data.json", job / "crop_data.json",
            job / "mediapipe_stdout.txt", job / "mediapipe_error.txt",
            job / "smart_crop_stdout.txt", job / "smart_crop_error.txt",
        ]
        archive = make_zip(job, rendered + debug)
        files.append(str(archive))
        states[current] = "done"
        yield snap("🎉 Semua tahap selesai.")

    except Exception as exc:
        states[current] = "error"
        yield snap(f"ERROR pada tahap **{current}**: {exc}")


with gr.Blocks(title="Clipping Lite Full Pipeline") as demo:
    gr.Markdown(
        """
        # 🎬 Clipping Lite — Full Pipeline

        **Drive/Upload → FFmpeg → Whisper → PySceneDetect → Audio →
        OCR → Groq Llama → MediaPipe → Smart Crop → Subtitle → Render**
        """
    )

    with gr.Row():
        with gr.Column():
            upload = gr.Video(label="Upload video — opsional")
            drive = gr.Textbox(
                label="Link Google Drive publik",
                placeholder="https://drive.google.com/file/d/FILE_ID/view?usp=sharing",
                lines=2,
            )
            whisper = gr.Dropdown(
                ["Groq Whisper (disarankan)", "Local Whisper tiny", "Local Whisper base"],
                value="Groq Whisper (disarankan)",
                label="Mesin transkripsi",
            )
            with gr.Row():
                count = gr.Slider(1, 5, value=3, step=1, label="Jumlah clip")
                duration = gr.Slider(20, 60, value=30, step=5, label="Durasi target")
            ocr_box = gr.Checkbox(False, label="Aktifkan OCR (lebih lambat)")
            button = gr.Button("🚀 Proses Full Otomatis", variant="primary")

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


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=1, max_size=4)
    demo.launch(server_name="0.0.0.0", server_port=7860)
