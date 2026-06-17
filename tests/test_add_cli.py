"""Phase 1: `add` command — dedup, robots refusal, board listing.

Network is monkeypatched: fetch_html returns a saved fixture so no browser or
internet is used in tests.
"""
from pathlib import Path

from typer.testing import CliRunner

from jobpilot import db, extract
from jobpilot.cli import app

runner = CliRunner()
FIX = Path(__file__).parent / "fixtures"


def _patch_fetch(monkeypatch, fixture="job_jsonld.html", allow=True):
    html = (FIX / fixture).read_text(encoding="utf-8")
    monkeypatch.setattr(extract, "fetch_html", lambda url, delay=0: html)
    monkeypatch.setattr(extract, "robots_allows", lambda url, user_agent=extract.USER_AGENT: allow)


def test_add_stores_job(monkeypatch):
    _patch_fetch(monkeypatch)
    result = runner.invoke(app, ["add", "https://boards.acme.ai/jobs/123", "--delay", "0"])
    assert result.exit_code == 0
    assert "Added job" in result.stdout

    conn = db.connect()
    job = db.job_by_url(conn, "https://boards.acme.ai/jobs/123")
    assert job is not None
    assert job["company"] == "Acme AI"
    # an 'add' event was logged
    assert any(e["kind"] == "add" for e in db.events(conn, job["id"]))
    conn.close()


def test_add_dedups_without_refetch(monkeypatch):
    _patch_fetch(monkeypatch)
    url = "https://boards.acme.ai/jobs/123"
    runner.invoke(app, ["add", url, "--delay", "0"])

    # Second add must not call fetch again.
    def boom(*a, **k):
        raise AssertionError("fetch_html should not be called for a duplicate")

    monkeypatch.setattr(extract, "fetch_html", boom)
    result = runner.invoke(app, ["add", url, "--delay", "0"])
    assert result.exit_code == 0
    assert "Already tracked" in result.stdout


def test_add_refuses_when_robots_disallow(monkeypatch):
    _patch_fetch(monkeypatch, allow=False)
    result = runner.invoke(app, ["add", "https://blocked.com/job", "--delay", "0"])
    assert result.exit_code == 1
    assert "Refusing to fetch" in result.stdout
    conn = db.connect()
    assert db.job_by_url(conn, "https://blocked.com/job") is None
    assert any(e["kind"] == "robots_blocked" for e in db.events(conn))
    conn.close()


def test_add_rejects_bad_url(monkeypatch):
    result = runner.invoke(app, ["add", "not-a-url"])
    assert result.exit_code == 1
    assert "valid http" in result.stdout


def test_board_lists_added_job(monkeypatch):
    _patch_fetch(monkeypatch)
    runner.invoke(app, ["add", "https://boards.acme.ai/jobs/123", "--delay", "0"])
    result = runner.invoke(app, ["board"])
    assert result.exit_code == 0
    assert "Tracked jobs" in result.stdout
    assert "Acme AI" in result.stdout
