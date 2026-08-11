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
