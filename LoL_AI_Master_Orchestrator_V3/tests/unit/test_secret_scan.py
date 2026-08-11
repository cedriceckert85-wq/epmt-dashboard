"""Secret scan: provider key formats detected, matches truncated, clean
code untouched."""
from orchestrator.secret_scan import scan_text, scan_paths


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


def test_scan_paths_skips_binary_and_missing(tmp_path):
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01secret sk-ant-abcdefghijklmnop")
    (tmp_path / "leak.py").write_text('t = "ghp_abcdefghijklmnopqrstuv1234"')
    hits = scan_paths(tmp_path, ["bin.dat", "leak.py", "missing.py"])
    assert {h["origin"] for h in hits} == {"leak.py"}
