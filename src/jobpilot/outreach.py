"""Outreach messages — referrals and recruiter notes.

Networking is the highest-leverage thing you can do to get hired, so JobPilot
drafts short, honest outreach you can send after a human reviews it. Built only
from real profile facts and the JD. Follows the same writing style as the cover
letter: natural voice, no em dashes or hyphenated compounds, no Oxford comma,
no clichés. JobPilot never sends these for you.
"""
from __future__ import annotations

from . import profile, research

NAME = profile.CONTACT["name"]


def _best_story(jd_text: str):
    chosen = profile.select_stories(jd_text or "", k=1)
    return chosen[0][0] if chosen else None


def referral_message(job: dict) -> str:
    """A short LinkedIn-style note asking a contact for a referral."""
    company = job.get("company") or "your company"
    role = job.get("title") or "the open role"
    story = _best_story(job.get("jd_text", ""))
    proof = f" I recently {story['result'][0].lower()}{story['result'][1:]}" if story else ""
    proof = proof.rstrip(".") + "." if proof else ""
    return (
        f"Hi [name], I noticed {company} is hiring for {role} and it lines up well with my background."
        f"{(' ' + proof) if proof else ''} I am finishing my M.S. in Computer Science at Boston University "
        f"and would love a referral if you think I am a fit. Happy to send my resume and a short summary. "
        f"Thanks either way.\n\n{NAME}"
    )


def recruiter_message(job: dict) -> str:
    """A concise note to a recruiter or hiring manager."""
    company = job.get("company") or "your team"
    role = job.get("title") or "the role"
    stack = research.tech_in_jd(job.get("jd_text", ""))
    stack_line = f" My work maps closely to {', '.join(stack[:3])}." if stack else ""
    story = _best_story(job.get("jd_text", ""))
    proof = f" For example, {story['action'][0].lower()}{story['action'][1:]}" if story else ""
    return (
        f"Hi [name], I am applying for {role} at {company} and wanted to reach out directly."
        f"{stack_line}{proof.rstrip('.') + '.' if proof else ''} I am Boston based and open to relocation or remote. "
        f"Could we set up a quick call? I can share specifics on how I would contribute.\n\n{NAME}"
    )


def build_outreach(job: dict) -> dict:
    return {
        "referral": referral_message(job),
        "recruiter": recruiter_message(job),
    }


def build_outreach_prompt(job: dict) -> str:
    return f"""Write two short outreach messages for Gagan Veginati applying to the job below.
Use ONLY facts that fit a real early-career CS candidate (MS at Boston University, AI/ML, data,
MLOps, full-stack). Do not invent specifics. Each under 90 words. Natural voice, no em dashes,
no hyphenated compounds, no Oxford comma, no clichés.
1) A LinkedIn note asking a current employee for a referral.
2) A direct note to the recruiter or hiring manager.

JOB: {job.get('title','')} @ {job.get('company','')}
{job.get('jd_text','')}"""
