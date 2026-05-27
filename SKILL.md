---
name: video-podcast-clipper
description: >
  AI-powered short-form clip extractor for videos, podcasts, webinars, interviews,
  and all long-form content. Transcribes with faster-whisper, scores segments with
  a neuroscience-informed 8-dimension rubric, tracks faces with MediaPipe for smart
  crop positioning, renders vertical 1080x1920 clips with ffmpeg, generates animated
  captions with Remotion, and exports platform-optimized files.
  Works with any AI coding agent (Claude Code, Hermes, OpenClaw, Codex, etc.).
  Use when the user says "clip this", "extract shorts", "make clips", "short-form",
  "vertical clips", "reels", "shorts", "tiktok", or "repurpose".
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - AskUserQuestion
---

# Video Podcast Clipper — AI Short-Form Clip Extractor for Any Long-Form Content

Turn long-form video or audio into viral-ready vertical short clips.
Designed to run on any AI coding agent with no proprietary dependencies.

## Quick Start (Minimal Path)

If you just want to get clips out fast:

```bash
# 1. Install dependencies
pip install faster-whisper mediapipe opencv-python-headless 2>/dev/null
# ffmpeg must be available: ffmpeg -version
# Node.js must be available for Remotion captions: node --version

# 2. Put your source video in the working directory as source.mp4

# 3. Tell the agent:
#    "Clip this video: source.mp4"
```

The agent will transcribe, find the best moments, track faces for smart crop positioning, render vertical clips with animated captions, and place them in `./exports/`.

\---

## Full Pipeline (12 Steps)

### Step 1: Preflight

Validate the input and environment before doing any work. Stop early if anything fails — do not proceed past Step 1 with a bad source.

**Source integrity checks (REQUIRED — abort if any fail):**

```bash
# 1. File must exist and be readable
test -f source.mp4 && test -r source.mp4 || { echo "ABORT: source.mp4 not found or not readable"; exit 1; }

# 2. File must be non-zero
SIZE=$(stat -c%s source.mp4 2>/dev/null || stat -f%z source.mp4 2>/dev/null)
test "$SIZE" -gt 1024 || { echo "ABORT: source.mp4 is zero-byte or too small ($SIZE bytes)"; exit 1; }

# 3. Must be a valid media file with streams (not DRM, not HTML, not corrupt)
ffprobe -v error -show_entries stream=codec_name,width,height,duration \
  -of csv=p=0 source.mp4 2>&1
# If ffprobe returns nothing or errors: ABORT. File is encrypted, corrupt, or not media.

# 4. Must have audio AND video streams (warn if audio-only)
HAS_VIDEO=$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 source.mp4)
HAS_AUDIO=$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 source.mp4)
test -z "$HAS_AUDIO" && { echo "ABORT: No audio stream found — transcription requires audio"; exit 1; }
test -z "$HAS_VIDEO" && echo "WARNING: Audio-only source. Face tracking and smart crop will be skipped. Clips will use static background."

# 5. Duration must be finite and > 5 seconds
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 source.mp4)
test -n "$DUR" && python3 -c "import sys; sys.exit(0 if float('$DUR') > 5 else 1)" \
  || { echo "ABORT: Duration is missing, zero, or under 5 seconds"; exit 1; }

# 6. Check tools
ffmpeg -version 2>&1 | head -1
ffprobe -version 2>&1 | head -1
python3 --version
python3 -c "import faster_whisper; print('faster-whisper OK')" || echo "WARNING: faster-whisper not installed"
python3 -c "import mediapipe; print('mediapipe OK')" 2>/dev/null || echo "WARNING: mediapipe not installed — face tracking disabled"
python3 -c "import cv2; print('opencv OK')" 2>/dev/null || echo "WARNING: opencv not installed — face tracking disabled"

# 7. Check disk space (need at least 2x source file size + 500MB overhead)
REQUIRED_KB=$(( (SIZE / 1024) * 2 + 512000 ))
AVAIL_KB=$(df --output=avail . 2>/dev/null | tail -1 || df -k . | awk 'NR==2{print $4}')
test "$AVAIL_KB" -gt "$REQUIRED_KB" || { echo "ABORT: Not enough disk space. Need ${REQUIRED_KB}KB, have ${AVAIL_KB}KB"; exit 1; }
```

Report to the user: source resolution, duration, codec, disk space, tool status, estimated processing time. If the source is under 720p, warn that vertical upscaling will be soft. If audio-only, state that face tracking/crop are skipped and clips will use a static background or waveform visualization.

**Supported input formats:** MP4, MKV, MOV, AVI, WebM, MP3, WAV, M4A.
**Supported sources:** Local file, YouTube URL (via yt-dlp), direct video URL.

\---

### Step 2: Source Acquisition

If the user provides a local file, verify it with ffprobe and move on.

If the user provides a URL:

```bash
# YouTube — download to a temp file first, then verify
yt-dlp -f "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]" \
  -o "/tmp/source_download.mp4" "<URL>" || { echo "ABORT: yt-dlp download failed (auth/geo-block/private?)"; exit 1; }

# Direct video URL
curl -L -o /tmp/source_download.mp4 "<URL>" || { echo "ABORT: curl download failed (HTTP error, timeout, or redirect loop)"; exit 1; }
```

**After download, validate with ffprobe (NOT the `file` command — `file` only catches HTML, not broken video):**

```bash
# Verify the download is actual media with valid streams
AUDIO_CHECK=$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 /tmp/source_download.mp4 2>&1)
VIDEO_CHECK=$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 /tmp/source_download.mp4 2>&1)

# If either check is empty or contains HTML/error text: ABORT
echo "$AUDIO_CHECK" | grep -qi "html\|error\|$" && { echo "ABORT: Downloaded file is not valid media (HTML page, error, or HLS manifest)"; file /tmp/source_download.mp4; exit 1; }
test -z "$AUDIO_CHECK" && { echo "ABORT: No audio stream in download — cannot transcribe"; exit 1; }

# Only rename to source.mp4 after validation passes (avoid overwriting good sources)
test -f source.mp4 && { echo "ABORT: source.mp4 already exists. Move or rename it before downloading."; exit 1; }
mv /tmp/source_download.mp4 source.mp4
```

**Source collision rule:** Never overwrite `source.mp4`. If it exists, ask the user to rename or remove it. For batch work, use timestamped filenames: `source_$(date +%Y%m%d_%H%M%S).mp4`.

**HLS/DASH/manifest detection:** If the URL ends in `.m3u8` or `.mpd`, or if `curl -I` returns `content-type: application/vnd.apple.mpegurl` or `application/dash+xml`, route through `yt-dlp` or `ffmpeg` instead of raw `curl`:

```bash
ffmpeg -i "<MANIFEST_URL>" -c copy /tmp/source_download.mp4
```

\---

### Step 3: Transcribe

Extract audio and transcribe with faster-whisper. Always use the Python
library (not the CLI — the CLI times out on CPU).

```python
# Extract audio
ffmpeg -y -i source.mp4 -vn -acodec pcm\_s16le -ar 16000 -ac 1 /tmp/audio.wav

# Transcribe (run inside the agent's Python execution environment)
from faster\_whisper import WhisperModel
model = WhisperModel("base", device="cpu", compute\_type="int8")
segments, info = model.transcribe("/tmp/audio.wav", language="en",
                                   word\_timestamps=True, vad\_filter=True)

# Collect results
words = \[]
for seg in segments:
    for w in seg.words:
        words.append({"word": w.word, "start": w.start, "end": w.end})

# Write transcript
import json
with open("transcript.json", "w") as f:
    json.dump({"words": words, "duration": info.duration}, f)
```

**Model selection:**

* `base` — good accuracy, \~145MB, fast on CPU (recommended default)
* `small` — better accuracy, \~244MB, moderate speed
* `large-v3` — best accuracy, \~1.6GB, slow on CPU (use only with GPU)

**For videos >30 minutes:** Split audio into 10-minute chunks and transcribe in batches to avoid timeout. Combine the word lists with adjusted timestamps.

**Chunked transcription merge validation (REQUIRED when chunking):**

After merging chunks, validate the result before proceeding to Step 4:

```bash
# 1. Timestamps must be monotonically increasing (no overlap, no gaps > 5s)
python3 -c "
import json
with open('transcript.json') as f:
    data = json.load(f)
words = data['words']
for i in range(1, len(words)):
    if words[i]['start'] < words[i-1]['start']:
        print(f'ABORT: Non-monotonic timestamp at word {i}: {words[i-1][\"start\"]} -> {words[i][\"start\"]}')
        exit(1)
    gap = words[i]['start'] - words[i-1]['end']
    if gap > 5.0:
        print(f'WARNING: Large gap ({gap:.1f}s) between words {i-1} and {i} — possible missing chunk')
print(f'OK: {len(words)} words, duration {data[\"duration\"]:.1f}s, monotonic')
"

# 2. Coverage check: transcript should cover ≥ 90% of source duration
python3 -c "
import json
with open('transcript.json') as f:
    data = json.load(f)
dur = data['duration']
# Source duration from ffprobe
import subprocess, json
p = subprocess.run(['ffprobe','-v','quiet','-print_format','json','-show_format','source.mp4'],
                   capture_output=True, text=True)
src = json.loads(p.stdout)
src_dur = float(src['format']['duration'])
coverage = (dur / src_dur) * 100
if coverage < 90:
    print(f'ABORT: Transcript covers only {coverage:.0f}% of source — chunks may be missing')
    exit(1)
print(f'Coverage: {coverage:.0f}% — OK')
"
```

**VAD filter note:** `vad\_filter=True` removes silence and secondary speakers.
This is ideal for guest-focused clips. Set `vad\_filter=False` if you need
host questions captured in the transcript.

\---

### Step 4: Analyze — Score Segment Candidates

Read the full transcript and identify 6-12 candidate segments using the
**8-dimension Neuro-Engagement Scoring Rubric** (`references/scoring-rubric.md`).

**Scoring Formula:**

```
final_score = (visual_engagement   × 0.12)
            + (auditory_dynamics   × 0.12)
            + (linguistic_density  × 0.12)
            + (cross_modal_sync    × 0.10)
            + (hook_strength       × 0.15)
            + (emotional_arc       × 0.12)
            + (standalone_coherence × 0.15)
            + (payoff_resolution   × 0.12)
```

**Minimum threshold:** 65/100. **Target duration:** 15-55 seconds per clip.

The 8 dimensions:

| # | Dimension | Weight | What it measures |
|---|-----------|--------|------------------|
| 1 | Visual Engagement | 0.12 | Motion dynamics, facial expressiveness, scene changes |
| 2 | Auditory Dynamics | 0.12 | Vocal energy, prosodic variation, emotional voice qualities |
| 3 | Linguistic Density | 0.12 | Information richness, semantic novelty, conceptual depth |
| 4 | Cross-Modal Sync | 0.10 | Voice + face + words all amplifying the same moment ("goosebumps") |
| 5 | Hook Strength | 0.15 | First 3 seconds — bold claims, curiosity gaps, pattern interrupts |
| 6 | Emotional Arc | 0.12 | Does energy build, peak, and release? Brain tracks CHANGE, not absolute level |
| 7 | Standalone Coherence | 0.15 | Complete self-contained narrative arc. No external context needed |
| 8 | Payoff Resolution | 0.12 | Satisfying ending — punchline, twist, actionable takeaway |

Full scoring tables with levels and indicators are in `references/scoring-rubric.md`.
Use the **Quick-Score Reference Card** at the bottom for rapid scanning.

**Candidate selection rules:**
- Target 6-12 candidates from a typical 30-60 minute video
- Clips at least 90s apart in the source timeline (brain needs ~100s to reset between engagement peaks)
- Diversity: at least 2 clips each with strong Visual/Auditory/Linguistic scores (≥70)
- At least 1 "Build → Peak → Release" emotional arc
- Max 2 clips on same subtopic; max 2 clips with same hook archetype
- Align start/end with sentence boundaries, not mid-word
- For each candidate, record: start time, end time, duration, score on all 8 dimensions, hook text, and rationale

**Candidate time validation (REQUIRED — reject any candidate that fails):**

Before presenting candidates to the user, validate every candidate:

```python
# Validate candidate times against source
import json, subprocess

# Get source duration
p = subprocess.run(['ffprobe','-v','quiet','-print_format','json','-show_format','source.mp4'],
                   capture_output=True, text=True)
src_dur = float(json.loads(p.stdout)['format']['duration'])

for clip in candidates:
    start, end = clip['start'], clip['end']
    # Must be within source bounds
    assert 0 <= start < end <= src_dur, \
        f"Candidate {clip['id']}: times [{start}, {end}] out of bounds [0, {src_dur}]"
    # Duration must be 15-55s
    dur = end - start
    assert 15 <= dur <= 55, \
        f"Candidate {clip['id']}: duration {dur:.1f}s outside [15, 55]"
    # Must not overlap with other candidates (90s separation)
    for other in candidates:
        if other['id'] != clip['id']:
            gap = abs(clip['start'] - other['start'])
            assert gap >= 90, \
                f"Candidates {clip['id']} and {other['id']} only {gap:.0f}s apart (need ≥90s)"
```

If validation fails, drop the invalid candidate — don't adjust times silently. If fewer than 3 valid candidates remain, lower the threshold to 55 and re-analyze.

**Red flags (automatic low coherence score):**
- "As I mentioned earlier..." / "Going back to what we discussed..."
- Pronouns without clear referents ("he said that...")
- Cuts off mid-sentence at the end

**Clip selection policy (configurable):**
- Default: Guest-focused. Host only included for lead-in questions.
- Positive framing only: If a clip portrays the subject negatively
  (admitting failure, incompetence, products failing), drop it entirely.
- No dangling pronouns: If the first 3-5 words contain a pronoun or proper
  name without context, move the start forward to the next self-contained
  statement.

\---

### Step 5: Present — Show Candidates

Present candidates in a formatted table:

```
| # | Start | End | Dur | Hook | Engagement Score | Rationale |
|---|-------|-----|-----|------|-----------------|-----------|
| 1 | 04:22 → 05:01 | 39s | "Nobody talks about..." | 87 | Contrarian take with data |
```

Ask the user:

1. Which segments? (all, specific numbers, or "re-analyze")
2. Caption style? (none / clean / bold / bounce — see Step 9)
3. Platform? (youtube / tiktok / instagram / all)

Write approved selections to `clips.json` using an atomic write (write to temp file, validate, then rename):

```python
import json, os

# Build the clips data
clips_data = {
  "source": "source.mp4",
  "clips": [
    {
      "id": "01",
      "title": "Nobody talks about this",
      "start": 262.0,
      "end": 301.0,
      "duration": 39.0,
      "score": 87,
      "hook": "Nobody talks about this hidden cost"
    }
  ],
  "caption_style": "none",
  "platform": "all"
}

# Validate schema before writing
valid_styles = {"none", "clean", "bold", "bounce"}
valid_platforms = {"youtube", "tiktok", "instagram", "all"}
assert clips_data["caption_style"] in valid_styles, f"Invalid caption style: {clips_data['caption_style']}"
assert clips_data["platform"] in valid_platforms, f"Invalid platform: {clips_data['platform']}"
for clip in clips_data["clips"]:
    assert isinstance(clip["start"], (int, float)), f"Clip {clip['id']}: start is not numeric"
    assert isinstance(clip["end"], (int, float)), f"Clip {clip['id']}: end is not numeric"
    assert clip["start"] < clip["end"], f"Clip {clip['id']}: start >= end"
    assert 0 <= clip["score"] <= 100, f"Clip {clip['id']}: score {clip['score']} out of range"
    assert len(clip["id"]) > 0, f"Clip missing id"

# Atomic write: temp file first, then rename
with open("clips.json.tmp", "w") as f:
    json.dump(clips_data, f, indent=2)
os.rename("clips.json.tmp", "clips.json")
print(f"Wrote {len(clips_data['clips'])} clips to clips.json")
```

\---

### Step 6: Snap Boundaries

Adjust cut points to natural audio boundaries so clips never cut mid-word.

**Rules:**

1. Snap start time to the beginning of the nearest word
2. Prefer sentence starts (after `.` `?` `!`) if within 1.5s
3. Extend end time to the next sentence boundary if within 3 seconds
4. Add 300ms padding after the last word
5. Enforce minimum 15s / maximum 60s duration

```bash
# Optional: detect silence points for cleaner cuts
ffmpeg -i source.mp4 -af "silencedetect=noise=-35dB:d=0.3" -f null - 2>\&1 | \\
  grep "silence\_start\\|silence\_end"
```

\---

### Step 7: Face Track — MediaPipe FaceLandmarker

Use MediaPipe's FaceLandmarker to automatically detect face position in each clip segment.

```bash
python3 scripts/face\_track.py \\
  --source source.mp4 \\
  --clips clips.json \\
  --output face\_data.json \\
  --fps 10
```

**What it does:**

* Extracts frames from each clip at 10 fps (good balance of speed vs. accuracy)
* Runs MediaPipe FaceLandmarker (468-point face mesh) on each frame
* Outputs per-frame face position (nose tip X/Y, face width, confidence)
* Detects split-screen layouts automatically

**Output:** `face\_data.json` with per-clip frame arrays:

```json
{
  "clips": {
    "01": {
      "frames": \[
        {"time": 0.0, "face\_x": 0.52, "face\_y": 0.33, "confidence": 0.98, "detected": true},
        ...
      ],
      "split\_screen": false,
      "dominant\_side": "center"
    }
  }
}
```

**Model:** The FaceLandmarker model (\~3MB) auto-downloads on first run to
`\~/.mediapipe/`. Requires `pip install mediapipe opencv-python-headless`.

**Performance:** \~2-5 seconds per clip on CPU (depending on duration and resolution).

\---

### Step 8: Smart Crop Compute (NEW)

Convert face tracking data into smooth crop keyframes for ffmpeg.

```bash
python3 scripts/smart\_crop.py \\
  --face-data face\_data.json \\
  --clips clips.json \\
  --output crop\_data.json \\
  --source source.mp4 \\
  --padding 0.15 \\
  --smooth 5
```

**What it does:**

* Reads face position data from Step 7
* Applies moving-average smoothing (default: 5-frame window) to eliminate jitter
* Converts face X position to crop X offset using rule-of-thirds composition
(face positioned at \~38% from left of crop window)
* Handles gap-filling when face detection drops frames
* Detects split-screen and uses fixed crop targeting the guest side
* Deduplicates keyframes (only writes when crop\_x changes by 4+ pixels)

**Crop strategies (auto-selected):**

|Strategy|When Used|Behavior|
|-|-|-|
|`face\_track`|Face detected in ≥30% of frames|Animated crop follows speaker|
|`split\_screen`|Two faces detected on opposite sides|Fixed crop on guest side|
|`center`|No face detected|Static center crop (fallback)|

**Output:** `crop\_data.json` with per-clip keyframe arrays:

```json
{
  "clips": {
    "01": {
      "keyframes": \[
        {"time": 0.0, "crop\_x": 656},
        {"time": 1.5, "crop\_x": 620},
        {"time": 3.2, "crop\_x": 645}
      ],
      "crop\_w": 608,
      "crop\_h": 1080,
      "strategy": "face\_track"
    }
  }
}
```

**Parameters:**

* `--padding 0.15` — Extra space around face (15% of crop width). Increase for more headroom.
* `--smooth 5` — Smoothing window in frames. Higher = smoother but slower response to movement.

**Crop geometry validation (REQUIRED — validate crop_data.json before rendering):**

```python
import json, subprocess

# Get source dimensions
p = subprocess.run(['ffprobe','-v','quiet','-print_format','json',
    '-select_streams','v:0','-show_entries','stream=width,height','source.mp4'],
    capture_output=True, text=True)
src_stream = json.loads(p.stdout)['streams'][0]
src_w, src_h = src_stream['width'], src_stream['height']

with open('crop_data.json') as f:
    crop = json.load(f)

for clip_id, data in crop['clips'].items():
    cw, ch = data['crop_w'], data['crop_h']

    # Crop window must fit inside source
    assert ch <= src_h, f"Clip {clip_id}: crop height {ch} > source height {src_h}"
    assert cw <= src_w, f"Clip {clip_id}: crop width {cw} > source width {src_w}"

    # Validate keyframes
    for kf in data.get('keyframes', []):
        cx = kf['crop_x']
        assert 0 <= cx <= src_w - cw, \
            f"Clip {clip_id}: crop_x {cx} out of range [0, {src_w - cw}]"
        assert isinstance(kf['time'], (int, float)) and kf['time'] >= 0, \
            f"Clip {clip_id}: invalid keyframe time {kf.get('time')}"

    # For portrait source that can't crop 9:16: switch to pad+scale
    if src_w / src_h > 0.7:  # Wider than ~0.7:1 can't cleanly crop to 9:16
        print(f"WARNING: Clip {clip_id}: source aspect {src_w/src_h:.2f} too wide for 9:16 crop. Using pad+scale fallback.")
        data['strategy'] = 'pad_scale'

print("Crop geometry validation: OK")
```

\---

### Step 9: Prepare — Extract Clips

Extract each segment via ffmpeg. **CRITICAL: Use `-t` (duration), NOT `-to` (end time) when `-ss` comes before `-i`.** With `-ss ... -to ... -i`, the `-to` flag is ignored for MP4 containers and the clip runs to the end of the source.

```bash
DURATION=$(python3 -c "print($END - $START)")  # end minus start in seconds
mkdir -p clips

# CORRECT: -ss before -i, use -t for duration
ffmpeg -y -ss $START -i source.mp4 -t $DURATION -c copy clips/clip_01.mp4
```

**Verify every extracted clip immediately (REQUIRED):**

```bash
# Check clip duration matches expected (within 1 second tolerance)
EXPECTED_DUR=39.0
ACTUAL_DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 clips/clip_01.mp4)
python3 -c "import sys; diff=abs(float('$ACTUAL_DUR') - float('$EXPECTED_DUR')); sys.exit(0 if diff < 1.0 else 1)" \
  || { echo "ABORT: Clip 01 duration mismatch: expected ${EXPECTED_DUR}s, got ${ACTUAL_DUR}s"; exit 1; }

# Check for A/V stream presence
ffprobe -v error -show_entries stream=codec_type -of csv=p=0 clips/clip_01.mp4 | grep -q video \
  || echo "WARNING: Clip 01 has no video stream (audio-only source?)"
ffprobe -v error -show_entries stream=codec_type -of csv=p=0 clips/clip_01.mp4 | grep -q audio \
  || echo "WARNING: Clip 01 has no audio stream"

# Check for corrupt frames (nonzero packet count)
PKT_COUNT=$(ffprobe -v error -count_packets -select_streams v:0 -show_entries stream=nb_read_packets -of csv=p=0 clips/clip_01.mp4)
test "$PKT_COUNT" -gt 0 || { echo "ABORT: Clip 01 has zero video packets — stream copy failed"; exit 1; }
```

**Stream copy failure recovery:** If any clip fails verification (wrong duration, zero packets, missing streams), re-extract with re-encode:

```bash
# Accurate seek with re-encode (slower but reliable)
ffmpeg -y -i source.mp4 -ss $START -t $DURATION -c:v libx264 -preset veryfast -crf 18 -c:a aac -b:a 128k clips/clip_01.mp4
```

Then re-verify. If re-encode also fails, mark the clip as failed and continue with remaining clips (don't abort the entire batch).

### Step 10: Render — Vertical Clips with Smart Crop

Render each clip using the smart crop keyframes from Step 8:

```bash
python3 scripts/render.py \\
  --source source.mp4 \\
  --clips clips.json \\
  --output-dir exports/vertical/ \\
  --crop-data crop_data.json \\
  --crf 23
```

Face-tracked crop follows the speaker using time-varying crop X expressions interpolated between keyframes.

**Encoding settings:**

* `-crf 23` — good balance of quality and file size for review
* `-crf 18` — higher quality for final delivery
* `-preset veryfast` — fast encoding; use `-preset slow` for final masters
* `-movflags +faststart` — enables web playback before full download

**Also render horizontal (source resolution) clips first** as a reference check:

```bash
python3 scripts/render.py --source source.mp4 --clips clips.json \\
  --output-dir exports/vertical/ --horizontal --crf 23
```

**Batch rendering:** Render horizontals first (fast), then verticals. For
verticals at 1080p, render in batches of 3 to avoid timeout. At 720p, batches
of 5 are safe.

**Verify every output (REQUIRED — expanded check):**

```bash
# 1. Basic stream check
ffprobe -v error -show_entries stream=codec_name,width,height,duration \
  -of csv=p=0 exports/vertical/01_v.mp4

# 2. Vertical clips MUST be 1080x1920
W=$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of csv=p=0 exports/vertical/01_v.mp4)
H=$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of csv=p=0 exports/vertical/01_v.mp4)
test "$W" = "1080" -a "$H" = "1920" || echo "FAIL: Expected 1080x1920, got ${W}x${H}"

# 3. Duration must match clip definition within 0.5s
EXPECTED_DUR=39.0
ACTUAL_DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 exports/vertical/01_v.mp4)
python3 -c "import sys; sys.exit(0 if abs(float('$ACTUAL_DUR') - $EXPECTED_DUR) < 0.5 else 1)" \
  || echo "FAIL: Duration mismatch: expected ${EXPECTED_DUR}s, got ${ACTUAL_DUR}s"

# 4. Must have both audio and video streams
ffprobe -v error -show_entries stream=codec_type -of csv=p=0 exports/vertical/01_v.mp4 | tr ',' '\n' | sort | tr '\n' ' '
echo ""  # Should show: audio video

# 5. Nonzero frame count
FRAMES=$(ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of csv=p=0 exports/vertical/01_v.mp4)
test "$FRAMES" -gt 0 || echo "FAIL: Zero frames"

# 6. Moov atom present (faststart check — ensures web playback)
ffprobe -v error -show_entries format=format_name -of csv=p=0 exports/vertical/01_v.mp4 | grep -q mov \
  && echo "moov atom: OK" || echo "WARNING: moov atom may be missing"

# 7. Not all black (sample 3 frames at 25%, 50%, 75% — check for zero variance)
for PCT in 25 50 75; do
    FRAME_TIME=$(python3 -c "print($ACTUAL_DUR * $PCT / 100)")
    MEAN=$(ffmpeg -ss $FRAME_TIME -i exports/vertical/01_v.mp4 -vframes 1 -f rawvideo -pix_fmt gray - 2>/dev/null | xxd | head -1)
    test -n "$MEAN" || echo "WARNING: Frame at ${PCT}% appears blank"
done

echo "Output verification complete"
```

\---

### Step 11: Captions — Remotion Animated Overlays (Enhanced)

**Do NOT generate captions by default.** Only when the user explicitly asks.

Remotion renders animated caption overlays as transparent WebM files, which are
then composited onto the video. This produces much higher quality than ffmpeg's
built-in ASS subtitles — with per-word animations, custom colors, and smooth motion.

**Three caption styles:**

|Style|Font|Look|Best For|
|-|-|-|-|
|**Clean**|Arial 52|White text, black outline, bottom-third|Interviews, podcasts, professional|
|**Bold**|Arial 60 Bold|ALL CAPS, yellow active word, pop-in|Business, education, motivation|
|**Bounce**|Impact 72|Bouncy scale, rotating bright colors|Entertainment, reactions, energy|

**Step 11a: Prepare caption data**

```bash
python3 scripts/render_captions.py \\
  --clips clips.json \\
  --transcript transcript.json \\
  --output-dir captions_remotion/ \\
  --style bold
```

This reads the word-level transcript and generates per-clip caption data JSON files
with cleaned text (filler words removed), word timestamps, and style config.

**Step 11b: Render caption overlays with Remotion**

```bash
cd scripts/captions\_remotion
npm install  # first time only
node render\_all.js --data-dir ./ --output-dir ./
```

This renders each clip's captions as a transparent WebM (VP8 with alpha channel)
at 1080x1920, 30fps. Output: `<id>\_captions.webm`.

**Step 11b (alternative):** Use the `--render` flag to do both steps at once:

```bash
python3 scripts/render\_captions.py \\
  --clips clips.json --transcript transcript.json \\
  --output-dir captions\_remotion/ --style bold --render
```

**Step 11c: Composite captions onto video**

```bash
python3 scripts/render.py \\
  --source source.mp4 --clips clips.json \\
  --output-dir exports/vertical/ \\
  --crop-data crop\_data.json \\
  --captions-remotion-dir captions\_remotion/ \\
  --crf 23
```

This overlays the transparent caption WebM onto each clip using ffmpeg's
`overlay` filter. Output: `<id>\_v\_captions.mp4`.

**Caption rules:**

* Max 2 lines per caption event, \~6 words per line
* Position in bottom third of frame (MarginV=500 on 1920px canvas)
* 135px left/right margins (1/8 of 1080px)
* Short phrases (3-6 seconds each), not long transcript segments
* Filler words (um, uh, you know, like, I mean) are automatically removed
* Pop-in animation: spring-based scale + opacity (4 frames)
- Bold style: active word highlighted in accent color
* Bounce style: per-word color cycling with spring scale

**Fallback (no Node.js/Remotion):** If Remotion is not available, use the
original ASS subtitle method:

```bash
ffmpeg -y -i clip\_v.mp4 -vf "subtitles=captions.ass" \\
  -c:v libx264 -preset veryfast -crf 23 -c:a copy clip\_captioned.mp4
```

\---

### Step 12: Export — Platform-Optimized Encoding

Export with platform-specific settings:

|Platform|Codec|Video Bitrate|Audio|Max Duration|
|-|-|-|-|-|
|YouTube Shorts|H.264 High 4.2|12 Mbps|AAC 192k|60s|
|TikTok|H.264 CRF 18|10 Mbps cap|AAC 128k|60s|
|Instagram Reels|H.264 High 4.2|4.5 Mbps|AAC 128k|90s|

**YouTube Shorts (CPU):**

```bash
ffmpeg -y -i clip\_v.mp4 \\
  -c:v libx264 -preset slow -b:v 12M -maxrate 14M -bufsize 24M \\
  -profile:v high -level 4.2 \\
  -c:a aac -b:a 192k -ar 48000 \\
  -pix\_fmt yuv420p -movflags +faststart \\
  exports/shorts/short\_01\_yt.mp4
```

**TikTok (CPU):**

```bash
ffmpeg -y -i clip\_v.mp4 \\
  -c:v libx264 -preset slow -crf 18 \\
  -maxrate 10M -bufsize 20M \\
  -c:a aac -b:a 128k -ar 44100 \\
  -pix\_fmt yuv420p -movflags +faststart \\
  exports/shorts/short\_01\_tt.mp4
```

**Instagram Reels (CPU):**

```bash
ffmpeg -y -i clip\_v.mp4 \\
  -c:v libx264 -preset slow -b:v 4500k -maxrate 5000k -bufsize 10M \\
  -profile:v high -level 4.2 \\
  -c:a aac -b:a 128k -ar 44100 \\
  -pix\_fmt yuv420p -movflags +faststart \\
  exports/shorts/short\_01\_ig.mp4
```

**With NVIDIA GPU (NVENC):** Replace `-c:v libx264 -preset slow` with
`-c:v h264\_nvenc -preset p5 -tune hq` for 5-10x faster encoding.

**Audio normalization (optional):** Add `-af loudnorm=I=-14:TP=-1:LRA=11`
to normalize to -14 LUFS (streaming standard).

\---

## Edit Adjustments

When the user provides revision instructions, timestamps are **clip-relative**
(not source time). Convert: `source\_time = clip\_start + relative\_time`.

**Common edit patterns:**

```
"01\_edits": {
  "start": "start the clip at 00:27 right before 'lifespans have'",
  "end": "extend to finish the thought"
}
```

**Mute a word or phrase:**

```bash
ffmpeg -y -ss <start> -i source.mp4 -t <duration> \\
  -vf "crop=...,scale=1080:1920" \\
  -af "volume=enable='between(t,<clip\_t1>,<clip\_t2>)':volume=0" \\
  -c:v libx264 -preset veryfast -crf 23 -c:a aac -b:a 128k output.mp4
```

**Remove a mid-clip segment (concat):**

```bash
# Render two parts
ffmpeg -y -ss <start> -i source.mp4 -t <part1\_dur> -c copy partA.mp4
ffmpeg -y -ss <part2\_start> -i source.mp4 -t <part2\_dur> -c copy partB.mp4

# Concat
echo "file 'partA.mp4'" > concat.txt
echo "file 'partB.mp4'" >> concat.txt
ffmpeg -y -f concat -safe 0 -i concat.txt -c copy output.mp4
```

\---

## File Organization

```
project/
├── source.mp4              # Original source
├── transcript.json         # Word-level transcript (Step 3)
├── clips.json              # Clip definitions (Step 5)
├── face\_data.json          # Per-frame face positions (Step 7)
├── crop\_data.json          # Smart crop keyframes (Step 8)
├── scripts/
│   ├── transcribe.py       # Step 3: faster-whisper transcription
│   ├── snap\_boundaries.py  # Step 6: snap to word boundaries
│   ├── face\_track.py       # Step 7: MediaPipe face tracking
│   ├── smart\_crop.py       # Step 8: compute crop keyframes
│   ├── render.py           # Step 10: render vertical/horizontal clips
│   ├── render\_captions.py  # Step 11a: prepare caption data
│   ├── export.sh           # Step 12: platform-specific encoding
│   └── captions\_remotion/  # Step 11b: Remotion caption project
│       ├── package.json
│       ├── src/
│       │   ├── index.ts
│       │   ├── Root.tsx
│       │   └── CaptionsComposition.tsx
│       ├── render\_all.js
│       └── \*.json           # Per-clip caption data + rendered .webm overlays
├── exports/
│   ├── horizontal/         # Source resolution, crf 18
│   │   ├── 01\_h.mp4
│   │   └── ...
│   └── vertical/           # 1080x1920, crf 23
│       ├── 01\_v.mp4
│       ├── 01\_v\_captions.mp4  # (if captions requested)
│       └── ...
└── shorts/                 # Platform-optimized exports
    ├── 01\_yt.mp4
    ├── 01\_tt.mp4
    ├── 01\_ig.mp4
    └── ...
```

\---

## Edge Cases \& Pitfalls

### Transcription

* **Whisper CLI times out on CPU.** Always use the `faster\_whisper` Python
library, not the `whisper` CLI command.
* **VAD filter gaps.** `vad\_filter=True` may filter out secondary speakers.
Use `vad\_filter=False` if you need host questions captured.
* **Long videos.** For 50+ min sources, split audio into 10-min chunks and
transcribe in batches of 2 to stay under execution timeouts.

### Face Tracking (MediaPipe)

* **FaceLandmarker model auto-download.** First run downloads \~3MB model to
`\~/.mediapipe/`. This requires internet access. If the download fails, manually
download from: `https://storage.googleapis.com/mediapipe-models/face\_landmarker/face\_landmarker/float16/1/face\_landmarker.task`
* **GPU not required.** FaceLandmarker runs on CPU. Expect \~2-5s per clip at 10 fps.
- **Split-screen detection.** MediaPipe may detect both faces in a split-screen
layout. The smart_crop.py script handles this by selecting the dominant side.
* **Low-light or out-of-frame:** If the speaker moves out of frame or lighting is
poor, face detection drops. smart\_crop.py fills gaps with interpolation and
falls back to the last known position. The `--smooth` parameter controls how
aggressively it fills gaps.
- **Multiple speakers talking over each other.** FaceLandmarker may jump between
faces. Increase `--smooth` to 7-9 for more stable tracking.

### Rendering

* **`-to` vs `-t`.** When `-ss` precedes `-i`, use `-t` (duration), NOT `-to`
(end time). `-to` is ignored for mp4 containers and the clip runs to the end.
* **moov atom not found.** Background ffmpeg processes may be killed before
writing the moov atom. Re-render in foreground mode with `timeout=300`.
* **360p source.** Direct crop from 360p to 1080x1920 is a 5.3x upscale.
The result will be visibly soft. Warn the user before rendering.
* **Batch timeouts.** At 1080p, render verticals in batches of 3. At 720p,
batches of 5 are safe.
* **Animated crop with face tracking adds \~20-30% render time** compared to
static crop, due to ffmpeg's per-frame crop expression evaluation.

### Remotion Captions

* **First-time setup requires `npm install`** in `scripts/captions\_remotion/`.
This downloads Remotion + Puppeteer (\~200MB). Only needed once.
* **Puppeteer downloads Chromium on first render.** Expect a \~150MB download.
If download fails, set `PUPPETEER\_EXECUTABLE\_PATH` to an existing Chrome/Chromium binary.
* **Transparent output requires VP8 codec.** Use `--codec=vp8` (not h264).
VP8 supports alpha channel; h264 does not.
* **Caption timing is relative to clip start.** render\_captions.py converts
absolute timestamps to clip-relative automatically.
* **Filler words are stripped automatically.** "um", "uh", "you know", "like",
"i mean" are removed from captions. If the user wants them kept, edit
the `FILLER\_WORDS` set in render\_captions.py.
* **Remotion falls back to ASS subtitles** if Node.js is not available.
The ASS method works but lacks per-word animations and custom colors.

### Crop Positioning

- **Face tracking handles positioning automatically.** Steps 7-8 (face_track.py + smart_crop.py) detect face position and compute optimal crop coordinates. No manual positioning needed.
- **Always verify with a test frame.** Render one frame before batch rendering to confirm composition.

### Disk \& Performance

* **Disk fills silently.** Delete WAV files immediately after transcription.
Check `df -h` before batch rendering.
* **Face tracking frame extraction** creates raw video in memory (not on disk),
so no additional disk space is needed beyond the output JSON.
* **File sizes.** Expect \~10-20MB per 40-50s vertical clip at crf 23,
\~20-50MB per horizontal clip at crf 18.
* **Caption overlays (WebM)** are \~2-5MB per clip and are rendered separately.

### Content Quality

* **Dangling pronouns.** If a clip starts with "He said..." or "That is..."
without context, move the start forward to a self-contained statement.
* **Negative framing.** Delete clips that portray the subject negatively.
Don't try to salvage with edits.
* **Timestamp vs content cue conflict.** When the user gives both a relative
timestamp AND a content cue ("start at 00:43 right before 'you don't need'"),
trust the content cue. The timestamp is approximate.

\---

## Configuration

These defaults work for most content. Adjust per-project as needed.

|Parameter|Default|When to Change|
|-|-|-|
|Whisper model|`base`|Use `small` for low VRAM, `large-v3` with GPU|
|Clip duration|15-55s|TikTok prefers 21-34s|
|Score threshold|60|Lower for longer videos with fewer highlights|
|Vertical crf|23|Use 18 for final master exports|
|Horizontal crf|18|Use 17 for archive quality|
|Handle duration|0s (exact cut)|Add 1s handles if user wants padding|
|Caption style|none|Only generate when explicitly requested|
|Platform|all|Single-platform if user specifies|

\---

## Dependencies

### Required

* **ffmpeg** — video/audio processing (`ffmpeg -version`)
* **Python 3.8+** — script execution
* **faster-whisper** — transcription (`pip install faster-whisper`)

### Optional

* **yt-dlp** — YouTube download (`pip install yt-dlp`)
* **NVIDIA GPU** — faster transcription and NVENC encoding
* **pysrt** — SRT subtitle parsing (`pip install pysrt`)

### Verify installation

```bash
ffmpeg -version 2>\&1 | head -1
python3 -c "import faster\_whisper; print('faster-whisper OK')"
python3 -c "import yt\_dlp; print('yt-dlp OK')" 2>/dev/null || echo "yt-dlp not installed (optional)"
```

\---

## Version History

* **v1.0** — Initial open-source release. Core pipeline: transcribe, score,
snap, crop, render, export. Three caption styles. Platform-specific encoding.

