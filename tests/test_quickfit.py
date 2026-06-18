"""Quick-fit estimate: instant ranking on add, full rubric deferred."""
import pytest
from fastapi.testclient import TestClient

from jobpilot import relevance
from jobpilot.web.server import app

client = TestClient(app)


def test_quick_fit_shape():
    qf = relevance.quick_fit("Machine Learning Engineer",
                             "Build ML and deep learning with Python and PyTorch.")
    assert set(qf) == {"fit", "track", "seniority"}
    assert 0 <= qf["fit"] <= 100
    assert qf["fit"] > 0
    assert qf["track"]


def test_quick_fit_is_cached_and_stable():
    a = relevance.quick_fit("Data Scientist", "SQL, Power BI, forecasting, statistics.")
    b = relevance.quick_fit("Data Scientist", "SQL, Power BI, forecasting, statistics.")
    assert a == b


def test_bulk_add_without_score_returns_instantly_with_quick_fit():
    body = {"jobs": [
        {"title": "Machine Learning Engineer", "company": "Aurora",
         "jd_text": "Build ML and RAG with Python, PyTorch. Remote.", "url": "https://q/1"},
    ], "score": False}
    r = client.post("/api/jobs/bulk", json=body).json()
    assert r["added"] == 1
    assert r["scored"] == 0  # full rubric deferred

    # state should carry a quick_fit for the unscored job
    jobs = client.get("/api/state").json()["jobs"]
    mine = [j for j in jobs if j["title"] == "Machine Learning Engineer"]
    assert mine and mine[0]["score"] is None
    assert mine[0]["quick_fit"] is not None and mine[0]["quick_fit"] > 0
    assert "quick_track" in mine[0]


def test_detail_has_quick_fit_until_scored():
    jid = client.post("/api/jobs", json={"title": "ML Engineer",
                                         "jd_text": "machine learning python pytorch deep learning"}).json()["id"]
    detail = client.get(f"/api/jobs/{jid}").json()
    assert detail["score"] is None
    assert detail["quick_fit"] > 0
