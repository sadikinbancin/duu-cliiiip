import os
import tempfile
import uuid
from urllib.parse import urlparse

import gdown
import gradio as gr


ALLOWED_DRIVE_HOSTS = {
    "drive.google.com",
}


def prepare_video(uploaded_video, drive_url):
    """
    Mengambil video dari salah satu sumber:
    1. Upload manual
    2. Link Google Drive publik

    Mengembalikan path lokal yang nantinya bisa diteruskan
    ke FFmpeg, Whisper, MediaPipe, dan engine scoring.
    """

    # Upload manual diprioritaskan jika keduanya diisi.
    if uploaded_video:
        return uploaded_video, "✅ Video upload sudah siap diproses."

    drive_url = (drive_url or "").strip()

    if not drive_url:
        raise gr.Error("Upload video atau masukkan link Google Drive dulu, Wee 🗿")

    parsed = urlparse(drive_url)
    hostname = (parsed.hostname or "").lower()

    if parsed.scheme not in {"http", "https"}:
        raise gr.Error("Link harus menggunakan http atau https.")

    if hostname not in ALLOWED_DRIVE_HOSTS:
        raise gr.Error(
            "Untuk sementara hanya menerima link Google Drive: "
            "https://drive.google.com/..."
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
            fuzzy=True,
        )
    except Exception as exc:
        raise gr.Error(
            f"Gagal mengambil video dari Google Drive: {exc}"
        ) from exc

    final_path = downloaded_path or output_path

    if not os.path.isfile(final_path):
        raise gr.Error(
            "Download gagal. Pastikan file Google Drive bisa dibuka "
            "oleh siapa saja yang memiliki link."
        )

    file_size = os.path.getsize(final_path)

    if file_size <= 0:
        raise gr.Error("File hasil download kosong.")

    size_mb = file_size / (1024 * 1024)

    return (
        final_path,
        f"✅ Video Drive berhasil diambil — ukuran {size_mb:.1f} MB.",
    )


with gr.Blocks(title="Clipping Lite") as demo:
    gr.Markdown(
        """
        # 🎬 Clipping Lite

        Masukkan video melalui **upload manual** atau **link Google Drive publik**.
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
                    "https://drive.google.com/file/d/FILE_ID/view?usp=sharing"
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

            status = gr.Textbox(
                label="Status",
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
            status,
        ],
    )


if __name__ == "__main__":
    demo.queue()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
    )
