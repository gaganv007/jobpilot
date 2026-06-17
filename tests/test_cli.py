"""Phase 0: CLI skeleton smoke tests."""
from typer.testing import CliRunner

from jobpilot import db
from jobpilot.cli import app
from jobpilot.models import Status

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "JobPilot" in result.stdout


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("add", "score", "tailor", "research", "prep", "board", "status", "batch"):
        assert cmd in result.stdout


def test_board_empty():
    result = runner.invoke(app, ["board"])
    assert result.exit_code == 0
    assert "No jobs yet" in result.stdout


def test_status_updates_pipeline():
    conn = db.connect()
    job_id, _ = db.add_job(conn, "https://x.com/job/1")
    conn.close()

    result = runner.invoke(app, ["status", str(job_id), "tailored"])
    assert result.exit_code == 0

    conn = db.connect()
    appn = db.get_application(conn, job_id)
    assert appn["status"] == Status.tailored.value
    conn.close()


def test_status_rejects_invalid():
    conn = db.connect()
    job_id, _ = db.add_job(conn, "https://x.com/job/1")
    conn.close()
    result = runner.invoke(app, ["status", str(job_id), "bogus"])
    assert result.exit_code == 1
    assert "Invalid status" in result.stdout


def test_status_applied_sets_real_timestamp():
    conn = db.connect()
    job_id, _ = db.add_job(conn, "https://x.com/job/1")
    conn.close()
    result = runner.invoke(app, ["status", str(job_id), "applied"])
    assert result.exit_code == 0
    conn = db.connect()
    appn = db.get_application(conn, job_id)
    assert appn["applied_at"] is not None
    conn.close()


def test_stub_commands_exit_nonzero():
    # Phase-0 stubs should fail loudly rather than pretend to work.
    for args in (["add", "http://x"], ["tailor", "1"], ["research", "1"], ["prep", "1"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 1
