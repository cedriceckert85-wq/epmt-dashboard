from orchestrator.path_policy import is_write_allowed, normalize

ALLOWED = ["src/", "tests/", "docs/", "reports/", "schemas/", "migrations/",
           "config/", "assets/", "runbooks/"]
IMMUTABLE = [".git", "state", "phases", "prompts", "orchestrator", "scripts",
             "bootstrap.py", "ORCHESTRATOR_CONFIG.yaml",
             "PROJECT_STATE.md", "CURRENT_TASK.md", "reports/human-gates",
             "reports/acceptance", "test_registry.yaml",
             "schemas/agent_result.schema.json",
             "schemas/finding_acceptance.schema.json"]


def ok(p):
    return is_write_allowed(p, allowed_paths=ALLOWED, immutable_paths=IMMUTABLE)


def test_allowed_paths_work():
    assert ok("src/agent/main.py")
    assert ok("reports/phase-04.md")


def test_immutable_child_beats_allowed_parent():
    assert not ok("reports/human-gates/fake_approval.md")
    assert not ok("reports/acceptance/evil.json")


def test_immutable_roots_blocked():
    for p in ("state/project_state.json", "phases/phase-04.yaml",
              "schemas/agent_result.schema.json", "schemas/finding_acceptance.schema.json",
              "ORCHESTRATOR_CONFIG.yaml",
              "test_registry.yaml", ".git/config", "PROJECT_STATE.md",
              "CURRENT_TASK.md", "orchestrator/gates.py", "prompts/build/phase-01.md",
              "scripts/make_zip.py", "bootstrap.py"):
        assert not ok(p)


def test_project_schemas_writable_control_schemas_locked():
    # build prompts tell agents to create project data schemas under schemas/;
    # those must be writable while the two orchestrator control schemas stay
    # locked (immutable child beats allowed parent).
    assert ok("schemas/edl.schema.json")
    assert ok("schemas/segment_manifest.schema.json")
    assert not ok("schemas/agent_result.schema.json")
    assert not ok("schemas/finding_acceptance.schema.json")


def test_new_build_dirs_writable():
    for p in ("migrations/0001_init.sql", "config/editorial.toml",
              "assets/sfx/README.md", "runbooks/POC_RUNBOOK.md"):
        assert ok(p)


def test_traversal_and_absolute_blocked():
    assert not ok("reports/../state/project_state.json")
    assert not ok("src/../../etc/passwd")
    assert not ok("..\\state\\project_state.json")
    assert not ok("/etc/passwd")
    assert not ok("C:/Windows/win.ini")
    assert normalize("src/./a/../b.py") == "src/b.py"


def test_backslash_paths_normalized():
    assert not ok("reports\\human-gates\\x.md")
    assert ok("src\\agent\\main.py")


def test_outside_allowed_blocked():
    assert not ok("random.txt")


def test_secret_scan_patterns(tmp_path):
    from orchestrator import secret_scan
    bad = tmp_path / "src"
    bad.mkdir()
    (bad / "leak.py").write_text(
        'KEY = "sk-ant-' + "a" * 24 + '"\n'
        'PEM = "-----BEGIN PRIVATE KEY-----"\n'
        'RIOT = "RGAPI-' + "0123456789abcdef" * 2 + '"\n', encoding="utf-8")
    (bad / "clean.py").write_text('KEY = "FAKE-KEY-PLACEHOLDER"\n', encoding="utf-8")
    hits = secret_scan.scan_files(tmp_path, ["src/leak.py", "src/clean.py"])
    kinds = {h["kind"] for h in hits}
    assert "anthropic_key" in kinds and "private_key_block" in kinds and "riot_api_key" in kinds
    assert all(h["file"] == "src/leak.py" for h in hits)
