"""Dead-simple job finder: one command -> a clean page of full-time, resume-matched
jobs with Apply buttons. No server, no database, no multi-step flow.

    jobpilot find "machine learning" --location Boston

It searches top companies' public feeds (and Adzuna if a key is set), keeps only
full-time early-career roles that fit your resumes, and writes a standalone HTML
file it opens in your browser. Every job links straight to the real posting so
you apply yourself. JobPilot never applies for you.
"""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path


def _esc(s: str) -> str:
    return html.escape(s or "")


def gather(query: str, location: str = "", limit: int = 30,
           include_senior: bool = False) -> tuple[list[dict], int]:
    """Search all sources, rank by resume fit, return (jobs, total_found)."""
    from . import discover, relevance, scan

    raw: list[dict] = []
    try:
        raw += scan.scan(query=query, total_limit=150)
    except Exception:
        pass
    try:
        raw += discover.search(query, location=location, limit=50)
    except Exception:
        pass

    # De-dupe by url and by company+title (same role across locations).
    seen_url, seen_key, merged = set(), set(), []
    for r in raw:
        u = r.get("url", "")
        key = (r.get("company", "").lower(), r.get("title", "").lower())
        if not u or u in seen_url or key in seen_key:
            continue
        seen_url.add(u)
        seen_key.add(key)
        merged.append(r)

    ranked = relevance.rank(merged, include_senior=include_senior)
    return ranked[:limit], len(merged)


def render_html(jobs: list[dict], query: str, location: str, total_found: int) -> str:
    rows = []
    for j in jobs:
        fit = j.get("fit", 0)
        cls = "hi" if fit >= 60 else "mid" if fit >= 35 else "lo"
        apply_url = j.get("apply_url") or j.get("url") or "#"
        loc = j.get("location") or ("Remote" if j.get("remote") else "")
        rows.append(f"""
      <div class="job">
        <div class="left">
          <span class="fit {cls}">{fit}%</span>
          <div>
            <div class="title">{_esc(j.get('title',''))}</div>
            <div class="meta">{_esc(j.get('company',''))}{(' &middot; ' + _esc(loc)) if loc else ''}
              <span class="track">{_esc(j.get('track',''))}</span></div>
          </div>
        </div>
        <a class="apply" href="{_esc(apply_url)}" target="_blank" rel="noopener">Apply &rarr;</a>
      </div>""")

    when = datetime.now().strftime("%b %d, %Y %I:%M %p")
    subtitle = f'{len(jobs)} full-time matches for &ldquo;{_esc(query)}&rdquo;'
    if location:
        subtitle += f' near {_esc(location)}'
    subtitle += f' &middot; from {total_found} found'

    body = "".join(rows) or '<p class="empty">No matching full-time roles right now. Try a broader role keyword.</p>'
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>JobPilot matches</title>
<style>
  :root {{ --bg:#0e1117; --panel:#161b25; --b:#2a3344; --t:#e6e9ef; --m:#8b95a7; --a:#4f8cff; --g:#28c76f; --w:#ff9f43; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--t); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width:880px; margin:0 auto; padding:28px 18px 60px; }}
  h1 {{ margin:0 0 2px; font-size:22px; }}
  .sub {{ color:var(--m); font-size:13.5px; margin-bottom:4px; }}
  .note {{ color:var(--m); font-size:12px; margin-bottom:18px; }}
  .job {{ display:flex; justify-content:space-between; align-items:center; gap:14px;
          background:var(--panel); border:1px solid var(--b); border-radius:12px; padding:14px 16px; margin-bottom:10px; }}
  .left {{ display:flex; gap:14px; align-items:center; min-width:0; }}
  .fit {{ font-weight:800; font-size:14px; padding:6px 10px; border-radius:10px; flex:0 0 auto; }}
  .fit.hi {{ background:rgba(40,199,111,.16); color:var(--g); }}
  .fit.mid {{ background:rgba(79,140,255,.16); color:var(--a); }}
  .fit.lo {{ background:rgba(255,159,67,.14); color:var(--w); }}
  .title {{ font-weight:600; font-size:15px; }}
  .meta {{ color:var(--m); font-size:13px; margin-top:2px; }}
  .track {{ border:1px solid var(--b); border-radius:999px; padding:1px 8px; font-size:11px; margin-left:6px; }}
  .apply {{ background:linear-gradient(135deg,#4f8cff,#7c5cff); color:#fff; text-decoration:none;
            font-weight:700; font-size:13.5px; padding:9px 16px; border-radius:9px; flex:0 0 auto; white-space:nowrap; }}
  .empty {{ color:var(--m); }}
  .foot {{ color:var(--m); font-size:12px; margin-top:22px; text-align:center; }}
</style></head>
<body><div class="wrap">
  <h1>&#9992;&#65039; JobPilot &mdash; jobs for you</h1>
  <div class="sub">{subtitle}</div>
  <div class="note">Ranked by fit to your resumes. Internships, PhD-required and senior roles hidden. You click Apply &mdash; JobPilot never applies for you.</div>
  {body}
  <div class="foot">Generated {when}. Re-run: <code>jobpilot find "{_esc(query)}"</code></div>
</div></body></html>"""


def find(query: str, location: str = "", limit: int = 30,
         include_senior: bool = False, out_path: Path | None = None) -> tuple[Path, int, int]:
    """Search, rank, write the HTML page. Returns (path, shown, total_found)."""
    jobs, total = gather(query, location, limit, include_senior)
    html_doc = render_html(jobs, query, location, total)
    out = out_path or (Path.home() / "Desktop" / "jobpilot_matches.html")
    out.write_text(html_doc, encoding="utf-8")
    return out, len(jobs), total
