"""Phase 1: JD extraction parsing (no network — uses saved HTML fixtures)."""
from pathlib import Path
from urllib import robotparser

import pytest

from jobpilot import extract

FIX = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_parse_jsonld_jobposting():
    html = _read("job_jsonld.html")
    job = extract.parse_job(html, "https://boards.acme.ai/jobs/123")
    assert job["title"] == "Senior Machine Learning Engineer"
    assert job["company"] == "Acme AI"
    assert "Boston" in job["location"] and "MA" in job["location"]
    assert "RAG" in job["jd_text"]
    assert "PyTorch" in job["jd_text"]
    assert job["source"] == "boards.acme.ai"


def test_parse_plain_html_fallback():
    html = _read("job_plain.html")
    job = extract.parse_job(html, "https://www.globex.com/careers/ds")
    assert "Data Scientist" in job["title"]
    assert "Power BI" in job["jd_text"]
    # script content must be stripped from the visible JD text
    assert "should not appear" not in job["jd_text"]
    assert job["source"] == "globex.com"  # www. trimmed


def test_source_from_url():
    assert extract.source_from_url("https://www.linkedin.com/jobs/1") == "linkedin.com"
    assert extract.source_from_url("https://jobs.lever.co/x") == "jobs.lever.co"


def test_is_valid_url():
    assert extract.is_valid_url("https://x.com/job")
    assert not extract.is_valid_url("ftp://x.com")
    assert not extract.is_valid_url("not a url")


def test_robots_disallow_is_respected(monkeypatch):
    # Simulate a reachable robots.txt that blocks everything for our agent.
    def fake_can_fetch_setup(robots_text):
        rp = robotparser.RobotFileParser()
        rp.parse(robots_text.splitlines())
        return rp

    rp = fake_can_fetch_setup("User-agent: *\nDisallow: /")
    assert rp.can_fetch(extract.USER_AGENT, "https://x.com/job") is False

    rp2 = fake_can_fetch_setup("User-agent: *\nDisallow: /private")
    assert rp2.can_fetch(extract.USER_AGENT, "https://x.com/job") is True
