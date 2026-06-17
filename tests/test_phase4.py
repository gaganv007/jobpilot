"""Phase 4: research, prep (STAR+R), and the one-page packet."""
from typer.testing import CliRunner

from jobpilot import db, prep, profile, research
from jobpilot.cli import app

runner = CliRunner()

JD = ("Machine Learning Engineer. Build LLM and RAG systems with Python and PyTorch on AWS. "
      "Experience with Kubernetes and CI/CD. Strong SQL.")


def _seed(jd=JD, company="Acme AI", title="ML Engineer"):
    conn = db.connect()
    jid, _ = db.add_job(conn, "https://x.com/job/1", company=company, title=title, jd_text=jd)
    conn.close()
    return jid


# ---- profile / story selection ----
def test_select_stories_prefers_overlap():
    chosen = profile.select_stories(JD, k=3)
    assert len(chosen) == 3
    # the Gavel (LLM/RAG/AWS) or retention (ML) stories should surface
    titles = [s["title"] for s, _ in chosen]
    assert any("Gavel" in t or "retention" in t.lower() for t in titles)


def test_select_stories_generic_jd_falls_back():
    chosen = profile.select_stories("We value teamwork and communication.", k=3)
    assert len(chosen) == 3  # still returns stories, honestly unlabeled


# ---- research ----
def test_research_tech_detection_and_points():
    job = {"company": "Acme", "title": "ML Eng", "jd_text": JD}
    stack = research.tech_in_jd(JD)
    assert "python" in stack and "pytorch" in stack and "kubernetes" in stack
    pts = research.talking_points(job)
    assert len(pts) == 3
    qs = research.smart_questions(job)
    assert len(qs) == 2


def test_research_summary_is_jd_grounded():
    job = {"company": "Acme", "title": "ML Eng", "jd_text": JD}
    summary = research.company_summary(job)
    assert "Acme" in summary
    assert "verify" in summary.lower()  # honesty caveat present


# ---- prep ----
def test_prep_doc_has_star_and_topics():
    job = {"company": "Acme", "title": "ML Eng", "jd_text": JD}
    doc = prep.build_prep_doc(job)
    for field in ("Situation:", "Task:", "Action:", "Result:", "Reflection:"):
        assert field in doc
    assert "Likely technical topics" in doc


def test_likely_topics_from_jd():
    topics = prep.likely_topics(JD)
    assert any("LLM" in t or "ML" in t for t in topics)


# ---- CLI ----
def test_research_cli_writes_file():
    jid = _seed()
    result = runner.invoke(app, ["research", str(jid)])
    assert result.exit_code == 0
    conn = db.connect()
    assert any(e["kind"] == "research" for e in db.events(conn, jid))
    conn.close()


def test_prep_cli_prompt_mode():
    jid = _seed()
    result = runner.invoke(app, ["prep", str(jid), "--prompt"])
    assert result.exit_code == 0
    assert "STAR" in result.stdout or "interview" in result.stdout.lower()


def test_packet_cli_assembles():
    jid = _seed()
    # score it first so the packet shows a fit score
    from jobpilot import scoring
    import json
    conn = db.connect()
    dims = {d: 4 for d in scoring.DIMENSIONS}
    overall, gate = scoring.compute_overall(dims)
    db.upsert_score(conn, jid, overall, gate, json.dumps(dims), "ok")
    conn.close()

    result = runner.invoke(app, ["packet", str(jid)])
    assert result.exit_code == 0
    out = result.stdout
    assert "Application packet" in out
    assert "never applies" in out.lower()
    # apply link present
    assert "https://x.com/job/1" in out
