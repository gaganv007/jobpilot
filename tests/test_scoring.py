"""Phase 2: gate/cap logic, reply parsing, and the heuristic scorer."""
import pytest

from jobpilot import scoring


def _full(score=4):
    return {d: score for d in scoring.DIMENSIONS}


def test_all_high_passes_gate():
    overall, gate = scoring.compute_overall(_full(5))
    assert gate is True
    assert overall == 5.0


def test_role_match_gate_fails_and_caps():
    dims = _full(5)
    dims["Role Match"] = 2  # below GATE_MIN
    overall, gate = scoring.compute_overall(dims)
    assert gate is False
    # Even though the raw weighted mean is high, overall is capped.
    assert overall <= scoring.CAP_WHEN_GATE_FAILS


def test_skills_gate_fails_and_caps():
    dims = _full(5)
    dims["Skills Alignment"] = 0
    overall, gate = scoring.compute_overall(dims)
    assert gate is False
    assert overall <= scoring.CAP_WHEN_GATE_FAILS


def test_gate_exactly_at_min_passes():
    dims = _full(5)
    dims["Role Match"] = scoring.GATE_MIN
    dims["Skills Alignment"] = scoring.GATE_MIN
    overall, gate = scoring.compute_overall(dims)
    assert gate is True


def test_weak_job_cannot_masquerade_as_good():
    # Non-gate dims maxed, but a gate is weak -> must not look like a strong fit.
    dims = _full(5)
    dims["Skills Alignment"] = 1
    overall, gate = scoring.compute_overall(dims)
    assert gate is False
    assert scoring.band(overall, gate) == "FAIL (gate)"
    assert overall < 3.0


def test_weighted_mean_is_correct_when_passing():
    dims = _full(4)
    overall, gate = scoring.compute_overall(dims)
    # all equal -> weighted mean equals the common value
    assert gate is True
    assert overall == 4.0


def test_validate_dims_rejects_missing_and_out_of_range():
    with pytest.raises(ValueError):
        scoring.compute_overall({"Role Match": 5})
    bad = _full(5)
    bad["Domain Fit"] = 9
    with pytest.raises(ValueError):
        scoring.compute_overall(bad)


def test_band_labels():
    assert scoring.band(4.5, True) == "strong"
    assert scoring.band(3.2, True) == "solid"
    assert scoring.band(2.5, True) == "marginal"
    assert scoring.band(1.0, True) == "weak"
    assert scoring.band(1.9, False) == "FAIL (gate)"


def test_parse_score_reply_json():
    parts = ", ".join(f'"{d}": {{"score": 4, "rationale": "ok"}}' for d in scoring.DIMENSIONS)
    text = "Here is the score:\n```json\n{" + parts + "}\n```"
    scored = scoring.parse_score_reply(text)
    assert set(scored) == set(scoring.DIMENSIONS)
    assert scored["Role Match"]["score"] == 4


def test_parse_score_reply_rejects_bad_range():
    parts = ", ".join(f'"{d}": {{"score": 7, "rationale": "x"}}' for d in scoring.DIMENSIONS)
    with pytest.raises(ValueError):
        scoring.parse_score_reply("{" + parts + "}")


# ---- heuristic scorer needs jd_agent; skip if not importable (e.g. CI) ----
jd_available = pytest.importorskip  # alias for readability


def _bridge_ok():
    from jobpilot import jd_bridge

    return jd_bridge.available()


@pytest.mark.skipif(not _bridge_ok(), reason="jd_agent not available")
def test_heuristic_is_deterministic_and_complete():
    jd = ("Senior Machine Learning Engineer. Build LLM and RAG systems with Python, "
          "PyTorch, AWS and Kubernetes. Remote. US citizen, no sponsorship.")
    a = scoring.heuristic_dimensions(jd)
    b = scoring.heuristic_dimensions(jd)
    assert scoring.dims_only(a) == scoring.dims_only(b)  # deterministic
    assert set(a) == set(scoring.DIMENSIONS)
    overall, gate = scoring.compute_overall(scoring.dims_only(a))
    assert 0 <= overall <= 5


@pytest.mark.skipif(not _bridge_ok(), reason="jd_agent not available")
def test_heuristic_flags_clearance_as_gap():
    jd = "ML role requiring an active TS/SCI security clearance and polygraph."
    scored = scoring.heuristic_dimensions(jd)
    assert scored["Visa/Work-Auth Fit"]["score"] <= 2
