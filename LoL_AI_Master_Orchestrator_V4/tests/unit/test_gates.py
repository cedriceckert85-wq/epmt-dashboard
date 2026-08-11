from orchestrator.gates import (
    evaluate_completion_gate, validate_lifecycle_transition, validate_merge_commit,
)

BASE = dict(
    test_exit_codes={"x": 0},
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


def _phase(human=False, **kw):
    d = {"id": "04", "required_tests": ["x"], "human_gate": human,
         "gate": {"max_blockers": 0, "max_unaccepted_high": 0}}
    d.update(kw)
    return d


def _acc(fid="F1", sha="abc", phase="04", decision="ACCEPT"):
    return {"phase_id": phase, "finding_id": fid, "commit_sha": sha, "decision": decision,
            "reason": "resolved risk", "approver": "human",
            "timestamp_utc": "2026-08-11T18:00:00Z"}


# ---- transition validation is separate and SHA-free ----
def test_early_transition_needs_no_shas_or_tests():
    assert validate_lifecycle_transition(_phase(), lifecycle_from="BUILDING",
                                         lifecycle_to="TESTING").passed


def test_illegal_transition_blocked():
    assert not validate_lifecycle_transition(_phase(), lifecycle_from="BUILDING",
                                             lifecycle_to="PASSED").passed


def test_human_gate_cannot_skip_state():
    assert not validate_lifecycle_transition(_phase(human=True),
                                             lifecycle_from="GATE_EVALUATION",
                                             lifecycle_to="PASSED").passed


def test_human_gate_pass_from_human_gate_state_is_legal_transition():
    assert validate_lifecycle_transition(_phase(human=True),
                                         lifecycle_from="HUMAN_GATE",
                                         lifecycle_to="PASSED").passed


def test_gate_eval_to_fixing_is_legal():
    assert validate_lifecycle_transition(_phase(), lifecycle_from="GATE_EVALUATION",
                                         lifecycle_to="FIXING").passed


def test_merge_commit_identity():
    assert validate_merge_commit(candidate_commit="abc", merged_commit="abc").passed
    assert not validate_merge_commit(candidate_commit="abc", merged_commit="def").passed


# ---- completion gate ----
def test_missing_required_test_blocks():
    args = BASE.copy(); args["test_exit_codes"] = {}
    assert not evaluate_completion_gate(_phase(), **args).passed


def test_high_finding_blocks_without_acceptance_record():
    args = BASE.copy()
    args["review_findings"] = [{"id": "F1", "severity": "high", "title": "x"}]
    assert not evaluate_completion_gate(_phase(), **args).passed


def test_valid_acceptance_record_accepts_exactly_that_finding():
    args = BASE.copy()
    args["review_findings"] = [{"id": "F1", "severity": "high", "title": "x"}]
    args["acceptance_records"] = [_acc("F1")]
    assert evaluate_completion_gate(_phase(), **args).passed


def test_stale_sha_acceptance_accepts_nothing_but_does_not_error():
    # a stale ACCEPT (bound to an earlier candidate) must neither accept the
    # finding nor emit a blocking 'stale' error — otherwise it would
    # permanently block the phase even on a clean fresh rebuild.
    args = BASE.copy()
    args["review_findings"] = [{"id": "F1", "severity": "high", "title": "x"}]
    args["acceptance_records"] = [_acc("F1", sha="OLD")]
    d = evaluate_completion_gate(_phase(), **args)
    assert not d.passed
    assert any("unaccepted high findings" in r for r in d.reasons)
    assert not any("stale" in r for r in d.reasons)


def test_stale_acceptance_does_not_block_a_clean_rebuild():
    # new candidate has NO findings; an old acceptance for a prior candidate
    # must not turn a clean rebuild into a BLOCK.
    args = BASE.copy()
    args["review_findings"] = []
    args["acceptance_records"] = [_acc("F1", sha="OLD")]
    assert evaluate_completion_gate(_phase(), **args).passed


def test_wrong_phase_acceptance_does_not_accept():
    args = BASE.copy()
    args["review_findings"] = [{"id": "F1", "severity": "high", "title": "x"}]
    args["acceptance_records"] = [_acc("F1", phase="05")]
    assert not evaluate_completion_gate(_phase(), **args).passed


def test_reject_decision_accepts_nothing():
    args = BASE.copy()
    args["review_findings"] = [{"id": "F1", "severity": "high", "title": "x"}]
    args["acceptance_records"] = [_acc("F1", decision="REJECT")]
    assert not evaluate_completion_gate(_phase(), **args).passed


def test_incomplete_record_is_reported_not_ignored():
    args = BASE.copy()
    rec = _acc("F1"); rec["approver"] = ""
    args["review_findings"] = [{"id": "F1", "severity": "high", "title": "x"}]
    args["acceptance_records"] = [rec]
    d = evaluate_completion_gate(_phase(), **args)
    assert not d.passed and any("incomplete" in r for r in d.reasons)


def test_finding_without_id_can_never_be_accepted():
    args = BASE.copy()
    args["review_findings"] = [{"severity": "high", "title": "no id"}]
    args["acceptance_records"] = [_acc("index:0"), _acc("None"), _acc("no id")]
    assert not evaluate_completion_gate(_phase(), **args).passed


def test_human_gate_pass_requires_exact_sha_approval():
    args = BASE.copy()
    args.update(approved_commit="abc",
                human_approval_record={"decision": "APPROVE", "commit_sha": "abc",
                                       "approver": "human"})
    assert evaluate_completion_gate(_phase(human=True), **args).passed


def test_human_gate_pass_blocks_without_approval():
    assert not evaluate_completion_gate(_phase(human=True), **BASE.copy()).passed


def test_secret_findings_block():
    args = BASE.copy(); args["secret_findings"] = [{"file": "a", "kind": "k", "line": 1}]
    assert not evaluate_completion_gate(_phase(), **args).passed


def test_forbidden_changes_block():
    args = BASE.copy(); args["forbidden_changes"] = ["schemas/x.json"]
    assert not evaluate_completion_gate(_phase(), **args).passed


def test_sha_invariants_block():
    args = BASE.copy(); args["tested_commit"] = "zzz"
    assert not evaluate_completion_gate(_phase(), **args).passed
    args = BASE.copy(); args["reviewed_commit"] = "zzz"
    assert not evaluate_completion_gate(_phase(), **args).passed


# ---- V4: deferral (one-shot adaptation) ----
def test_deferred_test_passes_gate_only_if_deferrable():
    phase = _phase(required_tests=["x", "hw"], deferrable_tests=["hw"])
    args = BASE.copy()
    args["test_exit_codes"] = {"x": 0}          # hw produced no exit code
    d = evaluate_completion_gate(phase, deferred_tests=["hw"], **args)
    assert d.passed


def test_deferred_test_blocks_if_not_deferrable():
    phase = _phase(required_tests=["x", "hw"])   # hw NOT deferrable
    args = BASE.copy()
    args["test_exit_codes"] = {"x": 0}
    d = evaluate_completion_gate(phase, deferred_tests=["hw"], **args)
    assert not d.passed
    assert any("not deferrable" in r for r in d.reasons)


def test_deferred_test_never_counts_as_pass_via_exit_codes():
    # even a (bogus) 0 exit code for a deferred test must not be needed:
    # the gate skips it explicitly, it is not "passed"
    phase = _phase(required_tests=["hw"], deferrable_tests=["hw"])
    args = BASE.copy()
    args["test_exit_codes"] = {}
    assert evaluate_completion_gate(phase, deferred_tests=["hw"], **args).passed


def test_metric_from_deferred_test_is_deferred_with_it():
    phase = _phase(required_tests=["x"],
                   metrics=[{"name": "m1", "op": "==", "value": 1}])
    args = BASE.copy()
    d = evaluate_completion_gate(phase, deferred_metrics={"m1"}, **args)
    assert d.passed
    d2 = evaluate_completion_gate(phase, **args)
    assert not d2.passed and any("metric missing" in r for r in d2.reasons)
