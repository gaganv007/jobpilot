"""Rank discovered/scanned roles by fit to MY resume, and filter out roles that
do not make sense for an early-career candidate.

Why this exists: a raw company feed returns everything — Principal, Director, PM,
Sales. That is noise. This module scores each role against my 4 resume tracks
(best-fit track + keyword coverage) and tags its seniority from the title, so the
UI can show the roles that actually fit me first and hide senior postings by
default. It never invents skills; relevance is measured, not faked.
"""
from __future__ import annotations

import re
from functools import lru_cache

# Title signals. Order matters: entry words win over senior words
# ("Junior Staff Engineer" is rare, but entry intent should dominate).
ENTRY_RE = re.compile(
    r"\b(intern|internship|new[\s-]?grad|graduate|junior|jr\.?|entry[\s-]?level|"
    r"early[\s-]?career|apprentice|trainee|campus|university|associate)\b", re.I)
SENIOR_RE = re.compile(
    r"\b(senior|sr\.?|staff|principal|distinguished|fellow|lead|"
    r"director|vp|vice\s+president|head\s+of|chief|architect|"
    r"manager|mgr|\biii\b|\biv\b|10\+\s*years|8\+\s*years)\b", re.I)

# Role families I do NOT target (I am engineering/ML/data, not sales/PM/etc.).
OFFTRACK_RE = re.compile(
    r"\b(sales|account\s+executive|alliance|partnership|business\s+development|"
    r"bdr|sdr|recruit\w*|talent|marketing|customer\s+success|support\s+engineer|"
    r"solutions?\s+consultant|product\s+manager|program\s+manager|project\s+manager|"
    r"designer|legal|finance|accountant|operations\s+manager|people\s+ops)\b", re.I)


def detect_seniority(title: str) -> str:
    """entry | mid | senior, from the job title."""
    t = title or ""
    if ENTRY_RE.search(t):
        return "entry"
    if SENIOR_RE.search(t):
        return "senior"
    return "mid"


def _fit_with_engine(text: str):
    """(fit 0-100, track, coverage, weight) using jd_agent matching, or None.

    Uses only match_track (cheap regex over the JD) so ranking 100+ roles stays
    fast — no per-candidate resume-PDF reads here. weight is the best track's
    keyword-overlap strength; off-track roles (sales/PM) score ~0 and drop out.
    """
    from . import jd_bridge

    if not jd_bridge.available():
        return None
    try:
        track, ranked = jd_bridge.match_track(text)
        weight = ranked[0][1] if ranked else 0
        fit = min(100, weight * 7)
        return fit, track, 0.0, weight
    except Exception:
        return None


# Fallback role vocab when jd_agent is unavailable (e.g. CI).
_FALLBACK = {
    "AI/ML Engineer": ("machine learning", "ml", "deep learning", "llm", "nlp", "pytorch", "model", "ai"),
    "Data Scientist / Analyst": ("data scientist", "analytics", "sql", "statistics", "dashboard", "forecasting"),
    "DevOps / MLOps Engineer": ("devops", "mlops", "kubernetes", "ci/cd", "infrastructure", "platform"),
    "Software Engineer (Full-Stack)": ("software engineer", "full stack", "react", "backend", "api", "typescript"),
}


def _fit_fallback(text: str):
    tl = (text or "").lower()
    best, best_n = "AI/ML Engineer", 0
    for track, kws in _FALLBACK.items():
        n = sum(1 for k in kws if k in tl)
        if n > best_n:
            best, best_n = track, n
    fit = min(100, best_n * 18)
    return fit, best, 0.0, best_n


def annotate(candidate: dict) -> dict:
    """Add fit, track, seniority, off_track, relevant to a candidate (in place)."""
    text = f"{candidate.get('title','')} {candidate.get('title','')} {candidate.get('jd_text','')}"
    res = _fit_with_engine(text) or _fit_fallback(text)
    fit, track, coverage, weight = res
    candidate["fit"] = int(fit)
    candidate["track"] = track
    candidate["seniority"] = detect_seniority(candidate.get("title", ""))
    candidate["off_track"] = bool(OFFTRACK_RE.search(candidate.get("title", "")))
    # "relevant" = an engineering/ML/data role with a real keyword signal
    candidate["relevant"] = (not candidate["off_track"]) and (weight >= 3 or fit >= 35)
    return candidate


@lru_cache(maxsize=4096)
def _cached_fit(title: str, jd_text: str) -> tuple[int, str, str]:
    c = annotate({"title": title, "jd_text": jd_text})
    return c["fit"], c["track"], c["seniority"]


def quick_fit(title: str, jd_text: str) -> dict:
    """Instant, cheap fit estimate for a job (no resume-PDF reads, cached).

    Used to rank jobs the moment they are added, before the full rubric runs."""
    fit, track, seniority = _cached_fit(title or "", jd_text or "")
    return {"fit": fit, "track": track, "seniority": seniority}


def rank(
    candidates: list[dict],
    include_senior: bool = False,
    only_relevant: bool = True,
) -> list[dict]:
    """Annotate, filter, and sort candidates best-fit first.

    By default drops senior and off-track (sales/PM/etc.) roles and anything
    with no real fit, then sorts by fit. Pass include_senior=True to keep senior
    roles (they sort below entry/mid of equal fit)."""
    annotated = [annotate(dict(c)) for c in candidates]
    kept = []
    for c in annotated:
        if c["off_track"]:
            continue
        if only_relevant and not c["relevant"]:
            continue
        if not include_senior and c["seniority"] == "senior":
            continue
        kept.append(c)

    level_rank = {"entry": 0, "mid": 1, "senior": 2}
    kept.sort(key=lambda c: (level_rank.get(c["seniority"], 1), -c["fit"]))
    return kept
