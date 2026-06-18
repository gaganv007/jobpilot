"""Web API tests (FastAPI TestClient). Network-free: discovery is monkeypatched."""
import pytest
from fastapi.testclient import TestClient

from jobpilot import discover
from jobpilot.web.server import app

client = TestClient(app)


def test_index_serves_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "JobPilot" in r.text


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert "jd_agent" in r.json()


def test_add_paste_and_state():
    r = client.post("/api/jobs", json={"title": "ML Eng", "company": "Acme", "jd_text": "Build ML systems."})
    assert r.status_code == 200
    jid = r.json()["id"]

    state = client.get("/api/state").json()
    assert any(j["id"] == jid for j in state["jobs"])
    assert "discovered" in state["counts"]


def test_paste_requires_jd():
    r = client.post("/api/jobs", json={"jd_text": "   "})
    assert r.status_code == 400


def test_job_detail_and_status_flow():
    jid = client.post("/api/jobs", json={"title": "T", "jd_text": "Python role"}).json()["id"]

    detail = client.get(f"/api/jobs/{jid}").json()
    assert detail["id"] == jid
    assert "ats" in detail and "weights" in detail

    # human-only status flagged
    r = client.post(f"/api/jobs/{jid}/status", json={"status": "applied", "note": "by hand"})
    assert r.status_code == 200
    assert r.json()["human_action"] is True

    r = client.post(f"/api/jobs/{jid}/status", json={"status": "nonsense"})
    assert r.status_code == 400


def test_research_prep_packet_generate():
    jid = client.post("/api/jobs", json={"title": "Data Scientist", "company": "Globex",
                                         "jd_text": "Power BI dashboards, SQL, forecasting."}).json()["id"]
    for ep in ("research", "prep", "packet"):
        r = client.post(f"/api/jobs/{jid}/{ep}")
        assert r.status_code == 200
        assert r.json()["markdown"]
    # packet must always carry the never-applies reminder
    pk = client.post(f"/api/jobs/{jid}/packet").json()["markdown"]
    assert "never applies" in pk.lower()


def test_delete_job():
    jid = client.post("/api/jobs", json={"jd_text": "x"}).json()["id"]
    assert client.delete(f"/api/jobs/{jid}").status_code == 200
    assert client.get(f"/api/jobs/{jid}").status_code == 404


def test_file_endpoint_blocks_traversal():
    jid = client.post("/api/jobs", json={"jd_text": "x"}).json()["id"]
    r = client.get(f"/api/jobs/{jid}/file/..%2F..%2Fsecret")
    assert r.status_code in (400, 404)


def test_discover_endpoint_monkeypatched(monkeypatch):
    sample = [{"url": "https://j/1", "company": "Co", "title": "ML Eng",
               "location": "Remote", "source": "remotive.com", "jd_text": "ml", "remote": True}]
    monkeypatch.setattr(discover, "discover", lambda q, s=None, limit=25: sample)
    # server imported the module symbol; patch there too
    from jobpilot.web import server
    monkeypatch.setattr(server.discover, "discover", lambda q, s=None, limit=25: sample)

    r = client.post("/api/discover", json={"query": "ml", "sources": ["remotive"]})
    assert r.status_code == 200
    assert r.json()["results"][0]["title"] == "ML Eng"


def test_discover_parsing_from_fake_payload(monkeypatch):
    """discover.search_remotive normalizes the public API shape (httpx mocked)."""
    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"jobs": [{"url": "https://r/1", "company_name": "Acme",
                              "title": "ML Engineer", "candidate_required_location": "USA",
                              "description": "<p>Build <b>ML</b> systems</p>"}]}

    monkeypatch.setattr(discover.httpx, "get", lambda *a, **k: FakeResp())
    out = discover.search_remotive("ml", limit=5)
    assert out[0]["company"] == "Acme"
    assert "ML" in out[0]["jd_text"]
    assert "<p>" not in out[0]["jd_text"]  # HTML stripped
