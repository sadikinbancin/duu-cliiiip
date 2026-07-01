# Clipping Lite Stage 3 — Gemini Vision

Tahap ini menambah Gemini Vision sebelum Groq Llama scoring.

Secret yang dibaca:

- `GROQ_API_KEY`
- `GROQ_WHISPER_MODEL`
- `GROQ_LLM_MODEL`
- `GOOGLE_API_KEY`
- Opsional: `GEMINI_VISION_MODEL`, default `gemini-2.5-flash`

Pipeline:

1. Google Drive / upload
2. Normalisasi video AV1/H.265 ke H.264
3. Groq Whisper
4. Scene/audio/OCR
5. Gemini Vision melihat 3 frame per kandidat clip
6. Groq Llama memilih clip dengan bantuan sinyal visual
7. MediaPipe face tracking
8. Animated Smart Crop
9. Subtitle
10. Render + ZIP hasil

Debug ZIP berisi:

- `gemini_vision_request.json`
- `gemini_vision_response.txt`
- `gemini_vision_error.txt`
- `gemini_vision.json`
- folder frame kandidat Gemini sebagai JPG
