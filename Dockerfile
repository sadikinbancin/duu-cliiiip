FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/tmp/hf-cache

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ffmpeg \
       tesseract-ocr \
       tesseract-ocr-eng \
       libglib2.0-0 \
       libgl1 \
       fonts-dejavu-core \
       ca-certificates \
       curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN mkdir -p /app/models \
    && curl -L --fail --retry 3 \
       "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task" \
       -o /app/models/face_landmarker.task \
    && test -s /app/models/face_landmarker.task

ENV MEDIAPIPE_MODEL_PATH=/app/models/face_landmarker.task


COPY requirements.txt .
RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

COPY . .

EXPOSE 7860

CMD ["python", "app.py"]
