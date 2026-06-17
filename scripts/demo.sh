#!/usr/bin/env bash
# JobPilot demo — seeds a throwaway DB with a couple of sample jobs (no network)
# and walks the pipeline so you can see the dashboard, scoring, and packet output.
#
# Usage:  ./scripts/demo.sh
# Records to an asciinema cast if `asciinema` is installed:
#   asciinema rec -c ./scripts/demo.sh docs/demo.cast
set -euo pipefail

export JOBPILOT_HOME="$(mktemp -d)"
echo "Using throwaway JOBPILOT_HOME=$JOBPILOT_HOME"

python - <<'PY'
# Seed two sample jobs + scores without touching the network.
import json
from jobpilot import db, scoring
conn = db.connect()
samples = [
    ("https://demo.jobs/ml-eng", "Aurora AI", "Machine Learning Engineer",
     "Build LLM and RAG systems with Python, PyTorch and AWS. Kubernetes a plus. US citizen."),
    ("https://demo.jobs/data-sci", "Globex", "Data Scientist",
     "Power BI dashboards, A/B testing and forecasting. Strong SQL and statistics."),
]
for url, co, title, jd in samples:
    jid, _ = db.add_job(conn, url, company=co, title=title, jd_text=jd)
    try:
        scored = scoring.heuristic_dimensions(jd)
        dims = scoring.dims_only(scored)
        overall, gate = scoring.compute_overall(dims)
        db.upsert_score(conn, jid, overall, gate, json.dumps(dims), scoring.rationale_text(scored))
        db.set_status(conn, jid, "scored")
    except Exception as e:
        print("（scoring skipped — jd_agent not available:", e, "）")
print("seeded", len(samples), "jobs")
PY

echo; echo "### jobpilot board"
jobpilot board || true
echo; echo "### jobpilot packet 1"
jobpilot packet 1 || true
echo; echo "### jobpilot gaps"
jobpilot gaps || true
