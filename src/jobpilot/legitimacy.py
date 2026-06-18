"""Legitimacy check — flag likely scams and ghost jobs before you spend effort.

Inspired by Career-Ops' "Block G". This protects your application budget and your
hit rate: applying to scams or evergreen ghost postings is wasted time. It is a
*warning*, computed only from real signals in the JD text — it never fabricates,
and it never auto-rejects a job. The human decides.

Returns {risk: clear|caution|high_risk, score: int, flags: [..]}.
"""
from __future__ import annotations

import re

# (regex, weight, human reason). Higher weight = stronger scam/ghost signal.
SCAM_SIGNALS: list[tuple[str, int, str]] = [
    (r"\b(wire transfer|western union|moneygram|gift card|bitcoin payment|crypto payment)\b", 4, "asks about money transfer / gift cards"),
    (r"\b(registration fee|training fee|starter kit|processing fee|pay (a )?fee)\b", 4, "mentions an upfront fee"),
    (r"\b(ssn|social security number|bank account|routing number)\b.{0,40}\b(upfront|to start|before)\b", 4, "wants sensitive financial info to start"),
    (r"\b(telegram|whatsapp|signal app)\b.{0,30}\b(interview|contact|chat)\b", 3, "interviews over Telegram/WhatsApp"),
    (r"\b(no experience (needed|required)|no skills needed)\b.{0,40}\b(\$?\d{3,}|high pay|weekly pay)\b", 3, "no experience but high/weekly pay"),
    (r"\b(earn|make)\s*\$?\d{3,4}\s*(/|per)?\s*(day|week)\b", 3, "promises unusually high quick pay"),
    (r"\b(work from home|remote)\b.{0,20}\b(guaranteed (income|job)|easy money)\b", 3, "guaranteed income / easy money"),
    (r"\b(personal email|gmail\.com|yahoo\.com|outlook\.com)\b.{0,30}\b(apply|resume|cv)\b", 2, "apply to a personal email address"),
    (r"\bimmediate (start|hire)\b.{0,30}\bno interview\b", 3, "immediate hire with no interview"),
]

GHOST_SIGNALS: list[tuple[str, int, str]] = [
    (r"\b(always (hiring|accepting)|evergreen|general application|talent (pool|community|network))\b", 3, "evergreen / talent-pool posting, not a specific opening"),
    (r"\b(we are always (looking|accepting)|ongoing recruitment|pipeline (req|requisition))\b", 3, "ongoing/pipeline requisition language"),
    (r"\b(multiple (positions|openings)|various locations|locations? worldwide)\b", 1, "very broad, non-specific posting"),
]


def _hits(text: str, signals) -> list[tuple[int, str]]:
    out = []
    for pattern, weight, reason in signals:
        if re.search(pattern, text, re.I):
            out.append((weight, reason))
    return out


def assess(jd_text: str, *, company: str = "", title: str = "") -> dict:
    """Score scam + ghost-job risk from the JD. Pure and explainable."""
    text = jd_text or ""
    scam = _hits(text, SCAM_SIGNALS)
    ghost = _hits(text, GHOST_SIGNALS)

    # A near-empty JD is weakly suspicious (low information / possible ghost).
    thin = 0 < len(text.split()) < 20
    flags = [{"kind": "scam", "weight": w, "reason": r} for w, r in scam]
    flags += [{"kind": "ghost", "weight": w, "reason": r} for w, r in ghost]
    if thin:
        flags.append({"kind": "ghost", "weight": 2, "reason": "very short description (low signal)"})

    score = sum(f["weight"] for f in flags)
    scam_weight = sum(f["weight"] for f in flags if f["kind"] == "scam")

    if scam_weight >= 4 or score >= 6:
        risk = "high_risk"
    elif score >= 2:
        risk = "caution"
    else:
        risk = "clear"

    return {
        "risk": risk,
        "score": score,
        "flags": flags,
        "summary": _summary(risk, flags),
    }


def _summary(risk: str, flags: list[dict]) -> str:
    if risk == "clear":
        return "No scam or ghost-job signals detected."
    reasons = "; ".join(sorted({f["reason"] for f in flags}))
    label = "High risk" if risk == "high_risk" else "Caution"
    return f"{label}: {reasons}. Verify before spending an application."
