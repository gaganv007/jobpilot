"""The JobPilot scoring rubric.

Ten dimensions, each 0-5. Two are GATES (Role Match, Skills Alignment): each
must be >= GATE_MIN or the whole job fails and `overall` is capped, so a
weak-fit job can never masquerade as a good one. This is the core
"don't waste applications" filter.

`compute_overall` is a pure, deterministic function — unit-tested directly.
Dimension scores can come from a deterministic heuristic (offline, honest) or
from an LLM reply (paste-mode JSON). Neither path invents resume facts; scoring
only measures fit, it never edits the resume.
"""
from __future__ import annotations

import json
import re
from typing import Optional

# dimension -> weight. Gates carry the most weight; "unknown" dimensions least.
WEIGHTS: dict[str, float] = {
    "Role Match": 2.0,          # gate
    "Skills Alignment": 2.0,    # gate
    "Seniority Fit": 1.0,
    "Domain Fit": 1.0,
    "Location/Remote Fit": 1.0,
    "Compensation Fit": 0.5,
    "Tech-Stack Overlap": 1.0,
    "Visa/Work-Auth Fit": 1.0,
    "Company Stage Fit": 0.5,
    "Growth/Title Trajectory": 0.5,
}
DIMENSIONS = list(WEIGHTS.keys())
GATES = ("Role Match", "Skills Alignment")
GATE_MIN = 3
CAP_WHEN_GATE_FAILS = 2.0


def active_weights() -> dict[str, float]:
    """Default weights, overlaid with any human-approved overrides from
    weights.json in JOBPILOT_HOME (written via calibration, never silently)."""
    weights = dict(WEIGHTS)
    try:
        import json

        from . import config

        p = config.home_dir() / "weights.json"
        if p.exists():
            override = json.loads(p.read_text(encoding="utf-8"))
            for k, v in override.items():
                if k in weights and isinstance(v, (int, float)) and v >= 0:
                    weights[k] = float(v)
    except Exception:
        pass
    return weights


def validate_dims(dims: dict[str, int]) -> None:
    missing = [d for d in DIMENSIONS if d not in dims]
    if missing:
        raise ValueError(f"Missing dimension scores: {missing}")
    for d in DIMENSIONS:
        v = dims[d]
        if not isinstance(v, (int, float)) or not (0 <= v <= 5):
            raise ValueError(f"Dimension {d!r} must be 0-5, got {v!r}")


def compute_overall(dims: dict[str, int]) -> tuple[float, bool]:
    """Weighted mean of all 10 dimensions, with the gate rule applied.

    Returns (overall, gate_passed). If either gate < GATE_MIN, gate_passed is
    False and overall is capped at CAP_WHEN_GATE_FAILS.
    """
    validate_dims(dims)
    weights = active_weights()
    weighted = sum(dims[d] * weights[d] for d in DIMENSIONS)
    total_w = sum(weights.values())
    mean = weighted / total_w

    gate_passed = all(dims[g] >= GATE_MIN for g in GATES)
    overall = mean if gate_passed else min(mean, CAP_WHEN_GATE_FAILS)
    return round(overall, 2), gate_passed


def band(overall: float, gate_passed: bool) -> str:
    """Human label for a score."""
    if not gate_passed:
        return "FAIL (gate)"
    if overall >= 4.0:
        return "strong"
    if overall >= 3.0:
        return "solid"
    if overall >= 2.0:
        return "marginal"
    return "weak"


# ---------- deterministic heuristic scorer (offline, honest) ----------
def _has(text: str, *words: str) -> bool:
    t = text.lower()
    return any(w in t for w in words)


def _band_from_ratio(r: float) -> int:
    if r >= 0.8:
        return 5
    if r >= 0.6:
        return 4
    if r >= 0.45:
        return 3
    if r >= 0.3:
        return 2
    if r >= 0.12:
        return 1
    return 0


def heuristic_dimensions(jd_text: str) -> dict[str, dict]:
    """Derive the 10 dimension scores from the JD using jd_agent's matching.

    Every score is a real, explainable computation over the JD and my resume
    keyword data. No resume facts are invented. Returns
    {dim: {"score": int, "rationale": str}}.
    """
    from . import jd_bridge

    jd = jd_text or ""
    best, ranked = jd_bridge.match_track(jd)
    top_weight = ranked[0][1] if ranked else 0
    present, missing = jd_bridge.keyword_gaps(jd, best)
    coverage = len(present) / max(1, len(present) + len(missing))

    out: dict[str, dict] = {}

    # Gate 1: Role Match — strength of the best track keyword signal.
    role = 5 if top_weight >= 9 else 4 if top_weight >= 5 else 3 if top_weight >= 3 else 2 if top_weight >= 1 else 1
    out["Role Match"] = {
        "score": role,
        "rationale": f"Best-fit track '{best}' (keyword weight {top_weight}).",
    }

    # Gate 2: Skills Alignment — resume coverage of JD keywords.
    skills = _band_from_ratio(coverage)
    out["Skills Alignment"] = {
        "score": skills,
        "rationale": f"{len(present)} of {len(present)+len(missing)} JD keywords already in resume "
                     f"({coverage:.0%} coverage). Missing: {', '.join(missing[:6]) or 'none'}.",
    }

    # Seniority Fit — I am early-career (MS student + internships/grad assistant).
    if _has(jd, "principal", "staff engineer", "10+ years", "15+ years", "director", "vp "):
        sen, why = 2, "Senior/principal level; I am early-career."
    elif _has(jd, "senior", "lead ", "7+ years", "8+ years"):
        sen, why = 3, "Senior-leaning; a stretch but defensible."
    elif _has(jd, "new grad", "entry level", "entry-level", "junior", "associate", "0-2 years", "1-3 years", "graduate"):
        sen, why = 5, "Entry / new-grad level matches my stage."
    else:
        sen, why = 4, "Mid-level with no hard seniority bar."
    out["Seniority Fit"] = {"score": sen, "rationale": why}

    # Domain Fit — overlap of my real domains with the JD.
    my_domains = {
        "ml/ai": ("machine learning", "deep learning", "ml", "ai", "llm", "nlp", "model"),
        "data": ("data", "analytics", "dashboard", "statistics", "forecasting"),
        "blockchain": ("blockchain", "web3", "solidity", "smart contract", "on-chain", "crypto"),
        "finance": ("finance", "fintech", "fraud", "anomaly", "payments", "trading"),
        "devops": ("devops", "mlops", "kubernetes", "ci/cd", "infrastructure", "platform"),
    }
    hit = [name for name, kws in my_domains.items() if _has(jd, *kws)]
    dom = 5 if len(hit) >= 3 else 4 if len(hit) == 2 else 3 if len(hit) == 1 else 2
    out["Domain Fit"] = {"score": dom, "rationale": f"Overlapping domains: {', '.join(hit) or 'none clear'}."}

    # Location / Remote Fit — Boston, open to relocation/remote.
    if _has(jd, "remote", "work from home", "anywhere"):
        loc, why = 5, "Remote-friendly."
    elif _has(jd, "boston", "cambridge", "massachusetts", " ma "):
        loc, why = 5, "Boston area; my home base."
    elif _has(jd, "united states", "u.s.", "usa", "hybrid"):
        loc, why = 4, "US-based; open to relocation."
    elif _has(jd, "london", "india", "remote (eu", "europe", "canada", "singapore"):
        loc, why = 2, "Outside the US; relocation/visa friction."
    else:
        loc, why = 3, "Location unclear from JD."
    out["Location/Remote Fit"] = {"score": loc, "rationale": why}

    # Compensation Fit — no comp preference data, stay neutral and honest.
    out["Compensation Fit"] = {"score": 3, "rationale": "No comp data captured; neutral until known."}

    # Tech-Stack Overlap — JD tech tokens present in resume.
    tech_vocab = ("python", "pytorch", "tensorflow", "sql", "aws", "docker", "kubernetes",
                  "react", "node", "fastapi", "spark", "langchain", "rag", "typescript",
                  "java", "c++", "redis", "mongodb", "github actions", "terraform")
    jd_tech = [t for t in tech_vocab if t in jd.lower()]
    resume_tech_present = [t for t in jd_tech if t in [p.lower() for p in present]] if jd_tech else []
    # fall back: count tech tokens also in the broad present list
    tech_ratio = (len(resume_tech_present) / len(jd_tech)) if jd_tech else 0.5
    tech = _band_from_ratio(tech_ratio) if jd_tech else 3
    out["Tech-Stack Overlap"] = {
        "score": tech,
        "rationale": f"{len(resume_tech_present)} of {len(jd_tech)} JD tech tokens in resume." if jd_tech
        else "No specific stack named in JD.",
    }

    # Visa / Work-Auth Fit — US citizen with work authorization.
    if _has(jd, "security clearance", "clearance", "ts/sci", "secret clearance", "polygraph"):
        visa, why = 2, "Requires a clearance I do not hold (flag as gap)."
    elif _has(jd, "citizen", "citizenship", "must be authorized", "no sponsorship", "without sponsorship"):
        visa, why = 5, "Citizenship/work-auth required; I qualify (US citizen)."
    else:
        visa, why = 5, "No work-auth obstacle (US citizen)."
    out["Visa/Work-Auth Fit"] = {"score": visa, "rationale": why}

    # Company Stage Fit — I have startup/hackathon + research experience.
    if _has(jd, "startup", "early stage", "seed", "series a", "fast-growing", "founding"):
        stage, why = 4, "Startup stage; matches my hackathon/0-to-1 projects."
    elif _has(jd, "enterprise", "fortune 500", "large organization"):
        stage, why = 3, "Enterprise scale; less of my background but workable."
    else:
        stage, why = 3, "Company stage unclear."
    out["Company Stage Fit"] = {"score": stage, "rationale": why}

    # Growth / Title Trajectory — does this move my career forward?
    if _has(jd, "senior", "lead", "staff"):
        traj, why = 4, "Title is a step up; good trajectory if attainable."
    else:
        traj, why = 3, "Lateral/early-career title; reasonable trajectory."
    out["Growth/Title Trajectory"] = {"score": traj, "rationale": why}

    return out


def dims_only(scored: dict[str, dict]) -> dict[str, int]:
    return {d: scored[d]["score"] for d in DIMENSIONS}


def rationale_text(scored: dict[str, dict]) -> str:
    return "\n".join(f"{d} ({scored[d]['score']}/5): {scored[d]['rationale']}" for d in DIMENSIONS)


# ---------- LLM paste-mode (optional, richer) ----------
def build_score_prompt(jd_text: str, company: str = "", title: str = "") -> str:
    """A tight, self-contained prompt for scoring in a Claude chat (paste mode)."""
    return f"""Score how well this job fits the candidate. Return ONLY a JSON object,
no prose. For each of these 10 dimensions give an integer 0-5 and a one-line rationale:
{', '.join(DIMENSIONS)}.

Rules:
- "Role Match" and "Skills Alignment" are gates: be strict, do not inflate.
- Judge fit only. Do not invent any candidate skill or fact.
- Output shape exactly:
{{"Role Match": {{"score": 4, "rationale": "..."}}, ... all 10 dimensions ...}}

CANDIDATE: Gagan Veginati — early-career (MS CS, Boston University), strengths in AI/ML,
data science, MLOps/DevOps, full-stack; US citizen with work authorization; no security clearance.

JOB: {title} @ {company}
{jd_text}"""


def parse_score_reply(text: str) -> dict[str, dict]:
    """Parse a JSON scoring reply (tolerant of code fences / surrounding prose)."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("No JSON object found in reply.")
    data = json.loads(m.group(0))
    out: dict[str, dict] = {}
    for d in DIMENSIONS:
        if d not in data:
            raise ValueError(f"Reply missing dimension: {d}")
        entry = data[d]
        if isinstance(entry, dict):
            score = int(entry.get("score"))
            rat = str(entry.get("rationale", "")).strip()
        else:
            score = int(entry)
            rat = ""
        if not 0 <= score <= 5:
            raise ValueError(f"{d} score out of range: {score}")
        out[d] = {"score": score, "rationale": rat}
    return out
