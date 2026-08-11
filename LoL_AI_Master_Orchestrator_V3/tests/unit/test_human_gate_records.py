"""Human-gate approval records: exact-SHA binding, reject handling."""
import pytest

from orchestrator.human_gate import record_decision, latest_decision, HumanGateError


def test_record_and_lookup_exact_sha(tmp_path):
    rec, path = record_decision(tmp_path, phase_id="00", commit_sha="sha-a",
                                approver="wam", decision="APPROVE", reason="ok")
    assert path.exists()
    found = latest_decision(tmp_path, phase_id="00", commit_sha="sha-a")
    assert found["approval_id"] == rec["approval_id"]
    # a different SHA never matches — approval is bound to the exact commit
    assert latest_decision(tmp_path, phase_id="00", commit_sha="sha-b") is None
    # a different phase never matches
    assert latest_decision(tmp_path, phase_id="01", commit_sha="sha-a") is None


def test_reject_record_is_returned_and_gate_blocks_on_it(tmp_path):
    record_decision(tmp_path, phase_id="00", commit_sha="sha-a",
                    approver="wam", decision="REJECT", reason="not good")
    rec = latest_decision(tmp_path, phase_id="00", commit_sha="sha-a")
    assert rec["decision"] == "REJECT"
    from orchestrator import gates
    phase = {"id": "00", "human_gate": True, "required_tests": [],
             "gate": {"max_blockers": 0, "max_unaccepted_high": 0}}
    d = gates.evaluate_completion_gate(
        phase, test_exit_codes={}, metrics={}, review_findings=[],
        forbidden_changes=[], secret_findings=[], clean_main=True,
        candidate_commit="sha-a", tested_commit="sha-a", reviewed_commit="sha-a",
        approved_commit=None, human_approval_record=rec, acceptance_records=[])
    assert not d.passed
    assert any("not approved" in r for r in d.reasons)


def test_invalid_decision_and_missing_fields_rejected(tmp_path):
    with pytest.raises(HumanGateError):
        record_decision(tmp_path, phase_id="00", commit_sha="s",
                        approver="a", decision="MAYBE")
    with pytest.raises(HumanGateError):
        record_decision(tmp_path, phase_id="00", commit_sha="",
                        approver="a", decision="APPROVE")


def test_corrupt_record_ignored(tmp_path):
    (tmp_path).mkdir(exist_ok=True)
    (tmp_path / "zz-corrupt.json").write_text("{nope")
    assert latest_decision(tmp_path, phase_id="00", commit_sha="x") is None
