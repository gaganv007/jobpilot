"""Unified multi-source search: The Muse parsing, keyword filter, /api/search."""
import pytest
from fastapi.testclient import TestClient

from jobpilot import discover, scan
from jobpilot.web.server import app

client = TestClient(app)


def test_themuse_parse(monkeypatch):
    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"results": [{
                "name": "Machine Learning Engineer",
                "company": {"name": "Acme"},
                "locations": [{"name": "Boston, MA"}],
                "contents": "<p>Build ML with Python</p>",
                "refs": {"landing_page": "https://themuse/jobs/acme/ml"},
            }]}
    monkeypatch.setattr(discover.httpx, "get", lambda *a, **k: FakeResp())
    out = discover.search_themuse("machine learning", pages=1)
    assert out and out[0]["company"] == "Acme"
    assert out[0]["apply_url"] == "https://themuse/jobs/acme/ml"
    assert "<p>" not in out[0]["jd_text"]


def test_keyword_filter_synonyms():
    items = [
        {"title": "Machine Learning Engineer", "jd_text": "pytorch"},
        {"title": "Sales Associate", "jd_text": "quota"},
    ]
    # "ml" should match "machine learning" via synonym expansion
    out = discover._keyword_filter(items, "ml")
    assert len(out) == 1 and out[0]["title"] == "Machine Learning Engineer"


def test_search_merges_and_dedupes(monkeypatch):
    a = [{"url": "u1", "title": "ML Eng", "company": "A", "location": "", "source": "themuse.com", "jd_text": "ml"}]
    b = [{"url": "u1", "title": "ML Eng dup", "company": "A", "location": "", "source": "remotive.com", "jd_text": "ml"},
         {"url": "u2", "title": "Data Sci", "company": "B", "location": "", "source": "remotive.com", "jd_text": "data"}]
    monkeypatch.setattr(discover, "search_themuse", lambda q, location="", pages=1: a)
    monkeypatch.setattr(discover, "search_remotive", lambda q, limit=25: b)
    monkeypatch.setattr(discover, "search_arbeitnow", lambda q, limit=25: [])
    out = discover.search("ml")
    urls = sorted(c["url"] for c in out)
    assert urls == ["u1", "u2"]  # u1 deduped


def test_scan_matches_title_with_synonyms():
    job = {"title": "Machine Learning Engineer", "jd_text": "build models"}
    assert scan._matches(job, "ml") is True       # synonym
    assert scan._matches(job, "machine learning") is True
    assert scan._matches(job, "sales") is False


def test_scan_apply_url_present(monkeypatch):
    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"jobs": [{"title": "ML Engineer", "absolute_url": "https://gh/x/1",
                              "location": {"name": "Remote"}, "content": "ml"}]}
    monkeypatch.setattr(scan.httpx, "get", lambda *a, **k: FakeResp())
    out = scan.fetch_greenhouse("x", "X")
    assert out[0]["apply_url"] == "https://gh/x/1"


def test_search_endpoint(monkeypatch):
    from jobpilot.web import server

    sample = [{"url": "https://c/1", "title": "Machine Learning Engineer", "company": "Acme",
               "location": "Boston", "source": "greenhouse/acme",
               "jd_text": "Build ML and deep learning with Python and PyTorch.", "remote": False,
               "apply_url": "https://c/1"}]
    monkeypatch.setattr(server.scan_mod, "scan", lambda targets, q, per, tot: sample)
    monkeypatch.setattr(server.discover, "search", lambda q, loc, src, lim: [])
    r = client.post("/api/search", json={"query": "machine learning", "location": "Boston"})
    assert r.status_code == 200
    body = r.json()
    assert body["results"], "should return ranked results"
    top = body["results"][0]
    assert top["fit"] > 0 and top["apply_url"] == "https://c/1"
