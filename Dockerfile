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
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

COPY . .

EXPOSE 7860

CMD ["python", "app.py"]
