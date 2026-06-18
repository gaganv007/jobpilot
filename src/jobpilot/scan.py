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
from concurrent.futures import ThreadPoolExecutor

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
            link = j.get("absolute_url", "")
            out.append({
                "url": link,
                "company": company or token.title(),
                "title": j.get("title", ""),
                "location": loc,
                "source": f"greenhouse/{token}",
                "jd_raw": j.get("content", ""),  # cleaned later, only if matched
                "remote": "remote" in loc.lower(),
                "apply_url": link,
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
            link = j.get("hostedUrl", "")
            out.append({
                "url": link,
                "company": company or token.title(),
                "title": j.get("text", ""),
                "location": loc,
                "source": f"lever/{token}",
                "jd_raw": j.get("descriptionPlain") or j.get("description", ""),
                "remote": "remote" in (loc or "").lower(),
                "apply_url": j.get("applyUrl") or link,
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
            link = j.get("jobUrl") or j.get("applyUrl", "")
            out.append({
                "url": link,
                "company": company or token.title(),
                "title": j.get("title", ""),
                "location": loc,
                "source": f"ashby/{token}",
                "jd_raw": j.get("descriptionPlain") or j.get("descriptionHtml", ""),
                "remote": bool(j.get("isRemote")) or "remote" in loc.lower(),
                "apply_url": link,
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
    # AI labs
    ("greenhouse", "anthropic", "Anthropic"),
    ("ashby", "openai", "OpenAI"),
    ("ashby", "cohere", "Cohere"),
    ("ashby", "harvey", "Harvey"),
    ("ashby", "sierra", "Sierra"),
    ("ashby", "watershed", "Watershed"),
    # Data / infra
    ("greenhouse", "databricks", "Databricks"),
    ("greenhouse", "samsara", "Samsara"),
    ("greenhouse", "cloudflare", "Cloudflare"),
    ("greenhouse", "twilio", "Twilio"),
    ("lever", "palantir", "Palantir"),
    # Fintech
    ("greenhouse", "stripe", "Stripe"),
    ("ashby", "ramp", "Ramp"),
    ("greenhouse", "brex", "Brex"),
    ("greenhouse", "affirm", "Affirm"),
    ("greenhouse", "coinbase", "Coinbase"),
    ("greenhouse", "robinhood", "Robinhood"),
    # Product / consumer
    ("ashby", "notion", "Notion"),
    ("ashby", "linear", "Linear"),
    ("greenhouse", "figma", "Figma"),
    ("greenhouse", "airbnb", "Airbnb"),
    ("greenhouse", "instacart", "Instacart"),
    ("greenhouse", "dropbox", "Dropbox"),
    ("greenhouse", "gitlab", "GitLab"),
    ("greenhouse", "roblox", "Roblox"),
    ("greenhouse", "pinterest", "Pinterest"),
    ("greenhouse", "reddit", "Reddit"),
    ("greenhouse", "lyft", "Lyft"),
    ("greenhouse", "asana", "Asana"),
    ("greenhouse", "discord", "Discord"),
    ("greenhouse", "flexport", "Flexport"),
    ("greenhouse", "nuro", "Nuro"),
    ("lever", "spotify", "Spotify"),
    ("ashby", "zapier", "Zapier"),
]


# Synonyms so "ml" matches "machine learning" in titles, etc.
_SYN = {
    "ml": ["machine learning"], "ai": ["artificial intelligence", "machine learning"],
    "swe": ["software engineer"], "nlp": ["natural language"],
    "ds": ["data scien"], "frontend": ["front end", "front-end"],
    "backend": ["back end", "back-end"], "fullstack": ["full stack", "full-stack"],
}


def _matches(job: dict, query: str) -> bool:
    """Match the query against the TITLE first (what users actually search), then
    fall back to the JD. Token-AND with light synonym expansion. Uses the raw
    (uncleaned) JD so we avoid HTML-parsing every job before knowing it matches."""
    if not query:
        return True
    title = job.get("title", "").lower()
    body = (job.get("jd_text") or job.get("jd_raw") or "")[:1500].lower()
    q = query.lower().strip()
    if q in title:
        return True
    for term in q.split():
        variants = [term] + _SYN.get(term, [])
        if not (any(v in title for v in variants) or any(v in body for v in variants)):
            return False
    return True


def scan_target(ats: str, token: str, company: str | None = None) -> list[dict]:
    fn = FETCHERS.get(ats)
    try:
        return fn(token, company) if fn else []
    except Exception:
        return []


def scan(
    targets: list[tuple[str, str, str]] | None = None,
    query: str = "",
    per_company_limit: int = 12,
    total_limit: int = 80,
) -> list[dict]:
    """Scan target companies' ATS feeds in parallel and return matching jobs.

    `targets` is a list of (ats, token, label). Defaults to TARGETS.
    Matches `query` against title (then JD). Honest: public APIs, user-triggered.
    """
    targets = targets or TARGETS
    with ThreadPoolExecutor(max_workers=min(16, len(targets) or 1)) as pool:
        per_company = list(pool.map(lambda t: scan_target(t[0], t[1], t[2]), targets))

    seen: set[str] = set()
    results: list[dict] = []
    for jobs in per_company:
        matched = 0
        for job in jobs:
            if not job.get("url") or job["url"] in seen:
                continue
            if not _matches(job, query):
                continue
            # Clean the JD HTML only now that we know the job matched.
            if "jd_text" not in job:
                job["jd_text"] = _clean(job.pop("jd_raw", ""))
            seen.add(job["url"])
            results.append(job)
            matched += 1
            if matched >= per_company_limit:
                break
    return results[:total_limit]
