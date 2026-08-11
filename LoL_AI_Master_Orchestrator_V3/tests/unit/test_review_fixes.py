"""Regression tests for the confirmed adversarial-review findings.

Each test reproduces the attack the reviewer found and asserts the fix
holds. IDs reference the review report.
"""
import json
import threading
import time
from pathlib import Path

import pytest

from orchestrator.gitops import GitOps
from orchestrator.lock import SingleWriterLock, LockHeldError
from tests.util.fixture_project import make_fixture_project, make_engine


# ---------------------------------------------------- CONC-01 lock TOCTOU race
def test_conc01_concurrent_stale_takeover_yields_single_owner(tmp_path):
    import socket
    p = tmp_path / "o.lock"
    stale = json.dumps({"pid": 99999999, "host": socket.gethostname(),
                        "created_utc": "2026-01-01T00:00:00Z"})
    results = {}

    def takeover(name, barrier):
        lock = SingleWriterLock(p)
        barrier.wait()
        try:
            lock.acquire(takeover_stale=True)
            results[name] = "owned"
        except LockHeldError:
            results[name] = "blocked"

    # hammer the race many times; the guard mutex must always yield exactly
    # one owner and one loser (never two owners)
    for _ in range(40):
        p.write_text(stale)
        barrier = threading.Barrier(2)
        a = threading.Thread(target=takeover, args=("A", barrier))
        b = threading.Thread(target=takeover, args=("B", barrier))
        results.clear()
        a.start(); b.start(); a.join(); b.join()
        owners = [k for k, v in results.items() if v == "owned"]
        assert len(owners) == 1, f"expected 1 owner, got {results}"
        SingleWriterLock(p).release() if False else p.unlink(missing_ok=True)


def test_conc01_break_stale_still_refuses_live_lock(tmp_path):
    import os, socket
    p = tmp_path / "o.lock"
    p.write_text(json.dumps({"pid": os.getpid(), "host": socket.gethostname(),
                             "created_utc": "2026-01-01T00:00:00Z"}))
    from orchestrator.lock import LockError
    with pytest.raises(LockError):
        SingleWriterLock(p).break_stale()


# ------------------------------------------- CONC-02 recover from MERGED wedge
def test_conc02_recover_from_merged_finalizes_not_crashes(tmp_path):
    root = make_fixture_project(tmp_path)
    engine, cfg, _ = make_engine(root)
    # drive a real phase to MERGED first
    assert engine.run_phase("00").status == "MERGED"
    # simulate a crash that left lifecycle at MERGED with the merge on main
    sp = root / "state" / "project_state.json"
    st = json.loads(sp.read_text())
    main_head = GitOps(root).rev_parse("main")
    st["lifecycle"] = "MERGED"
    st["phase_id"] = "00"
    st["candidate_commit"] = main_head
    st["merged_commit"] = main_head
    sp.write_text(json.dumps(st))
    engine2, _, _ = make_engine(root)
    result = engine2.recover()           # must NOT raise
    assert result.status in ("RECOVERED", "READY"), result.reasons
    assert json.loads(sp.read_text())["lifecycle"] == "READY"


def test_conc02_recover_never_crashes_on_any_lifecycle(tmp_path):
    for lc in ("BUILDING", "TESTING", "REVIEWING", "GATE_EVALUATION",
               "HUMAN_GATE", "PASSED", "BLOCKED"):
        root = make_fixture_project(tmp_path / lc)
        engine, cfg, _ = make_engine(root)
        sp = root / "state" / "project_state.json"
        st = json.loads(sp.read_text())
        st["lifecycle"] = lc
        sp.write_text(json.dumps(st))
        result = engine.recover()        # never a traceback
        assert result.status in ("RECOVERED", "READY", "BLOCKED")


# --------------------------- CONC-03 crash between merge and MERGED state write
def test_conc03_crash_after_merge_before_state_is_reconciled(tmp_path):
    root = make_fixture_project(tmp_path)
    engine, cfg, _ = make_engine(root)
    assert engine.run_phase("00").status == "MERGED"
    main_head = GitOps(root).rev_parse("main")
    # simulate: merge landed on main, but engine died BEFORE writing MERGED —
    # lifecycle still says PASSED, candidate == current main HEAD
    sp = root / "state" / "project_state.json"
    st = json.loads(sp.read_text())
    st["lifecycle"] = "PASSED"
    st["phase_id"] = "00"
    st["candidate_commit"] = main_head
    sp.write_text(json.dumps(st))
    result = make_engine(root)[0].recover()
    assert result.status == "RECOVERED"
    st2 = json.loads(sp.read_text())
    assert st2["lifecycle"] == "READY" and st2["phase_id"] == "01"


# ------------------------------------------- CONC-04 recover reload-after-lock
def test_conc04_recover_reads_state_after_acquiring_lock(tmp_path):
    # recover must operate on the CURRENT on-disk state, not a stale snapshot.
    root = make_fixture_project(tmp_path)
    engine, cfg, _ = make_engine(root)
    sp = root / "state" / "project_state.json"
    st = json.loads(sp.read_text())
    st["lifecycle"] = "BUILDING"
    st["sequence"] = 5
    sp.write_text(json.dumps(st))
    result = engine.recover()
    assert result.status == "RECOVERED"
    final = json.loads(sp.read_text())
    assert final["lifecycle"] == "READY"
    assert final["sequence"] > 5          # advanced from the on-disk sequence


# ------------------------------- RW-INJ-02 forged acceptance via escaped write
def test_rwinj02_reviewer_forged_acceptance_is_detected(tmp_path):
    from orchestrator.adapters.fake import FakeAdapter
    root = make_fixture_project(tmp_path, max_fix_cycles=0)
    forge = str((root / "reports" / "acceptance" / "forged.json").resolve())
    fake_script = Path(__file__).resolve().parents[2] / "tests" / "fakes" / "fake_agent.py"
    reviewer = FakeAdapter(fake_script, provider="fake-codex",
                           mode="forge-acceptance",
                           extra_args=["--forge-path", forge], timeout_s=60)
    engine, cfg, _ = make_engine(root, builder_mode="write-secret", reviewer=reviewer)
    result = engine.run_phase("00")
    assert result.status == "BLOCKED"
    assert any("trust store" in r for r in result.reasons)
    # the gate must NOT have been unblocked by the forged record
    assert json.loads((root / "state" / "project_state.json").read_text())[
        "lifecycle"] == "BLOCKED"


# ---------------------------- GIT-INTEGRITY-01 rename masks source deletion
def test_gitint01_rename_exposes_both_sides(tmp_path):
    root = make_fixture_project(tmp_path)
    git = GitOps(root, main_branch="main")
    base = git.rev_parse("main")
    wt = git.create_worktree(root / ".orchestrator" / "worktrees" / "r1",
                             "candidate/r1", base)
    # "rename" an immutable file (state/project_state.json) out to src/ —
    # a rename-detecting diff would hide the deletion of the immutable source
    (wt / "src").mkdir(exist_ok=True)
    src = wt / "state" / "project_state.json"
    dst = wt / "src" / "relocated.json"
    dst.write_text(src.read_text())
    src.unlink()
    changed = git.changed_paths(wt, base)
    assert "state/project_state.json" in changed   # deletion of source visible
    assert "src/relocated.json" in changed
    git.remove_worktree(wt, branch="candidate/r1")


def test_gitint01_engine_blocks_immutable_relocation(tmp_path):
    # end-to-end: a builder that deletes an immutable file (via rename) blocks
    from orchestrator.adapters.fake import FakeAdapter
    fake_script = Path(__file__).resolve().parents[2] / "tests" / "fakes" / "fake_agent.py"
    root = make_fixture_project(tmp_path)
    builder = FakeAdapter(fake_script, provider="fake-claude",
                          mode="write-state", timeout_s=60)
    engine, _, _ = make_engine(root, builder=builder)
    r = engine.run_phase("00")
    assert r.status == "BLOCKED"
