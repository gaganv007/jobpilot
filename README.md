# JobPilot

A local, single-user job-search command center. **It automates the analysis, never the decision.**

JobPilot reads a job you paste, scores the fit honestly, tailors a resume and cover letter from
*only* your real facts, drafts talking points and interview stories, and tracks your whole pipeline —
then hands the apply link to you. It is more capable than the open-source "Career-Ops" project but
follows the same philosophy.

> **JobPilot never applies for you.** A human does every irreversible action.

## Guardrails (non-negotiable)

1. **Never auto-submits.** No clicking apply, no logging in as you, no solving CAPTCHAs.
2. **Never fabricates resume content.** Tailoring is reordering, reframing, and keyword surfacing
   using only facts already in your resume. A proposed summary that introduces a skill you don't have
   is *rejected*, and the rejection is written into an honesty receipt. Missing skills become gaps,
   never inventions.
3. **Respects sites.** Only fetches a job page you explicitly paste; honors robots.txt; polite delays;
   never bypasses bot protection. No bulk scraping.
4. **No fake activity.** Real UTC timestamps, real data. Nothing is backdated or padded.
5. **Local and private.** All data stays in local files. No telemetry. Secrets via env vars only.

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium      # for live JD extraction (jobpilot add / Fetch URL)
```

## Web app (recommended)

```bash
jobpilot serve                   # then open http://127.0.0.1:8000
```

A single-page dashboard over the whole engine:

- **Kanban pipeline** by status with live fit-score pills (strong / solid / FAIL / unscored).
- **One powerful search:** the **🔎 Search jobs** tab queries 30+ top companies' official job feeds
  (Greenhouse, Lever, Ashby) **and** public boards (The Muse, Remotive, Arbeitnow) in parallel, merges
  and de-dupes them, and ranks everything by fit to your resumes — senior/off-track roles hidden by
  default, a real **Apply** link on every result. Optional location filter. Opt-in, review-only, no scraping.
- Also add jobs by pasting a JD or fetching a single URL (robots-respected).
- **Legitimacy gate:** every job is checked for scam and ghost-job signals; high-risk postings get a
  red banner so you never waste an application on them.
- **Per-job drawer:** the gated score with per-dimension bars (gates highlighted), an **ATS keyword
  match ring** with the exact missing keywords to close, and one-click **Score / Tailor / Research /
  Prep / Outreach / Packet** plus PDF downloads.
- **Outreach:** drafts a referral-request and a recruiter note from your real facts (networking is the
  biggest hire-rate lever) — you review and send; JobPilot never sends them.
- **One-click triage:** **Add all** ingests scan/discover results instantly with a cheap *quick-fit*
  estimate (no PDF reads), so the board is ranked the moment jobs land; **Score all** then runs the
  full rubric on everything when you choose.
- **Follow-up reminders:** applications that have gone quiet for 5+ days surface as clickable nudges
  (a timely follow-up lifts response rates) — JobPilot reminds, you send.
- **Gap intelligence** banner — the single highest-leverage skill to learn next.
- Status changes to applied/interview/offer are clearly recorded as *your* action; JobPilot never
  sets them for you.

Prefer the terminal? The full CLI below still works — the web app is just a UI over the same engine.

JobPilot reuses your existing `jd_agent` project (4 resume PDFs + `core.py`'s matching and PDF
builders). Point to it if it isn't at `~/Desktop/jd_agent`:

```bash
export JD_AGENT_DIR=/path/to/jd_agent
```

## Workflow

```bash
jobpilot add  https://boards.example.com/jobs/123   # fetch + dedup + store one pasted URL
jobpilot score 1                                     # gated rubric, per-dimension rationale
jobpilot tailor 1                                    # resume.pdf + evidence map + honesty receipt
#   ... paste tailor_prompt.txt into Claude, save the reply, then:
jobpilot tailor 1 --reply reply.txt                  # builds coverletter.pdf from the reply
jobpilot research 1                                  # company summary, talking points, questions
jobpilot prep 1                                      # STAR+R interview stories + likely topics
jobpilot packet 1                                    # one-page brief to read before you apply
#   ... you apply by hand, then:
jobpilot status 1 applied --note "referred by X"     # you update the pipeline (human-in-loop)
jobpilot board                                       # dashboard + skill-to-learn-next
```

Find roles and bulk-triage (resumable, never applies):

```bash
jobpilot scan "machine learning" --add   # pull roles from top companies' public ATS feeds, store them
jobpilot batch urls.txt          # add + score with a worker pool; prints a ranked shortlist
jobpilot outreach 1              # draft referral + recruiter messages (you review and send)
jobpilot followups               # applications that have gone quiet and are due a nudge
jobpilot gaps                    # the single highest-leverage skill to learn this week
jobpilot calibrate               # is my scoring predicting real interview/offer outcomes?
```

## Demo

`./scripts/demo.sh` seeds a throwaway DB (no network) and walks the pipeline:

```
                              Tracked jobs
┏━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┓
┃ # ┃ Title                     ┃ Company   ┃ Status ┃ Score ┃
┡━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━┩
│ 1 │ Machine Learning Engineer │ Aurora AI │ scored │   4.1 │
│ 2 │ Data Scientist            │ Globex    │ scored │   3.7 │
└───┴───────────────────────────┴───────────┴────────┴───────┘
Applications in the last 7 days: 0
Skill to learn next: forecasting (wanted by 1 job(s)). ...
```

To record a GIF/cast: `asciinema rec -c ./scripts/demo.sh docs/demo.cast`
(then `agg docs/demo.cast docs/demo.gif`).

## The scoring rubric

Ten dimensions, each 0–5. **Two are gates** — *Role Match* and *Skills Alignment* — each must be ≥ 3
or the job fails and `overall` is capped at 2.0, so a weak fit can never look like a good one.

| Gates | Other dimensions |
| --- | --- |
| Role Match, Skills Alignment | Seniority Fit, Domain Fit, Location/Remote Fit, Compensation Fit, Tech-Stack Overlap, Visa/Work-Auth Fit, Company Stage Fit, Growth/Title Trajectory |

Scoring runs offline via a deterministic, explainable heuristic by default. `jobpilot score N --prompt`
emits a tight LLM prompt; `--reply file.json` ingests a richer score. No paid API key is required.

## What makes JobPilot stronger than Career-Ops

1. **Gap intelligence** — aggregates missing keywords across all scored jobs and names the single
   highest-leverage skill to learn next, with which of your real projects to extend.
2. **Evidence-linked tailoring** — every reordered bullet is tagged with the JD requirement it answers
   (`evidence.md`), so you can defend it in the interview.
3. **Calibration** — tracks score vs. real outcome and reports whether your scoring is predictive;
   suggests weight tweaks that *you* approve (`weights.json`).
4. **Honesty receipts** — each tailored doc ships a diff vs. the base resume proving only the summary
   and skill order changed (`honesty_receipt.md`).
5. **One-page packet** — a single Markdown brief per job: score + rationale, doc links, talking points,
   STAR stories, and the apply link.

## Configuration

| Env var | Default | Purpose |
| --- | --- | --- |
| `JOBPILOT_HOME` | `~/.jobpilot` | Base dir for DB + generated artifacts |
| `JOBPILOT_DB` | `$JOBPILOT_HOME/jobpilot.db` | Explicit DB path |
| `JD_AGENT_DIR` | `~/Desktop/jd_agent` | Existing jd_agent project (resumes + PDF builders) |

## Data model (`jobpilot.db`)

`jobs` (dedup on `url`), `scores` (gate + per-dimension JSON + rationale), `applications` (status,
doc paths), `events` (honest activity log). Schema is versioned via `PRAGMA user_version` with
incremental migrations applied on connect.

## Development

```bash
pytest                    # full suite
JD_AGENT_DIR=/nope pytest # simulates CI: jd_agent-dependent tests skip
```

CI runs pytest on Python 3.11 and 3.12 (`.github/workflows/ci.yml`).

Built in small, tested, real commits — one per phase.
