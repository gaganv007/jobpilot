"""JobPilot web backend (FastAPI).

A thin JSON API over the existing JobPilot engine plus a static single-page UI.
Every guardrail still holds: the API has no endpoint that applies to a job, logs
in, or fabricates content. Discovery uses public APIs only and is user-triggered.
Status changes to applied/interview/offer/etc. are recorded as the human's action.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import (
    calibration,
    config,
    db,
    discover,
    followups as followups_mod,
    gaps as gaps_mod,
    legitimacy,
    outreach as outreach_mod,
    packet as packet_mod,
    prep as prep_mod,
    research as research_mod,
    scan as scan_mod,
    scoring,
    tailor as tailor_mod,
)
from ..models import HUMAN_ONLY_STATUSES, Status

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="JobPilot", docs_url="/api/docs")


# ---------- request models ----------
class PasteJob(BaseModel):
    url: str | None = None
    company: str = ""
    title: str = ""
    location: str = ""
    jd_text: str


class FetchJob(BaseModel):
    url: str


class DiscoverReq(BaseModel):
    query: str = ""
    sources: list[str] | None = None
    limit: int = 25
    include_senior: bool = False


class ScanReq(BaseModel):
    query: str = ""
    targets: list[list[str]] | None = None  # [[ats, token, label], ...]
    limit: int = 60
    include_senior: bool = False


class Candidate(BaseModel):
    url: str | None = None
    company: str = ""
    title: str = ""
    location: str = ""
    jd_text: str = ""


class BulkReq(BaseModel):
    jobs: list[Candidate]
    score: bool = True


class TailorReq(BaseModel):
    reply: str | None = None


class StatusReq(BaseModel):
    status: str
    note: str = ""


# ---------- helpers ----------
def _job_row_view(conn, job) -> dict:
    sc = db.get_score(conn, job["id"])
    appn = db.get_application(conn, job["id"])
    view = {
        "id": job["id"],
        "url": job["url"],
        "company": job["company"],
        "title": job["title"],
        "location": job["location"],
        "source": job["source"],
        "created_at": job["created_at"],
        "status": appn["status"] if appn else "discovered",
        "resume_path": appn["resume_path"] if appn else None,
        "cover_path": appn["cover_path"] if appn else None,
        "score": None,
        "gate_passed": None,
    }
    if sc is not None:
        view["score"] = sc["overall"]
        view["gate_passed"] = bool(sc["gate_passed"])
    else:
        # No full rubric yet: show an instant, cheap fit estimate so the job is
        # rankable the moment it is added.
        from .. import relevance

        qf = relevance.quick_fit(job["title"], job["jd_text"])
        view["quick_fit"] = qf["fit"]
        view["quick_track"] = qf["track"]
    return view


def _ats(jd_text: str) -> dict:
    """ATS keyword coverage for the JD against the best-matching resume."""
    try:
        from .. import jd_bridge

        if not jd_bridge.available():
            return {"available": False}
        track, ranked = jd_bridge.match_track(jd_text)
        present, missing = jd_bridge.keyword_gaps(jd_text, track)
        total = len(present) + len(missing)
        return {
            "available": True,
            "track": track,
            "coverage": round(100 * len(present) / total) if total else 0,
            "present": present,
            "missing": missing,
            "ranking": [{"track": n, "weight": w} for n, w in ranked],
        }
    except Exception:
        return {"available": False}


def _read_if(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


# ---------- state ----------
@app.get("/api/health")
def health():
    from .. import jd_bridge

    return {"ok": True, "jd_agent": jd_bridge.available()}


@app.get("/api/state")
def state():
    conn = db.connect()
    jobs = [_job_row_view(conn, j) for j in db.all_jobs(conn)]
    counts = db.status_counts(conn)
    week = conn.execute(
        "SELECT COUNT(*) n FROM applications "
        "WHERE applied_at IS NOT NULL AND applied_at >= datetime('now', '-7 days')"
    ).fetchone()["n"]
    lead = None
    try:
        lead = gaps_mod.highest_leverage(conn)
    except Exception:
        pass
    # Full-scored jobs first (by rubric), then quick-fit-ranked unscored jobs.
    jobs.sort(key=lambda j: (j["score"] is None, -(j["score"] or 0), -(j.get("quick_fit") or 0)))
    return {
        "jobs": jobs,
        "counts": counts,
        "weekly_applications": week,
        "gap_lead": lead,
        "followups": followups_mod.needs_followup(conn),
        "unscored": len(db.unscored_job_ids(conn)),
        "statuses": [s.value for s in Status],
        "human_only": [s.value for s in HUMAN_ONLY_STATUSES],
    }


# ---------- add ----------
@app.post("/api/jobs")
def add_paste(body: PasteJob):
    if not body.jd_text.strip():
        raise HTTPException(400, "jd_text is required")
    conn = db.connect()
    url = body.url or f"paste://{abs(hash(body.jd_text)) % (10**12)}"
    job_id, created = db.add_job(
        conn, url, company=body.company, title=body.title,
        location=body.location, jd_text=body.jd_text,
    )
    db.log_event(conn, "add", f"paste: {body.title} @ {body.company}", job_id=job_id)
    return {"id": job_id, "created": created}


@app.post("/api/jobs/fetch")
def add_fetch(body: FetchJob):
    from .. import extract

    if not extract.is_valid_url(body.url):
        raise HTTPException(400, "Not a valid http(s) URL")
    conn = db.connect()
    existing = db.job_by_url(conn, body.url)
    if existing is not None:
        return {"id": existing["id"], "created": False}
    if not extract.robots_allows(body.url):
        raise HTTPException(403, "robots.txt disallows fetching this page")
    try:
        details = extract.extract(body.url)
    except Exception as e:
        raise HTTPException(502, f"Could not extract: {e}")
    job_id, created = db.add_job(conn, **details)
    db.log_event(conn, "add", f"fetch: {details.get('title','')}", job_id=job_id)
    return {"id": job_id, "created": created}


@app.post("/api/discover")
def discover_jobs(body: DiscoverReq):
    # Public APIs only; returns candidates for review (nothing is stored).
    from .. import relevance

    raw = discover.discover(body.query, body.sources, body.limit)
    ranked = relevance.rank(raw, include_senior=body.include_senior)
    return {"results": ranked, "total_found": len(raw)}


@app.get("/api/scan/targets")
def scan_targets():
    return {"targets": [list(t) for t in scan_mod.TARGETS]}


@app.post("/api/scan")
def scan_jobs(body: ScanReq):
    # Public ATS feeds (Greenhouse/Lever/Ashby), user-triggered, review-only.
    # Results are ranked by fit to my resumes; senior roles hidden by default.
    from .. import relevance

    targets = [tuple(t) for t in body.targets] if body.targets else None
    raw = scan_mod.scan(targets, query=body.query, total_limit=max(body.limit, 120))
    ranked = relevance.rank(raw, include_senior=body.include_senior)
    return {"results": ranked[:body.limit], "total_found": len(raw)}


# ---------- per-job ----------
@app.get("/api/jobs/{job_id}")
def job_detail(job_id: int):
    conn = db.connect()
    job = db.get_job(conn, job_id)
    if job is None:
        raise HTTPException(404, "No such job")
    view = _job_row_view(conn, job)
    sc = db.get_score(conn, job_id)
    if sc is not None:
        try:
            view["dimensions"] = json.loads(sc["dimensions_json"])
        except Exception:
            view["dimensions"] = {}
        view["rationale"] = sc["rationale"]
        view["scored_at"] = sc["scored_at"]
    view["jd_text"] = job["jd_text"]
    view["ats"] = _ats(job["jd_text"])
    view["legitimacy"] = legitimacy.assess(job["jd_text"], company=job["company"], title=job["title"])
    view["weights"] = scoring.WEIGHTS
    view["gates"] = list(scoring.GATES)
    d = config.job_dir(job_id)
    view["artifacts"] = {
        "evidence": _read_if(d / "evidence.md"),
        "receipt": _read_if(d / "honesty_receipt.md"),
        "research": _read_if(d / "research.md"),
        "prep": _read_if(d / "prep.md"),
        "packet": _read_if(d / "packet.md"),
        "outreach": _read_if(d / "outreach.md"),
        "tailor_prompt": _read_if(d / "tailor_prompt.txt"),
    }
    view["files"] = [p.name for p in sorted(d.glob("*")) if p.is_file()]
    return view


def _do_score(conn, job_id: int) -> dict:
    """Score one job (heuristic), store it, advance discovered -> scored."""
    job = db.get_job(conn, job_id)
    scored = scoring.heuristic_dimensions(job["jd_text"])
    dims = scoring.dims_only(scored)
    overall, gate = scoring.compute_overall(dims)
    db.upsert_score(conn, job_id, overall, gate, json.dumps(dims), scoring.rationale_text(scored))
    appn = db.get_application(conn, job_id)
    if appn and appn["status"] == Status.discovered.value:
        db.set_status(conn, job_id, Status.scored.value)
    db.log_event(conn, "score", f"{overall:.1f}", job_id=job_id)
    return {"overall": overall, "gate_passed": gate, "band": scoring.band(overall, gate),
            "dimensions": {d: scored[d] for d in scoring.DIMENSIONS}}


@app.post("/api/jobs/{job_id}/score")
def score_job(job_id: int):
    conn = db.connect()
    if db.get_job(conn, job_id) is None:
        raise HTTPException(404, "No such job")
    try:
        return _do_score(conn, job_id)
    except Exception as e:
        raise HTTPException(503, f"Scoring needs jd_agent: {e}")


@app.post("/api/jobs/bulk")
def bulk_add(body: BulkReq):
    """Add many candidates (from scan/discover) and optionally score them, so a
    scan turns into a ranked shortlist in one click. Never applies."""
    conn = db.connect()
    added, scored_n, results = 0, 0, []
    can_score = body.score
    for c in body.jobs:
        if not c.jd_text.strip() and not c.url:
            continue
        url = c.url or f"paste://{abs(hash(c.jd_text)) % (10**12)}"
        job_id, created = db.add_job(conn, url, company=c.company, title=c.title,
                                     location=c.location, jd_text=c.jd_text)
        if created:
            added += 1
            db.log_event(conn, "add", f"bulk: {c.title}", job_id=job_id)
        entry = {"id": job_id, "created": created, "title": c.title}
        if can_score:
            try:
                s = _do_score(conn, job_id)
                entry.update(overall=s["overall"], gate_passed=s["gate_passed"])
                scored_n += 1
            except Exception:
                can_score = False  # jd_agent unavailable; stop trying
        results.append(entry)
    return {"added": added, "scored": scored_n, "results": results}


@app.post("/api/score-all")
def score_all():
    """Score every unscored job (heuristic)."""
    conn = db.connect()
    ids = db.unscored_job_ids(conn)
    scored_n, failed = 0, 0
    for jid in ids:
        try:
            _do_score(conn, jid)
            scored_n += 1
        except Exception:
            failed += 1
    return {"scored": scored_n, "failed": failed, "total": len(ids)}


@app.post("/api/jobs/{job_id}/tailor")
def tailor_job(job_id: int, body: TailorReq):
    from ..jd_bridge import JDAgentUnavailable

    conn = db.connect()
    job = db.get_job(conn, job_id)
    if job is None:
        raise HTTPException(404, "No such job")
    try:
        result = tailor_mod.tailor_job(dict(job), config.job_dir(job_id), reply_text=body.reply)
    except JDAgentUnavailable as e:
        raise HTTPException(503, str(e))
    db.set_doc_paths(conn, job_id, resume_path=result.resume_path, cover_path=result.cover_path)
    appn = db.get_application(conn, job_id)
    if appn and appn["status"] in (Status.discovered.value, Status.scored.value):
        db.set_status(conn, job_id, Status.tailored.value)
    db.log_event(conn, "tailor", f"track={result.track}", job_id=job_id)
    return {
        "track": result.track,
        "resume": Path(result.resume_path).name,
        "cover": Path(result.cover_path).name if result.cover_path else None,
        "honesty_ok": result.honesty.ok,
        "violations": result.honesty.violations,
    }


@app.post("/api/jobs/{job_id}/research")
def research_job(job_id: int):
    conn = db.connect()
    job = db.get_job(conn, job_id)
    if job is None:
        raise HTTPException(404, "No such job")
    doc = research_mod.build_research_doc(dict(job))
    (config.job_dir(job_id) / "research.md").write_text(doc, encoding="utf-8")
    db.log_event(conn, "research", "web", job_id=job_id)
    return {"markdown": doc}


@app.post("/api/jobs/{job_id}/prep")
def prep_job(job_id: int):
    conn = db.connect()
    job = db.get_job(conn, job_id)
    if job is None:
        raise HTTPException(404, "No such job")
    doc = prep_mod.build_prep_doc(dict(job))
    (config.job_dir(job_id) / "prep.md").write_text(doc, encoding="utf-8")
    db.log_event(conn, "prep", "web", job_id=job_id)
    return {"markdown": doc}


@app.post("/api/jobs/{job_id}/outreach")
def outreach_job(job_id: int):
    conn = db.connect()
    job = db.get_job(conn, job_id)
    if job is None:
        raise HTTPException(404, "No such job")
    msgs = outreach_mod.build_outreach(dict(job))
    doc = (f"# Outreach — {job['title']} @ {job['company']}\n\n"
           f"_Review and personalize before sending. JobPilot never sends these for you._\n\n"
           f"## Referral request (to an employee)\n\n{msgs['referral']}\n\n"
           f"## Recruiter / hiring manager note\n\n{msgs['recruiter']}\n")
    (config.job_dir(job_id) / "outreach.md").write_text(doc, encoding="utf-8")
    db.log_event(conn, "outreach", "web", job_id=job_id)
    return {"markdown": doc, **msgs}


@app.post("/api/jobs/{job_id}/packet")
def packet_job(job_id: int):
    conn = db.connect()
    if db.get_job(conn, job_id) is None:
        raise HTTPException(404, "No such job")
    doc = packet_mod.build_packet(conn, job_id)
    (config.job_dir(job_id) / "packet.md").write_text(doc, encoding="utf-8")
    db.log_event(conn, "packet", "web", job_id=job_id)
    return {"markdown": doc}


@app.post("/api/jobs/{job_id}/status")
def set_status(job_id: int, body: StatusReq):
    try:
        st = Status(body.status)
    except ValueError:
        raise HTTPException(400, "Invalid status")
    conn = db.connect()
    if db.get_job(conn, job_id) is None:
        raise HTTPException(404, "No such job")
    applied_at = db.utcnow() if st == Status.applied else None
    db.set_status(conn, job_id, st.value, note=body.note or None, applied_at=applied_at)
    db.log_event(conn, "status_change", f"-> {st.value}", job_id=job_id)
    return {"status": st.value, "human_action": st in HUMAN_ONLY_STATUSES}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: int):
    conn = db.connect()
    if db.get_job(conn, job_id) is None:
        raise HTTPException(404, "No such job")
    conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    conn.commit()
    return {"deleted": job_id}


@app.get("/api/jobs/{job_id}/file/{name}")
def job_file(job_id: int, name: str):
    # Prevent path traversal; only serve files inside the job's own dir.
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "Bad filename")
    p = config.job_dir(job_id) / name
    if not p.exists() or not p.is_file():
        raise HTTPException(404, "No such file")
    return FileResponse(p)


# ---------- analytics ----------
@app.get("/api/gaps")
def gaps_report():
    conn = db.connect()
    return {"markdown": gaps_mod.build_gap_report(conn),
            "aggregate": gaps_mod.aggregate_gaps(conn)}


@app.get("/api/calibrate")
def calibrate_report():
    conn = db.connect()
    rep = calibration.report(conn)
    return rep.__dict__


# ---------- static UI ----------
@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
