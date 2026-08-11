"""Hermetic fixture project for engine/integration tests.

Builds a tiny but structurally complete orchestrator project in a temp
dir (own git repo on `main`), so engine tests never touch the real
repository and never recurse into the real test suite.
"""
import json, shutil, subprocess, sys
from pathlib import Path

REAL_ROOT = Path(__file__).resolve().parents[2]

CONFIG_TMPL = """\
version: 2
project:
  name: fixture
  main_branch: main
  canonical_state: state/project_state.json
  current_task: state/current_task.json
  journal: state/journal.jsonl
  generated_state_markdown: PROJECT_STATE.md
  generated_task_markdown: CURRENT_TASK.md
  worktree_root: .orchestrator/worktrees
  artifact_root: .orchestrator/artifacts
  lock_file: state/orchestrator.lock
agents:
  claude: {{executable: claude, timeout_s: 60, max_retries: 2}}
  codex: {{executable: codex, timeout_s: 60, max_retries: 2}}
retry:
  infrastructure_backoff_s: {backoff}
  invalid_schema_retries: 1
  max_fix_cycles: {max_fix_cycles}
security:
  immutable_paths: [.git, state, schemas, phases, ORCHESTRATOR_CONFIG.yaml,
                    PROJECT_STATE.md, CURRENT_TASK.md, reports/human-gates,
                    reports/acceptance, test_registry.yaml]
  test_env_must_strip_provider_secrets: true
git: {{require_clean_main: true, merge_strategy: ff-only, agents_may_commit: false}}
human_gates: {{record_dir: reports/human-gates}}
acceptance: {{record_dir: reports/acceptance, schema: schemas/finding_acceptance.schema.json}}
test_registry: test_registry.yaml
gate_policy:
  review_acceptance_source: orchestrator_or_human_only
  require_sha_invariant: true
  require_legal_lifecycle_transition: true
  human_approval_must_bind_exact_sha: true
retryable_exit_codes: [75]
path_policy:
  precedence: immutable_over_allowed
  rule: immutable child always wins
"""

PHASE00_TMPL = """\
id: '00'
name: Fixture Phase
builder: claude
reviewer: codex
cross_vendor_review: true
human_gate: {human_gate}
required_tests: [fixture_test]
allowed_write_paths: [src/, docs/]
gate: {{max_blockers: 0, max_unaccepted_high: 0}}
preconditions: [none]
"""

PHASE01 = """\
id: '01'
name: Fixture Next
builder: claude
reviewer: codex
cross_vendor_review: true
human_gate: false
required_tests: []
allowed_write_paths: [src/]
gate: {max_blockers: 0, max_unaccepted_high: 0}
"""

REGISTRY_TMPL = """\
version: 1
tests:
  fixture_test:
    command: python run_fixture_test.py
    cwd: .
    timeout_s: 60
    requires: [{requires}]
    parser: exit_code
    evidence: .orchestrator/artifacts/{{run_id}}/fixture_test.txt
    implemented_in_phase: '00'
    produces_metrics: []
"""

FIXTURE_TEST = """\
import sys, pathlib
sys.exit(1 if pathlib.Path("test_should_fail.txt").exists() else 0)
"""

STATE = {
    "schema_version": 2, "run_id": None, "sequence": 0, "phase_id": "00",
    "lifecycle": "READY", "attempt": 0, "builder": None, "candidate_commit": None,
    "test_evidence_id": None, "review_evidence_id": None,
    "human_gate_required": True, "last_gate": None, "reviewer_provider": None,
    "builder_provider": None, "approved_commit": None, "reviewed_commit": None,
    "tested_commit": None, "merged_commit": None, "human_approval_id": None,
}


def _git(root, *args):
    r = subprocess.run(["git", "-c", "user.name=fixture", "-c", "user.email=f@local",
                        *args], cwd=root, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r


def make_fixture_project(tmp_path, *, human_gate=False, failing_test=False,
                         max_fix_cycles=2, backoff="[0, 0]", requires="none"):
    root = Path(tmp_path) / "fixture-repo"
    root.mkdir(parents=True)
    (root / "ORCHESTRATOR_CONFIG.yaml").write_text(
        CONFIG_TMPL.format(max_fix_cycles=max_fix_cycles, backoff=backoff))
    (root / "phases").mkdir()
    (root / "phases" / "phase-00.yaml").write_text(
        PHASE00_TMPL.format(human_gate="true" if human_gate else "false"))
    (root / "phases" / "phase-01.yaml").write_text(PHASE01)
    (root / "test_registry.yaml").write_text(REGISTRY_TMPL.format(requires=requires))
    (root / "run_fixture_test.py").write_text(FIXTURE_TEST)
    if failing_test:
        (root / "test_should_fail.txt").write_text("fail")
    (root / "schemas").mkdir()
    for schema in ("agent_result.schema.json", "finding_acceptance.schema.json"):
        shutil.copy(REAL_ROOT / "schemas" / schema, root / "schemas" / schema)
    (root / "prompts" / "build").mkdir(parents=True)
    (root / "prompts" / "build" / "phase-00.md").write_text("# build fixture phase\n")
    (root / "prompts" / "build" / "phase-01.md").write_text("# build next\n")
    (root / "prompts" / "review").mkdir()
    (root / "prompts" / "review" / "adversarial.md").write_text("# review fixture\n")
    (root / "prompts" / "fix").mkdir()
    (root / "prompts" / "fix" / "verified-findings-fix.md").write_text("# fix findings\n")
    (root / "state").mkdir()
    (root / "state" / "project_state.json").write_text(json.dumps(STATE, indent=2))
    (root / "state" / "current_task.json").write_text("{}")
    (root / "PROJECT_STATE.md").write_text("# PROJECT STATE\n")
    (root / "CURRENT_TASK.md").write_text("# CURRENT TASK\n")
    (root / ".gitignore").write_text("__pycache__/\n*.pyc\n.orchestrator/\n")
    _git(root, "init", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "fixture baseline")
    return root


def make_engine(root, *, builder_mode="success", reviewer_mode="reviewer-clean",
                builder_provider="fake-claude", reviewer_provider="fake-codex",
                capabilities=("none",), sleeps=None, builder=None, reviewer=None,
                agent_timeout_s=60):
    from orchestrator.adapters.fake import FakeAdapter
    from orchestrator.config import Config
    from orchestrator.engine import PhaseEngine
    fake_script = REAL_ROOT / "tests" / "fakes" / "fake_agent.py"
    cfg = Config.load(root)
    recorded = sleeps if sleeps is not None else []
    builder = builder or FakeAdapter(fake_script, provider=builder_provider,
                                     mode=builder_mode, timeout_s=agent_timeout_s)
    reviewer = reviewer or FakeAdapter(fake_script, provider=reviewer_provider,
                                       mode=reviewer_mode, timeout_s=agent_timeout_s)
    engine = PhaseEngine(root, cfg, builder, reviewer,
                         capabilities=set(capabilities),
                         sleep=recorded.append,
                         allow_empty_candidate=True)
    return engine, cfg, recorded
