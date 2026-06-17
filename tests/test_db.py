"""Phase 0: schema, migrations, dedup, and honest-timestamp behavior."""
from datetime import datetime, timezone

from jobpilot import db
from jobpilot.models import Status


def test_schema_version_applied(conn):
    assert db.schema_version(conn) == 1
    tables = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"jobs", "scores", "applications", "events"} <= tables


def test_migrate_is_idempotent(conn):
    # Reconnecting to the same DB must not re-run migrations or error.
    again = db.connect()
    assert db.schema_version(again) == 1
    again.close()


def test_add_job_creates_application_row(conn):
    job_id, created = db.add_job(conn, "https://x.com/job/1", company="Acme", title="ML Eng")
    assert created is True
    appn = db.get_application(conn, job_id)
    assert appn["status"] == Status.discovered.value


def test_add_job_dedups_on_url(conn):
    first_id, created1 = db.add_job(conn, "https://x.com/job/1", company="Acme")
    second_id, created2 = db.add_job(conn, "https://x.com/job/1", company="DIFFERENT")
    assert created1 is True
    assert created2 is False
    assert first_id == second_id
    # Existing row is never overwritten by a duplicate add.
    job = db.get_job(conn, first_id)
    assert job["company"] == "Acme"


def test_timestamps_are_real_utc(conn):
    before = datetime.now(timezone.utc)
    job_id, _ = db.add_job(conn, "https://x.com/job/ts")
    job = db.get_job(conn, job_id)
    ts = datetime.fromisoformat(job["created_at"])
    # Honest timestamp: within a sane window of "now", and timezone-aware UTC.
    assert ts.tzinfo is not None
    assert abs((ts - before).total_seconds()) < 60


def test_unscored_job_ids(conn):
    a, _ = db.add_job(conn, "https://x.com/a")
    b, _ = db.add_job(conn, "https://x.com/b")
    assert set(db.unscored_job_ids(conn)) == {a, b}
    db.upsert_score(conn, a, overall=4.0, gate_passed=True, dimensions_json="{}", rationale="ok")
    assert db.unscored_job_ids(conn) == [b]


def test_status_counts(conn):
    a, _ = db.add_job(conn, "https://x.com/a")
    b, _ = db.add_job(conn, "https://x.com/b")
    db.set_status(conn, a, Status.tailored.value)
    counts = db.status_counts(conn)
    assert counts[Status.tailored.value] == 1
    assert counts[Status.discovered.value] == 1


def test_event_log(conn):
    job_id, _ = db.add_job(conn, "https://x.com/a")
    db.log_event(conn, "test_kind", "detail here", job_id=job_id)
    evs = db.events(conn, job_id=job_id)
    assert evs[-1]["kind"] == "test_kind"
    assert evs[-1]["detail"] == "detail here"
