import json
import os
import subprocess
import tempfile
import uuid
from urllib.parse import urlparse

import gdown
import gradio as gr


ALLOWED_DRIVE_HOSTS = {
    "drive.google.com",
}


def normalize_video_path(value):
    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        for key in ("path", "video", "name"):
            path = value.get(key)
            if isinstance(path, str):
                return path

    path = getattr(value, "path", None)
    if isinstance(path, str):
        return path

    return None


def prepare_video(uploaded_video, drive_url):
    uploaded_path = normalize_video_path(uploaded_video)

    if uploaded_path:
        return uploaded_path, "✅ Video upload sudah siap diproses."

    drive_url = (drive_url or "").strip()

    if not drive_url:
        raise gr.Error(
            "Upload video atau masukkan link Google Drive dulu, Wee 🗿"
        )

    parsed = urlparse(drive_url)
    hostname = (parsed.hostname or "").lower()

    if parsed.scheme not in {"http", "https"}:
        raise gr.Error("Link harus menggunakan http atau https.")

    if hostname not in ALLOWED_DRIVE_HOSTS:
        raise gr.Error(
            "Untuk sementara hanya menerima link Google Drive."
        )

    download_dir = os.path.join(
        tempfile.gettempdir(),
        "clipping-lite-downloads",
    )
    os.makedirs(download_dir, exist_ok=True)

    output_path = os.path.join(
        download_dir,
        f"source_{uuid.uuid4().hex}.mp4",
    )

    try:
        downloaded_path = gdown.download(
            url=drive_url,
            output=output_path,
            quiet=False,
        )
    except Exception as exc:
        raise gr.Error(
            f"Gagal mengambil video dari Google Drive: {exc}"
        ) from exc

    final_path = downloaded_path or output_path

    if not os.path.isfile(final_path):
        raise gr.Error(
            "Download gagal. Pastikan akses Drive diatur "
            "Anyone with the link."
        )

    file_size = os.path.getsize(final_path)

    if file_size <= 0:
        raise gr.Error("File hasil download kosong.")

    size_mb = file_size / (1024 * 1024)

    return (
        final_path,
        f"✅ Video berhasil diambil — ukuran {size_mb:.1f} MB.",
    )


def run_command(command):
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        message = result.stderr.strip() or "Command gagal."
        raise RuntimeError(message)

    return result.stdout


def parse_fps(value):
    try:
        numerator, denominator = value.split("/")
        denominator_value = float(denominator)

        if denominator_value == 0:
            return 0.0

        return float(numerator) / denominator_value
    except (ValueError, AttributeError, ZeroDivisionError):
        return 0.0


def analyze_video(video_value):
    video_path = normalize_video_path(video_value)

    if not video_path or not os.path.isfile(video_path):
        raise gr.Error("Ambil atau upload video terlebih dahulu.")

    probe_command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        (
            "format=duration,size,bit_rate:"
            "stream=index,codec_type,codec_name,"
            "width,height,r_frame_rate,sample_rate,channels"
        ),
        "-of",
        "json",
        video_path,
    ]

    try:
        raw_probe = run_command(probe_command)
        probe_data = json.loads(raw_probe)
    except Exception as exc:
        raise gr.Error(
            f"FFprobe gagal membaca video: {exc}"
        ) from exc

    streams = probe_data.get("streams", [])
    format_data = probe_data.get("format", {})

    video_stream = next(
        (
            stream
            for stream in streams
            if stream.get("codec_type") == "video"
        ),
        None,
    )

    audio_stream = next(
        (
            stream
            for stream in streams
            if stream.get("codec_type") == "audio"
        ),
        None,
    )

    if video_stream is None:
        raise gr.Error("File tidak memiliki stream video.")

    duration = float(format_data.get("duration") or 0)
    size_bytes = int(format_data.get("size") or 0)
    bitrate = int(format_data.get("bit_rate") or 0)

    width = video_stream.get("width", 0)
    height = video_stream.get("height", 0)
    video_codec = video_stream.get("codec_name", "unknown")
    fps = parse_fps(video_stream.get("r_frame_rate", "0/1"))

    metadata_lines = [
        f"Durasi: {duration:.1f} detik",
        f"Resolusi: {width} × {height}",
        f"FPS: {fps:.2f}",
        f"Codec video: {video_codec}",
        f"Ukuran: {size_bytes / (1024 * 1024):.1f} MB",
        f"Bitrate: {bitrate / 1000:.0f} kbps",
    ]

    audio_path = None

    if audio_stream:
        audio_codec = audio_stream.get("codec_name", "unknown")
        sample_rate = audio_stream.get("sample_rate", "unknown")
        channels = audio_stream.get("channels", "unknown")

        metadata_lines.extend(
            [
                f"Codec audio: {audio_codec}",
                f"Sample rate: {sample_rate} Hz",
                f"Channel: {channels}",
            ]
        )

        audio_dir = os.path.join(
            tempfile.gettempdir(),
            "clipping-lite-audio",
        )
        os.makedirs(audio_dir, exist_ok=True)

        audio_path = os.path.join(
            audio_dir,
            f"audio_{uuid.uuid4().hex}.wav",
        )

        ffmpeg_command = [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            audio_path,
        ]

        try:
            run_command(ffmpeg_command)
        except Exception as exc:
            raise gr.Error(
                f"FFmpeg gagal mengekstrak audio: {exc}"
            ) from exc
    else:
        metadata_lines.append("Audio: tidak ditemukan")

    metadata = "\n".join(metadata_lines)

    return (
        metadata,
        audio_path,
        "✅ FFmpeg berhasil membaca video dan menyiapkan audio.",
    )


with gr.Blocks(title="Clipping Lite") as demo:
    gr.Markdown(
        """
        # 🎬 Clipping Lite

        Masukkan video melalui **upload manual**
        atau **link Google Drive publik**.
        """
    )

    with gr.Row():
        with gr.Column():
            upload_video = gr.Video(
                label="Upload video — opsional",
            )

            drive_url = gr.Textbox(
                label="Link Google Drive",
                placeholder=(
                    "https://drive.google.com/file/d/"
                    "FILE_ID/view?usp=sharing"
                ),
            )

            prepare_button = gr.Button(
                "Ambil Video",
                variant="primary",
            )

        with gr.Column():
            preview_video = gr.Video(
                label="Preview video sumber",
            )

            source_status = gr.Textbox(
                label="Status sumber",
                interactive=False,
            )

    gr.Markdown("## Analisis FFmpeg")

    analyze_button = gr.Button(
        "Analisis Video",
        variant="secondary",
    )

    with gr.Row():
        metadata_output = gr.Textbox(
            label="Informasi video",
            lines=10,
            interactive=False,
        )

        audio_output = gr.Audio(
            label="Audio 16 kHz untuk Whisper",
        )

    analysis_status = gr.Textbox(
        label="Status analisis",
        interactive=False,
    )

    prepare_button.click(
        fn=prepare_video,
        inputs=[
            upload_video,
            drive_url,
        ],
        outputs=[
            preview_video,
            source_status,
        ],
    )

    analyze_button.click(
        fn=analyze_video,
        inputs=[
            preview_video,
        ],
        outputs=[
            metadata_output,
            audio_output,
            analysis_status,
        ],
    )


if __name__ == "__main__":
    demo.queue()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
    )
