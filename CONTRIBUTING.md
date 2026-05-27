# Contributing

Thanks for considering contributing to Video Podcast Clipper.

## How to Contribute

1. **Open an issue first** — discuss what you want to build before writing code. This avoids wasted effort on something that may not fit the project direction.

2. **Areas where help is especially valuable:**
   - New Remotion caption styles (compositions in `scripts/captions_remotion/src/`)
   - Platform export presets (Snapchat, LinkedIn, X/Twitter video)
   - Multi-language transcription support (languages beyond English)
   - GPU pipeline optimization (batched face tracking, parallel encoding)
   - Split-screen detection improvements (better guest/host heuristics)
   - Test coverage (the pipeline currently has no automated tests)

3. **Keep PRs focused** — one feature or fix per pull request.

4. **Python code style** — follow PEP 8. Type hints appreciated but not required. Scripts are designed to be readable by AI agents as well as humans.

5. **Test your changes** — run the full pipeline on a short test video before submitting.

## Development Setup

```bash
git clone https://github.com/your-org/video-podcast-clipper.git
cd video-podcast-clipper
pip install faster-whisper mediapipe opencv-python-headless
# Optional: pip install yt-dlp
# Optional: cd scripts/captions_remotion && npm install
```

## Architecture Notes

The pipeline is intentionally modular — each step is a standalone script that reads/writes JSON. This design choice means:

- Steps can be run independently or by an AI agent orchestrating them
- Intermediate data (transcript, face positions, crop keyframes) is inspectable and debuggable
- Individual components can be swapped (swap faster-whisper for WhisperX, swap MediaPipe for YOLO face detection, etc.)

The scoring rubric in `references/scoring-rubric.md` is the intellectual core — improvements to the rubric improve every clip the pipeline produces.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
