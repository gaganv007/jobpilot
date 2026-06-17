"""Shared pytest fixtures. Every test runs against a throwaway DB/home dir so
nothing touches the real ~/.jobpilot data."""
import os

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Point JobPilot at a temp home + DB for the duration of each test."""
    home = tmp_path / "jpilot_home"
    home.mkdir()
    monkeypatch.setenv("JOBPILOT_HOME", str(home))
    monkeypatch.setenv("JOBPILOT_DB", str(home / "jobpilot.db"))
    # Make sure config picks these up freshly.
    yield home


@pytest.fixture
def conn():
    from jobpilot import db

    c = db.connect()
    yield c
    c.close()
