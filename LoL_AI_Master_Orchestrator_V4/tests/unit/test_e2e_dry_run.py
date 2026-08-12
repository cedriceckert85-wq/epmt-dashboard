"""End-to-end dry run of the one-shot engine with fake agents in a tmp repo:
phases advance READY->...->MERGED, gates enforce, fix loops cap, resume works.
"""
import json
import sys
import textwrap

import pytest

from orchestrator import human_gate
from orchestrator.config import load_config
from orchestrator.gitops import GitRepo
from orchestrator.phase_loop import PhaseEngine
from orchestrator.state import StateStore

PY = sys.executable

CONFIG = """
version: 4
project:
  name: fixture
  main_branch: main
  canonical_state: state/project_state.json
  current_task: state/current_task.json
  journal: state/journal.jsonl
  artifact_root: .orchestrator/artifacts
  lock_file: state/orchestrator.lock
execution:
  gate_mode: auto
agents:
  claude: {executable: claude, timeout_s: 60, max_retries: 1}
  codex: {executable: codex, timeout_s: 60, max_retries: 1}
retry:
  infrastructure_backoff_s: [0]
  invalid_schema_retries: 1
  max_fix_cycles: 2
security:
  immutable_paths: [.git, .venv, .orchestrator, state, schemas, phases, prompts,
                    orchestrator, ORCHESTRATOR_CONFIG.yaml, PROJECT_STATE.md,
                    CURRENT_TASK.md, reports/human-gates, reports/acceptance,
                    test_registry.yaml]
git: {require_clean_main: true, merge_strategy: ff-only, agents_may_commit: false}
human_gates: {record_dir: reports/human-gates}
acceptance: {record_dir: reports/acceptance, schema: schemas/finding_acceptance.schema.json}
test_registry: test_registry.yaml
gate_policy: {require_sha_invariant: true}
"""

GITIGNORE = """
.orchestrator/
state/
PROJECT_STATE.md
CURRENT_TASK.md
reports/human-gates/
reports/acceptance/
reports/agent_result.json
__pycache__/
"""


def make_project(tmp_path, *, gate_mode="auto"):
    root = tmp_path / "proj"
    root.mkdir()
    cfg_text = CONFIG.replace("gate_mode: auto", f"gate_mode: {gate_mode}")
    (root / "ORCHESTRATOR_CONFIG.yaml").write_text(cfg_text, encoding="utf-8")
    (root / ".gitignore").write_text(GITIGNORE, encoding="utf-8")

    (root / "phases").mkdir()
    (root / "phases" / "phase-00.yaml").write_text(textwrap.dedent("""\
        id: '00'
        name: Self-Check
        builder: claude
        reviewer: codex
        agentless: true
        cross_vendor_review: false
        human_gate: true
        required_tests: [p00_t]
        allowed_write_paths: [reports/]
        gate: {max_blockers: 0, max_unaccepted_high: 0}
        """), encoding="utf-8")
    for pid, human in (("01", "true"), ("02", "false")):
        (root / "phases" / f"phase-{pid}.yaml").write_text(textwrap.dedent(f"""\
            id: '{pid}'
            name: Fixture {pid}
            builder: {'claude' if pid == '01' else 'codex'}
            reviewer: {'codex' if pid == '01' else 'claude'}
            cross_vendor_review: true
            human_gate: {human}
            required_tests: [p{pid}_t]
            allowed_write_paths: [src/, tests/, docs/, reports/]
            gate: {{max_blockers: 0, max_unaccepted_high: 0}}
            """), encoding="utf-8")

    ok_cmd = f'"{PY}" -c "print(1)"'
    reg = {"tests": {f"p{pid}_t": {
        "command": ok_cmd, "cwd": ".", "timeout_s": 60, "requires": ["none"],
        "parser": "exit_code", "evidence": f"ev/{pid}.txt",
        "implemented_in_phase": pid} for pid in ("00", "01", "02")}}
    import yaml
    (root / "test_registry.yaml").write_text(yaml.safe_dump(reg), encoding="utf-8")

    (root / "prompts" / "build").mkdir(parents=True)
    (root / "prompts" / "fix").mkdir(parents=True)
    for pid in ("01", "02"):
        (root / "prompts" / "build" / f"phase-{pid}.md").write_text(
            f"# build {pid}\n", encoding="utf-8")
    (root / "prompts" / "fix" / "verified-findings-fix.md").write_text(
        "# fix\n", encoding="utf-8")
    (root / "reports").mkdir()
    (root / "reports" / ".gitkeep").write_text("", encoding="utf-8")

    repo = GitRepo(root)
    repo.init("main")
    repo.add_all_and_commit("baseline")

    cfg = load_config(root)
    store = StateStore(cfg.state_file, cfg.journal_file)
    store.init_if_missing()
    return cfg, store, repo


def make_engine(cfg, store, repo, **kw):
    return PhaseEngine(cfg, store, repo, dry_run=True, log=lambda *a: None, **kw)


def set_fake_control(cfg, mapping):
    d = cfg.root / ".orchestrator"
    d.mkdir(exist_ok=True)
    (d / "fake_control.json").write_text(json.dumps(mapping), encoding="utf-8")


def test_full_run_merges_all_phases(tmp_path):
    cfg, store, repo = make_project(tmp_path)
    status, st = make_engine(cfg, store, repo).run(
        phases=["00", "01", "02"], capabilities={})
    assert status == "done", st.get("blocked_reason")
    hist = st["phase_history"]
    assert set(hist) == {"00", "01", "02"}
    assert all(h["gate"] == "PASS" for h in hist.values())
    repo.checkout("main")
    assert repo.head_sha() == hist["02"]["merged_commit"]
    assert (cfg.root / "src" / "phase_01_builder.txt").exists()
    # auto human-gate record exists for the human-gated phases, SHA-bound
    rec = human_gate.load_approval(cfg.root / "reports/human-gates", "01",
                                   hist["01"]["merged_commit"])
    assert rec and rec["decision"] == "APPROVE" and rec["mode"] == "auto"


def test_resume_continues_where_it_stopped(tmp_path):
    cfg, store, repo = make_project(tmp_path)
    status, st = make_engine(cfg, store, repo).run(phases=["00", "01"], capabilities={})
    assert status == "done" and set(st["phase_history"]) == {"00", "01"}
    status, st = make_engine(cfg, store, repo).run(
        phases=["00", "01", "02"], capabilities={})
    assert status == "done"
    assert set(st["phase_history"]) == {"00", "01", "02"}


def test_blocker_findings_exhaust_fix_cycles_then_block(tmp_path):
    cfg, store, repo = make_project(tmp_path)
    set_fake_control(cfg, {"02:reviewer": {"findings": [
        {"id": "B1", "severity": "blocker", "title": "broken"}]}})
    status, st = make_engine(cfg, store, repo).run(
        phases=["00", "01", "02"], capabilities={})
    assert status == "blocked"
    assert st["phase_id"] == "02" and st["lifecycle"] == "BLOCKED"
    assert "max fix cycles" in st["blocked_reason"]
    assert int(st["fix_cycles"]) == 2
    # phases 00/01 stayed merged
    assert set(st["phase_history"]) == {"00", "01"}


def test_agent_tamper_with_protected_runtime_blocks(tmp_path):
    cfg, store, repo = make_project(tmp_path)
    set_fake_control(cfg, {"01:builder": {"write_forbidden": True}})
    status, st = make_engine(cfg, store, repo).run(
        phases=["00", "01"], capabilities={})
    assert status == "blocked"
    assert "protected runtime files" in st["blocked_reason"]


def test_missing_result_file_blocks_after_retry(tmp_path):
    cfg, store, repo = make_project(tmp_path)
    set_fake_control(cfg, {"01:builder": {"omit_result": True}})
    status, st = make_engine(cfg, store, repo).run(
        phases=["00", "01"], capabilities={})
    assert status == "blocked"
    assert "result invalid" in st["blocked_reason"] or "agent did not write" in st["blocked_reason"]


def test_strict_mode_waits_for_human_then_resumes(tmp_path):
    cfg, store, repo = make_project(tmp_path, gate_mode="strict")
    status, st = make_engine(cfg, store, repo).run(phases=["00"], capabilities={})
    assert status == "waiting_human"
    assert st["lifecycle"] == "HUMAN_GATE"
    candidate = st["candidate_commit"]
    human_gate.write_approval(cfg.root / "reports/human-gates", phase_id="00",
                              commit_sha=candidate, approver="tester",
                              decision="APPROVE", mode="strict")
    status, st = make_engine(cfg, store, repo).run(phases=["00"], capabilities={})
    assert status == "done"
    assert st["phase_history"]["00"]["gate"] == "PASS"


def test_strict_mode_reject_blocks(tmp_path):
    cfg, store, repo = make_project(tmp_path, gate_mode="strict")
    status, st = make_engine(cfg, store, repo).run(phases=["00"], capabilities={})
    assert status == "waiting_human"
    human_gate.write_approval(cfg.root / "reports/human-gates", phase_id="00",
                              commit_sha=st["candidate_commit"], approver="tester",
                              decision="REJECT", mode="strict")
    status, st = make_engine(cfg, store, repo).run(phases=["00"], capabilities={})
    assert status == "blocked"


def test_failing_required_test_triggers_fix_then_blocks(tmp_path):
    cfg, store, repo = make_project(tmp_path)
    import yaml
    reg = yaml.safe_load((cfg.root / "test_registry.yaml").read_text())
    reg["tests"]["p01_t"]["command"] = f'"{PY}" -c "import sys;sys.exit(1)"'
    (cfg.root / "test_registry.yaml").write_text(yaml.safe_dump(reg), encoding="utf-8")
    repo.add_all_and_commit("registry tweak")
    status, st = make_engine(cfg, store, repo).run(phases=["00", "01"], capabilities={})
    assert status == "blocked"
    assert st["phase_id"] == "01"
    assert "max fix cycles" in st["blocked_reason"]


def test_reviewer_unverified_status_blocks(tmp_path):
    cfg, store, repo = make_project(tmp_path)
    set_fake_control(cfg, {"01:reviewer": {"status": "unverified", "findings": []}})
    status, st = make_engine(cfg, store, repo).run(
        phases=["00", "01"], capabilities={})
    assert status == "blocked"
    assert st["phase_id"] == "01"
    assert "not 'completed'" in st["blocked_reason"]


def test_agent_git_commit_of_forbidden_file_is_caught(tmp_path):
    cfg, store, repo = make_project(tmp_path)
    # a builder that commits an edit to an immutable tracked file itself
    d = cfg.root / ".orchestrator"
    d.mkdir(exist_ok=True)
    (d / "fake_control.json").write_text(json.dumps(
        {"01:builder": {"self_commit_immutable": True}}), encoding="utf-8")
    status, st = make_engine(cfg, store, repo).run(phases=["00", "01"], capabilities={})
    assert status == "blocked"
    assert "HEAD" in st["blocked_reason"] or "forbidden" in st["blocked_reason"]


def test_agent_poison_main_via_checkout_is_caught(tmp_path):
    # builder checks out main, commits a forbidden edit, checks back — the
    # candidate HEAD sha is unchanged but a ref moved. Ref-pinning must catch it.
    cfg, store, repo = make_project(tmp_path)
    set_fake_control(cfg, {"01:builder": {"poison_main": True}})
    status, st = make_engine(cfg, store, repo).run(phases=["00", "01"], capabilities={})
    assert status == "blocked"
    assert "git refs" in st["blocked_reason"] or "moved git" in st["blocked_reason"]
    # main must be back at its pre-poison commit (no forbidden edit merged)
    repo.checkout("main")
    assert "poisoned" not in (cfg.root / "test_registry.yaml").read_text(encoding="utf-8")


def _symlinks_work():
    import os
    import tempfile
    try:
        with tempfile.TemporaryDirectory() as d:
            t = os.path.join(d, "t"); open(t, "w").close()
            os.symlink(t, os.path.join(d, "l"))
            return True
    except (OSError, NotImplementedError, AttributeError):
        return False


def test_symlink_forged_human_gate_is_caught(tmp_path):
    # a builder that plants a forged human-gate approval as a symlink must be
    # detected by the integrity snapshot (symlinks recorded, not skipped).
    if not _symlinks_work():
        import pytest
        pytest.skip("symlinks unavailable (non-admin Windows)")
    cfg, store, repo = make_project(tmp_path)  # auto mode: phase 00 auto-approves
    set_fake_control(cfg, {"01:builder": {"symlink_forge_gate": True}})
    status, st = make_engine(cfg, store, repo).run(phases=["00", "01"], capabilities={})
    assert status == "blocked"
    assert st["phase_id"] == "01"
    assert "protected" in st["blocked_reason"] or "control-plane" in st["blocked_reason"]
    assert "01" not in st.get("phase_history", {})


def test_main_baseline_detects_out_of_band_main_move(tmp_path):
    # simulate a detached process moving main between phases: after phase 00
    # merges, tamper main directly, then the next phase start must BLOCK.
    cfg, store, repo = make_project(tmp_path)
    status, st = make_engine(cfg, store, repo).run(phases=["00"], capabilities={})
    assert status == "done"
    # move main out from under the orchestrator
    repo.checkout("main")
    (cfg.root / "src").mkdir(exist_ok=True)
    (cfg.root / "src" / "sneak.txt").write_text("x", encoding="utf-8")
    repo.add_all_and_commit("out-of-band main move")
    status, st = make_engine(cfg, store, repo).run(phases=["00", "01"], capabilities={})
    assert status == "blocked"
    assert "main HEAD moved" in st["blocked_reason"]


def test_git_hooks_are_disabled_for_orchestrator(tmp_path):
    # a planted pre-commit hook must NOT run during the orchestrator's commits
    cfg, store, repo = make_project(tmp_path)
    hooks = cfg.root / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-commit").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    import os
    os.chmod(hooks / "pre-commit", 0o755)
    # if the hook ran, the (failing) hook would break the orchestrator's commits
    status, st = make_engine(cfg, store, repo).run(phases=["00"], capabilities={})
    assert status == "done"


def test_unblock_and_reset_work_on_a_dirty_tree(tmp_path):
    # a fix-cycle infra failure leaves the candidate branch checked out with a
    # dirty tree; unblock/reset-phase must not crash trying to switch to main.
    from orchestrator.main import cmd_unblock, cmd_reset_phase
    cfg, store, repo = make_project(tmp_path)
    set_fake_control(cfg, {"01:reviewer": {"findings": [
        {"id": "B1", "severity": "blocker", "title": "x"}]}})
    status, st = make_engine(cfg, store, repo).run(phases=["00", "01"], capabilities={})
    assert status == "blocked"
    # leave the candidate branch checked out and dirty (as a real block does)
    repo.checkout(st["candidate_branch"])
    (cfg.root / "src").mkdir(exist_ok=True)
    (cfg.root / "src" / "phase_01_builder.txt").write_text("uncommitted edit\n" * 3, encoding="utf-8")
    assert not repo.is_clean()

    class A:
        pass
    rc = cmd_unblock(cfg, A())            # must not raise GitError
    assert rc == 0
    st = store.load()
    assert st["lifecycle"] == "READY"
    # and reset-phase also survives a dirty tree
    repo.checkout(cfg.project["main_branch"])
    rc = cmd_reset_phase(cfg, A())
    assert rc == 0


def test_recovery_after_fix_commit_to_main_does_not_permanently_block(tmp_path):
    # emulate: a phase blocks, operator commits a fix to main, unblock re-pins
    # the baseline, and the next run does NOT trip the main-baseline check.
    from orchestrator.main import cmd_unblock
    cfg, store, repo = make_project(tmp_path)
    set_fake_control(cfg, {"01:reviewer": {"findings": [
        {"id": "B1", "severity": "blocker", "title": "x"}]}})
    status, st = make_engine(cfg, store, repo).run(phases=["00", "01"], capabilities={})
    assert status == "blocked" and st["phase_id"] == "01"
    # operator commits a fix on main (an expected move)
    repo.checkout("main")
    (cfg.root / "docs").mkdir(exist_ok=True)
    (cfg.root / "docs" / "fix.md").write_text("fixed", encoding="utf-8")
    repo.add_all_and_commit("operator fix")

    class A:
        pass
    cmd_unblock(cfg, A())
    # clear the blocker so the phase can pass this time
    set_fake_control(cfg, {"01:reviewer": {"findings": []}})
    status, st = make_engine(cfg, store, repo).run(phases=["00", "01"], capabilities={})
    assert status == "done"
    assert "main HEAD moved" not in (st.get("blocked_reason") or "")


def test_resume_when_saved_phase_is_outside_window_does_not_restart(tmp_path):
    # state left at phase 02 (out of a later default window that excludes it);
    # a run over {00,01} must recognize both are already done, NOT restart at 00.
    cfg, store, repo = make_project(tmp_path)
    status, st = make_engine(cfg, store, repo).run(phases=["00", "01", "02"], capabilities={})
    assert status == "done" and set(st["phase_history"]) == {"00", "01", "02"}
    # now a narrower run whose window excludes the saved phase (02)
    status, st = make_engine(cfg, store, repo).run(phases=["00", "01"], capabilities={})
    assert status == "done"
    # phase 00 was NOT rebuilt (history unchanged, single merged commit each)
    assert set(st["phase_history"]) >= {"00", "01"}


def test_skipped_earlier_phase_is_built_when_window_reincludes_it(tmp_path):
    # complete {00,02} (01 excluded), then request {00,01,02}: phase 01 (earlier
    # than the saved phase 02, not in history) MUST get built, not silently done.
    cfg, store, repo = make_project(tmp_path)
    status, st = make_engine(cfg, store, repo).run(phases=["00", "02"], capabilities={})
    assert status == "done" and set(st["phase_history"]) == {"00", "02"}
    status, st = make_engine(cfg, store, repo).run(phases=["00", "01", "02"], capabilities={})
    assert status == "done"
    assert "01" in st["phase_history"], "phase 01 must be built, not skipped"


def test_already_merged_phase_is_not_rerun_on_a_wider_window(tmp_path):
    # completing {00,02} then requesting a range that also contains the parked
    # phase must NOT re-run an already-merged phase (no spurious rebuild/block).
    cfg, store, repo = make_project(tmp_path)
    status, st = make_engine(cfg, store, repo).run(phases=["00", "02"], capabilities={})
    merged02 = st["phase_history"]["02"]["merged_commit"]
    status, st = make_engine(cfg, store, repo).run(phases=["00", "01", "02"], capabilities={})
    assert status == "done"
    # 02 kept its original merge (not rebuilt)
    assert st["phase_history"]["02"]["merged_commit"] == merged02


def test_reset_phase_removes_it_from_history_so_it_reruns(tmp_path):
    from orchestrator.main import cmd_reset_phase
    cfg, store, repo = make_project(tmp_path)
    status, st = make_engine(cfg, store, repo).run(phases=["00", "01"], capabilities={})
    assert status == "done" and "01" in st["phase_history"]

    class A:
        pass
    # point state at phase 01 and reset it
    store.save({**store.load(), "phase_id": "01"})
    cmd_reset_phase(cfg, A())
    assert "01" not in store.load().get("phase_history", {})
    status, st = make_engine(cfg, store, repo).run(phases=["00", "01"], capabilities={})
    assert status == "done" and "01" in st["phase_history"]


def test_agentless_selfcheck_failure_blocks_directly_not_via_fix_loop(tmp_path):
    cfg, store, repo = make_project(tmp_path)
    import yaml
    reg = yaml.safe_load((cfg.root / "test_registry.yaml").read_text())
    reg["tests"]["p00_t"]["command"] = f'"{PY}" -c "import sys;sys.exit(1)"'
    (cfg.root / "test_registry.yaml").write_text(yaml.safe_dump(reg), encoding="utf-8")
    repo.add_all_and_commit("break self-check")
    status, st = make_engine(cfg, store, repo).run(phases=["00"], capabilities={})
    assert status == "blocked" and st["phase_id"] == "00"
    assert "self-check" in st["blocked_reason"].lower()
    assert "max fix cycles" not in st["blocked_reason"]
    assert int(st.get("fix_cycles", 0)) == 0     # never entered the fix loop


def test_deferred_hardware_test_recorded_not_faked(tmp_path):
    cfg, store, repo = make_project(tmp_path)
    import yaml
    reg = yaml.safe_load((cfg.root / "test_registry.yaml").read_text())
    reg["tests"]["p02_t"]["requires"] = ["gpu"]
    (cfg.root / "test_registry.yaml").write_text(yaml.safe_dump(reg), encoding="utf-8")
    ph = yaml.safe_load((cfg.root / "phases" / "phase-02.yaml").read_text())
    ph["deferrable_tests"] = ["p02_t"]
    (cfg.root / "phases" / "phase-02.yaml").write_text(yaml.safe_dump(ph), encoding="utf-8")
    repo.add_all_and_commit("defer tweak")
    status, st = make_engine(cfg, store, repo).run(
        phases=["00", "01", "02"], capabilities={"gpu": False})
    assert status == "done"
    assert st["deferred_tests"].get("02") == ["p02_t"]
    assert st["phase_history"]["02"]["deferred"] == ["p02_t"]
