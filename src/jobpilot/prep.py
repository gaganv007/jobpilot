"""Interview prep: STAR+R stories mapped to the JD, plus likely topics and gaps.

Stories are drawn only from my real projects/experience (profile.STAR_STORIES).
Likely technical topics come from the JD. Gaps (skills the JD wants that I lack)
are surfaced honestly, never papered over.
"""
from __future__ import annotations

from . import profile, research

# JD signal -> interview topics to revise. Kept conservative and honest.
TOPIC_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("machine learning", "ml", "model", "pytorch", "tensorflow"), "ML fundamentals: bias/variance, regularization, evaluation metrics"),
    (("llm", "rag", "langchain", "genai", "generative"), "LLM/RAG: retrieval, chunking, evaluation, hallucination control"),
    (("system design", "scalable", "distributed", "microservices"), "System design: scaling, caching, queues, failure modes"),
    (("data structures", "algorithms", "coding"), "Data structures and algorithms (timed coding)"),
    (("sql", "data warehouse", "etl", "pipeline"), "SQL and data modeling; ETL/pipeline tradeoffs"),
    (("kubernetes", "docker", "ci/cd", "devops", "mlops"), "Containers, CI/CD and deployment/rollback strategy"),
    (("aws", "gcp", "azure", "cloud", "serverless"), "Cloud architecture and serverless tradeoffs"),
    (("statistics", "a/b", "experiment", "forecasting"), "Statistics: hypothesis testing, A/B design, forecasting"),
    (("react", "frontend", "next.js", "typescript"), "Frontend: component design, state, rendering tradeoffs"),
]


def likely_topics(jd_text: str) -> list[str]:
    jl = (jd_text or "").lower()
    topics = [topic for signals, topic in TOPIC_HINTS if any(s in jl for s in signals)]
    return topics or ["General CS fundamentals and a walkthrough of your strongest project"]


def gaps(jd_text: str, track: str | None = None) -> list[str]:
    """Skills the JD asks for that are not in my resume (so I can prepare an
    honest answer). Uses jd_agent's keyword_gaps when available."""
    try:
        from . import jd_bridge

        if not jd_bridge.available():
            return []
        if track is None:
            track, _ = jd_bridge.match_track(jd_text)
        _present, missing = jd_bridge.keyword_gaps(jd_text, track)
        return missing
    except Exception:
        return []


def build_prep_doc(job: dict) -> str:
    jd = job.get("jd_text", "")
    lines = [
        f"# Interview prep — {job.get('title') or 'role'} @ {job.get('company') or 'company'}",
        "",
        "## STAR+R stories (all real, from my own work)",
    ]
    for story, matched in profile.select_stories(jd, k=3):
        tag = f"  _(relevant to: {', '.join(matched[:4])})_" if matched else "  _(strong general story)_"
        lines += [
            f"### {story['title']}{tag}",
            f"- **Situation:** {story['situation']}",
            f"- **Task:** {story['task']}",
            f"- **Action:** {story['action']}",
            f"- **Result:** {story['result']}",
            f"- **Reflection:** {story['reflection']}",
            "",
        ]
    lines += ["## Likely technical topics"]
    lines += [f"- {t}" for t in likely_topics(jd)]
    g = gaps(jd)
    if g:
        lines += ["", "## Gaps to prepare an honest answer for",
                  "These appear in the JD but are not on my resume. Be ready to say how "
                  "I would ramp, not to claim them:",
                  "- " + ", ".join(g[:12])]
    lines += [""]
    return "\n".join(lines)


def build_prep_prompt(job: dict) -> str:
    return f"""Help me prepare for an interview. Using ONLY the candidate facts I provide
(do not invent experience), write 3 STAR+R stories (Situation, Task, Action, Result,
Reflection) mapped to this job, and list the most likely technical topics.

JOB: {job.get('title','')} @ {job.get('company','')}
{job.get('jd_text','')}"""
