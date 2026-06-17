"""Phase 5: batch worker pool (locks, resumable), gaps, calibration."""
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jobpilot import batch, calibration, db, scoring
from jobpilot.cli import app
from jobpilot.models import Status

runner = CliRunner()
FIX = Path(__file__).parent / "fixtures"


# ---- locks ----
def test_lock_acquire_release():
    url = "https://x.com/job/lock"
    assert batch.acquire_lock(url) is True
    assert batch.acquire_lock(url) is False  # second acquire blocked
    batch.release_lock(url)
    assert batch.acquire_lock(url) is True  # available again
    batch.release_lock(url)


def test_stale_lock_is_reclaimed():
    url = "https://x.com/job/stale"
    assert batch.acquire_lock(url) is True
    # A lock with a 0-second staleness threshold is immediately reclaimable.
    assert batch.acquire_lock(url, stale_seconds=0) is True
    batch.release_lock(url)


def test_read_urls_dedups_and_skips_comments(tmp_path):
    f = tmp_path / "urls.txt"
    f.write_text("# comment\nhttps://a.com\n\nhttps://a.com\nhttps://b.com\n")
    assert batch.read_urls(f) == ["https://a.com", "https://b.com"]


# ---- batch processing (network mocked) ----
def _patch_extract(monkeypatch, fixture="job_jsonld.html"):
    html = (FIX / fixture).read_text(encoding="utf-8")
    monkeypatch.setattr(batch.extract, "fetch_html", lambda url, delay=0: html)
    monkeypatch.setattr(batch.extract, "robots_allows", lambda url, user_agent=None: True)


def test_batch_adds_and_scores(monkeypatch):
    _patch_extract(monkeypatch)
    urls = ["https://boards.acme.ai/jobs/1", "https://boards.acme.ai/jobs/2"]
    results = batch.run_batch(urls, workers=2, delay=0)
    assert all(r.status == "done" for r in results)
    assert all(r.overall is not None for r in results)
    conn = db.connect()
    # both stored and scored
    assert len(db.all_jobs(conn)) == 2
    conn.close()


def test_batch_is_resumable(monkeypatch):
    _patch_extract(monkeypatch)
    url = "https://boards.acme.ai/jobs/1"
    batch.run_batch([url], workers=1, delay=0)

    # On a second run the URL is already scored -> skipped without re-fetching.
    def boom(*a, **k):
        raise AssertionError("should not re-fetch an already-scored URL")

    monkeypatch.setattr(batch.extract, "fetch_html", boom)
    results = batch.run_batch([url], workers=1, delay=0)
    assert results[0].status == "skipped_scored"


def test_batch_never_advances_past_scored(monkeypatch):
    _patch_extract(monkeypatch)
    batch.run_batch(["https://boards.acme.ai/jobs/1"], workers=1, delay=0)
    conn = db.connect()
    appn = db.get_application(conn, 1)
    # never applied/tailored automatically
    assert appn["status"] == Status.scored.value
    conn.close()


# ---- gaps ----
def _bridge_ok():
    from jobpilot import jd_bridge

    return jd_bridge.available()


@pytest.mark.skipif(not _bridge_ok(), reason="jd_agent not available")
def test_gap_intelligence(monkeypatch):
    conn = db.connect()
    jd = "Need Kafka and Airflow and Snowflake experience for data pipelines."
    jid, _ = db.add_job(conn, "https://x/job", title="DE", jd_text=jd)
    scored = scoring.heuristic_dimensions(jd)
    db.upsert_score(conn, jid, 3.0, True, json.dumps(scoring.dims_only(scored)), "r")
    from jobpilot import gaps

    lead = gaps.highest_leverage(conn)
    assert lead is not None
    assert lead["jobs"] >= 1
    conn.close()


# ---- calibration ----
_seed_counter = iter(range(100000))


def _seed_outcome(conn, overall, status, dims_val=4):
    n = next(_seed_counter)
    jid, _ = db.add_job(conn, f"https://x/job/{n}")
    dims = {d: dims_val for d in scoring.DIMENSIONS}
    db.upsert_score(conn, jid, overall, True, json.dumps(dims), "r")
    db.set_status(conn, jid, status)
    return jid


def test_calibration_needs_min_data():
    conn = db.connect()
    _seed_outcome(conn, 4.0, Status.interview.value)
    rep = calibration.report(conn)
    assert rep.enough_data is False
    assert "Not enough" in rep.verdict
    conn.close()


def test_calibration_detects_well_calibrated():
    conn = db.connect()
    for _ in range(3):
        _seed_outcome(conn, 4.5, Status.interview.value)
    for _ in range(3):
        _seed_outcome(conn, 2.5, Status.rejected.value)
    rep = calibration.report(conn)
    assert rep.enough_data is True
    assert rep.avg_score_positive > rep.avg_score_negative
    assert "calibrated" in rep.verdict.lower()
    conn.close()


def test_weight_overrides_change_score(tmp_path, monkeypatch):
    # Default weights vs an override that zeroes a non-gate dimension.
    dims = {d: 5 for d in scoring.DIMENSIONS}
    dims["Compensation Fit"] = 0
    base_overall, _ = scoring.compute_overall(dims)

    from jobpilot import config

    (config.home_dir() / "weights.json").write_text(
        json.dumps({"Compensation Fit": 0.0}), encoding="utf-8"
    )
    new_overall, _ = scoring.compute_overall(dims)
    # Dropping the weight of the one weak dimension should raise the mean.
    assert new_overall > base_overall


def test_calibrate_cli_runs():
    conn = db.connect()
    db.add_job(conn, "https://x/cal")
    conn.close()
    result = runner.invoke(app, ["calibrate"])
    assert result.exit_code == 0
    assert "Outcomes recorded" in result.stdout
