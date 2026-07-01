# Clipping Lite — Stage 4 Queue / Batch

## Fitur baru

- Tempel banyak link Google Drive, satu link per baris.
- Diproses berurutan agar Hugging Face CPU Basic tetap stabil.
- Status dan tahap aktif terlihat untuk setiap link.
- Setiap video menghasilkan ZIP sendiri.
- Video yang gagal menghasilkan file log error sendiri.
- Setelah antrean selesai dibuat `batch_summary.json`, `batch_summary.csv`, dan `batch_all_results.zip`.
- Mode satu video dari Stage 3 tetap tersedia.

## File yang diganti di GitHub

Ganti file berikut dengan file dari paket ini:

- `app.py`
- `Dockerfile`
- `requirements.txt`
- `scripts/face_track.py`
- `scripts/smart_crop.py`

`README_STAGE4_QUEUE.md` boleh ditambahkan sebagai dokumentasi.

Jangan unggah folder `__pycache__` atau file `*.pyc`.

## Cara pakai

1. Buka tab **Batch Link Drive**.
2. Tempel link Drive publik, satu link per baris.
3. Pilih jumlah clip, durasi, Whisper, dan OCR.
4. Tekan **Jalankan Antrian Batch**.
5. Biarkan tab browser terbuka sampai antrean selesai.

## Batas awal

Default maksimal 20 link per batch. Bisa diubah melalui variable Hugging Face:

```text
MAX_BATCH_LINKS=20
```

Untuk pengujian pertama, gunakan 2–3 link dahulu.
