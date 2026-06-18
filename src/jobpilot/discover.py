"""Opt-in job discovery via public, ToS-friendly job APIs.

This is deliberately NOT scraping. It calls public JSON APIs that exist to be
queried (Remotive, Arbeitnow). Results are returned for the human to review and
choose from — nothing is added or applied to automatically. Discovery only runs
when the user explicitly triggers a search.

Each result is normalized to the same shape JobPilot stores:
  {url, company, title, location, source, jd_text, remote}
"""
from __future__ import annotations

from typing import Iterable

import httpx

from .extract import _visible_text

TIMEOUT = 20.0
HEADERS = {"User-Agent": "JobPilot/0.1 (single-user, public-api)"}


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
            out.append({
                "url": j.get("url", ""),
                "company": j.get("company_name", ""),
                "title": j.get("title", ""),
                "location": j.get("candidate_required_location", "Remote"),
                "source": "remotive.com",
                "jd_text": _clean(j.get("description", "")),
                "remote": True,
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
            out.append({
                "url": j.get("url", ""),
                "company": j.get("company_name", ""),
                "title": j.get("title", ""),
                "location": j.get("location", "") or ("Remote" if j.get("remote") else ""),
                "source": "arbeitnow.com",
                "jd_text": _clean(j.get("description", "")),
                "remote": bool(j.get("remote")),
                "tags": j.get("tags", []),
            })
            if len(out) >= limit:
                break
    except Exception:
        pass
    return out


SOURCES = {
    "remotive": search_remotive,
    "arbeitnow": search_arbeitnow,
}


def discover(query: str, sources: list[str] | None = None, limit: int = 25) -> list[dict]:
    """Search the chosen public sources and return normalized, de-duplicated jobs.

    Honest: only public APIs, only when the user asks. Returns candidates for
    review — storing/scoring/applying remains a separate, human-driven step.
    """
    chosen = sources or list(SOURCES)
    results: list[dict] = []
    for name in chosen:
        fn = SOURCES.get(name)
        if fn:
            results.extend(fn(query, limit=limit))
    return _dedupe(results)[: limit * 2]
