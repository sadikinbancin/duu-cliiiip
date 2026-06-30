# MediaPipe + Smart Crop Fix

Paket ini adalah pengganti penuh untuk file utama Clipping Lite.

## File yang diganti

Ganti file di root GitHub dengan file dari ZIP ini:

- `app.py`
- `Dockerfile`
- `requirements.txt`

Jangan hapus folder `scripts/`, karena `app.py` memakai:

- `scripts/face_track.py`
- `scripts/smart_crop.py`

## Perubahan utama

1. Model MediaPipe diunduh saat Docker build, bukan saat job berjalan.
2. MediaPipe dan Smart Crop punya status terpisah.
3. Error disimpan dalam ZIP hasil:
   - `mediapipe_error.txt`
   - `smart_crop_error.txt`
4. Log sukses juga disimpan:
   - `mediapipe_stdout.txt`
   - `smart_crop_stdout.txt`
5. MediaPipe tetap tidak membutuhkan API key.

## Setelah commit

Tunggu GitHub Actions dan Hugging Face selesai build. Jalankan satu video lagi.

Interpretasi status:

- `✅ MediaPipe` = wajah berhasil ditemukan.
- `🟡 MediaPipe` = proses berjalan tetapi tidak menemukan wajah, atau terjadi error.
- `✅ Smart crop` = `crop_data.json` berhasil dibuat.
- `🟡 Smart crop` = render memakai center crop.

Kalau masih kuning, unduh ZIP hasil dan lihat file error terkait.
