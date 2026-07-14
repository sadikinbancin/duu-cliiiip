from pathlib import Path
import ast

path = Path('app.py')
text = path.read_text(encoding='utf-8')


def replace_once(old, new, label):
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected 1 match, found {count}')
    text = text.replace(old, new, 1)


# Ask Groq for Stage 4 campaign evaluation fields only when campaign mode is active.
replace_once(
    '    prompt = f"""\nAnda adalah editor video short-form profesional.',
    '''    response_schema = (
        '{"clips":[{"candidate_id":"C001","score":90,'
        '"title":"judul singkat","reason":"alasan pemilihan"}]}'
    )
    if campaign_requirements:
        response_schema = (
            '{"clips":[{"candidate_id":"C001","score":90,'
            '"title":"judul singkat","reason":"alasan pemilihan",'
            '"campaign_match_score":94,'
            '"campaign_fit_reason":"mengapa cocok dengan brief",'
            '"matched_requirements":["aturan yang terpenuhi"],'
            '"violated_requirements":["aturan yang dilanggar atau belum pasti"],'
            '"posting_notes":["aturan akun/posting yang harus dilakukan"]}]}'
        )

    prompt = f"""
Anda adalah editor video short-form profesional.''',
    'add response schema',
)

replace_once(
    '6. Jangan mengarang kepatuhan. Bila tidak ada kandidat sempurna, pilih yang paling\n   mendekati dan tulis kekurangannya pada reason.\n""".strip()',
    '6. Jangan mengarang kepatuhan. Bila tidak ada kandidat sempurna, pilih yang paling\n   mendekati dan tulis kekurangannya pada reason.\n7. Untuk setiap clip terpilih, isi campaign_match_score 0-100, campaign_fit_reason,\n   matched_requirements, violated_requirements, dan posting_notes.\n8. matched_requirements dan violated_requirements hanya untuk aturan isi/edit clip.\n   posting_notes hanya untuk aturan akun/posting yang harus dilakukan pengguna.\n""".strip()',
    'extend campaign rules',
)

replace_once(
    'Hindari kandidat yang tumpang tindih. Balas JSON murni dengan format:\n{{"clips":[{{"candidate_id":"C001","score":90,"title":"judul singkat","reason":"alasan pemilihan"}}]}}',
    'Hindari kandidat yang tumpang tindih. Balas JSON murni dengan format:\n{response_schema}',
    'use response schema',
)

replace_once(
    '        candidate["title"] = str(result.get("title") or "Highlight")[:80]\n        candidate["reason"] = str(result.get("reason") or "")[:300]\n        ranked.append(candidate)',
    '''        candidate["title"] = str(result.get("title") or "Highlight")[:80]
        candidate["reason"] = str(result.get("reason") or "")[:300]
        if campaign_requirements:
            try:
                campaign_match_score = int(float(result.get("campaign_match_score", 50)))
            except (TypeError, ValueError):
                campaign_match_score = 50
            candidate["campaign_match_score"] = int(clamp(campaign_match_score, 0, 100))
            candidate["campaign_fit_reason"] = str(
                result.get("campaign_fit_reason")
                or result.get("reason")
                or candidate.get("campaign_visual_fit")
                or ""
            )[:500]
            candidate["matched_requirements"] = result.get("matched_requirements") or []
            candidate["violated_requirements"] = result.get("violated_requirements") or []
            candidate["posting_notes"] = result.get("posting_notes") or []
        ranked.append(candidate)''',
    'parse campaign results',
)

# Replace result writer so existing JSON output and ZIP expose Stage 4 fields.
start = text.find('def write_clips(selected: list[dict], job: Path):')
end = text.find('\n\ndef mediapipe_crop(', start)
if start == -1 or end == -1:
    raise SystemExit('write_clips block not found')

writer = '''def write_clips(selected: list[dict], job: Path, campaign_requirements: str = ""):
    campaign_requirements = (campaign_requirements or "").strip()
    campaign_mode = bool(campaign_requirements)
    clips = []

    for index, item in enumerate(selected, 1):
        def as_list(value):
            if value is None:
                return []
            if isinstance(value, list):
                return [str(entry)[:240] for entry in value if str(entry).strip()][:12]
            return [str(value)[:240]] if str(value).strip() else []

        campaign_match_score = None
        campaign_fit_reason = ""
        matched_requirements = []
        violated_requirements = []
        posting_notes = []

        if campaign_mode:
            try:
                campaign_match_score = int(
                    clamp(int(float(item.get("campaign_match_score", 50))), 0, 100)
                )
            except (TypeError, ValueError):
                campaign_match_score = 50
            campaign_fit_reason = str(
                item.get("campaign_fit_reason")
                or item.get("reason")
                or item.get("campaign_visual_fit")
                or "Kecocokan dinilai dari transkrip dan bukti visual."
            )[:500]
            matched_requirements = as_list(item.get("matched_requirements"))
            violated_requirements = as_list(item.get("violated_requirements"))
            posting_notes = as_list(item.get("posting_notes"))
            if not matched_requirements and item.get("campaign_visual_fit"):
                matched_requirements = as_list(item.get("campaign_visual_fit"))
            if not violated_requirements and item.get("campaign_visual_risk"):
                violated_requirements = as_list(item.get("campaign_visual_risk"))

        clips.append(
            {
                "id": f"{index:02d}",
                "start": float(item["start"]),
                "end": float(item["end"]),
                "duration": float(item["end"] - item["start"]),
                "title": item.get("title") or f"Highlight {index}",
                "score": int(item.get("score", 70)),
                "reason": item.get("reason") or "Heuristic selection",
                "visual_score": int(item.get("visual_score", 0) or 0),
                "hook_visual": item.get("hook_visual", ""),
                "visual_summary": item.get("visual_summary", ""),
                "visual_risk": item.get("visual_risk", ""),
                "campaign_match_score": campaign_match_score,
                "campaign_fit_reason": campaign_fit_reason,
                "matched_requirements": matched_requirements,
                "violated_requirements": violated_requirements,
                "posting_notes": posting_notes,
                "campaign_visual_fit": item.get("campaign_visual_fit", ""),
                "campaign_visual_risk": item.get("campaign_visual_risk", ""),
            }
        )

    payload = {
        "campaign_mode": campaign_mode,
        "campaign_requirements": campaign_requirements or None,
        "clips": clips,
    }
    path = job / "clips.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (job / "campaign_evaluation.json").write_text(
        json.dumps(
            {
                "campaign_mode": campaign_mode,
                "campaign_requirements": campaign_requirements or None,
                "clips": [
                    {
                        "id": clip["id"],
                        "title": clip["title"],
                        "campaign_match_score": clip["campaign_match_score"],
                        "campaign_fit_reason": clip["campaign_fit_reason"],
                        "matched_requirements": clip["matched_requirements"],
                        "violated_requirements": clip["violated_requirements"],
                        "posting_notes": clip["posting_notes"],
                    }
                    for clip in clips
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path, payload
'''
text = text[:start] + writer + text[end:]

replace_once(
    '        clips_path, clips = write_clips(selected, job)',
    '        clips_path, clips = write_clips(selected, job, campaign_requirements)',
    'connect result writer',
)

replace_once(
    '            job / "gemini_vision.json",\n            job / "clips.json",',
    '            job / "gemini_vision.json",\n            job / "clips.json",\n            job / "campaign_evaluation.json",',
    'include evaluation file',
)

ast.parse(text)
path.write_text(text, encoding='utf-8')
