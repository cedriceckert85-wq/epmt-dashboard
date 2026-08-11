"""Seeded state-transition / fault-injection soak harness (Phase 00).

Fuzzes the REAL control-plane logic (lifecycle legality, completion gate,
acceptance scoping, atomic state persistence) with deterministic,
seed-driven fault injection and checks invariants every iteration:

  I1  an illegal lifecycle transition is never accepted
  I2  the completion gate never passes with a failing/missing required
      test, a blocker finding, a secret hit, forbidden changes, a dirty
      main, or any SHA mismatch (tested/reviewed/approved != candidate)
  I3  the gate passes when — and only when — every input is clean
  I4  the canonical state file remains valid JSON after every atomic
      write (simulated-crash tolerant)
  I5  stale (wrong-SHA) acceptance records never unblock a high finding

Usage (test_registry: soak_8h_pipeline):
  python tests/soak/run_8h_soak.py --hours 8 --json out.json
  python tests/soak/run_8h_soak.py --iterations 2000 --json out.json  (CI)
"""
import argparse, json, random, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from orchestrator import gates, acceptance                    # noqa: E402
from orchestrator.gates import LEGAL_TRANSITIONS              # noqa: E402
from orchestrator.state_store import StateStore, StateError   # noqa: E402
from orchestrator.models import Lifecycle                     # noqa: E402

PHASE = {"id": "00", "human_gate": True, "required_tests": ["t1", "t2"],
         "gate": {"max_blockers": 0, "max_unaccepted_high": 0}, "metrics": []}
ALL_STATES = list(LEGAL_TRANSITIONS.keys())


def fresh_state():
    return {"schema_version": 2, "run_id": "soak", "sequence": 0, "phase_id": "00",
            "lifecycle": "READY", "attempt": 0, "builder": None,
            "candidate_commit": None, "test_evidence_id": None,
            "review_evidence_id": None, "human_gate_required": True,
            "last_gate": None, "reviewer_provider": None, "builder_provider": None,
            "approved_commit": None, "reviewed_commit": None, "tested_commit": None,
            "merged_commit": None, "human_approval_id": None}


def iteration(rng, store, counters):
    # --- I1: random transition legality fuzz -----------------------------
    frm = rng.choice(ALL_STATES)
    to = rng.choice(ALL_STATES + ["NONSENSE"])
    d = gates.validate_lifecycle_transition(PHASE, lifecycle_from=frm, lifecycle_to=to)
    legal = to in LEGAL_TRANSITIONS.get(frm, set())
    if to == "PASSED" and frm != "HUMAN_GATE":
        legal = False  # human-gate phase must pass through HUMAN_GATE
    if d.passed != legal:
        counters["invariant_violations"] += 1
        counters["examples"].append(f"I1 {frm}->{to}: passed={d.passed} legal={legal}")

    # --- I2/I3/I5: completion-gate fuzz ----------------------------------
    candidate = f"sha-{rng.randrange(1 << 30):08x}"
    faults = set()
    test_exit_codes = {"t1": 0, "t2": 0}
    if rng.random() < 0.30:
        test_exit_codes[rng.choice(["t1", "t2"])] = rng.choice([1, 2, None])
        faults.add("failing_test")
    findings = []
    if rng.random() < 0.25:
        findings.append({"id": "B1", "severity": "blocker", "title": "soak blocker"})
        faults.add("blocker")
    acceptance_records = []
    if rng.random() < 0.30:
        findings.append({"id": "H1", "severity": "high", "title": "soak high"})
        roll = rng.random()
        if roll < 0.34:
            faults.add("unaccepted_high")                       # no record at all
        elif roll < 0.67:                                       # stale SHA record (I5)
            acceptance_records.append({
                "phase_id": "00", "finding_id": "H1", "commit_sha": "sha-stale",
                "decision": "ACCEPT", "reason": "stale", "approver": "soak",
                "timestamp_utc": "2026-01-01T00:00:00Z"})
            faults.add("unaccepted_high")
        else:                                                   # valid record
            acceptance_records.append({
                "phase_id": "00", "finding_id": "H1", "commit_sha": candidate,
                "decision": "ACCEPT", "reason": "accepted in soak", "approver": "soak",
                "timestamp_utc": "2026-01-01T00:00:00Z"})
    forbidden = rng.random() < 0.10
    if forbidden:
        faults.add("forbidden_changes")
    secrets = [{"pattern": "soak"}] if rng.random() < 0.10 else []
    if secrets:
        faults.add("secret")
    clean_main = rng.random() > 0.10
    if not clean_main:
        faults.add("dirty_main")
    tested = candidate if rng.random() > 0.10 else "sha-other"
    reviewed = candidate if rng.random() > 0.10 else "sha-other"
    if tested != candidate:
        faults.add("sha_mismatch")
    if reviewed != candidate:
        faults.add("sha_mismatch")
    approval_sha = candidate if rng.random() > 0.15 else "sha-other"
    approval = {"decision": rng.choice(["APPROVE", "APPROVE", "REJECT"]),
                "commit_sha": approval_sha, "approval_id": "soak"}
    if approval["decision"] != "APPROVE" or approval_sha != candidate:
        faults.add("approval_invalid")
    approved_commit = approval_sha if approval["decision"] == "APPROVE" else None

    d = gates.evaluate_completion_gate(
        PHASE, test_exit_codes=test_exit_codes, metrics={},
        review_findings=findings, forbidden_changes=forbidden,
        secret_findings=secrets, clean_main=clean_main,
        candidate_commit=candidate, tested_commit=tested,
        reviewed_commit=reviewed, approved_commit=approved_commit,
        human_approval_record=approval, acceptance_records=acceptance_records)
    should_pass = not faults
    if d.passed and not should_pass:
        counters["gate_false_passes"] += 1
        counters["examples"].append(f"I2 gate passed despite {sorted(faults)}")
    if should_pass and not d.passed:
        counters["gate_false_blocks"] += 1
        counters["examples"].append(f"I3 gate blocked clean run: {d.reasons}")

    # --- I4: atomic state persistence fuzz -------------------------------
    st = fresh_state()
    st["lifecycle"] = rng.choice([s for s in ALL_STATES])
    st["sequence"] = rng.randrange(1000)
    store.save(st)
    try:
        loaded = store.load()
        if loaded["sequence"] != st["sequence"] + 1:
            counters["state_corruptions"] += 1
            counters["examples"].append("I4 sequence not incremented")
    except StateError as e:
        counters["state_corruptions"] += 1
        counters["examples"].append(f"I4 reload failed: {e}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--hours", type=float, default=None)
    p.add_argument("--iterations", type=int, default=None)
    p.add_argument("--seed", type=int, default=20260811)
    p.add_argument("--json", dest="json_out", default=None)
    a = p.parse_args()

    if a.iterations is None and a.hours is None:
        a.iterations = 2000
    rng = random.Random(a.seed)
    deadline = time.monotonic() + a.hours * 3600 if a.hours else None

    counters = {"soak_iterations": 0, "invariant_violations": 0,
                "gate_false_passes": 0, "gate_false_blocks": 0,
                "state_corruptions": 0, "examples": []}
    with tempfile.TemporaryDirectory(prefix="soak-state-") as td:
        store = StateStore(Path(td) / "project_state.json")
        while True:
            iteration(rng, store, counters)
            counters["soak_iterations"] += 1
            if a.iterations is not None and counters["soak_iterations"] >= a.iterations:
                break
            if deadline is not None and time.monotonic() >= deadline:
                break

    examples = counters.pop("examples")[:20]
    violations = (counters["invariant_violations"] + counters["gate_false_passes"] +
                  counters["gate_false_blocks"] + counters["state_corruptions"])
    out = {"metrics": dict(counters), "seed": a.seed, "examples": examples}
    if a.json_out:
        Path(a.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json_out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out if violations else {"metrics": counters}, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
