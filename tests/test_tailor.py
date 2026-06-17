"""Phase 3: tailoring — honesty guard, evidence mapping, and PDF integration."""
import pytest

from jobpilot import tailor


# ---- pure honesty logic (monkeypatched, no jd_agent needed) ----
def test_honesty_rejects_unsupported_skill(monkeypatch):
    monkeypatch.setattr(tailor, "base_resume_text", lambda t: "Python and React and SQL.")
    monkeypatch.setattr(tailor, "base_summary", lambda t: "Original summary.")
    monkeypatch.setattr(tailor, "_skill_vocab", lambda: {"python", "react", "kafka", "rust"})

    res = tailor.honesty_check("AI/ML Engineer", "Built pipelines with Python and Kafka and Rust.")
    assert res.ok is False
    assert set(res.violations) == {"kafka", "rust"}
    # On rejection we fall back to the real summary, unchanged.
    assert res.summary_used == "Original summary."
    assert res.summary_changed is False


def test_honesty_accepts_supported_summary(monkeypatch):
    monkeypatch.setattr(tailor, "base_resume_text", lambda t: "Python PyTorch AWS Kubernetes.")
    monkeypatch.setattr(tailor, "base_summary", lambda t: "Old.")
    monkeypatch.setattr(tailor, "_skill_vocab", lambda: {"python", "pytorch", "aws", "kubernetes", "rust"})

    res = tailor.honesty_check("AI/ML Engineer", "ML engineer skilled in Python, PyTorch and AWS.")
    assert res.ok is True
    assert res.violations == []
    assert res.summary_changed is True
    assert "PyTorch" in res.summary_used


def test_empty_summary_uses_base(monkeypatch):
    monkeypatch.setattr(tailor, "base_summary", lambda t: "Base summary.")
    res = tailor.honesty_check("AI/ML Engineer", "")
    assert res.ok is True
    assert res.summary_used == "Base summary."
    assert res.summary_changed is False


# ---- evidence mapping (monkeypatched bullets) ----
def test_evidence_map_links_bullets_to_requirements(monkeypatch):
    monkeypatch.setattr(
        tailor, "base_bullets",
        lambda t: [
            "Built RF and XGBoost retention models with 89% accuracy on 15000 records",
            "Shipped a Next.js frontend for a live oracle",
        ],
    )
    jd = ("We need someone to build XGBoost and retention models on large records.\n"
          "Frontend experience with React is a plus.")
    em = tailor.evidence_map(jd, "AI/ML Engineer")
    assert em[0]["answers"]  # first bullet matches the modeling requirement
    assert "xgboost" in em[0]["shared"]


def test_keyword_helpers_drop_stopwords():
    kws = tailor._keywords("We will build a scalable XGBoost model for the team")
    assert "xgboost" in kws
    assert "the" not in kws and "will" not in kws


# ---- full integration (needs jd_agent + reportlab) ----
def _bridge_ok():
    from jobpilot import jd_bridge

    return jd_bridge.available()


@pytest.mark.skipif(not _bridge_ok(), reason="jd_agent not available")
def test_tailor_job_builds_resume_and_receipts(tmp_path):
    job = {
        "url": "https://x/job",
        "company": "Acme AI",
        "title": "Machine Learning Engineer",
        "jd_text": "Build ML and RAG systems with Python, PyTorch, AWS and Kubernetes.",
    }
    result = tailor.tailor_job(job, tmp_path)
    import os

    assert os.path.exists(result.resume_path)
    assert os.path.getsize(result.resume_path) > 1000  # a real PDF
    assert os.path.exists(result.evidence_path)
    assert os.path.exists(result.receipt_path)
    # no reply -> cover not built, prompt written instead
    assert result.cover_path is None
    assert os.path.exists(result.prompt_path)
    receipt = open(result.receipt_path).read()
    assert "No-fabrication check" in receipt


@pytest.mark.skipif(not _bridge_ok(), reason="jd_agent not available")
def test_tailor_job_with_reply_builds_cover_and_guards_fabrication(tmp_path):
    job = {
        "url": "https://x/job2",
        "company": "Acme AI",
        "title": "ML Engineer",
        "jd_text": "Build ML systems with Python and PyTorch. Kafka a plus.",
    }
    # Reply sneaks in 'Kafka', which is not in the resume -> must be rejected.
    reply = (
        "TRACK: AI/ML Engineer\n\n"
        "SUMMARY:\nML engineer expert in Python, PyTorch and Kafka streaming.\n\n"
        "COVER LETTER:\nFirst paragraph about the role.\n\n"
        "Second paragraph about the company.\n\n"
        "Third paragraph with achievements.\n\n"
        "Fourth paragraph closing from Boston.\n"
    )
    result = tailor.tailor_job(job, tmp_path, reply_text=reply)
    import os

    assert os.path.exists(result.cover_path)  # cover built from the reply body
    assert result.honesty.ok is False
    assert "kafka" in result.honesty.violations
    receipt = open(result.receipt_path).read()
    assert "REJECTED" in receipt
