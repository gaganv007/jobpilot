"""Adzuna source, settings, and the full-time new-grad filters."""
import pytest
from fastapi.testclient import TestClient

from jobpilot import config, discover, relevance
from jobpilot.web.server import app

client = TestClient(app)


# ---- intern / phd filtering ----
def test_intern_and_phd_excluded_by_default():
    cands = [
        {"title": "Machine Learning Engineer", "jd_text": "python pytorch deep learning ml"},
        {"title": "Machine Learning Intern", "jd_text": "python pytorch ml"},
        {"title": "Machine Learning Engineer, PhD", "jd_text": "python ml"},
        {"title": "ML Research Co-op", "jd_text": "python ml deep learning"},
    ]
    titles = [c["title"] for c in relevance.rank(cands)]
    assert titles == ["Machine Learning Engineer"]


def test_include_intern_and_phd_flags():
    cands = [
        {"title": "Machine Learning Intern", "jd_text": "python pytorch deep learning ml"},
        {"title": "Data Scientist, PhD", "jd_text": "statistics sql ml python data"},
    ]
    assert relevance.rank(cands) == []
    assert len(relevance.rank(cands, include_intern=True, include_phd=True)) == 2


def test_phd_required_from_jd():
    c = relevance.annotate({"title": "Machine Learning Engineer",
                            "jd_text": "This role requires a PhD in computer science."})
    assert c["phd_required"] is True
    c2 = relevance.annotate({"title": "Machine Learning Engineer",
                             "jd_text": "MS or PhD welcome; strong Python."})
    assert c2["phd_required"] is False  # "or PhD" is allowed


# ---- Adzuna source ----
def test_adzuna_returns_empty_without_creds(monkeypatch):
    monkeypatch.setattr(config, "adzuna_creds", lambda: None)
    assert discover.search_adzuna("ml") == []


def test_adzuna_parses(monkeypatch):
    monkeypatch.setattr(config, "adzuna_creds", lambda: ("id", "key"))

    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"results": [{
                "title": "Machine Learning Engineer",
                "company": {"display_name": "Acme"},
                "location": {"display_name": "Boston, MA"},
                "description": "Build ML systems with Python.",
                "redirect_url": "https://adzuna/apply/1",
            }]}
    captured = {}
    def fake_get(url, params=None, **k):
        captured.update(params or {})
        return FakeResp()
    monkeypatch.setattr(discover.httpx, "get", fake_get)

    out = discover.search_adzuna("machine learning", location="Boston", exclude="senior intern")
    assert out[0]["company"] == "Acme"
    assert out[0]["apply_url"] == "https://adzuna/apply/1"
    assert out[0]["source"] == "adzuna"
    assert captured["what"] == "machine learning"
    assert captured["where"] == "Boston"
    assert captured["what_exclude"] == "senior intern"


# ---- settings endpoint ----
def test_settings_roundtrip(monkeypatch):
    # No creds -> not configured.
    assert client.get("/api/settings").json()["adzuna"] is False

    monkeypatch.setattr("jobpilot.web.server.discover.search_adzuna", lambda *a, **k: [{"url": "x"}])
    r = client.post("/api/settings", json={"adzuna_app_id": "abc", "adzuna_app_key": "def"})
    body = r.json()
    assert body["adzuna"] is True
    assert body["verified"] is True
    assert config.get_settings()["adzuna_app_id"] == "abc"


def test_search_reports_adzuna_status():
    r = client.post("/api/search", json={"query": "machine learning", "companies": False, "boards": False})
    assert "adzuna" in r.json()
