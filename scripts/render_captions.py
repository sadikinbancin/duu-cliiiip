#!/usr/bin/env python3
"""
Render caption overlays using Remotion.

Reads clips.json and transcript.json, generates per-clip caption data JSON files,
then invokes a Node.js helper that uses @remotion/renderer to output transparent
WebM caption overlays.

Usage:
    python3 render_captions.py --clips clips.json --transcript transcript.json \\
        --output-dir captions_remotion/ --style bold

Prerequisites:
    cd captions_remotion && npm install
    # Puppeteer (Chromium) will be auto-downloaded on first render run
"""

import argparse
import json
import math
import os
import subprocess
import sys
import time


# Default style configs (matching STYLES in Root.tsx)
STYLES = {
    "default": {
        "clean": {
            "fontFamily": "Arial, sans-serif",
            "fontSize": 52,
            "color": "#FFFFFF",
            "outlineColor": "#000000",
            "outlineWidth": 3.5,
            "shadowColor": "rgba(0,0,0,0.5)",
            "shadowBlur": 1.5,
            "alignment": "center",
            "position": "bottom",
            "marginV": 500,
            "marginL": 135,
            "marginR": 135,
        },
        "bold": {
            "fontFamily": "Arial Black, Arial, sans-serif",
            "fontSize": 60,
            "color": "#FFFFFF",
            "activeColor": "#FFD700",
            "outlineColor": "#000000",
            "outlineWidth": 4,
            "alignment": "center",
            "position": "bottom",
            "marginV": 480,
            "marginL": 100,
            "marginR": 100,
            "uppercase": True,
        },
        "bounce": {
            "fontFamily": "Impact, sans-serif",
            "fontSize": 72,
            "color": "#FFFFFF",
            "outlineColor": "#000000",
            "outlineWidth": 5,
            "alignment": "center",
            "position": "bottom",
            "marginV": 450,
            "marginL": 80,
            "marginR": 80,
        },
    },
}

DEFAULT_STYLES = STYLES["default"]

FILLER_WORDS = {"um", "uh", "you know", "like", "i mean", "sort of", "kind of"}


def clean_word(word):
    w = word.lower().strip().rstrip(".,!?;:")
    if w in FILLER_WORDS:
        return None
    return word.strip()


def words_to_events(words, max_words=6):
    """Convert word-level timestamps into caption events."""
    events = []
    batch = []
    for w in words:
        cleaned = clean_word(w.get("word", ""))
        if cleaned is None:
            continue
        batch.append({"word": cleaned, "start": w["start"], "end": w["end"]})
        if len(batch) >= max_words:
            events.append({
                "words": batch[:],
                "start": batch[0]["start"],
                "end": batch[-1]["end"],
                "text": " ".join(bw["word"] for bw in batch),
            })
            batch = []
    if batch:
        events.append({
            "words": batch[:],
            "start": batch[0]["start"],
            "end": batch[-1]["end"],
            "text": " ".join(bw["word"] for bw in batch),
        })
    return events


def clip_events(clip, all_events):
    """Filter events to those within clip time range."""
    return [
        e for e in all_events
        if e["start"] >= clip["start"] and e["end"] <= clip["end"]
    ]


def make_clip_relative(events, clip_start):
    """Make event timestamps relative to clip start."""
    rel = []
    for e in events:
        rel.append({
            "words": [
                {"word": w["word"], "start": round(w["start"] - clip_start, 3), "end": round(w["end"] - clip_start, 3)}
                for w in e["words"]
            ],
            "start": round(e["start"] - clip_start, 3),
            "end": round(e["end"] - clip_start, 3),
            "text": e["text"],
        })
    return rel


def main():
    parser = argparse.ArgumentParser(description="Prepare caption data for Remotion rendering")
    parser.add_argument("--clips", required=True, help="Clips JSON file")
    parser.add_argument("--transcript", required=True, help="Transcript JSON file")
    parser.add_argument("--output-dir", default="captions_remotion/",
                        help="Output directory for caption data and overlays")
    parser.add_argument("--style", default="clean", choices=["clean", "bold", "bounce"],
                        help="Caption style (default: clean)")
    parser.add_argument("--max-words", type=int, default=6,
                        help="Max words per caption event (default: 6)")
    parser.add_argument("--render", action="store_true",
                        help="Also invoke Remotion renderer (requires npm install)")

    args = parser.parse_args()

    with open(args.clips) as f:
        clips_data = json.load(f)
    with open(args.transcript) as f:
        transcript_data = json.load(f)

    clips = clips_data.get("clips", [])
    all_words = transcript_data.get("words", [])

    style_config = STYLES["default"].get(args.style, STYLES["default"]["clean"])
    style_slug = args.style  # component uses this to select animation mode

    all_events = words_to_events(all_words, args.max_words)
    print(f"Parsed {len(all_events)} caption events from {len(all_words)} words")

    os.makedirs(args.output_dir, exist_ok=True)
    start_time = time.time()

    for clip in clips:
        clip_id = clip.get("id", "01")
        clip_start = clip["start"]
        clip_end = clip["end"]

        events = clip_events(clip, all_events)
        if not events:
            print(f"  Clip {clip_id}: No caption events, skipping")
            continue

        rel_events = make_clip_relative(events, clip_start)
        duration = clip_end - clip_start

        caption_data = {
            "events": rel_events,
            "style": style_config,
            "styleSlug": style_slug,
            "durationFrames": math.ceil(duration * 30),
            "fps": 30,
        }

        data_path = os.path.join(args.output_dir, f"{clip_id}_caption_data.json")
        with open(data_path, "w") as f:
            json.dump(caption_data, f, indent=2)

        print(f"  Clip {clip_id}: {len(rel_events)} events, {duration:.1f}s -> {data_path}")

    elapsed = time.time() - start_time
    print(f"\nCaption data prepared in {elapsed:.1f}s")
    print(f"Data files in: {args.output_dir}")

    # Optionally invoke Remotion renderer
    if args.render:
        render_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "render_all.js")
        if os.path.exists(render_script):
            print(f"\nInvoking Remotion renderer...")
            result = subprocess.run(
                ["node", render_script, "--data-dir", args.output_dir, "--output-dir", args.output_dir],
                capture_output=False,
            )
            sys.exit(result.returncode)
        else:
            print(f"\nRender script not found: {render_script}")
            print("Install dependencies: cd captions_remotion && npm install")
            print("Or use Remotion CLI directly:")
            for clip in clips:
                clip_id = clip.get("id", "01")
                data_path = os.path.join(args.output_dir, f"{clip_id}_caption_data.json")
                print(f"  npx remotion render captions_remotion CaptionsComp "
                      f"--input-props='{data_path}' "
                      f"--output={args.output_dir}{clip_id}_captions.webm "
                      f"--codec=vp8")


if __name__ == "__main__":
    main()
