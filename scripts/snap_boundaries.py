#!/usr/bin/env python3
"""Snap segment boundaries to natural audio cut points.

Adjusts proposed segment start/end times to:
1. Align with word boundaries (never cut mid-word)
2. Prefer sentence starts (after . ? !) if within window
3. Extend to sentence completion if close
4. Add configurable padding after the last word

Usage:
    python3 snap_boundaries.py --segments clips.json --transcript transcript.json --output snapped.json
    python3 snap_boundaries.py --segments clips.json --transcript transcript.json --output snapped.json --pad 0.3
"""
import argparse
import json
import os
import subprocess
import sys


def load_words(transcript_path):
    """Load word-level timestamps from transcript JSON."""
    with open(transcript_path) as f:
        data = json.load(f)

    words = data.get("words", [])
    if not words:
        # Try extracting from segments
        for seg in data.get("segments", []):
            for w in seg.get("words", []):
                words.append(w)
    return words


def detect_silences(video_path, min_duration=0.3, noise_threshold=-35):
    """Find silence regions using FFmpeg silencedetect."""
    cmd = [
        "ffmpeg", "-i", video_path,
        "-af", f"silencedetect=noise={noise_threshold}dB:d={min_duration}",
        "-f", "null", "-"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    stderr = result.stderr

    silences = []
    current_start = None
    for line in stderr.split("\n"):
        if "silence_start:" in line:
            try:
                current_start = float(line.split("silence_start:")[1].strip().split()[0])
            except (IndexError, ValueError):
                pass
        elif "silence_end:" in line and current_start is not None:
            try:
                parts = line.split("silence_end:")[1].strip().split()
                end = float(parts[0])
                silences.append({"start": current_start, "end": end})
                current_start = None
            except (IndexError, ValueError):
                pass
    return silences


def snap_start(words, proposed_start, search_window=1.5):
    """Snap start to nearest word boundary, preferring sentence starts."""
    candidates = [(i, w) for i, w in enumerate(words)
                  if abs(w["start"] - proposed_start) <= search_window]
    if not candidates:
        return proposed_start

    # Prefer sentence starts
    sentence_starts = []
    for idx, w in candidates:
        if idx == 0:
            sentence_starts.append((idx, w))
        elif words[idx - 1]["word"].rstrip()[-1:] in ".?!":
            sentence_starts.append((idx, w))

    if sentence_starts:
        _, best = min(sentence_starts, key=lambda x: abs(x[1]["start"] - proposed_start))
        return best["start"]

    _, best = min(candidates, key=lambda x: abs(x[1]["start"] - proposed_start))
    return best["start"]


def snap_end(words, proposed_end, search_window=3.0, pad=0.3):
    """Snap end to after the last complete sentence."""
    # Find last word ending at or before proposed_end
    last_idx = None
    for i, w in enumerate(words):
        if w["end"] <= proposed_end + 0.2:
            last_idx = i

    if last_idx is None:
        return proposed_end + pad

    # If last word ends a sentence, use it
    if words[last_idx]["word"].rstrip()[-1:] in ".?!":
        return words[last_idx]["end"] + pad

    # Look forward for sentence boundary
    for i in range(last_idx + 1, len(words)):
        if words[i]["start"] > proposed_end + search_window:
            break
        if words[i]["word"].rstrip()[-1:] in ".?!":
            return words[i]["end"] + pad

    # Fall back to nearest word end
    return words[last_idx]["end"] + pad


def main():
    parser = argparse.ArgumentParser(description="Snap segment boundaries to audio")
    parser.add_argument("--segments", required=True, help="Clips JSON file")
    parser.add_argument("--transcript", required=True, help="Transcript JSON file")
    parser.add_argument("--input-video", help="Source video (for silence detection)")
    parser.add_argument("--output", required=True, help="Output snapped segments JSON")
    parser.add_argument("--pad", type=float, default=0.3,
                        help="Padding in seconds after last word (default: 0.3)")
    parser.add_argument("--no-silence", action="store_true",
                        help="Skip silence detection")
    parser.add_argument("--min-dur", type=float, default=15.0,
                        help="Minimum clip duration in seconds (default: 15)")
    parser.add_argument("--max-dur", type=float, default=60.0,
                        help="Maximum clip duration in seconds (default: 60)")

    args = parser.parse_args()

    words = load_words(args.transcript)
    if not words:
        print("ERROR: No word-level timestamps found in transcript")
        sys.exit(1)

    with open(args.segments) as f:
        segments_data = json.load(f)

    silences = []
    if args.input_video and not args.no_silence:
        print("Detecting silences...")
        silences = detect_silences(args.input_video)
        print(f"  Found {len(silences)} silence regions")

    clips = segments_data.get("clips", [])
    adjustments = []

    for clip in clips:
        old_start = clip["start"]
        old_end = clip["end"]

        new_start = snap_start(words, old_start)
        new_end = snap_end(words, old_end, pad=args.pad)

        # Clamp duration
        if new_end - new_start < args.min_dur:
            new_end = new_start + args.min_dur
        if new_end - new_start > args.max_dur:
            new_end = new_start + args.max_dur

        clip["start"] = round(new_start, 3)
        clip["end"] = round(new_end, 3)
        clip["duration"] = round(new_end - new_start, 3)

        adjustments.append({
            "id": clip.get("id", "?"),
            "old": f"{old_start:.1f}-{old_end:.1f}",
            "new": f"{new_start:.3f}-{new_end:.3f}",
            "delta_start": f"{(new_start - old_start)*1000:+.0f}ms",
            "delta_end": f"{(new_end - old_end)*1000:+.0f}ms",
        })

    # Write output
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(segments_data, f, indent=2)

    # Print summary
    print(f"\nSnapped {len(adjustments)} segments:")
    for adj in adjustments:
        print(f"  Clip {adj['id']}: {adj['old']} -> {adj['new']} "
              f"(start {adj['delta_start']}, end {adj['delta_end']})")


if __name__ == "__main__":
    main()
