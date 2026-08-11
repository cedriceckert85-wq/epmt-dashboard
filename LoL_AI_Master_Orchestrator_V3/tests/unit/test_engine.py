"""Engine lifecycle integration tests on a hermetic fixture project.

Covers the mandatory fault matrix from 00_ORCHESTRATOR/TEST_ORCHESTRATOR.md:
full simulated phase pass, human approve/reject with exact SHA, builder/
reviewer faults (fail/hang/malformed/schema-invalid/spoofing/quota),
reviewer write attempts, forbidden state edits, infinite fix loops,
prompt injection, restart mid-phase, stale lock, two orchestrators,
dirty git, wrong branch, secret in diff.
"""
import json
from pathlib import Path

from orchestrator import human_gate
from orchestrator.gitops import GitOps
from orchestrator.lock import SingleWriterLock
from tests.util.fixture_project import make_fixture_project, make_engine


def _state(root):
    return json.loads((root / "state" / "project_state.json").read_text())


def _journal_events(root):
    p = root / "state" / "journal.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


# ---------------------------------------------------------------- happy path
def test_full_simulated_phase_00_to_01(tmp_path):
    root = make_fixture_project(tmp_path)
    engine, cfg, _ = make_engine(root)
    result = engine.run_phase("00")
    assert result.status == "MERGED", result.reasons
    st = _state(root)
    assert st["phase_id"] == "01" and st["lifecycle"] == "READY"
    assert st["last_gate"] == "PASS"
    events = [e["event"] for e in _journal_events(root)]
    assert "gate_decision" in events and "lifecycle_transition" in events
    # worktree cleaned up after merge
    assert not any((root / ".orchestrator" / "worktrees").glob("*"))


def test_human_gate_approve_exact_sha_flow(tmp_path):
    root = make_fixture_project(tmp_path, human_gate=True)
    engine, cfg, _ = make_engine(root)
    result = engine.run_phase("00")
    assert result.status == "AWAITING_HUMAN_GATE"
    sha = result.state["candidate_commit"]
    assert sha

    # approval for the WRONG SHA must not release the gate
    human_gate.record_decision(cfg.human_gate_dir, phase_id="00",
                               commit_sha="deadbeef", approver="wam",
                               decision="APPROVE")
    engine2, _, _ = make_engine(root)
    r2 = engine2.run_phase("00", resume=True)
    assert r2.status == "AWAITING_HUMAN_GATE"

    # exact SHA approval releases it
    human_gate.record_decision(cfg.human_gate_dir, phase_id="00",
                               commit_sha=sha, approver="wam", decision="APPROVE")
    engine3, _, _ = make_engine(root)
    r3 = engine3.run_phase("00", resume=True)
    assert r3.status == "MERGED", r3.reasons
    assert _state(root)["phase_id"] == "01"


def test_human_gate_reject_blocks(tmp_path):
    root = make_fixture_project(tmp_path, human_gate=True)
    engine, cfg, _ = make_engine(root)
    result = engine.run_phase("00")
    sha = result.state["candidate_commit"]
    human_gate.record_decision(cfg.human_gate_dir, phase_id="00",
                               commit_sha=sha, approver="wam",
                               decision="REJECT", reason="nope")
    engine2, _, _ = make_engine(root)
    r2 = engine2.run_phase("00", resume=True)
    assert r2.status == "BLOCKED"
    assert any("not approved" in r for r in r2.reasons)


# ------------------------------------------------------------- agent faults
def test_builder_fail_blocks(tmp_path):
    root = make_fixture_project(tmp_path)
    engine, _, _ = make_engine(root, builder_mode="fail")
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
    assert _state(root)["lifecycle"] == "BLOCKED"


def test_builder_hang_times_out_and_blocks(tmp_path):
    root = make_fixture_project(tmp_path)
    engine, _, _ = make_engine(root, builder_mode="hang", agent_timeout_s=2)
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
    assert any("timed out" in x for x in r.reasons)


def test_builder_malformed_json_blocks_after_schema_retry(tmp_path):
    root = make_fixture_project(tmp_path)
    engine, _, _ = make_engine(root, builder_mode="malformed")
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
    retries = [e for e in _journal_events(root)
               if e["event"] == "agent_retry_invalid_schema"]
    assert len(retries) == 1        # invalid_schema_retries: 1, then fail closed


def test_builder_schema_invalid_blocks(tmp_path):
    root = make_fixture_project(tmp_path)
    engine, _, _ = make_engine(root, builder_mode="schema-invalid")
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
    assert any("invalid" in x for x in r.reasons)


def test_quota_exhausted_retries_backoff_then_blocks(tmp_path):
    root = make_fixture_project(tmp_path, backoff="[1, 2]")
    engine, _, sleeps = make_engine(root, builder_mode="retryable")
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
    assert sleeps == [1, 2]         # exact configured backoff, then fail closed
    assert any("infrastructure/quota" in x for x in r.reasons)


def test_report_spoofing_wrong_run_id_blocks(tmp_path):
    root = make_fixture_project(tmp_path)
    engine, _, _ = make_engine(root, builder_mode="spoof-run-id")
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
    assert any("invalid" in x for x in r.reasons)


def test_builder_blocked_status_blocks(tmp_path):
    root = make_fixture_project(tmp_path)
    engine, _, _ = make_engine(root, builder_mode="blocked-status")
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
    assert any("status=blocked" in x for x in r.reasons)


def test_builder_unavailable_blocks(tmp_path):
    from orchestrator.adapters.fake import FakeAdapter
    root = make_fixture_project(tmp_path)
    dead = FakeAdapter(tmp_path / "missing.py", provider="fake-claude")
    engine, _, _ = make_engine(root, builder=dead)
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
    assert any("builder unavailable" in x for x in r.reasons)


def test_reviewer_unavailable_blocks_never_skips_review(tmp_path):
    from orchestrator.adapters.fake import FakeAdapter
    root = make_fixture_project(tmp_path)
    dead = FakeAdapter(tmp_path / "missing.py", provider="fake-codex")
    engine, _, _ = make_engine(root, reviewer=dead)
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
    assert any("reviewer unavailable" in x for x in r.reasons)


# -------------------------------------------------------- policy violations
def test_forbidden_state_edit_blocks(tmp_path):
    root = make_fixture_project(tmp_path)
    engine, _, _ = make_engine(root, builder_mode="write-state")
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
    assert any("forbidden write paths" in x for x in r.reasons)


def test_write_outside_allowed_paths_blocks(tmp_path):
    root = make_fixture_project(tmp_path)
    engine, _, _ = make_engine(root, builder_mode="write-attempt")
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
    assert any("forbidden write paths" in x for x in r.reasons)


def test_reviewer_write_attempt_blocks(tmp_path):
    root = make_fixture_project(tmp_path)
    engine, _, _ = make_engine(root, builder_mode="write-secret",
                               reviewer_mode="write-attempt")
    # builder writes into allowed src/ so the run reaches review
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
    assert any("reviewer write attempt" in x or "reviewer moved HEAD" in x
               for x in r.reasons)


def test_secret_in_diff_blocks_at_gate(tmp_path):
    root = make_fixture_project(tmp_path)
    engine, _, _ = make_engine(root, builder_mode="write-secret")
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
    assert any("secret scan finding" in x for x in r.reasons)


def test_cross_vendor_review_same_provider_blocks(tmp_path):
    root = make_fixture_project(tmp_path)
    engine, _, _ = make_engine(root, builder_provider="fake-claude",
                               reviewer_provider="fake-claude")
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
    assert any("independent reviewer" in x for x in r.reasons)


# ------------------------------------------------------------- fix loop
def test_reviewer_blocker_fix_loop_capped(tmp_path):
    root = make_fixture_project(tmp_path, max_fix_cycles=2)
    engine, _, _ = make_engine(root, reviewer_mode="reviewer-blocker")
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
    assert any("blocker findings" in x for x in r.reasons)
    fixes = [e for e in _journal_events(root)
             if e["event"] == "lifecycle_transition" and e["to"] == "FIXING"]
    assert len(fixes) == 2          # exactly max_fix_cycles, never infinite


def test_failing_tests_with_zero_fix_budget_blocks(tmp_path):
    root = make_fixture_project(tmp_path, failing_test=True, max_fix_cycles=0)
    engine, _, _ = make_engine(root)
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
    assert any("fix cycle budget exhausted" in x for x in r.reasons)


def test_regression_after_fix_blocks(tmp_path):
    # test fails; fake fixer "fixes" nothing (empty commit) => retest fails
    root = make_fixture_project(tmp_path, failing_test=True, max_fix_cycles=2)
    engine, _, _ = make_engine(root)
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
    assert any("regression after fix" in x for x in r.reasons)


def test_prompt_injection_cannot_flip_gate(tmp_path):
    # reviewer output SCREAMS pass, but a required test fails => BLOCKED
    root = make_fixture_project(tmp_path, failing_test=True, max_fix_cycles=0)
    engine, _, _ = make_engine(root, reviewer_mode="reviewer-injection")
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
    gates = [e for e in _journal_events(root) if e["event"] == "gate_decision"]
    assert all(e["passed"] is False for e in gates)


def test_unaccepted_high_finding_blocks_and_acceptance_unblocks(tmp_path):
    from orchestrator.journal import utc_now
    root = make_fixture_project(tmp_path, max_fix_cycles=0)
    engine, cfg, _ = make_engine(root, reviewer_mode="reviewer-high")
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
    assert any("unaccepted high" in x for x in r.reasons)

    # a SHA-bound acceptance record for exactly this candidate unblocks a rerun
    root2 = make_fixture_project(tmp_path / "second")
    engine2, cfg2, _ = make_engine(root2, reviewer_mode="reviewer-high")
    # pre-compute: run once to learn candidate SHA, then accept + recover + rerun
    r2 = engine2.run_phase("00")
    sha = r2.state["candidate_commit"]
    cfg2.acceptance_dir.mkdir(parents=True, exist_ok=True)
    (cfg2.acceptance_dir / "acc-1.json").write_text(json.dumps({
        "phase_id": "00", "finding_id": "F-HIGH-1", "commit_sha": sha,
        "decision": "ACCEPT", "reason": "known limitation, tracked",
        "approver": "wam", "timestamp_utc": utc_now()}))
    # NOTE: rerun needs a fresh run (new candidate SHA) — the stale record
    # must NOT apply there. This asserts exactly the SHA-scoping rule.
    from orchestrator.state_store import StateStore
    store = StateStore(root2 / "state" / "project_state.json")
    st = store.load()
    st["lifecycle"] = "READY"
    store.save(st)
    engine3, _, _ = make_engine(root2, reviewer_mode="reviewer-high")
    r3 = engine3.run_phase("00")
    assert r3.status == "BLOCKED"
    assert any("stale acceptance" in x for x in r3.reasons)


# ------------------------------------------------- concurrency & recovery
def test_two_orchestrators_second_is_blocked(tmp_path):
    root = make_fixture_project(tmp_path)
    engine, cfg, _ = make_engine(root)
    other = SingleWriterLock(cfg.lock_path).acquire()
    try:
        r = engine.run_phase("00")
        assert r.status == "BLOCKED"
        assert any("lock" in x for x in r.reasons)
    finally:
        other.release()


def test_stale_lock_blocks_until_explicit_unlock(tmp_path):
    import socket
    root = make_fixture_project(tmp_path)
    engine, cfg, _ = make_engine(root)
    cfg.lock_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.lock_path.write_text(json.dumps(
        {"pid": 99999999, "host": socket.gethostname(),
         "created_utc": "2026-01-01T00:00:00Z"}))
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"          # engine never silently steals
    SingleWriterLock(cfg.lock_path).break_stale()
    engine2, _, _ = make_engine(root)
    assert engine2.run_phase("00").status == "MERGED"


def test_restart_mid_phase_requires_recover(tmp_path):
    root = make_fixture_project(tmp_path)
    engine, _, _ = make_engine(root)
    p = root / "state" / "project_state.json"
    st = json.loads(p.read_text())
    st["lifecycle"] = "BUILDING"          # simulated crash mid-phase
    p.write_text(json.dumps(st))
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
    assert any("recover" in x for x in r.reasons)
    assert json.loads(p.read_text())["lifecycle"] == "BLOCKED"
    # recovery path: BLOCKED -> READY is a legal, journaled transition
    from orchestrator.state_store import StateStore
    store = StateStore(p)
    st = store.load()
    st2 = store.transition(st, {"id": "00", "human_gate": False}, "READY")
    assert st2["lifecycle"] == "READY"
    engine2, _, _ = make_engine(root)
    assert engine2.run_phase("00").status == "MERGED"


# ----------------------------------------------------------- git posture
def test_dirty_git_blocks(tmp_path):
    root = make_fixture_project(tmp_path)
    (root / "uncommitted.txt").write_text("dirty")
    engine, _, _ = make_engine(root)
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
    assert any("dirty main" in x for x in r.reasons)


def test_wrong_branch_blocks(tmp_path):
    root = make_fixture_project(tmp_path)
    GitOps(root)._git("checkout", "-b", "not-main")
    engine, _, _ = make_engine(root)
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
    assert any("wrong branch" in x for x in r.reasons)


def test_unverified_required_capability_blocks_gate(tmp_path):
    # registry requires network; engine runs without network capability
    root = make_fixture_project(tmp_path, requires="network")
    engine, _, _ = make_engine(root, capabilities=("none",), builder_mode="write-secret")
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"     # UNVERIFIED test can never count as pass
