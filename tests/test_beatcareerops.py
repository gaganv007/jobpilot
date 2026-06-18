"""Tests for the Career-Ops-beating features: company scan, legitimacy, outreach."""
import pytest
from fastapi.testclient import TestClient

from jobpilot import legitimacy, outreach, scan
from jobpilot.web.server import app

client = TestClient(app)


# ---- scan (network mocked) ----
def test_scan_greenhouse_normalizes(monkeypatch):
    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"jobs": [{
                "title": "ML Engineer", "absolute_url": "https://gh/anthropic/1",
                "location": {"name": "Remote - US"},
                "content": "&lt;p&gt;Build &lt;b&gt;ML&lt;/b&gt; systems with Python&lt;/p&gt;",
            }]}
    monkeypatch.setattr(scan.httpx, "get", lambda *a, **k: FakeResp())
    out = scan.fetch_greenhouse("anthropic", "Anthropic")
    assert out[0]["company"] == "Anthropic"
    assert out[0]["title"] == "ML Engineer"
    assert out[0]["remote"] is True
    assert out[0]["source"] == "greenhouse/anthropic"
    # JD is kept raw by the fetcher (cleaned lazily, only for matched jobs).
    assert "jd_raw" in out[0]
    # scan() cleans matched jobs: entities unescaped + tags stripped.
    monkeypatch.setattr(scan, "scan_target", lambda ats, token, label=None: out)
    cleaned = scan.scan([("greenhouse", "anthropic", "Anthropic")], query="ml")
    assert "ML" in cleaned[0]["jd_text"] and "<" not in cleaned[0]["jd_text"]


def test_scan_filters_by_query(monkeypatch):
    jobs = [
        {"url": "u1", "title": "ML Engineer", "company": "X", "location": "", "jd_text": "pytorch", "source": "s"},
        {"url": "u2", "title": "Sales Rep", "company": "X", "location": "", "jd_text": "quota", "source": "s"},
    ]
    monkeypatch.setattr(scan, "scan_target", lambda ats, token, label=None: jobs)
    res = scan.scan([("greenhouse", "x", "X")], query="ml")
    assert [r["title"] for r in res] == ["ML Engineer"]


def test_scan_dedupes_urls(monkeypatch):
    jobs = [{"url": "dup", "title": "A", "company": "X", "location": "", "jd_text": "", "source": "s"}]
    monkeypatch.setattr(scan, "scan_target", lambda ats, token, label=None: jobs)
    res = scan.scan([("greenhouse", "a", "A"), ("greenhouse", "b", "B")])
    assert len(res) == 1


def test_scan_endpoint(monkeypatch):
    from jobpilot.web import server
    monkeypatch.setattr(server.scan_mod, "scan", lambda targets=None, query="", total_limit=60: [
        {"url": "u", "title": "Machine Learning Engineer", "company": "Anthropic", "location": "Remote",
         "source": "greenhouse/anthropic",
         "jd_text": "Build machine learning and deep learning systems with Python and PyTorch and LLM.",
         "remote": True}])
    r = client.post("/api/scan", json={"query": "ml"})
    assert r.status_code == 200
    assert r.json()["results"][0]["company"] == "Anthropic"
    t = client.get("/api/scan/targets")
    assert t.status_code == 200 and len(t.json()["targets"]) > 5


# ---- legitimacy ----
def test_legitimacy_flags_scam():
    jd = ("Work from home, guaranteed income! No experience required, earn $900 per day. "
          "Pay a small registration fee to start. Contact us on Telegram for the interview.")
    a = legitimacy.assess(jd)
    assert a["risk"] == "high_risk"
    assert any(f["kind"] == "scam" for f in a["flags"])


def test_legitimacy_flags_ghost():
    jd = "We are always accepting applications for our talent community across various locations."
    a = legitimacy.assess(jd)
    assert a["risk"] in ("caution", "high_risk")
    assert any(f["kind"] == "ghost" for f in a["flags"])


def test_legitimacy_clear_for_normal_jd():
    jd = ("Senior Machine Learning Engineer. Build and deploy LLM systems with Python and PyTorch. "
          "Five years of experience. Competitive salary and benefits. Apply on our careers page.")
    a = legitimacy.assess(jd)
    assert a["risk"] == "clear"
    assert a["flags"] == []


def test_legitimacy_thin_jd_caution():
    a = legitimacy.assess("Hiring now. DM me.")
    assert a["risk"] in ("caution", "high_risk")


# ---- outreach ----
def test_outreach_uses_real_facts_and_style():
    job = {"company": "Acme AI", "title": "ML Engineer",
           "jd_text": "Build ML and RAG systems with Python and PyTorch."}
    msgs = outreach.build_outreach(job)
    assert "Acme AI" in msgs["referral"]
    assert "Acme AI" in msgs["recruiter"]
    assert outreach.NAME in msgs["referral"]
    # style: no em dashes anywhere
    assert "—" not in msgs["referral"] and "—" not in msgs["recruiter"]


def test_outreach_endpoint():
    jid = client.post("/api/jobs", json={"title": "ML Eng", "company": "Acme",
                                         "jd_text": "Build ML with Python."}).json()["id"]
    r = client.post(f"/api/jobs/{jid}/outreach")
    assert r.status_code == 200
    assert "referral" in r.json() and "recruiter" in r.json()
    # surfaced as an artifact on the detail
    detail = client.get(f"/api/jobs/{jid}").json()
    assert detail["artifacts"]["outreach"]
    assert "legitimacy" in detail
