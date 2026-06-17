"""Gap intelligence.

Aggregate the missing-keyword gaps across all scored jobs and name the single
highest-leverage skill to learn next, with which of my real projects could best
be extended to close it. Honest: it only reports skills the JDs actually asked
for and that my resume lacks.
"""
from __future__ import annotations

from collections import Counter

from . import db, profile

# A missing skill -> the real project of mine most natural to extend to learn it.
# Only references projects that exist in profile.STAR_STORIES.
LEARN_HINTS: dict[str, str] = {
    "kafka": "Add a Kafka stream to the 5GB+ Spark ETL pipeline.",
    "airflow": "Orchestrate the Spark ETL pipeline with Airflow instead of ad-hoc runs.",
    "snowflake": "Land the ETL pipeline's output into Snowflake and query it.",
    "go": "Rewrite Gavel's FastAPI service (or one endpoint) in Go.",
    "golang": "Rewrite a Gavel endpoint in Go.",
    "rust": "Reimplement a hot path of the GNN pipeline in Rust.",
    "scala": "Port part of the Spark ETL job to Scala.",
    "terraform": "Provision the ML-Blockchain MLOps platform with Terraform.",
    "gcp": "Redeploy the MLOps platform on GCP alongside the AWS version.",
    "azure": "Stand up the MLOps platform on Azure.",
    "graphql": "Expose Gavel's API via GraphQL.",
    "tableau": "Rebuild the Power BI dashboards in Tableau.",
    "databricks": "Run the Spark ETL pipeline on Databricks.",
    "spark": "Extend the existing Spark ETL pipeline with more transforms.",
    "kubernetes": "Deepen the Docker+Kubernetes work in the MLOps platform.",
}


def _project_hint(skill: str) -> str:
    s = skill.lower()
    if s in LEARN_HINTS:
        return LEARN_HINTS[s]
    # fall back to the project whose tags are most related to the skill's words
    best, best_overlap = None, 0
    words = set(s.replace("-", " ").split())
    for story in profile.STAR_STORIES:
        overlap = len(words & set(" ".join(story["tags"]).split()))
        if overlap > best_overlap:
            best, best_overlap = story, overlap
    if best:
        return f"Closest project to extend: {best['title']}."
    return "Build a small, focused project that uses it, then add it to the resume."


def aggregate_gaps(conn) -> list[tuple[str, int]]:
    """Count missing JD keywords across all scored jobs (most common first)."""
    from . import jd_bridge

    if not jd_bridge.available():
        return []
    counter: Counter[str] = Counter()
    rows = conn.execute(
        "SELECT j.id, j.jd_text FROM jobs j JOIN scores s ON s.job_id = j.id"
    ).fetchall()
    for r in rows:
        jd = r["jd_text"] or ""
        try:
            track, _ = jd_bridge.match_track(jd)
            _present, missing = jd_bridge.keyword_gaps(jd, track)
        except Exception:
            continue
        for kw in set(missing):
            counter[kw] += 1
    return counter.most_common()


def highest_leverage(conn) -> dict | None:
    """The single skill that, if learned, would unblock the most scored jobs."""
    agg = aggregate_gaps(conn)
    if not agg:
        return None
    skill, count = agg[0]
    return {"skill": skill, "jobs": count, "suggestion": _project_hint(skill)}


def build_gap_report(conn, top: int = 8) -> str:
    agg = aggregate_gaps(conn)
    if not agg:
        return ("No gap data yet — score some jobs first "
                "(or jd_agent is unavailable).")
    lines = ["# Gap intelligence", "", "Skills the JDs asked for that my resume lacks, "
             "across all scored jobs:", ""]
    for skill, count in agg[:top]:
        lines.append(f"- **{skill}** — wanted by {count} job(s)")
    lead = highest_leverage(conn)
    if lead:
        lines += ["", "## Highest-leverage skill this week",
                  f"**{lead['skill']}** (unblocks {lead['jobs']} job(s)).",
                  f"How to close it: {lead['suggestion']}"]
    lines.append("")
    return "\n".join(lines)
