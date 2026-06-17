"""Resumable batch add+score over a list of URLs.

Design goals from the spec:
  - resumable: a URL already added+scored is skipped; re-running continues where
    a crashed run left off.
  - fault tolerant: per-URL lock files prevent two runs from double-processing the
    same URL; stale locks (from a crashed run) are reclaimed after a timeout.
  - polite: network fetches are serialized behind one lock, so we never hammer a
    portal even with multiple workers doing CPU-bound scoring in parallel.
  - it STOPS at scoring. It never tailors-and-submits, never applies. Crossing
    into "applied" is always a human action.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from . import config, db, extract, scoring
from .models import Status

STALE_LOCK_SECONDS = 3600
# Serialize the actual network fetch — politeness + avoids concurrent-browser issues.
_FETCH_LOCK = threading.Lock()


def read_urls(path: str | Path) -> list[str]:
    """One URL per line; blank lines and # comments ignored; de-duplicated in order."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        url = raw.strip()
        if not url or url.startswith("#"):
            continue
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _locks_dir() -> Path:
    d = config.artifacts_dir() / "locks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _lock_path(url: str) -> Path:
    return _locks_dir() / (hashlib.sha1(url.encode()).hexdigest() + ".lock")


def acquire_lock(url: str, stale_seconds: int = STALE_LOCK_SECONDS) -> bool:
    """Try to claim a URL. Returns False if another live run holds it.
    A lock older than stale_seconds (crashed run) is reclaimed."""
    lp = _lock_path(url)
    try:
        fd = os.open(lp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f"{os.getpid()} {time.time()}".encode())
        os.close(fd)
        return True
    except FileExistsError:
        try:
            age = time.time() - lp.stat().st_mtime
        except FileNotFoundError:
            return acquire_lock(url, stale_seconds)
        if age > stale_seconds:
            try:
                lp.unlink()
            except FileNotFoundError:
                pass
            return acquire_lock(url, stale_seconds)
        return False


def release_lock(url: str) -> None:
    try:
        _lock_path(url).unlink()
    except FileNotFoundError:
        pass


@dataclass
class BatchItem:
    url: str
    status: str  # done | skipped_scored | locked | error | robots_blocked
    job_id: int | None = None
    overall: float | None = None
    gate_passed: bool | None = None
    detail: str = ""


def process_url(url: str, delay: float | None = None) -> BatchItem:
    """Add (if new) and score one URL. Each call uses its own DB connection so it
    is thread-safe. Resumable: an already-scored URL is skipped."""
    conn = db.connect()
    try:
        if not extract.is_valid_url(url):
            return BatchItem(url, "error", detail="invalid URL")

        existing = db.job_by_url(conn, url)
        if existing is not None and db.get_score(conn, existing["id"]) is not None:
            sc = db.get_score(conn, existing["id"])
            return BatchItem(url, "skipped_scored", job_id=existing["id"],
                             overall=sc["overall"], gate_passed=bool(sc["gate_passed"]))

        if not acquire_lock(url):
            return BatchItem(url, "locked", detail="held by another run")

        try:
            job_id = existing["id"] if existing else None
            if job_id is None:
                kwargs = {} if delay is None else {"delay": delay}
                try:
                    details = extract.extract(url, **kwargs)
                except extract.RobotsDisallowed as e:
                    db.log_event(conn, "robots_blocked", url)
                    return BatchItem(url, "robots_blocked", detail=str(e))
                except Exception as e:
                    return BatchItem(url, "error", detail=str(e))
                job_id, _ = db.add_job(conn, **details)
                db.log_event(conn, "add", f"batch: {details.get('title','')}", job_id=job_id)

            job = db.get_job(conn, job_id)
            try:
                scored = scoring.heuristic_dimensions(job["jd_text"])
            except Exception as e:
                return BatchItem(url, "error", job_id=job_id, detail=f"score failed: {e}")
            dims = scoring.dims_only(scored)
            overall, gate = scoring.compute_overall(dims)
            db.upsert_score(conn, job_id, overall, gate, json.dumps(dims),
                            scoring.rationale_text(scored))
            appn = db.get_application(conn, job_id)
            if appn and appn["status"] == Status.discovered.value:
                db.set_status(conn, job_id, Status.scored.value)
            db.log_event(conn, "score", f"batch {overall:.1f}", job_id=job_id)
            return BatchItem(url, "done", job_id=job_id, overall=overall, gate_passed=gate)
        finally:
            release_lock(url)
    finally:
        conn.close()


def _fetch_serialized():
    """Wrap extract.extract so network fetches run one at a time (politeness)."""
    real = extract.extract

    def wrapped(url, **kw):
        with _FETCH_LOCK:
            return real(url, **kw)

    return real, wrapped


def run_batch(urls: list[str], workers: int = 4, delay: float | None = None) -> list[BatchItem]:
    """Process all URLs with a small worker pool; fetches are serialized."""
    original, serialized = _fetch_serialized()
    extract.extract = serialized  # politeness: one network fetch at a time
    try:
        results: list[BatchItem] = []
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futs = {pool.submit(process_url, u, delay): u for u in urls}
            for fut in as_completed(futs):
                results.append(fut.result())
    finally:
        extract.extract = original
    # keep input order for a stable report
    order = {u: i for i, u in enumerate(urls)}
    results.sort(key=lambda r: order.get(r.url, 0))
    return results


def shortlist(conn, limit: int = 10) -> list[dict]:
    """Ranked shortlist of gate-passing jobs, best first."""
    rows = conn.execute(
        "SELECT j.id, j.title, j.company, s.overall, s.gate_passed "
        "FROM jobs j JOIN scores s ON s.job_id = j.id "
        "ORDER BY s.gate_passed DESC, s.overall DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
