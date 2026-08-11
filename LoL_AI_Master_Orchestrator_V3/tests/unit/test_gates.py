from orchestrator.gates import (
    evaluate_completion_gate, validate_lifecycle_transition, validate_merge_commit,
)

BASE = dict(
    test_exit_codes={"x":0},
    metrics={},
    review_findings=[],
    forbidden_changes=[],
    secret_findings=[],
    clean_main=True,
    candidate_commit="abc",
    tested_commit="abc",
    reviewed_commit="abc",
    approved_commit=None,
    human_approval_record=None,
    acceptance_records=[],
)

def _phase(human=False):
    return {"id":"04","required_tests":["x"],"human_gate":human,
            "gate":{"max_blockers":0,"max_unaccepted_high":0}}

def _acc(fid="F1", sha="abc", phase="04", decision="ACCEPT"):
    return {"phase_id":phase,"finding_id":fid,"commit_sha":sha,"decision":decision,
            "reason":"resolved risk","approver":"human","timestamp_utc":"2026-08-11T18:00:00Z"}

# ---- transition validation is separate and SHA-free ----
def test_early_transition_needs_no_shas_or_tests():
    d=validate_lifecycle_transition(_phase(), lifecycle_from="BUILDING", lifecycle_to="TESTING")
    assert d.passed

def test_illegal_transition_blocked():
    d=validate_lifecycle_transition(_phase(), lifecycle_from="BUILDING", lifecycle_to="PASSED")
    assert not d.passed

def test_human_gate_cannot_skip_state():
    d=validate_lifecycle_transition(_phase(human=True), lifecycle_from="GATE_EVALUATION", lifecycle_to="PASSED")
    assert not d.passed

def test_human_gate_pass_from_human_gate_state_is_legal_transition():
    d=validate_lifecycle_transition(_phase(human=True), lifecycle_from="HUMAN_GATE", lifecycle_to="PASSED")
    assert d.passed

def test_merge_commit_identity():
    assert validate_merge_commit(candidate_commit="abc", merged_commit="abc").passed
    assert not validate_merge_commit(candidate_commit="abc", merged_commit="def").passed

# ---- completion gate ----
def test_missing_required_test_blocks():
    args=BASE.copy(); args["test_exit_codes"]={}
    assert not evaluate_completion_gate(_phase(), **args).passed

def test_high_finding_blocks_without_acceptance_record():
    args=BASE.copy()
    args["review_findings"]=[{"id":"F1","severity":"high","title":"x"}]
    assert not evaluate_completion_gate(_phase(), **args).passed

def test_valid_acceptance_record_accepts_exactly_that_finding():
    args=BASE.copy()
    args["review_findings"]=[{"id":"F1","severity":"high","title":"x"}]
    args["acceptance_records"]=[_acc("F1")]
    assert evaluate_completion_gate(_phase(), **args).passed

def test_stale_sha_acceptance_is_rejected_and_reported():
    args=BASE.copy()
    args["review_findings"]=[{"id":"F1","severity":"high","title":"x"}]
    args["acceptance_records"]=[_acc("F1", sha="OLD")]
    d=evaluate_completion_gate(_phase(), **args)
    assert not d.passed
    assert any("stale acceptance" in r for r in d.reasons)

def test_wrong_phase_acceptance_does_not_accept():
    args=BASE.copy()
    args["review_findings"]=[{"id":"F1","severity":"high","title":"x"}]
    args["acceptance_records"]=[_acc("F1", phase="05")]
    assert not evaluate_completion_gate(_phase(), **args).passed

def test_reject_decision_accepts_nothing():
    args=BASE.copy()
    args["review_findings"]=[{"id":"F1","severity":"high","title":"x"}]
    args["acceptance_records"]=[_acc("F1", decision="REJECT")]
    assert not evaluate_completion_gate(_phase(), **args).passed

def test_incomplete_record_is_reported_not_ignored():
    args=BASE.copy()
    rec=_acc("F1"); rec["approver"]=""
    args["review_findings"]=[{"id":"F1","severity":"high","title":"x"}]
    args["acceptance_records"]=[rec]
    d=evaluate_completion_gate(_phase(), **args)
    assert not d.passed and any("incomplete" in r for r in d.reasons)

def test_finding_without_id_can_never_be_accepted():
    args=BASE.copy()
    args["review_findings"]=[{"severity":"high","title":"no id"}]
    args["acceptance_records"]=[_acc("index:0"), _acc("None"), _acc("no id")]
    assert not evaluate_completion_gate(_phase(), **args).passed

def test_acceptance_is_order_independent():
    f1={"id":"F1","severity":"high","title":"a"}
    f2={"id":"F2","severity":"high","title":"b"}
    for findings in ([f1,f2],[f2,f1]):
        args=BASE.copy()
        args["review_findings"]=findings
        args["acceptance_records"]=[_acc("F1")]
        d=evaluate_completion_gate(_phase(), **args)
        assert not d.passed and "unaccepted high findings: 1>0" in d.reasons

def test_human_gate_pass_requires_exact_sha_approval():
    args=BASE.copy()
    args.update(approved_commit="abc",
        human_approval_record={"decision":"APPROVE","commit_sha":"abc","approver":"human"})
    assert evaluate_completion_gate(_phase(human=True), **args).passed

def test_human_gate_pass_blocks_without_approval():
    assert not evaluate_completion_gate(_phase(human=True), **BASE.copy()).passed
