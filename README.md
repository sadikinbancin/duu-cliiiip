---
title: Clipping Lite
emoji: 🎬
colorFrom: purple
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# Clipping Lite

AI-assisted podcast and long-form video clipper for Hugging Face Spaces.

## Runtime

The Docker container starts the Gradio application on:

```text
0.0.0.0:7860
```

Hugging Face is explicitly configured with `app_port: 7860` in the Space metadata above.

## Main pipeline

```text
Upload or Google Drive video
→ FFmpeg validation and codec normalization
→ Whisper transcription
→ scene, audio, OCR, and visual analysis
→ Gemini Vision and Groq/Llama scoring
→ optional Campaign Requirements matching
→ MediaPipe smart crop
→ subtitles
→ vertical render
→ downloadable clips and reports
```

## Campaign mode

Paste campaign requirements into the optional campaign field. Leave it empty to use the normal viral-selection mode.

Campaign results can include:

- `campaign_match_score`
- `campaign_fit_reason`
- `matched_requirements`
- `violated_requirements`
- `posting_notes`

## Required Space secrets

Configure these in **Settings → Variables and secrets** when the related provider is used:

```text
GROQ_API_KEY
GOOGLE_API_KEY
```

Optional model overrides:

```text
GROQ_WHISPER_MODEL=whisper-large-v3-turbo
GROQ_LLM_MODEL=llama-3.3-70b-versatile
GEMINI_VISION_MODEL=gemini-2.5-flash
```

## Local Docker

```bash
docker build -t clipping-lite .
docker run --rm -p 7860:7860 clipping-lite
```

Then open `http://localhost:7860`.

## Notes

- Process one video at a time on Hugging Face CPU Basic.
- Google Drive links must be public: **Anyone with the link → Viewer**.
- AV1 and other fragile codecs are normalized to H.264 before seeking and cropping.
- Keep API keys in Hugging Face Secrets, never inside repository files.

## License

MIT. Dependencies retain their respective licenses.
