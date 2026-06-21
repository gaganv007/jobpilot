"""Opt-in job search via public, ToS-friendly job APIs.

This is deliberately NOT scraping. It calls public JSON APIs that exist to be
queried (The Muse, Remotive, Arbeitnow). Results are returned for the human to
review, with a real apply link on every one — nothing is added or applied to
automatically. Search only runs when the user explicitly triggers it.

The Muse adds broad, non-remote, US-inclusive coverage with real apply links;
Remotive and Arbeitnow add remote roles. Results are normalized to:
  {url, company, title, location, source, jd_text, remote, apply_url}
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Iterable

import httpx

from .extract import _visible_text

TIMEOUT = 20.0
HEADERS = {"User-Agent": "JobPilot/0.1 (single-user, public-api)"}

# The Muse categories that actually return engineering/data/IT roles.
MUSE_CATEGORIES = ["Software Engineering", "Data and Analytics", "Computer and IT"]

# Light synonym expansion so "ml" also matches "machine learning", etc.
SYNONYMS = {
    "ml": ["machine learning"], "ai": ["artificial intelligence"],
    "ds": ["data science"], "swe": ["software engineer"],
    "nlp": ["natural language"], "frontend": ["front end", "front-end"],
    "backend": ["back end", "back-end"], "fullstack": ["full stack", "full-stack"],
}


def _clean(text: str) -> str:
    if not text:
        return ""
    return _visible_text(text) if "<" in text else text.strip()


def _dedupe(items: Iterable[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        u = it.get("url", "")
        if u and u not in seen:
            seen.add(u)
            out.append(it)
    return out


def search_remotive(query: str, limit: int = 25) -> list[dict]:
    """Remotive public API — remote roles. https://remotive.com/api/remote-jobs"""
    url = "https://remotive.com/api/remote-jobs"
    params = {"search": query, "limit": str(limit)} if query else {"limit": str(limit)}
    out: list[dict] = []
    try:
        r = httpx.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        for j in r.json().get("jobs", [])[:limit]:
            link = j.get("url", "")
            out.append({
                "url": link,
                "company": j.get("company_name", ""),
                "title": j.get("title", ""),
                "location": j.get("candidate_required_location", "Remote"),
                "source": "remotive.com",
                "jd_text": _clean(j.get("description", "")),
                "remote": True,
                "apply_url": link,
            })
    except Exception:
        pass
    return out


def search_arbeitnow(query: str, limit: int = 25) -> list[dict]:
    """Arbeitnow public job-board API. https://www.arbeitnow.com/api/job-board-api"""
    url = "https://www.arbeitnow.com/api/job-board-api"
    q = (query or "").lower()
    out: list[dict] = []
    try:
        r = httpx.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        for j in r.json().get("data", []):
            hay = " ".join([
                j.get("title", ""), j.get("company_name", ""),
                " ".join(j.get("tags", []) or []), j.get("description", "")[:500],
            ]).lower()
            if q and q not in hay:
                continue
            link = j.get("url", "")
            out.append({
                "url": link,
                "company": j.get("company_name", ""),
                "title": j.get("title", ""),
                "location": j.get("location", "") or ("Remote" if j.get("remote") else ""),
                "source": "arbeitnow.com",
                "jd_text": _clean(j.get("description", "")),
                "remote": bool(j.get("remote")),
                "tags": j.get("tags", []),
                "apply_url": link,
            })
            if len(out) >= limit:
                break
    except Exception:
        pass
    return out


def search_themuse(query: str, location: str = "", pages: int = 1) -> list[dict]:
    """The Muse public API — broad, US-inclusive, real apply links.
    https://www.themuse.com/developers/api/v2 . No key needed for light use."""
    out: list[dict] = []
    base = "https://www.themuse.com/api/public/jobs"
    for category in MUSE_CATEGORIES:
        for page in range(1, pages + 1):
            params = {"category": category, "page": page}
            if location:
                params["location"] = location
            try:
                r = httpx.get(base, params=params, headers=HEADERS, timeout=TIMEOUT)
                r.raise_for_status()
                for j in r.json().get("results", []):
                    locs = [l.get("name", "") for l in j.get("locations", [])]
                    loc = locs[0] if locs else ""
                    out.append({
                        "url": j.get("refs", {}).get("landing_page", ""),
                        "company": (j.get("company") or {}).get("name", ""),
                        "title": j.get("name", ""),
                        "location": loc,
                        "source": "themuse.com",
                        "jd_text": _clean(j.get("contents", "")),
                        "remote": any("remote" in (l or "").lower() or "flexible" in (l or "").lower() for l in locs),
                        "apply_url": j.get("refs", {}).get("landing_page", ""),
                    })
            except Exception:
                pass
    return _keyword_filter(out, query)


def _expand(query: str) -> list[str]:
    tokens = [t for t in (query or "").lower().split() if t]
    expanded = list(tokens)
    for t in tokens:
        expanded += SYNONYMS.get(t, [])
    return expanded


def _keyword_filter(items: list[dict], query: str) -> list[dict]:
    """Keep items whose title (preferred) or JD contains the query terms.
    Multi-word queries match as a phrase OR all tokens present."""
    if not query:
        return items
    q = query.lower().strip()
    terms = _expand(q)
    out = []
    for it in items:
        title = it.get("title", "").lower()
        hay = title + " " + it.get("jd_text", "")[:400].lower()
        if q in title or q in hay:
            out.append(it)
        elif all(any(syn in hay for syn in [t] + SYNONYMS.get(t, [])) for t in q.split()):
            out.append(it)
    return out


def search_adzuna(query: str, location: str = "", limit: int = 50,
                  exclude: str = "senior staff principal lead director intern internship") -> list[dict]:
    """Adzuna aggregator (pulls Indeed and others). Real keyword + location
    search with apply links. Needs a free API key (config.adzuna_creds()).

    https://developer.adzuna.com — free signup, generous limits.
    """
    from . import config

    creds = config.adzuna_creds()
    if not creds:
        return []
    app_id, app_key = creds
    url = "https://api.adzuna.com/v1/api/jobs/us/search/1"
    params = {
        "app_id": app_id, "app_key": app_key,
        "results_per_page": str(min(limit, 50)),
        "what": query or "software engineer",
        "max_days_old": "30",
        "content-type": "application/json",
    }
    if location:
        params["where"] = location
    if exclude:
        params["what_exclude"] = exclude
    out: list[dict] = []
    try:
        r = httpx.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        for j in r.json().get("results", []):
            link = j.get("redirect_url", "")
            loc = (j.get("location") or {}).get("display_name", "")
            out.append({
                "url": link,
                "company": (j.get("company") or {}).get("display_name", ""),
                "title": j.get("title", ""),
                "location": loc,
                "source": "adzuna",
                "jd_text": _clean(j.get("description", "")),
                "remote": "remote" in (loc or "").lower(),
                "apply_url": link,
            })
    except Exception:
        pass
    return out


SOURCES = {
    "adzuna": lambda q, limit=50, location="": search_adzuna(q, location, limit),
    "remotive": lambda q, limit=25, location="": search_remotive(q, limit),
    "arbeitnow": lambda q, limit=25, location="": search_arbeitnow(q, limit),
    "themuse": lambda q, limit=25, location="": search_themuse(q, location, pages=1),
}
# The Muse is excluded by default (its categorization is unreliable). Adzuna is
# the primary source when configured; remote boards supplement it.
DEFAULT_SOURCES = ["adzuna", "remotive", "arbeitnow"]


def search(
    query: str,
    location: str = "",
    sources: list[str] | None = None,
    limit: int = 40,
) -> list[dict]:
    """Search the chosen public sources in parallel; merge, dedupe, return.

    Honest: only public APIs, only when the user asks. Every result carries a
    real apply_url; storing/scoring/applying stays human-driven.
    """
    chosen = sources or DEFAULT_SOURCES
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(chosen) or 1) as pool:
        futs = []
        for name in chosen:
            fn = SOURCES.get(name)
            if fn:
                futs.append(pool.submit(fn, query, limit, location))
        for f in futs:
            try:
                results.extend(f.result())
            except Exception:
                pass
    return _dedupe(results)


# Back-compat alias.
def discover(query: str, sources: list[str] | None = None, limit: int = 25) -> list[dict]:
    return search(query, sources=sources, limit=limit)
