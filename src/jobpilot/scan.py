"""Company scanning via official, public ATS job-board APIs.

This is the "find the best jobs" engine. It queries the public JSON feeds that
Greenhouse, Lever and Ashby publish for job distribution — the same data a
careers page renders. It is NOT scraping behind logins and does not bypass bot
protection. It runs only when the user triggers a scan, and returns candidates
for review; nothing is added or applied to automatically.

Each result is normalized to JobPilot's shape:
  {url, company, title, location, source, jd_text, remote}
"""
from __future__ import annotations

import html as _html

import httpx

from .extract import _visible_text

TIMEOUT = 20.0
HEADERS = {"User-Agent": "JobPilot/0.1 (single-user, public-ats-api)"}


def _clean(text: str) -> str:
    if not text:
        return ""
    text = _html.unescape(text)
    return _visible_text(text) if "<" in text else text.strip()


# ---- per-ATS fetchers ----
def fetch_greenhouse(token: str, company: str | None = None) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    out: list[dict] = []
    try:
        r = httpx.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        for j in r.json().get("jobs", []):
            loc = (j.get("location") or {}).get("name", "")
            out.append({
                "url": j.get("absolute_url", ""),
                "company": company or token.title(),
                "title": j.get("title", ""),
                "location": loc,
                "source": f"greenhouse/{token}",
                "jd_text": _clean(j.get("content", "")),
                "remote": "remote" in loc.lower(),
            })
    except Exception:
        pass
    return out


def fetch_lever(token: str, company: str | None = None) -> list[dict]:
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    out: list[dict] = []
    try:
        r = httpx.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        for j in r.json():
            cats = j.get("categories", {}) or {}
            loc = cats.get("location", "")
            out.append({
                "url": j.get("hostedUrl", ""),
                "company": company or token.title(),
                "title": j.get("text", ""),
                "location": loc,
                "source": f"lever/{token}",
                "jd_text": _clean(j.get("descriptionPlain") or j.get("description", "")),
                "remote": "remote" in (loc or "").lower(),
            })
    except Exception:
        pass
    return out


def fetch_ashby(token: str, company: str | None = None) -> list[dict]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    out: list[dict] = []
    try:
        r = httpx.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        for j in r.json().get("jobs", []):
            loc = j.get("location", "") or ""
            out.append({
                "url": j.get("jobUrl") or j.get("applyUrl", ""),
                "company": company or token.title(),
                "title": j.get("title", ""),
                "location": loc,
                "source": f"ashby/{token}",
                "jd_text": _clean(j.get("descriptionPlain") or j.get("descriptionHtml", "")),
                "remote": bool(j.get("isRemote")) or "remote" in loc.lower(),
            })
    except Exception:
        pass
    return out


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
}

# Curated, live-verified target companies (edit freely). Each is (ats, token, label).
TARGETS: list[tuple[str, str, str]] = [
    ("greenhouse", "anthropic", "Anthropic"),
    ("ashby", "openai", "OpenAI"),
    ("ashby", "cohere", "Cohere"),
    ("greenhouse", "databricks", "Databricks"),
    ("greenhouse", "stripe", "Stripe"),
    ("ashby", "ramp", "Ramp"),
    ("ashby", "notion", "Notion"),
    ("ashby", "linear", "Linear"),
    ("greenhouse", "figma", "Figma"),
    ("greenhouse", "coinbase", "Coinbase"),
    ("greenhouse", "robinhood", "Robinhood"),
    ("greenhouse", "airbnb", "Airbnb"),
    ("greenhouse", "instacart", "Instacart"),
    ("greenhouse", "dropbox", "Dropbox"),
    ("greenhouse", "gitlab", "GitLab"),
]


def _matches(job: dict, query: str) -> bool:
    if not query:
        return True
    q = query.lower()
    hay = f"{job.get('title','')} {job.get('jd_text','')[:600]}".lower()
    return all(term in hay for term in q.split()) if " " in q else q in hay


def scan_target(ats: str, token: str, company: str | None = None) -> list[dict]:
    fn = FETCHERS.get(ats)
    return fn(token, company) if fn else []


def scan(
    targets: list[tuple[str, str, str]] | None = None,
    query: str = "",
    per_company_limit: int = 8,
    total_limit: int = 60,
) -> list[dict]:
    """Scan target companies' ATS feeds and return matching, normalized jobs.

    `targets` is a list of (ats, token, label). Defaults to TARGETS.
    Filters by `query` against title + JD. Honest: public APIs, user-triggered.
    """
    targets = targets or TARGETS
    seen: set[str] = set()
    results: list[dict] = []
    for ats, token, label in targets:
        matched = 0
        for job in scan_target(ats, token, label):
            if not job.get("url") or job["url"] in seen:
                continue
            if not _matches(job, query):
                continue
            seen.add(job["url"])
            results.append(job)
            matched += 1
            if matched >= per_company_limit:
                break
        if len(results) >= total_limit:
            break
    return results[:total_limit]
