"""The one-page application packet.

A single Markdown brief per job: fit score + rationale, tailored resume/cover
links, company talking points, the STAR stories, and the apply link — so the
human opens ONE file before deciding whether to apply.

JobPilot never applies. The packet ends with the apply link for the human.
"""
from __future__ import annotations

import json

from . import db, legitimacy, prep, profile, research, scoring


def build_packet(conn, job_id: int) -> str:
    job = db.get_job(conn, job_id)
    if job is None:
        raise ValueError(f"No job with id {job_id}")
    job = dict(job)
    appn = db.get_application(conn, job_id)
    sc = db.get_score(conn, job_id)

    c = profile.CONTACT
    lines = [
        f"# Application packet — {job.get('title') or 'role'} @ {job.get('company') or 'company'}",
        "",
        f"_{c['name']} · {c['location']} · {c['email']} · {c['github']}_",
        "",
        "## Fit score",
    ]

    if sc is not None:
        overall = sc["overall"]
        gate = bool(sc["gate_passed"])
        lines.append(f"**{overall:.2f} / 5 — {scoring.band(overall, gate)}** "
                     f"(gate {'PASS' if gate else 'FAIL'})")
        try:
            dims = json.loads(sc["dimensions_json"])
            weak = [d for d in scoring.GATES if dims.get(d, 5) < scoring.GATE_MIN]
            if weak:
                lines.append(f"\n> Gate concern: {', '.join(weak)} below {scoring.GATE_MIN}. "
                             f"Think hard before spending an application here.")
        except Exception:
            pass
        if sc["rationale"]:
            lines += ["", "<details><summary>Per-dimension rationale</summary>", "",
                      "```", sc["rationale"], "```", "</details>"]
    else:
        lines.append("_Not scored yet — run `jobpilot score " + str(job_id) + "`._")

    legit = legitimacy.assess(job.get("jd_text", ""), company=job.get("company", ""), title=job.get("title", ""))
    if legit["risk"] != "clear":
        icon = "🚩" if legit["risk"] == "high_risk" else "⚠️"
        lines += ["", f"## {icon} Legitimacy", f"> {legit['summary']}"]

    lines += ["", "## Tailored documents"]
    if appn and appn["resume_path"]:
        lines.append(f"- Resume: `{appn['resume_path']}`")
    else:
        lines.append("- Resume: _not built — run `jobpilot tailor " + str(job_id) + "`._")
    if appn and appn["cover_path"]:
        lines.append(f"- Cover letter: `{appn['cover_path']}`")
    else:
        lines.append("- Cover letter: _not built yet (needs a Claude reply via `tailor --reply`)._")

    lines += ["", "## Company talking points"]
    lines += [f"{i}. {p}" for i, p in enumerate(research.talking_points(job), 1)]

    lines += ["", "## Smart questions to ask"]
    lines += [f"{i}. {q}" for i, q in enumerate(research.smart_questions(job), 1)]

    lines += ["", "## STAR stories to lead with"]
    for story, matched in profile.select_stories(job.get("jd_text", ""), k=3):
        lines.append(f"- **{story['title']}** — {story['result']}")

    lines += ["", "## Apply (you do this — JobPilot never applies for you)",
              f"- Posting: {job.get('url')}",
              f"- Current status: **{appn['status'] if appn else 'discovered'}**",
              "- After you apply, run: `jobpilot status " + str(job_id) + " applied`",
              ""]
    return "\n".join(lines)
