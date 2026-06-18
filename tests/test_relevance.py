"""Resume-fit ranking and seniority/off-track filtering for scan/discover."""
import pytest

from jobpilot import relevance


def test_detect_seniority():
    assert relevance.detect_seniority("Senior Machine Learning Engineer") == "senior"
    assert relevance.detect_seniority("Staff Software Engineer") == "senior"
    assert relevance.detect_seniority("Principal Data Scientist") == "senior"
    assert relevance.detect_seniority("Engineering Manager") == "senior"
    assert relevance.detect_seniority("Sr. Alliance Director, AI GTM") == "senior"
    assert relevance.detect_seniority("Machine Learning Engineer") == "mid"
    assert relevance.detect_seniority("New Grad Software Engineer") == "entry"
    assert relevance.detect_seniority("Data Science Intern") == "entry"


def test_offtrack_titles_flagged():
    for title in ["Product Manager, Growth", "Account Executive", "Sr. Alliance Director",
                  "Recruiter", "Customer Success Manager", "UX Designer"]:
        c = relevance.annotate({"title": title, "jd_text": "great company doing things"})
        assert c["off_track"] is True


def test_rank_drops_senior_and_offtrack():
    cands = [
        {"title": "Senior ML Engineer", "company": "A", "jd_text": "machine learning pytorch python"},
        {"title": "Product Manager", "company": "B", "jd_text": "roadmap strategy stakeholders"},
        {"title": "Machine Learning Engineer", "company": "C", "jd_text": "machine learning pytorch python llm"},
        {"title": "New Grad Software Engineer", "company": "D", "jd_text": "react node typescript backend api"},
    ]
    out = relevance.rank(cands)
    titles = [c["title"] for c in out]
    # senior and PM dropped; entry/mid engineering kept
    assert "Senior ML Engineer" not in titles
    assert "Product Manager" not in titles
    assert "Machine Learning Engineer" in titles
    assert "New Grad Software Engineer" in titles
    # entry sorts before mid
    assert titles.index("New Grad Software Engineer") < titles.index("Machine Learning Engineer")


def test_rank_can_include_senior():
    cands = [{"title": "Senior ML Engineer", "company": "A",
              "jd_text": "machine learning pytorch python deep learning llm"}]
    assert relevance.rank(cands, include_senior=False) == []
    kept = relevance.rank(cands, include_senior=True)
    assert len(kept) == 1
    assert kept[0]["seniority"] == "senior"


def test_annotate_sets_fit_and_track():
    c = relevance.annotate({"title": "Machine Learning Engineer",
                            "jd_text": "build ML systems with python pytorch and deep learning"})
    assert 0 <= c["fit"] <= 100
    assert c["track"]
    assert c["fit"] > 0


def test_fallback_without_engine(monkeypatch):
    # Force the no-jd_agent path and confirm it still ranks engineering roles.
    monkeypatch.setattr(relevance, "_fit_with_engine", lambda text: None)
    cands = [
        {"title": "Machine Learning Engineer", "jd_text": "machine learning deep learning pytorch model ai"},
        {"title": "Account Executive", "jd_text": "sales quota pipeline"},
    ]
    out = relevance.rank(cands)
    assert [c["title"] for c in out] == ["Machine Learning Engineer"]
