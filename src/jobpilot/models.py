"""Pydantic models mirroring the sqlite schema."""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Status(str, Enum):
    """Pipeline status for an application. Humans advance this by hand."""

    discovered = "discovered"
    scored = "scored"
    tailored = "tailored"
    applied = "applied"
    screening = "screening"
    interview = "interview"
    offer = "offer"
    rejected = "rejected"
    skipped = "skipped"


# Statuses that mean a real human decided to pursue / submit. JobPilot never sets these.
HUMAN_ONLY_STATUSES = {
    Status.applied,
    Status.screening,
    Status.interview,
    Status.offer,
    Status.rejected,
}


class Job(BaseModel):
    id: Optional[int] = None
    url: str
    company: str = ""
    title: str = ""
    location: str = ""
    source: str = ""
    jd_text: str = ""
    created_at: str = ""


class Score(BaseModel):
    job_id: int
    overall: float = 0.0
    gate_passed: bool = False
    dimensions_json: str = "{}"
    rationale: str = ""
    scored_at: str = ""


class Application(BaseModel):
    job_id: int
    status: Status = Status.discovered
    resume_path: Optional[str] = None
    cover_path: Optional[str] = None
    applied_at: Optional[str] = None
    notes: str = ""


class Event(BaseModel):
    job_id: Optional[int] = None
    kind: str
    detail: str = ""
    at: str = ""
