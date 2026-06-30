---
title: Clipping Lite
emoji: 🎬
colorFrom: purple
colorTo: blue
sdk: docker
pinned: false
license: mit
---

# Video Podcast Clipper

AI auto clipper...
# Video Podcast Clipper

# Clipping Lite

AI auto clipper lite for Hugging Face Spaces.

**Turn long-form video into viral vertical clips.** Face-tracked smart crop follows the speaker. An 8-dimension neuro-engagement rubric finds the moments worth clipping. Animated captions in three styles. Works with Claude Code, Cursor, Codex, Hermes, or standalone.

<p align="center">
  <img src="https://img.shields.io/badge/python-3.8+-blue" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/ffmpeg-required-green" alt="ffmpeg required">
  <img src="https://img.shields.io/badge/license-MIT-brightgreen" alt="MIT License">
  <img src="https://img.shields.io/badge/platform-linux%20%7C%20macOS-lightgrey" alt="Linux | macOS">
</p>

---

## The Difference

Most clip extraction tools do one of three things: pick random timestamps, keyword-match a transcript, or make you scrub a timeline by hand.

Video Podcast Clipper scores every segment the way a brain does — using an 8-dimension model informed by Meta's TribeV2 multimodal brain encoding research. It measures **hook strength**, **emotional arc**, **cross-modal synchronization** (voice + face + words peaking together — the "goosebumps" dimension), and five other dimensions that predict viewer retention. Segments scoring below 65/100 don't make the cut.

Then it tracks the speaker's face with MediaPipe so the vertical crop follows them — no manual repositioning. Captions render with Remotion for per-word animation. Export presets for YouTube Shorts, TikTok, and Instagram Reels are built in.

**The result:** a 60-minute podcast becomes 8-12 platform-ready vertical clips with one agent prompt.

```
Source video (60 min) → [Score → Track → Crop → Render → Caption → Export] → 8-12 vertical clips
```

### See It In Action

> 📹 **[Example output clips coming soon]** — We're preparing a demo reel showing source footage side-by-side with scored, cropped, and captioned output across all three styles.

To generate your own demo: drop any MP4 in the folder, run the pipeline, and check `exports/vertical/`.

---

## Who Is This For?

- **Podcasters and interviewers** repurposing long episodes into social clips
- **Content marketing agencies** clipping client videos at scale
- **AI coding agent users** (Claude Code, Cursor, Codex, Hermes, Windsurf) who want to delegate the entire pipeline to an agent
- **Solo creators** who want quality clips without a video editor

---

## What You Get

- **Smart moment selection** — Not random. Not keyword grep. A neuroscience-informed 8-dimension scoring rubric finds segments people actually watch to the end.
- **Face-tracked vertical crop** — MediaPipe FaceLandmarker (468-point mesh) follows the speaker's face frame by frame. Smooth, natural 9:16 framing. Handles split-screen automatically.
- **Animated captions** — Remotion-rendered overlays with per-word pop-in, active word highlighting, or bouncy color cycling. Three styles: Clean, Bold, Bounce.
- **Platform-ready exports** — One command outputs correctly encoded files for YouTube Shorts (12 Mbps), TikTok (10 Mbps cap), and Instagram Reels (4.5 Mbps).
- **Zero API costs** — Everything runs locally. No transcription API bills. No cloud rendering fees.

---

## Quick Start

```bash
# 1. Install
pip install faster-whisper mediapipe opencv-python-headless

# 2. Drop your video in the folder as source.mp4

# 3. Tell your AI agent (or run each step manually):
#    "Clip this video: source.mp4"
```

**One prompt for AI agent users:** paste this into Claude Code, Cursor, or Hermes:

> Load the video-podcast-clipper skill, then clip source.mp4. Use face-tracked smart crop, bold captions, and export for all platforms.

First clip renders in ~2-4 minutes on CPU (depending on source length). GPU (NVIDIA NVENC) is 5-10x faster.

| Source Length | Clips Extracted | CPU Time (est.) | GPU Time (est.) |
|---------------|-----------------|-----------------|-----------------|
| 30 min | 6-8 | ~8 min | ~2 min |
| 60 min | 8-12 | ~15 min | ~4 min |
| 90 min | 10-15 | ~22 min | ~6 min |

---

## How It Scores Clips (The 8 Dimensions)

| # | Dimension | Weight | What It Measures |
|---|-----------|--------|------------------|
| 1 | **Hook Strength** | 15% | First 3 seconds — bold claims, curiosity gaps, pattern interrupts |
| 2 | **Standalone Coherence** | 15% | Complete self-contained narrative. No "as I mentioned earlier" |
| 3 | **Visual Engagement** | 12% | Motion dynamics, facial expressiveness, scene changes |
| 4 | **Auditory Dynamics** | 12% | Vocal energy, prosodic variation, emotional voice qualities |
| 5 | **Linguistic Density** | 12% | Information richness, framework-level insights, semantic novelty |
| 6 | **Emotional Arc** | 12% | Build → peak → release. Brains track change, not absolute level |
| 7 | **Payoff Resolution** | 12% | Punchlines, twists, actionable takeaways — satisfying ending |
| 8 | **Cross-Modal Sync** | 10% | Voice + face + words all amplifying the same moment ("goosebumps") |

**Minimum threshold: 65/100.** Full scoring tables with levels, indicators, and boosters in [`references/scoring-rubric.md`](references/scoring-rubric.md).

---

## Caption Styles

| Style | Font | Look | Best For |
|-------|------|------|----------|
| **Clean** | Arial 52 | White text, black outline, bottom-third | Interviews, podcasts, professional |
| **Bold** | Arial 60 Bold | ALL CAPS, yellow active word, pop-in animation | Business, education, motivation |
| **Bounce** | Impact 72 | Bouncy scale, rotating bright colors | Entertainment, reactions, energy |

Captions render as transparent WebM (VP8 alpha) and composite onto the final video. Filler words (um, uh, you know, like) are automatically stripped.

---

## Full Pipeline

### 1. Transcribe
```bash
python3 scripts/transcribe.py --source source.mp4 --model base
# → transcript.json (word-level with timestamps)
```

### 2. Score & Select
The agent reads `transcript.json`, applies the 8-dimension rubric, and outputs 6-12 candidates. You approve which to render.

### 3. Face Track
```bash
python3 scripts/face_track.py --source source.mp4 --clips clips.json --output face_data.json --fps 10
```

### 4. Smart Crop
```bash
python3 scripts/smart_crop.py --face-data face_data.json --clips clips.json --output crop_data.json --source source.mp4
```

### 5. Render
```bash
# Vertical (1080x1920, face-tracked crop)
python3 scripts/render.py --source source.mp4 --clips clips.json --output-dir exports/vertical/ --crop-data crop_data.json --crf 23

# Horizontal reference (source resolution)
python3 scripts/render.py --source source.mp4 --clips clips.json --output-dir exports/horizontal/ --horizontal --crf 18
```

### 6. Captions (optional)
```bash
python3 scripts/render_captions.py --clips clips.json --transcript transcript.json --output-dir captions_remotion/ --style bold
cd scripts/captions_remotion && npm install && node render_all.js
python3 scripts/render.py --source source.mp4 --clips clips.json --output-dir exports/vertical/ --crop-data crop_data.json --captions-remotion-dir captions_remotion/
```

### 7. Export
```bash
bash scripts/export.sh --clips clips.json --platform all
# → exports/shorts/01_yt.mp4 (YouTube Shorts)
# → exports/shorts/01_tt.mp4 (TikTok)
# → exports/shorts/01_ig.mp4 (Instagram Reels)
```

---

## Platform Export Specs

| Platform | Codec | Video Bitrate | Audio | Max Duration |
|----------|-------|---------------|-------|-------------|
| YouTube Shorts | H.264 High 4.2 | 12 Mbps | AAC 192k | 60s |
| TikTok | H.264 CRF 18 | 10 Mbps cap | AAC 128k | 60s |
| Instagram Reels | H.264 High 4.2 | 4.5 Mbps | AAC 128k | 90s |

GPU users: add `-c:v h264_nvenc -preset p5 -tune hq` for 5-10x faster encoding.

---

## Installation

```bash
# macOS
brew install ffmpeg
pip install faster-whisper mediapipe opencv-python-headless

# Ubuntu/Debian
sudo apt install ffmpeg
pip install faster-whisper mediapipe opencv-python-headless

# Optional: YouTube downloads
pip install yt-dlp

# Optional: Remotion captions (requires Node.js)
cd scripts/captions_remotion && npm install
```

---

## How It Compares

| Feature | Video Podcast Clipper | Opus Clip | Descript | Munch | Plain ffmpeg |
|---------|----------------------|-----------|----------|-------|-------------|
| AI moment scoring | ✅ 8-dim neuro rubric | ✅ proprietary | ❌ manual | ✅ proprietary | ❌ |
| Face-tracked smart crop | ✅ MediaPipe, animated | ✅ | ❌ | ✅ | ❌ manual |
| Animated captions | ✅ Remotion, 3 styles | ✅ | ✅ | ✅ | ❌ |
| Local / no API costs | ✅ | ❌ subscription | ❌ subscription | ❌ subscription | ✅ |
| Open source | ✅ MIT | ❌ | ❌ | ❌ | ✅ |
| Works via AI agents | ✅ native | ❌ | ❌ | ❌ | ❌ |
| Platform export presets | ✅ YT/TT/IG | ✅ | ✅ | ✅ | ❌ manual |

---

## Configuration

| Parameter | Default | Change When |
|-----------|---------|-------------|
| Whisper model | `base` | `small` for better accuracy; `large-v3` with GPU |
| Clip duration | 15-55s | TikTok performs best at 21-34s |
| Score threshold | 65 | Lower for longer videos with fewer highlights |
| Vertical CRF | 23 | 18 for final delivery masters |
| Face tracking FPS | 10 | 5 for speed on long clips; 15 for fast-moving speakers |
| Caption style | off | `clean` / `bold` / `bounce` — only when explicitly requested |

---

## File Organization

```
project/
├── source.mp4              # Your original video
├── transcript.json         # Word-level transcript
├── clips.json              # Clip definitions & scores
├── face_data.json          # Per-frame face positions
├── crop_data.json          # Smart crop keyframes
├── scripts/
│   ├── transcribe.py       # faster-whisper transcription
│   ├── snap_boundaries.py  # Snap cuts to word/sentence boundaries
│   ├── face_track.py       # MediaPipe FaceLandmarker tracking
│   ├── smart_crop.py       # Compute animated crop keyframes
│   ├── render.py           # Render vertical + horizontal clips
│   ├── render_captions.py  # Prepare Remotion caption data
│   ├── export.sh           # Platform-specific encoding
│   └── captions_remotion/  # Remotion caption rendering project
├── exports/
│   ├── horizontal/         # Source resolution (crf 18)
│   └── vertical/           # 1080x1920 (crf 23)
└── references/
    └── scoring-rubric.md   # Full 8-dimension rubric
```

---

## FAQ

**Can I use this commercially?** Yes. MIT license. The clips you produce are your content. Note: Remotion (captions) is source-available, not MIT — captions are an optional feature and Remotion is not bundled.

**What's the minimum source quality?** 720p recommended. 360p sources work but vertical upscaling will be visibly soft (5.3x upscale).

**Does it work with audio-only podcasts?** Yes. Face tracking and visual scoring default to neutral. The rubric still finds engaging segments from audio dynamics and linguistic density.

**Why MIT and not Apache 2.0 or GPL?** MIT maximizes adoption with zero legal friction for commercial users. This is orchestration code built on existing open-source libraries — MIT is the standard for this category. See [LICENSE](LICENSE).

**Can I run it without an AI agent?** Yes. Each script is standalone. Run the pipeline steps manually from the command line.

**How accurate is the face tracking?** MediaPipe FaceLandmarker achieves ~98% face detection on well-lit, front-facing footage. Low light, side profiles, and fast movement reduce accuracy. The smart crop engine fills gaps with interpolation and falls back to center crop.

---

## Contributing

Contributions welcome — especially:

- New caption styles (Remotion compositions)
- Platform presets (Snapchat, LinkedIn, X video)
- Multi-language transcription support
- GPU pipeline optimizations
- Split-screen detection improvements

Open an issue to discuss before submitting a PR. See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Dependencies

| Component | Purpose | License |
|-----------|---------|---------|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Transcription | MIT |
| [MediaPipe](https://github.com/google-ai-edge/mediapipe) | Face tracking | Apache 2.0 |
| [ffmpeg](https://ffmpeg.org/) | Video processing | LGPL/GPL |
| [Remotion](https://remotion.dev/) | Animated captions (optional) | Source-available |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | YouTube downloads (optional) | Unlicense |

---

## License

MIT — see [LICENSE](LICENSE). Dependencies have their own licenses. Remotion is source-available and not bundled; captions are an optional feature requiring a separate `npm install`.

---

<p align="center">
  <sub>Built for creators who want to spend less time editing and more time creating.</sub>
</p>
