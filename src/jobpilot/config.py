"""Configuration and filesystem locations for JobPilot.

Everything stays local. Paths can be overridden by environment variables so the
test-suite can point at a throwaway directory.

Env vars:
  JOBPILOT_HOME   -> base dir for the DB + generated artifacts (default ~/.jobpilot)
  JOBPILOT_DB     -> explicit path to the sqlite file (overrides JOBPILOT_HOME)
  JD_AGENT_DIR    -> location of the existing jd_agent project to reuse
"""
from __future__ import annotations

import os
from pathlib import Path


def home_dir() -> Path:
    """Base directory for all JobPilot local data."""
    p = Path(os.environ.get("JOBPILOT_HOME", Path.home() / ".jobpilot")).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    """Path to the sqlite tracker database."""
    explicit = os.environ.get("JOBPILOT_DB")
    if explicit:
        p = Path(explicit).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    return home_dir() / "jobpilot.db"


def artifacts_dir() -> Path:
    """Where tailored resumes, cover letters, packets, and locks are written."""
    p = home_dir() / "artifacts"
    p.mkdir(parents=True, exist_ok=True)
    return p


def job_dir(job_id: int) -> Path:
    """Per-job artifact directory."""
    p = artifacts_dir() / f"job_{job_id}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def settings_path() -> Path:
    return home_dir() / "settings.json"


def get_settings() -> dict:
    """Local user settings (e.g. Adzuna API creds). Stored in JOBPILOT_HOME."""
    import json

    p = settings_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_settings(updates: dict) -> dict:
    import json

    s = get_settings()
    s.update({k: v for k, v in updates.items() if v is not None})
    settings_path().write_text(json.dumps(s, indent=2), encoding="utf-8")
    return s


def adzuna_creds() -> tuple[str, str] | None:
    """(app_id, app_key) from settings or env, or None if not configured."""
    s = get_settings()
    app_id = s.get("adzuna_app_id") or os.environ.get("ADZUNA_APP_ID")
    app_key = s.get("adzuna_app_key") or os.environ.get("ADZUNA_APP_KEY")
    if app_id and app_key:
        return app_id, app_key
    return None


def jd_agent_dir() -> Path:
    """Location of the existing jd_agent project we reuse (core.py, resumes/)."""
    return Path(
        os.environ.get("JD_AGENT_DIR", Path.home() / "Desktop" / "jd_agent")
    ).expanduser()
