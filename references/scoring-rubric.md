# Neuro-Engagement Scoring Rubric v2.0

**Informed by:** Meta's TribeV2 multimodal brain encoding model
**Supersedes:** Original 5-dimension rubric (v1.0)
**Date:** May 2026

## Scoring Formula (8 Dimensions)

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

Minimum threshold: **65/100**. Duration sweet spot: **15-55 seconds**.

## Dimension 1: Visual Engagement (Weight: 0.12)

| Level | Score | Indicators |
|-------|-------|-------------|
| Dynamic | 85-100 | Active gesticulation, scene changes, B-roll, multiple angles |
| Expressive talking head | 70-84 | Hand gestures, facial variation, minor head movement |
| Standard talking head | 50-69 | Steady face, occasional small gestures — podcast baseline |
| Static | 20-49 | Low motion, flat background, same expression |
| No visual stimulus | 0-19 | Still frame, slide deck, audio-only |

**Visual novelty booster (+10):** Sudden visual change (prop, camera zoom, B-roll cut).

## Dimension 2: Auditory Dynamics (Weight: 0.12)

| Level | Score | Indicators |
|-------|-------|-------------|
| Highly dynamic | 85-100 | Wide pitch range, pace shifts, emotional voice breaks, laughter |
| Emotionally modulated | 70-84 | Clear emotional coloring, varied pacing, effective pausing |
| Engaged conversational | 50-69 | Normal variation, interested tone — baseline |
| Flat / monotone | 20-49 | Limited pitch variation, steady pace, "reading" quality |
| Robotic / artificial | 0-19 | Synthesized speech, no emotional variation |

**Transcript cues:** `[laughter]` +5, CAPS/bold emphasis +3, `...`/`—` pause +3, `?!` +5, `(voice breaks)` +8, 3+ turns in <10s +5.

## Dimension 3: Linguistic Density (Weight: 0.12)

| Level | Score | Indicators |
|-------|-------|-------------|
| Framework-level | 85-100 | Novel mental model, counterintuitive claim, quotable one-liner |
| Insight-rich | 70-84 | Specific advice with examples, fresh framing, actionable takeaway |
| Solid content | 50-69 | Good advice, some specifics, familiar territory — baseline |
| General commentary | 30-49 | Broad observations, opinion without support |
| Filler / small talk | 0-29 | Pleasantries, transitions, tangential anecdotes |

**Novelty adjustments:** +10 counterintuitive in context, +5 domain-specific language, -10 redundancy, -5 per 20% fillers.

## Dimension 4: Cross-Modal Synchronization (Weight: 0.10)

The "goosebumps" dimension — voice, face, and words all peak together.

| Level | Score | Indicators |
|-------|-------|-------------|
| Triple convergence | 85-100 | Voice emotion + expression + word content all amplify the same moment |
| Dual alignment | 65-84 | Two of three modalities aligned |
| Single channel dominant | 40-64 | One modality carries weight, others neutral |
| Modality conflict | 20-39 | Channels out of sync (calm voice with intense content) |
| Missing modalities | 10-19 | Audio-only, text-only |

## Dimension 5: Hook Strength (Weight: 0.15)

| Archetype | Example | Score Range |
|-----------|---------|-------------|
| Bold / Contrarian | "Everything you know about X is wrong" | 80-100 |
| Curiosity Gap | "There's one thing nobody tells you about..." | 75-95 |
| Value Promise | "Here's the exact framework I used to..." | 70-90 |
| Pattern Interrupt | "Wait, let me show you something weird" | 70-90 |
| Payoff Preview | "By the end of this you'll know how to..." | 65-85 |
| Mid-Action Start | Starts mid-sentence with energy | 60-80 |
| Hidden Knowledge | "The secret that [authority] doesn't share" | 60-80 |
| Weak / Generic | "So today I want to talk about..." | 10-40 |

**Boosters (+5-10):** specific numbers, named entities, personal experience, time pressure.
**Cross-modal hook bonus (+5):** simultaneous visual + auditory peak on the hook line.

## Dimension 6: Emotional Arc (Weight: 0.12)

| Arc Type | Score | Description |
|----------|-------|-------------|
| Build → Peak → Release | 85-100 | Classic story arc. Viewer feels a journey in 30-60s. |
| Sustained peak with micro-variation | 75-84 | High energy with small ebbs and flows. |
| Steady moderate | 50-74 | Consistent engagement, no strong arc. |
| Flat | 25-49 | No emotional variation. Same tone throughout. |
| Descending | 0-24 | Starts strong but fades. |

## Dimension 7: Standalone Coherence (Weight: 0.15)

| Level | Score | Criteria |
|-------|-------|----------|
| Self-contained narrative | 85-100 | Complete arc: setup → development → payoff. |
| Complete idea, minor gaps | 65-84 | Clear point, one sentence of context would help. |
| References earlier content | 40-64 | "As I said before..." — viewer missed setup. |
| Requires prior context | 10-39 | Depends on knowing who people are or episode premise. |
| Fragment | 0-9 | Starts/ends mid-thought, incomplete sentence. |

**Dangling reference check:** Read first 5 words — pronoun without antecedent, proper name without intro, or demonstrative without referent → fails. Move start forward.

## Dimension 8: Payoff / Resolution (Weight: 0.12)

| Resolution Type | Score | Description |
|-----------------|-------|-------------|
| Unexpected twist / reveal | 90-100 | Ending recontextualizes everything before it. |
| Satisfying closure | 80-89 | Tension resolves cleanly. Punchline lands. |
| Actionable takeaway | 65-79 | Clear CTA, lesson, or framework takeaway. |
| Natural stop | 40-64 | Idea completes, no strong resolution. |
| Trails off | 10-39 | Content loses energy and just stops. |
| Abrupt cut | 0-9 | Mid-sentence or mid-thought cutoff. |

## Diversity Constraints

**1. Modality Balance:** Across 6-8 clips, at least 2 with Visual ≥ 70, 2 with Auditory ≥ 70, 2 with Linguistic ≥ 70. No single modality dominates.

**2. Arc Variety:** At least 1 "Build → Peak → Release" arc. At most 2 "Unexpected twist" resolutions.

**3. Temporal Spacing:** Clips at least 90s apart in the source. If two candidates <60s apart, pick the higher-scoring one.

**4. Content Diversity:** Max 2 clips on same subtopic. Max 2 clips with same hook archetype. At least 3 different emotional tones.

## Quick-Score Reference Card

| Dimension | Quick Check | Low (0-39) | Mid (40-69) | High (70-100) |
|-----------|-------------|------------|-------------|---------------|
| Visual (V) | Face + motion? | Static / no video | Talking head | Dynamic / expressive |
| Auditory (A) | Voice variation? | Flat / monotone | Engaged | Passionate / modulated |
| Linguistic (L) | Info density? | Filler / small talk | Solid content | Framework / insight |
| Cross-Modal (X) | Voice+face+words amplify? | Conflict / missing | Single channel | Dual/triple convergence |
| Hook (H) | First 3-5 words grab? | Generic / weak | Mid-action / hidden | Bold claim / curiosity |
| Arc (Arc) | Does energy change? | Descending / flat | Steady moderate | Build → peak → release |
| Coherence (C) | Complete thought? | Fragment / needs context | Minor gaps | Self-contained arc |
| Payoff (P) | Satisfying ending? | Trails off / abrupt | Natural stop | Punchline / twist |

## Presenting Candidates

| # | Start | End | Dur | Hook | Engagement Score | Rationale |
|---|-------|-----|-----|------|-----------------|-----------|
| 1 | 04:22 → 05:01 | 39s | "Nobody talks about..." | 87 | Contrarian take with data |
