"""Canonical state store: atomic writes, schema validation, transition
legality enforcement, generated projections."""
import json
import pytest

from orchestrator.state_store import StateStore, StateError

PHASE = {"id": "00", "human_gate": True}


def _mk(tmp_path):
    return StateStore(tmp_path / "state" / "project_state.json",
                      current_task_path=tmp_path / "state" / "current_task.json",
                      state_md_path=tmp_path / "PROJECT_STATE.md",
                      task_md_path=tmp_path / "CURRENT_TASK.md")


def _base_state():
    return {"schema_version": 2, "run_id": "r", "sequence": 0, "phase_id": "00",
            "lifecycle": "READY", "attempt": 0, "builder": None,
            "candidate_commit": None, "test_evidence_id": None,
            "review_evidence_id": None, "human_gate_required": True,
            "last_gate": None, "reviewer_provider": None, "builder_provider": None,
            "approved_commit": None, "reviewed_commit": None, "tested_commit": None,
            "merged_commit": None, "human_approval_id": None}


def test_save_load_roundtrip_and_projections(tmp_path):
    store = _mk(tmp_path)
    st = store.save(_base_state())
    assert st["sequence"] == 1
    loaded = store.load()
    assert loaded == st
    assert "READY" in (tmp_path / "PROJECT_STATE.md").read_text()
    assert json.loads((tmp_path / "state" / "current_task.json").read_text())[
        "generated_from_project_state"] is True


def test_missing_file_fails_closed(tmp_path):
    with pytest.raises(StateError):
        _mk(tmp_path).load()


def test_corrupt_json_fails_closed(tmp_path):
    store = _mk(tmp_path)
    store.state_path.parent.mkdir(parents=True, exist_ok=True)
    store.state_path.write_text("{broken")
    with pytest.raises(StateError):
        store.load()


def test_incomplete_schema_fails_closed(tmp_path):
    store = _mk(tmp_path)
    store.state_path.parent.mkdir(parents=True, exist_ok=True)
    store.state_path.write_text(json.dumps({"phase_id": "00", "lifecycle": "READY"}))
    with pytest.raises(StateError):
        store.load()


def test_unknown_lifecycle_fails_closed(tmp_path):
    store = _mk(tmp_path)
    st = _base_state()
    st["lifecycle"] = "TOTALLY_FINE"
    store.state_path.parent.mkdir(parents=True, exist_ok=True)
    store.state_path.write_text(json.dumps(st))
    with pytest.raises(StateError):
        store.load()


def test_illegal_transition_never_persisted(tmp_path):
    store = _mk(tmp_path)
    st = store.save(_base_state())
    with pytest.raises(StateError):
        store.transition(st, PHASE, "MERGED")     # READY->MERGED illegal
    assert store.load()["lifecycle"] == "READY"   # unchanged on disk


def test_legal_transition_persists_and_updates(tmp_path):
    store = _mk(tmp_path)
    st = store.save(_base_state())
    st2 = store.transition(st, PHASE, "BUILDING", run_id="run-x")
    assert st2["lifecycle"] == "BUILDING" and st2["run_id"] == "run-x"
    assert store.load()["lifecycle"] == "BUILDING"


def test_human_gate_phase_cannot_pass_from_gate_evaluation(tmp_path):
    store = _mk(tmp_path)
    st = _base_state()
    st["lifecycle"] = "GATE_EVALUATION"
    st = store.save(st)
    with pytest.raises(StateError):
        store.transition(st, PHASE, "PASSED")
