"""Bridge to the existing jd_agent project.

We reuse jd_agent/core.py rather than rewriting its matching + PDF logic
(parse_claude_reply, match_track, keyword_gaps, build_optimized_resume,
build_cover_pdf). We wrap and improve it but keep its no-fabrication behavior.

core.py only imports langchain lazily (inside its LLM helpers), so importing the
module here needs nothing beyond pdfplumber + reportlab, which JobPilot already
depends on.
"""
from __future__ import annotations

import importlib
import sys
from functools import lru_cache
from types import ModuleType

from . import config


class JDAgentUnavailable(RuntimeError):
    """Raised when jd_agent/core.py cannot be imported (path/deps missing)."""


@lru_cache(maxsize=1)
def core() -> ModuleType:
    """Import and cache jd_agent's core module."""
    d = config.jd_agent_dir()
    core_py = d / "core.py"
    if not core_py.exists():
        raise JDAgentUnavailable(
            f"jd_agent core.py not found at {core_py}. "
            f"Set JD_AGENT_DIR to your jd_agent project."
        )
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))
    try:
        mod = importlib.import_module("core")
    except Exception as e:  # pragma: no cover - environment dependent
        raise JDAgentUnavailable(f"Could not import jd_agent core.py: {e}") from e
    return mod


def available() -> bool:
    try:
        core()
        return True
    except JDAgentUnavailable:
        return False


# ---- thin pass-throughs (keep names identical to core for clarity) ----
def match_track(jd: str):
    return core().match_track(jd)


def keyword_gaps(jd: str, track: str):
    return core().keyword_gaps(jd, track)


def suggested_skill_order(jd: str, track: str):
    return core().suggested_skill_order(jd, track)


def parse_claude_reply(text: str):
    return core().parse_claude_reply(text)


def build_optimized_resume(track: str, new_summary: str, skill_order: list, out_path: str):
    return core().build_optimized_resume(track, new_summary, skill_order, out_path)


def build_cover_pdf(body: str, company: str, role: str, out_path: str, **kw):
    return core().build_cover_pdf(body, company, role, out_path, **kw)


def resume_text(track: str) -> str:
    c = core()
    import os

    return c._pdf_text(os.path.join(c.RESUME_DIR, c.TRACKS[track]["file"]))


def tracks() -> dict:
    return core().TRACKS
