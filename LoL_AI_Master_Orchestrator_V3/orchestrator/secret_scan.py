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
    ("openai_api_key_legacy", re.compile(r"\bsk-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20}\b")),
    ("riot_api_key", re.compile(r"\bRGAPI-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("generic_assignment", re.compile(
        r"(?i)\b(api_key|apikey|secret|auth_token|access_token|password)\b\s*[:=]\s*['\"]?[^'\"\s]{12,}['\"]?")),
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
    """Scan every changed path. Anything that cannot be text-scanned
    (oversize, unreadable) becomes an 'unscannable_file' finding so the
    gate fails closed — a secret can never ride in by making its file
    too big, unreadable, or NUL-laced."""
    root = Path(root)
    findings = []
    for rel in rel_paths:
        p = root / rel
        try:
            if not p.is_file():
                continue
            if p.stat().st_size > MAX_FILE_BYTES:
                findings.append({"pattern": "unscannable_file", "origin": rel,
                                 "match": f">{MAX_FILE_BYTES}B (not scanned)"})
                continue
            data = p.read_bytes()
        except OSError as e:
            findings.append({"pattern": "unscannable_file", "origin": rel,
                             "match": f"unreadable: {type(e).__name__}"})
            continue
        # No binary carve-out: NUL bytes must not be an escape hatch. Decode
        # lossily and scan the text; MAX_FILE_BYTES already caps the cost.
        findings.extend(scan_text(data.decode("utf-8", errors="replace"), origin=rel))
    return findings


def redact(text):
    """Replace any secret match in free text with its truncated form, so
    stderr/reasons journaled or projected into git-tracked files never
    carry a plaintext secret."""
    if not text:
        return text
    out = text
    for _name, rx in PATTERNS:
        out = rx.sub(lambda m: m.group(0)[:12] + "…", out)
    return out
