# JobPilot

A local, single-user job-search command center. **It automates the analysis, never the decision.**

JobPilot prepares materials and surfaces decisions. A human does every irreversible action.

## Guardrails (non-negotiable)

1. **Never auto-submits.** No clicking apply, no logging in as you, no solving CAPTCHAs.
2. **Never fabricates resume content.** Tailoring is reordering, reframing, and keyword surfacing
   using only facts already in your resume. Missing skills are flagged as gaps, never invented.
3. **Respects sites.** Only fetches a job page you explicitly paste; honors robots.txt; polite delays.
4. **No fake activity.** Real timestamps, real data. Nothing is backdated or padded.
5. **Local and private.** All data stays in local files. No telemetry. Secrets via env vars only.

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium   # needed from Phase 1 for JD extraction
```

## Commands

| Command | What it does | Phase |
| --- | --- | --- |
| `jobpilot add <url>` | Extract a pasted job URL, dedup, store | 1 |
| `jobpilot score <job_id\|--all-unscored>` | Gated scoring rubric + rationale | 2 |
| `jobpilot tailor <job_id>` | ATS resume + cover letter (real facts only) | 3 |
| `jobpilot research <job_id>` | Company summary, talking points, questions | 4 |
| `jobpilot prep <job_id>` | STAR+R interview stories | 4 |
| `jobpilot board` | Pipeline dashboard | 1/6 |
| `jobpilot status <job_id> <new_status> [--note]` | Human-in-the-loop pipeline update | 0 |
| `jobpilot batch <urls.txt>` | Resumable add+score worker pool (stops at tailored) | 5 |

## Configuration

| Env var | Default | Purpose |
| --- | --- | --- |
| `JOBPILOT_HOME` | `~/.jobpilot` | Base dir for DB + generated artifacts |
| `JOBPILOT_DB` | `$JOBPILOT_HOME/jobpilot.db` | Explicit DB path |
| `JD_AGENT_DIR` | `~/Desktop/jd_agent` | Existing jd_agent project reused for resumes + PDF builders |

## Development

```bash
pytest
```

Built in phases; each phase is a small, tested, real commit.
