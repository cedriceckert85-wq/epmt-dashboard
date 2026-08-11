from .models import GateDecision
from . import acceptance

OPS={"<=":lambda a,b:a<=b,"<":lambda a,b:a<b,">=":lambda a,b:a>=b,">":lambda a,b:a>b,"==":lambda a,b:a==b}

LEGAL_TRANSITIONS = {
    "READY":{"BUILDING","BLOCKED"},
    "BUILDING":{"TESTING","BLOCKED"},
    "TESTING":{"CHECKPOINTED","FIXING","BLOCKED"},
    "CHECKPOINTED":{"REVIEWING","BLOCKED"},
    "REVIEWING":{"GATE_EVALUATION","FIXING","BLOCKED"},
    "FIXING":{"RETESTING","BLOCKED"},
    "RETESTING":{"CHECKPOINTED","BLOCKED"},
    "GATE_EVALUATION":{"HUMAN_GATE","PASSED","BLOCKED"},
    "HUMAN_GATE":{"PASSED","BLOCKED"},
    "PASSED":{"MERGED","BLOCKED"},
    "MERGED":{"READY"},
    "BLOCKED":{"READY","FIXING"},
}

def _finding_id(f):
    fid = f.get("id") or f.get("finding_id")
    return str(fid) if fid else None


def validate_lifecycle_transition(phase, *, lifecycle_from, lifecycle_to):
    """Pure transition legality. No SHAs, no tests, no approvals.
    Safe to call for EVERY transition (BUILDING->TESTING etc.)."""
    reasons=[]
    if lifecycle_to not in LEGAL_TRANSITIONS.get(lifecycle_from,set()):
        reasons.append(f"illegal lifecycle transition: {lifecycle_from}->{lifecycle_to}")
    if bool(phase.get("human_gate",False)) and lifecycle_to=="PASSED" and lifecycle_from!="HUMAN_GATE":
        reasons.append("human-gate phase must transition HUMAN_GATE->PASSED")
    return GateDecision(not reasons, tuple(reasons), bool(phase.get("human_gate",False)))


def validate_merge_commit(*, candidate_commit, merged_commit):
    """Called at PASSED->MERGED."""
    reasons=[]
    if not candidate_commit:
        reasons.append("candidate commit missing")
    if merged_commit != candidate_commit:
        reasons.append("merged SHA != candidate SHA")
    return GateDecision(not reasons, tuple(reasons), False)


def evaluate_completion_gate(
    phase, *,
    test_exit_codes,
    metrics,
    review_findings,
    forbidden_changes,
    secret_findings,
    clean_main,
    candidate_commit,
    tested_commit,
    reviewed_commit,
    approved_commit,
    human_approval_record,
    acceptance_records,
):
    """Decides PASS for a phase candidate. Called only when leaving
    GATE_EVALUATION/HUMAN_GATE towards PASSED - transition legality itself
    is validate_lifecycle_transition().

    acceptance_records are RAW records (e.g. loaded from
    reports/acceptance/). The gate validates them itself against this
    phase and the exact candidate SHA - a wrongly constructed id set can
    no longer bypass the gate."""
    reasons=[]

    for test in phase.get("required_tests",[]):
        if test_exit_codes.get(test) != 0:
            reasons.append(f"required test failed/missing: {test}")

    for rule in phase.get("metrics",[]):
        name=rule["name"]
        if name not in metrics:
            reasons.append(f"required metric missing: {name}")
        elif rule["op"] not in OPS or not OPS[rule["op"]](metrics[name], rule["value"]):
            reasons.append(f"metric {name} violates threshold")

    gate_cfg=phase.get("gate",{})
    max_blockers=int(gate_cfg.get("max_blockers",0))
    max_unaccepted_high=int(gate_cfg.get("max_unaccepted_high",0))

    accepted, acc_reasons = acceptance.accepted_ids(
        acceptance_records,
        phase_id=str(phase.get("id")),
        candidate_commit=candidate_commit,
    )
    # invalid acceptance records are reported, never silently ignored
    reasons.extend(acc_reasons)

    blockers=sum(1 for f in review_findings if f.get("severity")=="blocker")
    unaccepted_high=0
    for f in review_findings:
        if f.get("severity")=="high":
            fid=_finding_id(f)
            if fid is None or fid not in accepted:
                unaccepted_high += 1

    if blockers > max_blockers:
        reasons.append(f"blocker findings: {blockers}>{max_blockers}")
    if unaccepted_high > max_unaccepted_high:
        reasons.append(f"unaccepted high findings: {unaccepted_high}>{max_unaccepted_high}")

    if forbidden_changes:
        reasons.append("forbidden file changes")
    if secret_findings:
        reasons.append("secret scan finding")
    if not clean_main:
        reasons.append("main branch not clean")

    if not candidate_commit:
        reasons.append("candidate commit missing")
    if tested_commit != candidate_commit:
        reasons.append("tested SHA != candidate SHA")
    if reviewed_commit != candidate_commit:
        reasons.append("reviewed SHA != candidate SHA")

    needs_human=bool(phase.get("human_gate",False))
    if needs_human:
        if not human_approval_record:
            reasons.append("human approval record missing")
        else:
            if human_approval_record.get("decision")!="APPROVE":
                reasons.append("human gate not approved")
            if human_approval_record.get("commit_sha")!=candidate_commit:
                reasons.append("human approval SHA mismatch")
            if approved_commit!=candidate_commit:
                reasons.append("approved SHA != candidate SHA")

    return GateDecision(not reasons, tuple(reasons), needs_human)
