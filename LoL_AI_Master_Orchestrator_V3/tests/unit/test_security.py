from orchestrator.path_policy import is_write_allowed, normalize

ALLOWED=["src/","tests/","docs/","reports/"]
IMMUTABLE=[".git","state","schemas","phases","ORCHESTRATOR_CONFIG.yaml",
           "PROJECT_STATE.md","CURRENT_TASK.md","reports/human-gates",
           "reports/acceptance","test_registry.yaml"]

def ok(p): return is_write_allowed(p, allowed_paths=ALLOWED, immutable_paths=IMMUTABLE)

def test_allowed_paths_work():
    assert ok("src/agent/main.py")
    assert ok("reports/phase-04.md")

def test_immutable_child_beats_allowed_parent():
    assert not ok("reports/human-gates/fake_approval.md")
    assert not ok("reports/acceptance/evil.json")

def test_immutable_roots_blocked():
    for p in ("state/project_state.json","phases/phase-04.yaml",
              "schemas/agent_result.schema.json","ORCHESTRATOR_CONFIG.yaml",
              "test_registry.yaml",".git/config","PROJECT_STATE.md","CURRENT_TASK.md"):
        assert not ok(p)

def test_traversal_and_absolute_blocked():
    assert not ok("reports/../state/project_state.json")
    assert not ok("src/../../etc/passwd")
    assert not ok("..\\state\\project_state.json")
    assert not ok("/etc/passwd")
    assert not ok("C:/Windows/win.ini")
    assert normalize("src/./a/../b.py")=="src/b.py"

def test_backslash_paths_normalized():
    assert not ok("reports\\human-gates\\x.md")
    assert ok("src\\agent\\main.py")

def test_outside_allowed_blocked():
    assert not ok("orchestrator/gates.py")   # nicht in ALLOWED dieser Phase
    assert not ok("random.txt")

# NOTE: Full enforcement (post-run git diff inspection) is Phase 00 scope;
# this module is the reference implementation it must use.
