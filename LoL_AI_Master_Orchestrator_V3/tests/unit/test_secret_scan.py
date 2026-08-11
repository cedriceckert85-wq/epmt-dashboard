"""Secret scan: provider key formats detected, matches truncated, clean
code untouched."""
from orchestrator.secret_scan import scan_text, scan_paths, redact, MAX_FILE_BYTES


def test_detects_provider_secrets():
    samples = {
        "anthropic_api_key": 'k = "sk-ant-abc123def456ghi789jkl"',
        "openai_api_key": 'k = "sk-proj-abc123def456ghi789jkl"',
        "riot_api_key": 'RGAPI-12345678-abcd-ef01-2345-6789abcdef01',
        "github_token": 'ghp_abcdefghijklmnopqrstuv123456',
        "aws_access_key": 'AKIAIOSFODNN7EXAMPLE',
        "private_key": '-----BEGIN RSA PRIVATE KEY-----',
        "generic_assignment": 'api_key = "super-secret-value-123"',
    }
    for expected, text in samples.items():
        hits = scan_text(text, origin="x")
        assert any(h["pattern"] == expected for h in hits), expected


def test_match_is_truncated_never_logged_fully():
    hits = scan_text('key = "sk-ant-abcdefghijklmnopqrstuvwxyz"')
    assert all(len(h["match"]) <= 13 for h in hits)


def test_clean_text_has_no_findings():
    clean = "def add(a, b):\n    return a + b\n# talk about api keys in general\n"
    assert scan_text(clean) == []


def test_missing_files_are_ignored_but_present_ones_scanned(tmp_path):
    (tmp_path / "leak.py").write_text('t = "ghp_abcdefghijklmnopqrstuv1234"')
    hits = scan_paths(tmp_path, ["leak.py", "missing.py"])
    assert {h["origin"] for h in hits} == {"leak.py"}


def test_nul_laced_file_is_scanned_not_skipped(tmp_path):
    # SECENV-03: a NUL byte must not be an escape hatch for a plaintext secret
    (tmp_path / "sneaky.bin").write_bytes(
        b"\x00\x01 harmless \x00 key = \"sk-ant-abcdefghijklmnopqrstuv\" \x00")
    hits = scan_paths(tmp_path, ["sneaky.bin"])
    assert any(h["pattern"] == "anthropic_api_key" for h in hits)


def test_oversize_file_becomes_unscannable_finding(tmp_path):
    # SECENV-02: an oversize diff file fails closed (gate-blocking finding)
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * (MAX_FILE_BYTES + 10))
    hits = scan_paths(tmp_path, ["big.bin"])
    assert any(h["pattern"] == "unscannable_file" for h in hits)


def test_legacy_openai_key_detected():
    # SECENV-04
    key = "sk-" + "A" * 20 + "T3BlbkFJ" + "B" * 20
    assert any(h["pattern"] == "openai_api_key_legacy"
               for h in scan_text(f'k = "{key}"'))


def test_unquoted_env_assignment_detected():
    # SECENV-04: .env/.yaml style without quotes
    assert any(h["pattern"] == "generic_assignment"
               for h in scan_text("API_KEY=supersecretvalue123456"))


def test_redact_masks_secrets_in_free_text():
    # SECENV-05
    text = 'boom: token ghp_abcdefghijklmnopqrstuv1234 leaked in stderr'
    red = redact(text)
    assert "ghp_abcdefghijklmnopqrstuv1234" not in red
    assert "…" in red
