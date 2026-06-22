"""JobPilot CLI.

Each command is a self-contained "mode" that loads only the context it needs.

GUARDRAILS (these override any feature request that conflicts):
  1. Never auto-submit, click apply, log in, or solve CAPTCHAs. A human does
     every irreversible action.
  2. Never fabricate resume content.
  3. Respect sites: only fetch a URL the user pastes; honor robots.txt; be polite.
  4. No fake activity. Real timestamps, real data.
  5. Local and private.
"""
from __future__ import annotations

import typer
from rich.console import Console

from . import __version__, db
from .models import HUMAN_ONLY_STATUSES, Status

app = typer.Typer(
    add_completion=False,
    help="JobPilot — local job-search command center. Automates analysis, never the decision.",
    no_args_is_help=True,
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"JobPilot {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """JobPilot prepares materials and surfaces decisions. It never applies for you."""


_NOT_YET = "This command lands in a later build phase."


@app.command()
def add(
    url: str = typer.Argument(..., help="Job posting URL to fetch and store."),
    delay: float = typer.Option(
        None, "--delay", help="Seconds to wait before fetching (politeness)."
    ),
) -> None:
    """Extract a pasted job URL, dedup, and store it.

    Only this single URL is fetched. robots.txt is honored; nothing is submitted.
    """
    from . import extract

    if not extract.is_valid_url(url):
        console.print(f"[red]Not a valid http(s) URL:[/] {url}")
        raise typer.Exit(code=1)

    conn = db.connect()
    # Dedup first — cheaper than fetching, and we never re-scrape a known URL.
    existing = db.job_by_url(conn, url)
    if existing is not None:
        console.print(
            f"[yellow]Already tracked[/] as job {existing['id']}: "
            f"{existing['title'] or '(untitled)'} — not re-fetching."
        )
        raise typer.Exit(code=0)

    kwargs = {} if delay is None else {"delay": delay}
    try:
        with console.status(f"Fetching {url} (polite delay first)…"):
            details = extract.extract(url, **kwargs)
    except extract.RobotsDisallowed as e:
        console.print(f"[red]Refusing to fetch[/]: {e}")
        db.log_event(conn, "robots_blocked", url)
        raise typer.Exit(code=1)
    except Exception as e:  # network / browser errors
        console.print(f"[red]Could not extract[/] {url}: {e}")
        console.print(
            "[dim]If Playwright is not installed, run: playwright install chromium[/]"
        )
        raise typer.Exit(code=1)

    job_id, created = db.add_job(conn, **details)
    db.log_event(conn, "add", f"{details.get('title','')} @ {details.get('company','')}", job_id=job_id)
    console.print(
        f"[green]Added job {job_id}[/]: [bold]{details.get('title') or '(untitled)'}[/]"
        f" @ {details.get('company') or '(unknown company)'}"
        f"  [dim]{details.get('location') or ''}[/]"
    )
    console.print(f"[dim]JD captured: {len(details.get('jd_text',''))} chars. "
                  f"Next: jobpilot score {job_id}[/]")


@app.command()
def score(
    job_id: int = typer.Argument(None, help="Job id to score."),
    all_unscored: bool = typer.Option(False, "--all-unscored", help="Score every unscored job."),
    reply: str = typer.Option(
        None, "--reply", help="Path to an LLM JSON scoring reply (paste mode)."
    ),
    prompt: bool = typer.Option(
        False, "--prompt", help="Print the paste-mode scoring prompt instead of scoring."
    ),
) -> None:
    """Run the gated scoring rubric and store scores + per-dimension rationale.

    Default is a deterministic, offline heuristic (honest, explainable). Use
    --prompt to get an LLM prompt, then --reply <file> to ingest a richer score.
    """
    from . import scoring

    conn = db.connect()

    if all_unscored:
        ids = db.unscored_job_ids(conn)
        if not ids:
            console.print("Nothing to score — all jobs already scored.")
            return
    else:
        if job_id is None:
            console.print("[red]Provide a job_id or --all-unscored.[/]")
            raise typer.Exit(code=1)
        ids = [job_id]

    for jid in ids:
        job = db.get_job(conn, jid)
        if job is None:
            console.print(f"[red]No job with id {jid}.[/]")
            continue

        if prompt:
            console.print(scoring.build_score_prompt(job["jd_text"], job["company"], job["title"]))
            continue

        try:
            if reply:
                from pathlib import Path

                scored = scoring.parse_score_reply(Path(reply).read_text(encoding="utf-8"))
                # Backfill missing rationale from the heuristic, but only if it's
                # actually needed and available (heuristic needs jd_agent).
                if any(not scored[d]["rationale"] for d in scoring.DIMENSIONS):
                    try:
                        heur = scoring.heuristic_dimensions(job["jd_text"])
                        for d in scoring.DIMENSIONS:
                            if not scored[d]["rationale"]:
                                scored[d]["rationale"] = heur[d]["rationale"]
                    except Exception:
                        pass
                method = "llm"
            else:
                scored = scoring.heuristic_dimensions(job["jd_text"])
                method = "heuristic"
        except Exception as e:
            console.print(f"[red]Scoring failed for job {jid}: {e}[/]")
            raise typer.Exit(code=1)

        dims = scoring.dims_only(scored)
        overall, gate_passed = scoring.compute_overall(dims)
        rationale = scoring.rationale_text(scored)
        import json as _json

        db.upsert_score(conn, jid, overall, gate_passed, _json.dumps(dims), rationale)
        # Advance discovered -> scored, but never override a human-set status.
        appn = db.get_application(conn, jid)
        if appn and appn["status"] == Status.discovered.value:
            db.set_status(conn, jid, Status.scored.value)
        db.log_event(conn, "score", f"{overall:.1f} ({scoring.band(overall, gate_passed)}, {method})", job_id=jid)

        verdict = scoring.band(overall, gate_passed)
        color = "green" if gate_passed and overall >= 3 else ("yellow" if gate_passed else "red")
        console.print(
            f"[{color}]Job {jid}: {overall:.2f}/5 — {verdict}[/]"
            f"  (gate {'PASS' if gate_passed else 'FAIL'}, {method})"
        )
        if not all_unscored:
            from rich.table import Table

            t = Table(show_header=True)
            t.add_column("Dimension")
            t.add_column("Score", justify="right")
            t.add_column("Why")
            for d in scoring.DIMENSIONS:
                gate_tag = " [dim](gate)[/]" if d in scoring.GATES else ""
                t.add_row(d + gate_tag, f"{scored[d]['score']}/5", scored[d]["rationale"])
            console.print(t)


@app.command()
def tailor(
    job_id: int = typer.Argument(..., help="Job id to tailor for."),
    reply: str = typer.Option(
        None, "--reply", help="Path to a Claude reply (TRACK/SUMMARY/COVER LETTER)."
    ),
    prompt: bool = typer.Option(
        False, "--prompt", help="Print the paste-mode tailoring prompt and exit."
    ),
) -> None:
    """Build an ATS-optimized resume + cover letter from real facts only.

    Reorders skills and reframes the summary using existing facts; everything
    else is verbatim. Emits an evidence map and an honesty receipt (diff).
    """
    from . import config, tailor as tailor_mod
    from .jd_bridge import JDAgentUnavailable

    conn = db.connect()
    job = db.get_job(conn, job_id)
    if job is None:
        console.print(f"[red]No job with id {job_id}.[/]")
        raise typer.Exit(code=1)

    if prompt:
        from . import jd_bridge

        try:
            track, _ = jd_bridge.match_track(job["jd_text"])
        except JDAgentUnavailable as e:
            console.print(f"[red]{e}[/]")
            raise typer.Exit(code=1)
        console.print(tailor_mod.build_tailor_prompt(job["jd_text"], job["company"], job["title"], track))
        return

    reply_text = None
    if reply:
        from pathlib import Path

        reply_text = Path(reply).read_text(encoding="utf-8")

    out_dir = config.job_dir(job_id)
    try:
        result = tailor_mod.tailor_job(dict(job), out_dir, reply_text=reply_text)
    except JDAgentUnavailable as e:
        console.print(f"[red]Cannot tailor[/]: {e}")
        raise typer.Exit(code=1)

    db.set_doc_paths(conn, job_id, resume_path=result.resume_path, cover_path=result.cover_path)
    appn = db.get_application(conn, job_id)
    if appn and appn["status"] in (Status.discovered.value, Status.scored.value):
        db.set_status(conn, job_id, Status.tailored.value)
    db.log_event(conn, "tailor", f"track={result.track}", job_id=job_id)

    console.print(f"[green]Tailored job {job_id}[/] for track [bold]{result.track}[/].")
    console.print(f"  resume:   {result.resume_path}")
    if result.cover_path:
        console.print(f"  cover:    {result.cover_path}")
    else:
        console.print(f"  cover:    [yellow]not built[/] — paste this into Claude, then re-run with --reply:")
        console.print(f"            {result.prompt_path}")
    console.print(f"  evidence: {result.evidence_path}")
    console.print(f"  receipt:  {result.receipt_path}")
    if not result.honesty.ok:
        console.print(
            f"  [red]Honesty guard:[/] rejected a summary that added "
            f"unsupported skills ({', '.join(result.honesty.violations)}); used your real summary."
        )


def _require_job(conn, job_id: int):
    job = db.get_job(conn, job_id)
    if job is None:
        console.print(f"[red]No job with id {job_id}.[/]")
        raise typer.Exit(code=1)
    return dict(job)


@app.command()
def research(
    job_id: int = typer.Argument(..., help="Job id to research."),
    prompt: bool = typer.Option(False, "--prompt", help="Print a web-research LLM prompt instead."),
) -> None:
    """Summarize the company; talking points and questions. Facts only."""
    from . import config, research as research_mod

    conn = db.connect()
    job = _require_job(conn, job_id)
    if prompt:
        console.print(research_mod.build_research_prompt(job))
        return
    doc = research_mod.build_research_doc(job)
    out = config.job_dir(job_id) / "research.md"
    out.write_text(doc, encoding="utf-8")
    db.log_event(conn, "research", str(out), job_id=job_id)
    from rich.markdown import Markdown

    console.print(Markdown(doc))
    console.print(f"[dim]Saved: {out}[/]")


@app.command()
def prep(
    job_id: int = typer.Argument(..., help="Job id to prep for."),
    prompt: bool = typer.Option(False, "--prompt", help="Print an LLM prep prompt instead."),
) -> None:
    """Generate STAR+R interview stories from real experience, plus likely topics."""
    from . import config, prep as prep_mod

    conn = db.connect()
    job = _require_job(conn, job_id)
    if prompt:
        console.print(prep_mod.build_prep_prompt(job))
        return
    doc = prep_mod.build_prep_doc(job)
    out = config.job_dir(job_id) / "prep.md"
    out.write_text(doc, encoding="utf-8")
    db.log_event(conn, "prep", str(out), job_id=job_id)
    from rich.markdown import Markdown

    console.print(Markdown(doc))
    console.print(f"[dim]Saved: {out}[/]")


@app.command()
def packet(job_id: int = typer.Argument(..., help="Job id to assemble a packet for.")) -> None:
    """Assemble the one-page application packet (open this before you apply)."""
    from . import config, packet as packet_mod

    conn = db.connect()
    _require_job(conn, job_id)
    doc = packet_mod.build_packet(conn, job_id)
    out = config.job_dir(job_id) / "packet.md"
    out.write_text(doc, encoding="utf-8")
    db.log_event(conn, "packet", str(out), job_id=job_id)
    from rich.markdown import Markdown

    console.print(Markdown(doc))
    console.print(f"[dim]Saved: {out}[/]")


@app.command()
def batch(
    urls_file: str = typer.Argument(..., help="Text file of URLs, one per line."),
    workers: int = typer.Option(4, "--workers", help="Worker pool size."),
    delay: float = typer.Option(None, "--delay", help="Polite per-fetch delay (seconds)."),
) -> None:
    """Add + score many URLs with a resumable worker pool (lock files per URL).

    It STOPS at scoring and never applies. Re-run it to resume after a crash.
    """
    from pathlib import Path

    from . import batch as batch_mod

    if not Path(urls_file).exists():
        console.print(f"[red]No such file:[/] {urls_file}")
        raise typer.Exit(code=1)
    urls = batch_mod.read_urls(urls_file)
    if not urls:
        console.print("No URLs found in file.")
        return

    console.print(f"Processing {len(urls)} URL(s) with {workers} worker(s). "
                  f"[dim]Fetches are serialized for politeness. Never applies.[/]")
    results = batch_mod.run_batch(urls, workers=workers, delay=delay)

    from rich.table import Table

    summary = Table(title="Batch results")
    summary.add_column("URL")
    summary.add_column("Outcome")
    summary.add_column("Job", justify="right")
    summary.add_column("Score", justify="right")
    for r in results:
        score_cell = "—"
        if r.overall is not None:
            score_cell = f"{r.overall:.1f}{'' if r.gate_passed else ' ✗'}"
        summary.add_row(r.url[:50], r.status, str(r.job_id or "—"), score_cell)
    console.print(summary)

    conn = db.connect()
    sl = batch_mod.shortlist(conn, limit=10)
    if sl:
        ranked = Table(title="Ranked shortlist (gate-passing first) — you decide what to pursue")
        ranked.add_column("#", justify="right")
        ranked.add_column("Score", justify="right")
        ranked.add_column("Gate")
        ranked.add_column("Title")
        ranked.add_column("Company")
        for row in sl:
            ranked.add_row(
                str(row["id"]), f"{row['overall']:.2f}",
                "PASS" if row["gate_passed"] else "FAIL",
                (row["title"] or "(untitled)")[:40], (row["company"] or "—")[:24],
            )
        console.print(ranked)
    console.print("[dim]Next: jobpilot tailor <id>, then jobpilot packet <id>. JobPilot never applies for you.[/]")


@app.command()
def scan(
    query: str = typer.Argument("", help="Filter scanned roles by keywords."),
    add: bool = typer.Option(False, "--add", help="Store the matching jobs (does not score/apply)."),
    limit: int = typer.Option(40, "--limit", help="Max roles to return."),
) -> None:
    """Scan top companies' public ATS feeds (Greenhouse/Lever/Ashby) for roles."""
    from . import scan as scan_mod

    console.print(f"[dim]Scanning {len(scan_mod.TARGETS)} companies' public ATS feeds…[/]")
    results = scan_mod.scan(query=query, total_limit=limit)
    if not results:
        console.print("No matching roles found.")
        return
    from rich.table import Table

    t = Table(title=f"Scan results ({len(results)})")
    t.add_column("Title")
    t.add_column("Company")
    t.add_column("Location")
    t.add_column("Source")
    for r in results:
        t.add_row((r["title"] or "")[:42], (r["company"] or "")[:20],
                  (r["location"] or "")[:24], r["source"])
    console.print(t)

    if add:
        conn = db.connect()
        n = 0
        for r in results:
            _id, created = db.add_job(conn, r["url"], company=r["company"], title=r["title"],
                                      location=r["location"], source=r["source"], jd_text=r["jd_text"])
            if created:
                db.log_event(conn, "add", f"scan: {r['title']}", job_id=_id)
                n += 1
        console.print(f"[green]Added {n} new job(s).[/] Next: jobpilot score --all-unscored")
    else:
        console.print("[dim]Re-run with --add to store these. JobPilot never applies for you.[/]")


@app.command()
def outreach(job_id: int = typer.Argument(..., help="Job id to draft outreach for.")) -> None:
    """Draft referral + recruiter outreach messages (you review and send)."""
    from . import config, outreach as outreach_mod

    conn = db.connect()
    job = _require_job(conn, job_id)
    msgs = outreach_mod.build_outreach(job)
    doc = (f"# Outreach — {job['title']} @ {job['company']}\n\n"
           f"## Referral request\n\n{msgs['referral']}\n\n## Recruiter note\n\n{msgs['recruiter']}\n")
    (config.job_dir(job_id) / "outreach.md").write_text(doc, encoding="utf-8")
    db.log_event(conn, "outreach", "cli", job_id=job_id)
    from rich.markdown import Markdown

    console.print(Markdown(doc))
    console.print("[dim]Review and personalize before sending. JobPilot never sends these.[/]")


@app.command()
def gaps() -> None:
    """Aggregate skill gaps across scored jobs; name the best skill to learn next."""
    from . import gaps as gaps_mod

    conn = db.connect()
    from rich.markdown import Markdown

    console.print(Markdown(gaps_mod.build_gap_report(conn)))


@app.command()
def followups(days: int = typer.Option(5, "--days", help="Days of silence before a nudge.")) -> None:
    """List applications that have gone quiet and are due a follow-up."""
    from . import followups as followups_mod

    conn = db.connect()
    due = followups_mod.needs_followup(conn, days=days)
    if not due:
        console.print("Nothing due a follow-up. Nice and tidy.")
        return
    from rich.table import Table

    t = Table(title=f"Due a follow-up (>= {days} days quiet)")
    t.add_column("#", justify="right")
    t.add_column("Title")
    t.add_column("Company")
    t.add_column("Status")
    t.add_column("Days", justify="right")
    for r in due:
        t.add_row(str(r["job_id"]), (r["title"] or "")[:40], (r["company"] or "")[:24],
                  r["status"], str(r["days_since"]))
    console.print(t)
    console.print("[dim]A short, polite nudge lifts response rates. JobPilot never sends it for you.[/]")


@app.command()
def calibrate() -> None:
    """Report whether my scoring predicts real outcomes; suggest weight tweaks."""
    from . import calibration

    conn = db.connect()
    rep = calibration.report(conn)
    console.print(f"Outcomes recorded: {rep.n_outcomes} "
                  f"({rep.n_positive} advanced, {rep.n_negative} rejected)")
    if rep.avg_score_positive is not None:
        console.print(f"Avg score — advanced: {rep.avg_score_positive}")
    if rep.avg_score_negative is not None:
        console.print(f"Avg score — rejected: {rep.avg_score_negative}")
    console.print(f"[bold]{rep.verdict}[/]")
    if rep.suggestions:
        console.print("\n[bold]Suggestions (you approve before applying):[/]")
        for s in rep.suggestions:
            console.print(f"  - {s}")
        console.print("[dim]To apply: edit weights.json in JOBPILOT_HOME; scoring picks it up.[/]")


@app.command()
def board() -> None:
    """Dashboard: pipeline, tracked jobs, top un-applied picks, weekly count, next skill."""
    from rich.table import Table

    conn = db.connect()
    counts = db.status_counts(conn)
    if not counts:
        console.print("No jobs yet. Add one with [bold]jobpilot add <url>[/].")
        return

    pipe = Table(title="Pipeline by status")
    pipe.add_column("Status")
    pipe.add_column("Count", justify="right")
    for st in Status:
        if st.value in counts:
            pipe.add_row(st.value, str(counts[st.value]))
    console.print(pipe)

    jobs = db.all_jobs(conn)
    listing = Table(title="Tracked jobs")
    listing.add_column("#", justify="right")
    listing.add_column("Title")
    listing.add_column("Company")
    listing.add_column("Location")
    listing.add_column("Status")
    listing.add_column("Score", justify="right")
    for j in jobs:
        appn = db.get_application(conn, j["id"])
        sc = db.get_score(conn, j["id"])
        score_cell = "—"
        if sc is not None:
            mark = "" if sc["gate_passed"] else " ✗"
            score_cell = f"{sc['overall']:.1f}{mark}"
        else:
            try:
                from . import relevance

                qf = relevance.quick_fit(j["title"], j["jd_text"])
                score_cell = f"≈{qf['fit']}%"
            except Exception:
                pass
        listing.add_row(
            str(j["id"]),
            (j["title"] or "(untitled)")[:40],
            (j["company"] or "—")[:24],
            (j["location"] or "—")[:20],
            appn["status"] if appn else "—",
            score_cell,
        )
    console.print(listing)

    # Top-scoring jobs I have NOT applied to yet (where to spend effort).
    not_applied = {Status.discovered.value, Status.scored.value, Status.tailored.value}
    top = conn.execute(
        "SELECT j.id, j.title, j.company, s.overall, s.gate_passed "
        "FROM jobs j JOIN scores s ON s.job_id = j.id "
        "JOIN applications a ON a.job_id = j.id "
        "WHERE a.status IN ('discovered','scored','tailored') AND s.gate_passed = 1 "
        "ORDER BY s.overall DESC LIMIT 5"
    ).fetchall()
    if top:
        tt = Table(title="Top-scoring jobs you have not applied to yet")
        tt.add_column("#", justify="right")
        tt.add_column("Score", justify="right")
        tt.add_column("Title")
        tt.add_column("Company")
        for r in top:
            tt.add_row(str(r["id"]), f"{r['overall']:.2f}",
                       (r["title"] or "(untitled)")[:40], (r["company"] or "—")[:24])
        console.print(tt)

    # Weekly application count — honest, from real applied_at timestamps.
    week = conn.execute(
        "SELECT COUNT(*) n FROM applications "
        "WHERE applied_at IS NOT NULL AND applied_at >= datetime('now', '-7 days')"
    ).fetchone()["n"]
    console.print(f"Applications in the last 7 days: [bold]{week}[/]")

    # Highest-leverage gap to learn next.
    try:
        from . import gaps as gaps_mod

        lead = gaps_mod.highest_leverage(conn)
        if lead:
            console.print(
                f"Skill to learn next: [bold]{lead['skill']}[/] "
                f"(wanted by {lead['jobs']} job(s)). {lead['suggestion']}"
            )
    except Exception:
        pass


@app.command()
def find(
    query: str = typer.Argument(..., help='Role to search, e.g. "machine learning".'),
    location: str = typer.Option("", "--location", "-l", help="City or 'remote' (optional)."),
    limit: int = typer.Option(30, "--limit", help="Max jobs to show."),
    include_senior: bool = typer.Option(False, "--senior", help="Include senior roles."),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the page in your browser."),
) -> None:
    """Find full-time, resume-matched jobs and open them as a simple page.

    One command, no server: searches top companies (+ Adzuna if a key is set),
    ranks by fit to your resumes, and opens a page with an Apply link per job.
    """
    from . import find as find_mod

    with console.status(f'Searching for "{query}"…'):
        out, shown, total = find_mod.find(query, location, limit, include_senior)

    if shown == 0:
        console.print(f"[yellow]No full-time matches[/] for '{query}'"
                      + (f" near {location}" if location else "") + ".")
        console.print("[dim]Try a broader keyword, add --senior, or set an Adzuna key for full web search.[/]")
    else:
        console.print(f"[green]{shown} full-time matches[/] (of {total} found) → {out}")

    if open_browser:
        import webbrowser

        webbrowser.open(out.as_uri())


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host."),
    port: int = typer.Option(8000, help="Bind port."),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload (dev)."),
) -> None:
    """Launch the JobPilot web app (open http://HOST:PORT in your browser)."""
    import uvicorn

    console.print(f"[green]JobPilot web[/] → http://{host}:{port}  [dim](Ctrl-C to stop)[/]")
    uvicorn.run("jobpilot.web.server:app", host=host, port=port, reload=reload)


@app.command()
def status(
    job_id: int = typer.Argument(..., help="Job id to update."),
    new_status: str = typer.Argument(..., help="New pipeline status."),
    note: str = typer.Option("", "--note", help="Optional note."),
) -> None:
    """Update the pipeline by hand (human-in-the-loop)."""
    try:
        st = Status(new_status)
    except ValueError:
        valid = ", ".join(s.value for s in Status)
        console.print(f"[red]Invalid status[/] '{new_status}'. Valid: {valid}")
        raise typer.Exit(code=1)

    conn = db.connect()
    if db.get_job(conn, job_id) is None:
        console.print(f"[red]No job with id {job_id}.[/]")
        raise typer.Exit(code=1)

    applied_at = None
    if st == Status.applied:
        # Real timestamp only, set when the human reports they applied.
        applied_at = db.utcnow()

    db.set_status(conn, job_id, st.value, note=note or None, applied_at=applied_at)
    detail = f"status -> {st.value}" + (f" ({note})" if note else "")
    db.log_event(conn, "status_change", detail, job_id=job_id)
    marker = " [dim](human-only status; recorded as your action)[/]" if st in HUMAN_ONLY_STATUSES else ""
    console.print(f"[green]Job {job_id}[/] status set to [bold]{st.value}[/].{marker}")


if __name__ == "__main__":
    app()
