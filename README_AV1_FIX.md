# Stage 2.1 — AV1 corruption fix

Perbaikan ini menangani blok hijau/abu-abu dan frame rusak dari sumber AV1.

## Penyebab

Pipeline lama melakukan random seek langsung pada video AV1. Beberapa file AV1
baru memberikan sequence header di awal GOP, sehingga decoder dapat menghasilkan
`Missing Sequence Header` dan frame korup saat seek.

## Perubahan

- Video non-H.264 dinormalisasi sekali ke H.264 + yuv420p sebelum Whisper,
  SceneDetect, MediaPipe, Smart Crop, dan render.
- Untuk AV1, pipeline mencoba decoder `libdav1d`, kemudian fallback decoder
  FFmpeg bawaan.
- Frame korup dibuang selama normalisasi.
- Keyframe H.264 dibuat setiap 2 detik agar random seek MediaPipe stabil.
- Render dinaikkan dari `ultrafast / CRF 28` menjadi `veryfast / CRF 21`.
- ZIP hasil menambahkan `source_metadata.json` dan `normalization.log`.

## File yang diganti

- `app.py`

File berikut ikut disertakan agar paket lengkap, tetapi tidak berubah secara
substansial dari Stage 2:

- `Dockerfile`
- `requirements.txt`
- `scripts/face_track.py`
- `scripts/smart_crop.py`

## Secret

Secret Groq dan Google yang sudah dipasang tidak perlu diubah.
