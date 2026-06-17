"""Extract job details from a single pasted URL.

Site-respect rules (guardrail #3):
  - Only ever fetch a URL the user explicitly pasted. No crawling, no following
    links, no fetching anything the user did not ask for.
  - Honor robots.txt for our user-agent before fetching.
  - Polite fixed delay before the request; a real desktop user-agent; never log
    in, never bypass bot protection or CAPTCHAs.

The network fetch (Playwright) is separated from the HTML parsing so the parser
can be unit-tested against a saved fixture with no network access.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from html.parser import HTMLParser
from urllib import robotparser
from urllib.parse import urlparse

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 JobPilot/0.1 (single-user, polite)"
)
POLITE_DELAY_SECONDS = 2.0
FETCH_TIMEOUT_MS = 30000


def source_from_url(url: str) -> str:
    """Human-readable source = the host, minus a leading www."""
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def is_valid_url(url: str) -> bool:
    p = urlparse(url)
    return p.scheme in ("http", "https") and bool(p.netloc)


def robots_allows(url: str, user_agent: str = USER_AGENT) -> bool:
    """Check robots.txt for our user-agent. On a fetch error, fail OPEN only for
    the single user-pasted page (we never crawl), but still default to allow so a
    missing/broken robots.txt does not block a page the user explicitly chose.
    A reachable robots.txt that disallows the path is always respected."""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = robotparser.RobotFileParser()
    try:
        req = urllib.request.Request(robots_url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, timeout=10) as resp:
            rp.parse(resp.read().decode("utf-8", "replace").splitlines())
    except Exception:
        return True  # no reachable robots.txt -> allowed for a single explicit page
    return rp.can_fetch(user_agent, url)


# ---------- HTML -> text ----------
class _TextExtractor(HTMLParser):
    """Collect visible text, dropping script/style/nav noise."""

    _SKIP = {"script", "style", "noscript", "head", "svg"}

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        if tag in ("p", "br", "li", "div", "h1", "h2", "h3", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0 and data.strip():
            self.parts.append(data)


def _visible_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    text = "".join(p.parts)
    # collapse whitespace but keep paragraph breaks
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    out, blank = [], False
    for ln in lines:
        if ln:
            out.append(ln)
            blank = False
        elif not blank:
            out.append("")
            blank = True
    return "\n".join(out).strip()


def _meta(html: str, prop: str) -> str:
    """Read an og:/meta property value."""
    m = re.search(
        rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        re.I,
    )
    if not m:
        m = re.search(
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(prop)}["\']',
            html,
            re.I,
        )
    return m.group(1).strip() if m else ""


def _jsonld_jobposting(html: str) -> dict:
    """Return the first JobPosting JSON-LD object if present (common on boards)."""
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.I | re.S,
    ):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except Exception:
            continue
        candidates = data if isinstance(data, list) else [data]
        if isinstance(data, dict) and "@graph" in data:
            candidates = data["@graph"]
        for obj in candidates:
            if isinstance(obj, dict) and "JobPosting" in str(obj.get("@type", "")):
                return obj
    return {}


def _strip_tags(text: str) -> str:
    return _visible_text(text) if "<" in text else text.strip()


def parse_job(html: str, url: str) -> dict:
    """Parse company/title/location/jd_text from a job page's HTML.

    Prefers JSON-LD JobPosting structured data; falls back to og/meta tags and
    visible body text. Pure function, no network — unit-testable with a fixture.
    """
    ld = _jsonld_jobposting(html)

    title = (ld.get("title") or "").strip()
    if not title:
        title = _meta(html, "og:title")
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()
    if not title:
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
        if m:
            title = _strip_tags(m.group(1))

    company = ""
    org = ld.get("hiringOrganization")
    if isinstance(org, dict):
        company = (org.get("name") or "").strip()
    elif isinstance(org, str):
        company = org.strip()
    if not company:
        company = _meta(html, "og:site_name")

    location = ""
    loc = ld.get("jobLocation")
    if isinstance(loc, list) and loc:
        loc = loc[0]
    if isinstance(loc, dict):
        addr = loc.get("address", {})
        if isinstance(addr, dict):
            location = ", ".join(
                str(addr[k])
                for k in ("addressLocality", "addressRegion", "addressCountry")
                if addr.get(k)
            )
        elif isinstance(addr, str):
            location = addr.strip()

    if ld.get("description"):
        jd_text = _strip_tags(ld["description"])
    else:
        jd_text = _visible_text(html)

    return {
        "url": url,
        "company": company,
        "title": title,
        "location": location,
        "source": source_from_url(url),
        "jd_text": jd_text,
    }


def fetch_html(url: str, delay: float = POLITE_DELAY_SECONDS) -> str:
    """Fetch a single user-pasted page with Playwright (headless Chromium).

    Polite delay first, real user-agent, no login, no bot-protection bypass.
    Imported lazily so the rest of JobPilot works without a browser installed.
    """
    from playwright.sync_api import sync_playwright

    time.sleep(delay)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_context(user_agent=USER_AGENT).new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=FETCH_TIMEOUT_MS)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass  # best-effort; some pages never go idle
            return page.content()
        finally:
            browser.close()


class RobotsDisallowed(Exception):
    """Raised when robots.txt forbids fetching the requested page."""


def extract(url: str, delay: float = POLITE_DELAY_SECONDS) -> dict:
    """Full extract for one explicit URL: robots check -> fetch -> parse."""
    if not is_valid_url(url):
        raise ValueError(f"Not a valid http(s) URL: {url!r}")
    if not robots_allows(url):
        raise RobotsDisallowed(f"robots.txt disallows fetching {url}")
    html = fetch_html(url, delay=delay)
    return parse_job(html, url)
