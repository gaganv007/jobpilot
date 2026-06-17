"""Calibration: is my scoring actually predictive of real outcomes?

Compares each scored job's predicted fit against its real pipeline outcome
(interview/offer = positive, rejected = negative). Reports whether higher scores
are converting better, and ONLY suggests weight tweaks (the human approves and
applies them). It never silently changes the rubric.

Honesty: outcomes come from real, human-set statuses. With too little data it
says so rather than inventing a trend.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import config, scoring
from .models import Status

POSITIVE = {Status.interview.value, Status.offer.value}
NEGATIVE = {Status.rejected.value}
MIN_OUTCOMES = 5  # below this, do not claim calibration or suggest weight changes

WEIGHTS_FILE = "weights.json"


@dataclass
class CalibrationReport:
    n_outcomes: int = 0
    n_positive: int = 0
    n_negative: int = 0
    avg_score_positive: float | None = None
    avg_score_negative: float | None = None
    enough_data: bool = False
    verdict: str = ""
    suggestions: list[str] = field(default_factory=list)


def _outcomes(conn) -> list[tuple[float, bool, str]]:
    rows = conn.execute(
        "SELECT s.overall, s.gate_passed, a.status FROM scores s "
        "JOIN applications a ON a.job_id = s.job_id"
    ).fetchall()
    out = []
    for r in rows:
        if r["status"] in POSITIVE or r["status"] in NEGATIVE:
            out.append((r["overall"], bool(r["gate_passed"]), r["status"]))
    return out


def report(conn) -> CalibrationReport:
    data = _outcomes(conn)
    rep = CalibrationReport(n_outcomes=len(data))
    pos = [score for score, _g, st in data if st in POSITIVE]
    neg = [score for score, _g, st in data if st in NEGATIVE]
    rep.n_positive, rep.n_negative = len(pos), len(neg)
    rep.avg_score_positive = round(sum(pos) / len(pos), 2) if pos else None
    rep.avg_score_negative = round(sum(neg) / len(neg), 2) if neg else None

    if len(data) < MIN_OUTCOMES:
        rep.enough_data = False
        rep.verdict = (f"Not enough outcome data yet ({len(data)}/{MIN_OUTCOMES}). "
                       f"Keep updating statuses as you hear back.")
        return rep

    rep.enough_data = True
    if pos and neg:
        if rep.avg_score_positive > rep.avg_score_negative + 0.3:
            rep.verdict = ("Well calibrated: jobs that advanced scored higher on average "
                           f"({rep.avg_score_positive} vs {rep.avg_score_negative}).")
        elif rep.avg_score_negative > rep.avg_score_positive:
            rep.verdict = ("Miscalibrated: rejected jobs scored HIGHER than ones that "
                           "advanced. The rubric is rewarding the wrong signals.")
            rep.suggestions = _suggest_tweaks(conn, data)
        else:
            rep.verdict = ("Weakly calibrated: scores barely separate outcomes. More data "
                           "or a tweak may help.")
            rep.suggestions = _suggest_tweaks(conn, data)
    else:
        rep.verdict = "Only one outcome class so far; need both positives and negatives to calibrate."
    return rep


def _suggest_tweaks(conn, data) -> list[str]:
    """Suggest (do not apply) which dimensions failed to separate outcomes.

    For each dimension, compare its average value among positive vs negative
    outcomes. A dimension that scores the same (or inverted) for winners and
    losers is not pulling its weight."""
    rows = conn.execute(
        "SELECT s.dimensions_json, a.status FROM scores s "
        "JOIN applications a ON a.job_id = s.job_id"
    ).fetchall()
    pos_dims: dict[str, list[float]] = {d: [] for d in scoring.DIMENSIONS}
    neg_dims: dict[str, list[float]] = {d: [] for d in scoring.DIMENSIONS}
    for r in rows:
        try:
            dims = json.loads(r["dimensions_json"])
        except Exception:
            continue
        bucket = pos_dims if r["status"] in POSITIVE else neg_dims if r["status"] in NEGATIVE else None
        if bucket is None:
            continue
        for d in scoring.DIMENSIONS:
            if d in dims:
                bucket[d].append(dims[d])

    suggestions = []
    for d in scoring.DIMENSIONS:
        if pos_dims[d] and neg_dims[d]:
            ap = sum(pos_dims[d]) / len(pos_dims[d])
            an = sum(neg_dims[d]) / len(neg_dims[d])
            if an - ap >= 0.5:  # this dimension is higher for losers -> reduce its weight
                suggestions.append(
                    f"Consider lowering the weight on '{d}': it averaged {an:.1f} for "
                    f"rejected jobs vs {ap:.1f} for ones that advanced."
                )
    if not suggestions:
        suggestions.append("No single dimension is clearly misleading; gather more outcomes.")
    return suggestions


# ---- optional, human-approved weight overrides ----
def weights_path():
    return config.home_dir() / WEIGHTS_FILE


def load_weight_overrides() -> dict | None:
    p = weights_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def save_weight_overrides(weights: dict) -> None:
    weights_path().write_text(json.dumps(weights, indent=2), encoding="utf-8")
