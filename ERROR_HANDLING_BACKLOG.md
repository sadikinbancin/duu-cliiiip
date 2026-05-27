# Remaining Error-Handling Gaps (Ranked 11-50)
# For video-podcast-clipper — to be patched in a future pass
# Generated 2026-05-27 by Codex severity audit

## TIER 2 — HIGH (11-20): Produces broken/wrong output but pipeline may complete

11. Step 3(a): No audio/silent audio extraction failure path — missing/empty audio makes transcription invalid
12. Step 3(d): VAD may strip all words, seg.words assumed — can erase transcript or crash
13. Step 11(a): Assumes words exist for every clip — caption gen crashes on silent clips
14. Step 10(a): Missing crop_data.json no fallback — prevents rendering; need center-crop fallback
15. Step 8(a): Missing face_data.json crashes — face tracking failure blocks crop; need center fallback
16. Step 7(b): Per-clip frame extraction failures not independent — one bad segment blocks all face tracking
17. Step 10(c): No per-clip retry — transient render failure sinks whole batch
18. Step 12(e): Batch export no resume/manifest — interrupted exports hard to recover
19. Step 1(b): df -h doesn't enforce 2x disk rule (FIXED in Step 1 patch above)
20. Step 2(a): curl/yt-dlp exit codes unchecked (FIXED in Step 2 patch above)

## TIER 3 — MEDIUM (21-35): Degraded quality or avoidable late failures

21. Step 1(a): No early tool validation (FIXED in Step 1 patch above)
22. Step 3(b): Whisper model download/OOM/import failures not caught — need retry/fallback
23. Step 12(d): NVENC no CPU fallback — export fails on machines without NVIDIA GPU
24. Step 11(b): Remotion path/setup not validated — Node, packages, project paths unchecked
25. Step 11(c): WebM overlays not verified — transparent overlays may be missing/opaque/mistimed
26. Step 7(a): No MediaPipe model download fallback — first run or offline systems fail
27. Step 7(c): No face tracking quality gate — bad tracking produces unusable crops silently
28. Step 8(d): Keyframe data not validated — bad keyframes cause erratic crop motion
29. Step 8(c): Long gaps interpolated indefinitely — crop drifts through long detection failures
30. Step 7(d): Wrong face in split-screen — technically valid but editorially wrong crops
31. Step 4(c): Long transcripts exceed context — analysis fails on very long content
32. Step 4(b): No handling for zero candidates above threshold — pipeline stalls
33. Step 4(a): Visual/auditory scoring requested before features exist — scores may be fabricated
34. Step 5(a): User choices not validated — invalid selections create malformed manifests
35. Step 6(c): Snapping can push outside bounds — creates negative starts, overlong clips

## TIER 4 — LOW (36-50): Cosmetic, edge-case, or happy-path-only

36. Step 6(a): snap_boundaries.py no command path/failure behavior
37. Step 9(c): No temp-output/atomic-rename for clip extraction
38. Step 12(c): No platform compliance validation after encoding
39. Step 12(a): Ambiguous captioned vs non-captioned input for exports
40. Step 10(d): Horizontal writes to exports/vertical/ — path confusion
41. Step 12(b): Output dir inconsistency (exports/shorts vs shorts/)
42. Step 11(d): ASS fallback unspecified — caption fallback exists conceptually
43. Step 11(e): Font availability assumed — missing fonts degrade appearance
44. Step 6(b): No fallback when no punctuation near cut — less natural cuts
45. Step 6(d): grep silence detection nonzero when no silence — false failure
46. Step 3(c): Hardcoded language=en — non-English sources transcribe poorly
47. Step 4(d): Guest selection assumes diarization — speaker targeting may be wrong
48. Step 5(c): Re-analyze undefined — blocks iteration but not happy path
49. Step 2(c): HLS/DASH/signed URLs not detected (partially addressed in Step 2)
50. Step 1(c): Audio-only sources not rejected (addressed as WARNING in Step 1)
