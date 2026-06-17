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
) -> None:
    """Run the gated scoring rubric. (Phase 2)"""
    console.print(f"[yellow]score[/]: {_NOT_YET}")
    raise typer.Exit(code=1)


@app.command()
def tailor(job_id: int = typer.Argument(..., help="Job id to tailor for.")) -> None:
    """Build an ATS-optimized resume + cover letter from real facts only. (Phase 3)"""
    console.print(f"[yellow]tailor[/]: {_NOT_YET}")
    raise typer.Exit(code=1)


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
