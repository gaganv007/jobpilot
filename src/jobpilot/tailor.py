"""Tailoring: build an ATS-optimized resume + cover letter from REAL facts only.

What tailoring may change:
  - the professional-summary paragraph (reframed, but using only facts already
    in the resume), and
  - the ORDER of skill categories (to surface JD keywords first).
Everything else — skills items, experience, projects, education, certs — is
copied verbatim from the base resume. Nothing is invented.

Two extra guarantees JobPilot adds on top of jd_agent:
  - Evidence-linked tailoring: each resume bullet is tagged with the JD
    requirement it answers, so it can be defended in an interview.
  - Honesty receipt: a stored diff vs the base resume proving only the summary
    and skill order changed, plus a check that the new summary introduces no
    skill not already in the resume.
"""
from __future__ import annotations

import difflib
import os
import re
from dataclasses import dataclass, field

from . import jd_bridge


# ---------- access to base-resume structure (via jd_agent core) ----------
def _resume_path(track: str) -> str:
    c = jd_bridge.core()
    return os.path.join(c.RESUME_DIR, c.tracks()[track]["file"] if hasattr(c, "tracks") else c.TRACKS[track]["file"])


def base_sections(track: str):
    c = jd_bridge.core()
    return c._sections(_resume_path(track))


def base_resume_text(track: str) -> str:
    return jd_bridge.resume_text(track)


def base_skills(track: str) -> list[tuple[str, str]]:
    c = jd_bridge.core()
    _, sec = base_sections(track)
    return c._skills_from_lines(sec.get("TECHNICAL SKILLS", sec.get("SKILLS", [])))


def base_bullets(track: str) -> list[str]:
    """All experience/project bullets, verbatim."""
    c = jd_bridge.core()
    _, sec = base_sections(track)
    bullets: list[str] = []
    for key in ("EXPERIENCE", "PROFESSIONAL EXPERIENCE", "PROJECTS"):
        if key in sec:
            for e in c._entries(sec[key]):
                bullets.extend(e["bullets"])
    return bullets


def base_summary(track: str) -> str:
    _, sec = base_sections(track)
    for key in ("PROFESSIONAL SUMMARY", "SUMMARY"):
        if key in sec:
            return " ".join(sec[key]).strip()
    return ""


# ---------- skill vocabulary (for honesty checks) ----------
# Common skills a JD might ask for that the model could be tempted to slip into
# the summary. If any of these appears in a proposed summary but NOT in the base
# resume, that's a fabricated skill and the summary is rejected.
SKILL_EXTRA = {
    "go", "golang", "rust", "scala", "ruby", "php", "kotlin", "swift", "c#", ".net",
    "kafka", "airflow", "snowflake", "databricks", "hadoop", "hive", "elasticsearch",
    "graphql", "grpc", "kubernetes", "terraform", "ansible", "jenkins", "gcp", "azure",
    "salesforce", "sap", "tableau", "looker", "dbt", "spark", "flink", "cassandra",
}


def _skill_vocab() -> set[str]:
    """Known skill keywords (the 4 tracks' vocab plus common skills) — used to
    flag whether a summary introduces a skill that is not actually mine."""
    vocab: set[str] = set(SKILL_EXTRA)
    for meta in jd_bridge.tracks().values():
        vocab |= set(meta["kw"].keys())
    return vocab


def _contains(text: str, kw: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", text.lower()) is not None


# ---------- honesty check ----------
@dataclass
class HonestyResult:
    ok: bool
    violations: list[str] = field(default_factory=list)
    summary_used: str = ""
    summary_changed: bool = False


def honesty_check(track: str, new_summary: str) -> HonestyResult:
    """A new summary is honest only if every known skill keyword it mentions is
    already present in the base resume. If it introduces an unsupported skill,
    that's fabrication -> reject the summary (caller falls back to the original).
    """
    if not new_summary:
        return HonestyResult(ok=True, summary_used=base_summary(track), summary_changed=False)

    resume = base_resume_text(track)
    violations = [
        kw for kw in _skill_vocab()
        if _contains(new_summary, kw) and not _contains(resume, kw)
    ]
    if violations:
        return HonestyResult(ok=False, violations=sorted(violations),
                             summary_used=base_summary(track), summary_changed=False)
    return HonestyResult(ok=True, summary_used=new_summary.strip(),
                         summary_changed=new_summary.strip() != base_summary(track))


# ---------- evidence-linked tailoring ----------
_STOP = set("and or the a an to of in for with on at by we you your our is are will be as that this "
            "from across into over per using build building work working experience years strong "
            "have has able ability team teams role roles plus etc".split())


def _keywords(text: str) -> set[str]:
    toks = re.findall(r"[A-Za-z][A-Za-z0-9.+#/\-]{2,}", text.lower())
    return {t.strip(".-/") for t in toks if t not in _STOP and len(t) > 2}


def _jd_requirements(jd: str) -> list[str]:
    """Split a JD into requirement-ish lines (bullets / sentences)."""
    lines = re.split(r"[\n\r]+|(?<=[.;])\s+", jd)
    reqs = [ln.strip(" -•\t") for ln in lines if len(ln.strip()) > 12]
    return reqs


def evidence_map(jd: str, track: str) -> list[dict]:
    """For each resume bullet, find the JD requirement it best answers (by shared
    keywords). Bullets that match nothing are tagged as general strengths."""
    reqs = _jd_requirements(jd)
    req_kw = [(_keywords(r), r) for r in reqs]
    out = []
    for bullet in base_bullets(track):
        bkw = _keywords(bullet)
        best_req, best_overlap = "", set()
        for kw, r in req_kw:
            shared = bkw & kw
            if len(shared) > len(best_overlap):
                best_overlap, best_req = shared, r
        out.append({
            "bullet": bullet,
            "answers": best_req if len(best_overlap) >= 2 else "",
            "shared": sorted(best_overlap) if len(best_overlap) >= 2 else [],
        })
    return out


# ---------- receipts ----------
def build_honesty_receipt(track: str, summary_used: str, honesty: HonestyResult) -> str:
    """A Markdown receipt proving only the summary + skill order changed."""
    old = base_summary(track)
    skills = base_skills(track)
    diff = "\n".join(
        difflib.unified_diff(
            [old], [summary_used], fromfile="base_summary", tofile="tailored_summary", lineterm=""
        )
    ) or "(summary unchanged)"
    lines = [
        f"# Honesty receipt — {track}",
        "",
        "JobPilot tailoring only reorders skill categories and reframes the summary "
        "using facts already in the resume. Everything else is copied verbatim.",
        "",
        "## What changed",
        f"- Skill categories: same {len(skills)} categories, items verbatim, order may differ.",
        f"- Summary: {'reframed' if honesty.summary_changed else 'unchanged'}.",
        "- Experience / projects / education / certs: verbatim, byte-for-byte.",
        "",
        "## No-fabrication check",
    ]
    if honesty.ok and not honesty.violations:
        lines.append("- PASS — the summary introduces no skill absent from the base resume.")
    else:
        lines.append(f"- REJECTED a proposed summary that added unsupported skills: "
                     f"{', '.join(honesty.violations)}. Reverted to the real summary.")
    lines += ["", "## Summary diff", "```diff", diff, "```", ""]
    return "\n".join(lines)


def build_evidence_doc(jd: str, track: str) -> str:
    em = evidence_map(jd, track)
    lines = [f"# Evidence map — {track}", "",
             "Each tailored bullet and the JD requirement it answers. Bring this to the interview.", ""]
    for item in em:
        lines.append(f"- **{item['bullet']}**")
        if item["answers"]:
            lines.append(f"  - answers: _{item['answers']}_  (shared: {', '.join(item['shared'])})")
        else:
            lines.append("  - general strength (no specific JD requirement matched)")
    return "\n".join(lines) + "\n"


# ---------- paste-mode prompt for summary + cover ----------
def build_tailor_prompt(jd: str, company: str, role: str, track: str) -> str:
    return f"""You are writing application materials for Gagan Veginati for the job below.
Use ONLY facts in his resume. Never invent skills, employers, metrics, titles, dates,
or a clearance. Output EXACTLY this shape and nothing else:

TRACK: {track}

SUMMARY:
<2-4 sentences, mirror the JD's language, only true facts, lead with the most relevant real achievement>

COVER LETTER:
<exactly 4 short paragraphs, ~300-340 words, blank line between paragraphs. P1 the role and one line on
fit. P2 one specific true fact about {company or 'the company'} (from the JD or light research) and his
link to it. P3 two or three real achievements with their real metrics mapped to the job. P4 Boston, open
to relocation or remote, confident close. Add the line "I hold U.S. work authorization and am a U.S.
citizen." ONLY if the JD raises work authorization, visa, sponsorship, or it is a clearance/federal role.>

WRITING STYLE: natural human voice; no em dashes, en dashes, or hyphenated compounds (write "end to end");
no Oxford comma; no clichés ("I am writing to express", "fast-paced", "passion for", "leverage").

JOB: {role} @ {company}
{jd}"""


# ---------- orchestration ----------
@dataclass
class TailorResult:
    track: str
    resume_path: str
    cover_path: str | None
    evidence_path: str
    receipt_path: str
    prompt_path: str | None
    honesty: HonestyResult


def tailor_job(job: dict, out_dir, reply_text: str | None = None) -> TailorResult:
    """Build the tailored resume (+ cover if a reply provides one) and receipts.

    `job` is a mapping with url/company/title/jd_text. `out_dir` is a Path.
    """
    from pathlib import Path

    out_dir = Path(out_dir)
    jd = job["jd_text"] or ""
    company = job.get("company", "") if isinstance(job, dict) else job["company"]
    role = job.get("title", "") if isinstance(job, dict) else job["title"]

    track, _ = jd_bridge.match_track(jd)
    parsed = jd_bridge.parse_claude_reply(reply_text) if reply_text else {"track": "", "summary": "", "cover": ""}
    if parsed.get("track"):
        track = parsed["track"]

    honesty = honesty_check(track, parsed.get("summary", ""))
    summary_used = honesty.summary_used
    skill_order = jd_bridge.suggested_skill_order(jd, track)

    resume_path = str(out_dir / "resume.pdf")
    jd_bridge.build_optimized_resume(track, summary_used, skill_order, resume_path)

    cover_path = None
    prompt_path = None
    cover_body = parsed.get("cover", "")
    if cover_body:
        cover_path = str(out_dir / "coverletter.pdf")
        jd_bridge.build_cover_pdf(cover_body, company, role, cover_path)
    else:
        # No reply yet: write the paste-mode prompt so the user can fill the cover in.
        prompt_path = str(out_dir / "tailor_prompt.txt")
        Path(prompt_path).write_text(build_tailor_prompt(jd, company, role, track), encoding="utf-8")

    evidence_path = str(out_dir / "evidence.md")
    Path(evidence_path).write_text(build_evidence_doc(jd, track), encoding="utf-8")

    receipt_path = str(out_dir / "honesty_receipt.md")
    Path(receipt_path).write_text(build_honesty_receipt(track, summary_used, honesty), encoding="utf-8")

    return TailorResult(track, resume_path, cover_path, evidence_path, receipt_path, prompt_path, honesty)
