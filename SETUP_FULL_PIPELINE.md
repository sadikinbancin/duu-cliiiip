# Tambahan setup Full Pipeline

Setelah mengganti `app.py`, `requirements.txt`, dan `Dockerfile`, buka:

**Hugging Face Space → Settings → Variables and secrets → New secret**

Tambahkan:

- `GROQ_API_KEY` = API key dari Groq
- Opsional `GROQ_WHISPER_MODEL` = `whisper-large-v3-turbo`
- Opsional `GROQ_LLM_MODEL` = `meta-llama/llama-4-scout-17b-16e-instruct`

Tanpa `GROQ_API_KEY`, pipeline masih mencoba Local Whisper tiny dan heuristic scoring.

Roadmap status:
1. Input video
2. FFmpeg/ffprobe
3. Whisper
4. PySceneDetect
5. Audio dynamics
6. OCR
7. Groq Llama viral scoring
8. MediaPipe
9. Smart crop
10. Subtitle
11. Render
12. Paket hasil
