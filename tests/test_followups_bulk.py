"""Tests for follow-up reminders, bulk add+score, and score-all."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from jobpilot import db, followups
from jobpilot.models import Status
from jobpilot.web.server import app

client = TestClient(app)


def _bridge_ok():
    from jobpilot import jd_bridge

    return jd_bridge.available()


# ---- follow-ups ----
def test_followup_due_after_threshold():
    conn = db.connect()
    jid, _ = db.add_job(conn, "https://x/fu1", company="Acme", title="Eng")
    old = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat(timespec="seconds")
    db.set_status(conn, jid, Status.applied.value, applied_at=old)
    due = followups.needs_followup(conn, days=5)
    assert any(d["job_id"] == jid and d["days_since"] >= 9 for d in due)
    conn.close()


def test_followup_not_due_when_recent():
    conn = db.connect()
    jid, _ = db.add_job(conn, "https://x/fu2")
    db.set_status(conn, jid, Status.applied.value, applied_at=db.utcnow())
    assert followups.needs_followup(conn, days=5) == []
    conn.close()


def test_followup_ignores_non_pending_status():
    conn = db.connect()
    jid, _ = db.add_job(conn, "https://x/fu3")
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds")
    db.set_status(conn, jid, Status.offer.value, applied_at=old)  # offer = not pending
    assert all(d["job_id"] != jid for d in followups.needs_followup(conn))
    conn.close()


def test_state_includes_followups_and_unscored():
    jid = client.post("/api/jobs", json={"title": "T", "jd_text": "x"}).json()["id"]
    st = client.get("/api/state").json()
    assert "followups" in st and "unscored" in st
    assert st["unscored"] >= 1


# ---- bulk add (+ score) ----
def test_bulk_add_without_scoring():
    body = {"jobs": [
        {"title": "A", "jd_text": "Python role", "url": "https://b/1"},
        {"title": "B", "jd_text": "SQL role", "url": "https://b/2"},
    ], "score": False}
    r = client.post("/api/jobs/bulk", json=body)
    assert r.status_code == 200
    j = r.json()
    assert j["added"] == 2
    assert j["scored"] == 0


def test_bulk_dedupes():
    body = {"jobs": [{"title": "A", "jd_text": "x", "url": "https://b/dup"}], "score": False}
    client.post("/api/jobs/bulk", json=body)
    r = client.post("/api/jobs/bulk", json=body).json()
    assert r["added"] == 0  # already tracked


@pytest.mark.skipif(not _bridge_ok(), reason="jd_agent not available")
def test_bulk_add_and_score_ranks():
    body = {"jobs": [
        {"title": "ML Engineer", "company": "Aurora",
         "jd_text": "Build LLM and RAG with Python, PyTorch, AWS, Kubernetes. Remote.", "url": "https://b/ml"},
    ], "score": True}
    r = client.post("/api/jobs/bulk", json=body).json()
    assert r["scored"] == 1
    assert r["results"][0]["overall"] is not None


@pytest.mark.skipif(not _bridge_ok(), reason="jd_agent not available")
def test_score_all_endpoint():
    client.post("/api/jobs", json={"title": "X", "jd_text": "Python and SQL data role"})
    r = client.post("/api/score-all").json()
    assert r["scored"] >= 1
    # nothing left unscored
    assert client.get("/api/state").json()["unscored"] == 0
