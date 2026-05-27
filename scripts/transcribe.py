#!/usr/bin/env python3
"""Transcribe video with faster-whisper, output word-level JSON.

Usage:
    python3 transcribe.py INPUT_VIDEO --output transcript.json
    python3 transcribe.py INPUT_VIDEO --output transcript.json --model base
    python3 transcribe.py INPUT_VIDEO --output transcript.json --model small

Output JSON:
{
    "language": "en",
    "duration": 3600.0,
    "word_count": 12000,
    "segments": [
        {
            "start": 0.0, "end": 4.5,
            "text": "Hello and welcome to the show",
            "words": [
                {"word": "Hello", "start": 0.0, "end": 0.3},
                {"word": "and", "start": 0.35, "end": 0.5},
                ...
            ]
        }
    ]
}
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time


def extract_audio(video_path, audio_path):
    """Extract audio from video as 16kHz mono WAV."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        audio_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Audio extraction failed: {result.stderr[-500:]}")


def transcribe_audio(audio_path, model_name="base", device="cpu", compute_type="int8",
                     language="en", vad=True):
    """Transcribe audio with faster-whisper, return segments with word timestamps."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("ERROR: faster-whisper not installed. Run: pip install faster-whisper")
        sys.exit(1)

    print(f"Loading model '{model_name}' on {device} ({compute_type})...")
    model = WhisperModel(model_name, device=device, compute_type=compute_type)

    print(f"Transcribing {audio_path}...")
    start = time.time()
    segments, info = model.transcribe(
        audio_path,
        language=language,
        word_timestamps=True,
        vad_filter=vad,
    )

    results = []
    all_words = []
    word_count = 0

    for seg in segments:
        words = []
        if seg.words:
            for w in seg.words:
                words.append({
                    "word": w.word.strip(),
                    "start": round(w.start, 3),
                    "end": round(w.end, 3),
                })
                word_count += 1
        results.append({
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg.text.strip(),
            "words": words,
        })
        all_words.extend(words)

    elapsed = time.time() - start
    print(f"Transcribed {word_count} words in {elapsed:.1f}s "
          f"(model={model_name}, device={device})")

    return {
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration,
        "word_count": word_count,
        "transcription_time_sec": round(elapsed, 1),
        "model": model_name,
        "device": device,
        "segments": results,
        "words": all_words,
    }


def split_audio(audio_path, chunk_seconds=600):
    """Split audio into chunks for batch transcription of long files."""
    prefix = audio_path.replace(".wav", "_chunk")
    cmd = [
        "ffmpeg", "-y", "-i", audio_path,
        "-f", "segment", "-segment_time", str(chunk_seconds),
        "-c", "copy", f"{prefix}_%02d.wav"
    ]
    subprocess.run(cmd, capture_output=True)

    chunks = []
    i = 0
    while True:
        chunk_path = f"{prefix}_{i:02d}.wav"
        if not os.path.exists(chunk_path):
            break
        chunks.append(chunk_path)
        i += 1
    return chunks


def main():
    parser = argparse.ArgumentParser(description="Transcribe video with faster-whisper")
    parser.add_argument("input", help="Input video or audio file")
    parser.add_argument("--output", required=True, help="Output JSON file")
    parser.add_argument("--model", default="base",
                        choices=["tiny", "base", "small", "medium", "large-v3"],
                        help="Whisper model (default: base)")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"],
                        help="Device (default: cpu)")
    parser.add_argument("--compute-type", default="int8",
                        help="Compute type for CPU (default: int8)")
    parser.add_argument("--language", default="en", help="Language code (default: en)")
    parser.add_argument("--no-vad", action="store_true", help="Disable VAD filter")
    parser.add_argument("--chunk", type=int, default=0,
                        help="Split audio into N-second chunks (for long files)")

    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"ERROR: Input file not found: {args.input}")
        sys.exit(1)

    # Extract audio
    tmpdir = tempfile.mkdtemp(prefix="transcribe_")
    audio_path = os.path.join(tmpdir, "audio.wav")
    print(f"Extracting audio from {args.input}...")
    extract_audio(args.input, audio_path)

    vad = not args.no_vad

    if args.chunk > 0:
        # Long file: split and transcribe in chunks
        print(f"Splitting audio into {args.chunk}s chunks...")
        chunks = split_audio(audio_path, args.chunk)
        print(f"Found {len(chunks)} chunks")

        all_results = {
            "language": "en",
            "word_count": 0,
            "transcription_time_sec": 0,
            "model": args.model,
            "device": args.device,
            "segments": [],
            "words": [],
        }

        for i, chunk_path in enumerate(chunks):
            print(f"\n--- Chunk {i+1}/{len(chunks)} ---")
            offset = i * args.chunk
            result = transcribe_audio(
                chunk_path, args.model, args.device, args.compute_type,
                args.language, vad
            )
            # Adjust timestamps
            for seg in result["segments"]:
                seg["start"] += offset
                seg["end"] += offset
                for w in seg["words"]:
                    w["start"] += offset
                    w["end"] += offset
            for w in result["words"]:
                w["start"] += offset
                w["end"] += offset

            all_results["segments"].extend(result["segments"])
            all_results["words"].extend(result["words"])
            all_results["word_count"] += result["word_count"]
            all_results["transcription_time_sec"] += result["transcription_time_sec"]
            all_results["duration"] = all_results.get("duration", 0) + result["duration"]

            # Clean up chunk
            os.remove(chunk_path)

        result = all_results
    else:
        result = transcribe_audio(
            audio_path, args.model, args.device, args.compute_type,
            args.language, vad
        )

    # Write output
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\nTranscript written to {args.output}")
    print(f"  Words: {result['word_count']}")
    print(f"  Duration: {result['duration']:.1f}s")
    print(f"  Time: {result['transcription_time_sec']:.1f}s")

    # Clean up
    os.remove(audio_path)
    os.rmdir(tmpdir)


if __name__ == "__main__":
    main()
