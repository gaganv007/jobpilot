"""Company research from the JD (and the web if a human runs the LLM prompt).

Deterministic and offline by default: it summarizes what the JD itself states,
intersects the JD's tech stack with my real skills, and proposes talking points
and questions grounded in those facts. It does not assert company facts that are
not in the JD. For deeper research, build_research_prompt emits a paste-mode
prompt the user can run in a chat with web access.
"""
from __future__ import annotations

import re

from . import profile

TECH_VOCAB = [
    "python", "java", "typescript", "javascript", "go", "rust", "scala", "c++",
    "pytorch", "tensorflow", "keras", "scikit-learn", "xgboost", "llm", "rag",
    "langchain", "nlp", "computer vision", "react", "next.js", "node", "fastapi",
    "flask", "graphql", "rest", "aws", "gcp", "azure", "docker", "kubernetes",
    "terraform", "spark", "kafka", "airflow", "snowflake", "databricks", "sql",
    "power bi", "tableau", "redis", "mongodb", "postgres", "ci/cd", "github actions",
]


def tech_in_jd(jd: str) -> list[str]:
    jl = (jd or "").lower()
    return [t for t in TECH_VOCAB if re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", jl)]


def company_summary(job: dict) -> str:
    company = job.get("company") or "the company"
    title = job.get("title") or "this role"
    stack = tech_in_jd(job.get("jd_text", ""))
    bits = [f"{company} is hiring for {title}."]
    if stack:
        bits.append(f"The JD names this stack: {', '.join(stack[:10])}.")
    bits.append("Everything above is taken from the posting itself; verify other "
                "company facts before the interview.")
    return " ".join(bits)


def talking_points(job: dict, k: int = 3) -> list[str]:
    """Talking points that connect my real work to this JD. Facts only."""
    stack = set(tech_in_jd(job.get("jd_text", "")))
    points: list[str] = []
    for story, matched in profile.select_stories(job.get("jd_text", ""), k=k):
        overlap = [t for t in story["tags"] if t in stack]
        link = f" (overlaps the JD's {', '.join(overlap[:3])})" if overlap else ""
        points.append(f"{story['title']}: {story['result']}{link}")
    return points[:k]


def smart_questions(job: dict) -> list[str]:
    """Two specific questions grounded in JD signals (not fabricated facts)."""
    stack = tech_in_jd(job.get("jd_text", ""))
    qs = []
    if stack:
        qs.append(
            f"You mention {stack[0]}"
            + (f" and {stack[1]}" if len(stack) > 1 else "")
            + " in the JD. How is that stack actually used day to day, and what is owned by this role versus other teams?"
        )
    else:
        qs.append("What does the first 90 days look like for this role, and how is success measured?")
    qs.append("Where is this team headed over the next year, and what is the biggest technical problem you want this hire to own?")
    return qs[:2]


def build_research_doc(job: dict) -> str:
    lines = [
        f"# Company research — {job.get('company') or '(unknown company)'}",
        "",
        "## Summary (from the JD)",
        company_summary(job),
        "",
        "## Talking points (my real work mapped to this JD)",
    ]
    lines += [f"{i}. {p}" for i, p in enumerate(talking_points(job), 1)]
    lines += ["", "## Smart questions to ask them"]
    lines += [f"{i}. {q}" for i, q in enumerate(smart_questions(job), 1)]
    lines += ["", "_Facts here come from the posting and my real experience. "
              "Confirm anything else before you use it._", ""]
    return "\n".join(lines)


def build_research_prompt(job: dict) -> str:
    return f"""Research this company for a job interview and return facts only. If you are
unsure of a fact, leave it out — do not guess. Give:
1) a 3-4 sentence summary of what the company does and its stage,
2) 3 specific, recent facts (product, funding, customers, tech) with rough dates,
3) 2 thoughtful questions a candidate could ask that show they did the research.

COMPANY: {job.get('company','')}
ROLE: {job.get('title','')}
JOB DESCRIPTION:
{job.get('jd_text','')}"""
