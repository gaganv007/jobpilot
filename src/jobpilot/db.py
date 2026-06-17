"""SQLite tracker for JobPilot.

Schema is versioned via PRAGMA user_version. Migrations are applied
incrementally on every connect() so an old DB upgrades itself in place.

Honesty rule: timestamps are always the real current UTC time. Nothing here
backdates or pads activity.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from . import config

# Each migration is a (version, sql) pair applied in order. To evolve the
# schema, append a new migration; never edit an existing one.
MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE jobs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            url        TEXT UNIQUE NOT NULL,
            company    TEXT DEFAULT '',
            title      TEXT DEFAULT '',
            location   TEXT DEFAULT '',
            source     TEXT DEFAULT '',
            jd_text    TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE scores (
            job_id          INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
            overall         REAL DEFAULT 0,
            gate_passed     INTEGER DEFAULT 0,
            dimensions_json TEXT DEFAULT '{}',
            rationale       TEXT DEFAULT '',
            scored_at       TEXT NOT NULL
        );

        CREATE TABLE applications (
            job_id      INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
            status      TEXT NOT NULL DEFAULT 'discovered',
            resume_path TEXT,
            cover_path  TEXT,
            applied_at  TEXT,
            notes       TEXT DEFAULT ''
        );

        CREATE TABLE events (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
            kind   TEXT NOT NULL,
            detail TEXT DEFAULT '',
            at     TEXT NOT NULL
        );
        """,
    ),
]


def utcnow() -> str:
    """Real current UTC timestamp, ISO-8601 with seconds. Never faked."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Optional[Path | str] = None) -> sqlite3.Connection:
    """Open the DB, apply pending migrations, return the connection."""
    target = Path(path) if path is not None else config.db_path()
    conn = sqlite3.connect(target, timeout=30)
    conn.row_factory = sqlite3.Row
    # busy_timeout first so every later statement waits out a lock instead of
    # erroring; WAL lets the batch worker pool read while one writer commits.
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError:
        pass  # another connection is mid-write; WAL is persistent once set anyway
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for ver, sql in MIGRATIONS:
        if ver > version:
            conn.executescript(sql)
            conn.execute(f"PRAGMA user_version = {ver}")
            version = ver
    conn.commit()


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


# ---------- jobs ----------
def job_by_url(conn: sqlite3.Connection, url: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()


def get_job(conn: sqlite3.Connection, job_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def add_job(
    conn: sqlite3.Connection,
    url: str,
    company: str = "",
    title: str = "",
    location: str = "",
    source: str = "",
    jd_text: str = "",
) -> tuple[int, bool]:
    """Insert a job, deduping on url. Returns (job_id, created).

    If the url already exists, returns the existing id and created=False; the
    existing row is never overwritten (dedup is higher-ROI than re-scraping).
    """
    existing = job_by_url(conn, url)
    if existing is not None:
        return existing["id"], False
    cur = conn.execute(
        "INSERT INTO jobs (url, company, title, location, source, jd_text, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (url, company, title, location, source, jd_text, utcnow()),
    )
    conn.commit()
    job_id = int(cur.lastrowid)
    # Every new job starts an application row in 'discovered'.
    conn.execute(
        "INSERT INTO applications (job_id, status) VALUES (?, 'discovered')", (job_id,)
    )
    conn.commit()
    return job_id, True


def all_jobs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()


# ---------- scores ----------
def get_score(conn: sqlite3.Connection, job_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM scores WHERE job_id = ?", (job_id,)).fetchone()


def upsert_score(
    conn: sqlite3.Connection,
    job_id: int,
    overall: float,
    gate_passed: bool,
    dimensions_json: str,
    rationale: str,
) -> None:
    conn.execute(
        """
        INSERT INTO scores (job_id, overall, gate_passed, dimensions_json, rationale, scored_at)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(job_id) DO UPDATE SET
            overall=excluded.overall,
            gate_passed=excluded.gate_passed,
            dimensions_json=excluded.dimensions_json,
            rationale=excluded.rationale,
            scored_at=excluded.scored_at
        """,
        (job_id, overall, int(gate_passed), dimensions_json, rationale, utcnow()),
    )
    conn.commit()


def unscored_job_ids(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute(
        "SELECT j.id FROM jobs j LEFT JOIN scores s ON s.job_id = j.id "
        "WHERE s.job_id IS NULL ORDER BY j.id"
    ).fetchall()
    return [r["id"] for r in rows]


# ---------- applications ----------
def get_application(conn: sqlite3.Connection, job_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM applications WHERE job_id = ?", (job_id,)
    ).fetchone()


def set_status(
    conn: sqlite3.Connection,
    job_id: int,
    status: str,
    note: Optional[str] = None,
    applied_at: Optional[str] = None,
) -> None:
    fields = ["status = ?"]
    params: list = [status]
    if note is not None:
        fields.append("notes = ?")
        params.append(note)
    if applied_at is not None:
        fields.append("applied_at = ?")
        params.append(applied_at)
    params.append(job_id)
    conn.execute(
        f"UPDATE applications SET {', '.join(fields)} WHERE job_id = ?", tuple(params)
    )
    conn.commit()


def set_doc_paths(
    conn: sqlite3.Connection,
    job_id: int,
    resume_path: Optional[str] = None,
    cover_path: Optional[str] = None,
) -> None:
    conn.execute(
        "UPDATE applications SET resume_path = COALESCE(?, resume_path), "
        "cover_path = COALESCE(?, cover_path) WHERE job_id = ?",
        (resume_path, cover_path, job_id),
    )
    conn.commit()


def status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) n FROM applications GROUP BY status"
    ).fetchall()
    return {r["status"]: r["n"] for r in rows}


# ---------- events (honest activity log) ----------
def log_event(
    conn: sqlite3.Connection,
    kind: str,
    detail: str = "",
    job_id: Optional[int] = None,
) -> None:
    conn.execute(
        "INSERT INTO events (job_id, kind, detail, at) VALUES (?,?,?,?)",
        (job_id, kind, detail, utcnow()),
    )
    conn.commit()


def events(conn: sqlite3.Connection, job_id: Optional[int] = None) -> list[sqlite3.Row]:
    if job_id is None:
        return conn.execute("SELECT * FROM events ORDER BY id").fetchall()
    return conn.execute(
        "SELECT * FROM events WHERE job_id = ? ORDER BY id", (job_id,)
    ).fetchall()
