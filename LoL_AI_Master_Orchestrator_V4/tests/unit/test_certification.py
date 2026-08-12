from orchestrator.certification import certification_status, format_status

PHASES = [
    {"id": "20", "human_review_required": True},
    {"id": "08", "human_review_required": False},
]


def _state(history, deferred=None):
    return {"phase_history": history, "deferred_tests": deferred or {}}


def test_certified_when_no_deferred_and_human_reviewed():
    st = _state({"20": {"gate": "PASS", "human_review_required": True, "human_review": "human"},
                 "08": {"gate": "PASS", "human_review": "n/a"}})
    s = certification_status(st, all_phases=PHASES)
    assert s["certified"] and not s["deferred_gaps"] and not s["human_review_gaps"]


def test_not_certified_when_release_test_deferred():
    st = _state({"20": {"gate": "PASS", "human_review": "human", "human_review_required": True}},
                deferred={"20": ["e2e_real_stream"]})
    s = certification_status(st, all_phases=PHASES)
    assert not s["certified"]
    assert s["deferred_gaps"] == {"20": ["e2e_real_stream"]}


def test_not_certified_when_quality_gate_auto_approved():
    st = _state({"20": {"gate": "PASS", "human_review_required": True, "human_review": "auto"}})
    s = certification_status(st, all_phases=PHASES)
    assert not s["certified"] and s["human_review_gaps"] == ["20"]


def test_format_distinguishes_build_from_certified():
    st = _state({"20": {"gate": "PASS", "human_review_required": True, "human_review": "auto"}},
                deferred={"20": ["e2e_real_stream"]})
    txt = format_status(certification_status(st, all_phases=PHASES), overall="done")
    assert "BUILD_PASS" in txt and "e2e_real_stream" in txt and "phases 20" in txt
    # full pipeline built + human-reviewed => RELEASE_CERTIFIED
    ok = _state({"20": {"gate": "PASS", "human_review_required": True, "human_review": "human"},
                 "08": {"gate": "PASS", "human_review": "n/a"}})
    txt2 = format_status(certification_status(ok, all_phases=PHASES), overall="done")
    assert "RELEASE_CERTIFIED" in txt2


def test_partial_run_is_never_certified():
    # a subset run (only phase 20 of a 2-phase pipeline) is not certified
    st = _state({"20": {"gate": "PASS", "human_review_required": True, "human_review": "human"}})
    s = certification_status(st, all_phases=PHASES)
    assert not s["certified"] and "08" in s["missing_phases"]
