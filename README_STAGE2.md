# Clipping Lite — Stage 2

Paket ini mengaktifkan:

1. `GROQ_API_KEY` untuk Groq Whisper dan Groq Llama scoring.
2. `GROQ_WHISPER_MODEL` untuk memilih model transkripsi.
3. `GROQ_LLM_MODEL` untuk memilih model scoring viral.
4. MediaPipe FaceLandmarker lokal di CPU.
5. Animated smart crop yang mengikuti posisi wajah selama clip.
6. Fallback center crop jika tracking/render animated gagal.
7. Log debug lengkap di ZIP hasil.

`GOOGLE_API_KEY` dibaca dan ditampilkan sebagai tersedia, tetapi belum dipanggil pada Stage 2. Key itu disiapkan untuk Stage 3 Gemini Vision supaya tidak membuang kuota pada proses yang sudah bisa dilakukan lokal oleh MediaPipe.

## File yang diganti

Upload/ganti file berikut di root repo:

- `app.py`
- `Dockerfile`
- `requirements.txt`

Lalu ganti file di folder `scripts/`:

- `scripts/face_track.py`
- `scripts/smart_crop.py`

Jangan menghapus file lain di folder `scripts/`.

## Hugging Face Secrets

Gunakan nama berikut persis:

```text
GROQ_API_KEY
GROQ_WHISPER_MODEL
GROQ_LLM_MODEL
GOOGLE_API_KEY
```

Nilai yang cocok:

```text
GROQ_WHISPER_MODEL=whisper-large-v3-turbo
GROQ_LLM_MODEL=llama-3.3-70b-versatile
```

## Cara mengecek bahwa Secret benar-benar dipakai

Di UI baru akan muncul bagian **Konfigurasi runtime**. Saat pipeline berjalan:

- Tahap Whisper menulis model Groq yang dipakai.
- Tahap Groq Llama menulis model scoring yang dipakai.
- `runtime_config.json` masuk ke ZIP hasil.
- Respons model masuk ke `groq_scoring_response.txt`.

## Makna status render

- `animated crop` berarti wajah benar-benar diikuti melalui command keyframe FFmpeg.
- `center-crop fallback` berarti animated crop gagal atau wajah tidak ditemukan; video tetap dirender dan file error dimasukkan ke ZIP.

## Build pertama

Build pertama bisa lebih lama karena memasang MediaPipe, OpenCV, Faster-Whisper, dan mengunduh model FaceLandmarker. Setelah status Space kembali `Running`, tes video pendek 2–4 menit dahulu.
