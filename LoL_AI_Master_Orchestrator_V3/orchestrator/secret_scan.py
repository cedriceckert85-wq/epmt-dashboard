"""Secret scan over candidate diffs. Any hit is a gate-blocking finding.

Patterns are deliberately narrow enough not to drown the gate in false
positives, but every provider credential format used in this project
(Anthropic, OpenAI, Riot, GitHub, Slack, AWS, private keys) is covered.
"""
import re
from pathlib import Path

PATTERNS = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("anthropic_api_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}")),
    ("openai_api_key", re.compile(r"\bsk-(?:proj|svcacct|live)-[A-Za-z0-9_-]{16,}")),
    ("riot_api_key", re.compile(r"\bRGAPI-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("generic_assignment", re.compile(
        r"(?i)\b(api_key|apikey|secret|auth_token|access_token|password)\b\s*[:=]\s*['\"][^'\"\s]{12,}['\"]")),
)

MAX_FILE_BYTES = 1_000_000


def scan_text(text, origin=""):
    findings = []
    for name, rx in PATTERNS:
        for m in rx.finditer(text):
            findings.append({"pattern": name, "origin": origin,
                             "match": m.group(0)[:12] + "…"})  # never log the full secret
    return findings


def scan_paths(root, rel_paths):
    root = Path(root)
    findings = []
    for rel in rel_paths:
        p = root / rel
        try:
            if not p.is_file() or p.stat().st_size > MAX_FILE_BYTES:
                continue
            data = p.read_bytes()
        except OSError:
            continue
        if b"\x00" in data[:8000]:
            continue  # binary
        findings.extend(scan_text(data.decode("utf-8", errors="replace"), origin=rel))
    return findings
