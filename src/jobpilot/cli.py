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
                # Heuristic provides rationale where the reply omitted it.
                heur = scoring.heuristic_dimensions(job["jd_text"])
                for d in scoring.DIMENSIONS:
                    if not scored[d]["rationale"]:
                        scored[d]["rationale"] = heur[d]["rationale"]
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


@app.command()
def research(job_id: int = typer.Argument(..., help="Job id to research.")) -> None:
    """Summarize the company; talking points and questions. Facts only. (Phase 4)"""
    console.print(f"[yellow]research[/]: {_NOT_YET}")
    raise typer.Exit(code=1)


@app.command()
def prep(job_id: int = typer.Argument(..., help="Job id to prep for.")) -> None:
    """Generate STAR+R interview stories from real experience. (Phase 4)"""
    console.print(f"[yellow]prep[/]: {_NOT_YET}")
    raise typer.Exit(code=1)


@app.command()
def batch(urls_file: str = typer.Argument(..., help="Text file of URLs, one per line.")) -> None:
    """Add + score many URLs with a resumable worker pool. Stops at tailored. (Phase 5)"""
    console.print(f"[yellow]batch[/]: {_NOT_YET}")
    raise typer.Exit(code=1)


@app.command()
def board() -> None:
    """Dashboard: pipeline by status and tracked jobs (full dashboard in Phase 6)."""
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
        listing.add_row(
            str(j["id"]),
            (j["title"] or "(untitled)")[:40],
            (j["company"] or "—")[:24],
            (j["location"] or "—")[:20],
            appn["status"] if appn else "—",
            score_cell,
        )
    console.print(listing)


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
