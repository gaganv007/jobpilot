"""Follow-up reminders for applications going stale.

A short, well-timed follow-up measurably lifts recruiter response rates, so
JobPilot surfaces applications that have gone quiet. Honest: it reads only the
real applied_at timestamp and the current status. It reminds; it never sends
anything.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import db
from .models import Status

# Statuses where a follow-up makes sense (you applied / are mid-process).
PENDING = {Status.applied.value, Status.screening.value}
DEFAULT_DAYS = 5


def _days_since(iso: str) -> int | None:
    if not iso:
        return None
    try:
        ts = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).days


def needs_followup(conn, days: int = DEFAULT_DAYS) -> list[dict]:
    """Applications in a pending status whose last action is older than `days`.

    Uses applied_at when present; otherwise the latest status-change event, so a
    job sitting in 'screening' without an applied_at is still tracked.
    """
    rows = conn.execute(
        "SELECT a.job_id, a.status, a.applied_at, j.title, j.company "
        "FROM applications a JOIN jobs j ON j.id = a.job_id "
        "WHERE a.status IN ('applied','screening')"
    ).fetchall()
    out = []
    for r in rows:
        anchor = r["applied_at"]
        if not anchor:
            ev = conn.execute(
                "SELECT at FROM events WHERE job_id = ? AND kind = 'status_change' "
                "ORDER BY id DESC LIMIT 1",
                (r["job_id"],),
            ).fetchone()
            anchor = ev["at"] if ev else None
        d = _days_since(anchor)
        if d is not None and d >= days:
            out.append({
                "job_id": r["job_id"],
                "title": r["title"],
                "company": r["company"],
                "status": r["status"],
                "days_since": d,
            })
    out.sort(key=lambda x: -x["days_since"])
    return out
