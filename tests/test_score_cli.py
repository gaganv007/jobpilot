"""Phase 2: `score` command wiring (uses an injected LLM reply so it needs no
jd_agent and no network)."""
import json
from pathlib import Path

from typer.testing import CliRunner

from jobpilot import db, scoring
from jobpilot.cli import app
from jobpilot.models import Status

runner = CliRunner()


def _seed_job():
    conn = db.connect()
    jid, _ = db.add_job(conn, "https://x.com/job/1", company="Acme", title="ML Eng",
                        jd_text="Build ML systems.")
    conn.close()
    return jid


def _reply_file(tmp_path, score=4):
    data = {d: {"score": score, "rationale": "r"} for d in scoring.DIMENSIONS}
    p = tmp_path / "reply.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def test_score_with_reply_passes_gate(tmp_path):
    jid = _seed_job()
    rf = _reply_file(tmp_path, score=5)
    result = runner.invoke(app, ["score", str(jid), "--reply", rf])
    assert result.exit_code == 0
    conn = db.connect()
    sc = db.get_score(conn, jid)
    assert sc is not None
    assert sc["gate_passed"] == 1
    assert sc["overall"] == 5.0
    # status advanced discovered -> scored
    assert db.get_application(conn, jid)["status"] == Status.scored.value
    conn.close()


def test_score_with_failing_gate_caps(tmp_path):
    jid = _seed_job()
    data = {d: {"score": 5, "rationale": "r"} for d in scoring.DIMENSIONS}
    data["Role Match"] = {"score": 1, "rationale": "weak"}
    p = tmp_path / "reply.json"
    p.write_text(json.dumps(data), encoding="utf-8")

    result = runner.invoke(app, ["score", str(jid), "--reply", str(p)])
    assert result.exit_code == 0
    assert "FAIL" in result.stdout
    conn = db.connect()
    sc = db.get_score(conn, jid)
    assert sc["gate_passed"] == 0
    assert sc["overall"] <= scoring.CAP_WHEN_GATE_FAILS
    conn.close()


def test_score_prompt_mode_prints_prompt(tmp_path):
    jid = _seed_job()
    result = runner.invoke(app, ["score", str(jid), "--prompt"])
    assert result.exit_code == 0
    assert "Role Match" in result.stdout
    # prompt mode must not write a score
    conn = db.connect()
    assert db.get_score(conn, jid) is None
    conn.close()


def test_score_does_not_override_human_status(tmp_path):
    jid = _seed_job()
    conn = db.connect()
    db.set_status(conn, jid, Status.applied.value)
    conn.close()
    rf = _reply_file(tmp_path, score=5)
    runner.invoke(app, ["score", str(jid), "--reply", rf])
    conn = db.connect()
    # human 'applied' status preserved, not reset to 'scored'
    assert db.get_application(conn, jid)["status"] == Status.applied.value
    conn.close()
