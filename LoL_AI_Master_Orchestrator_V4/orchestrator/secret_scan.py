"""Secret scan over changed files. Any hit fails the completion gate."""
import re
from pathlib import Path

PATTERNS = [
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}")),
    ("openai_key", re.compile(r"sk-(?:proj|svcacct|None)?-?[A-Za-z0-9_-]{32,}")),
    ("github_token", re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}")),
    ("github_pat", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("riot_api_key", re.compile(r"\bRGAPI-[0-9a-fA-F-]{30,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    ("tailscale_key", re.compile(r"\btskey-[A-Za-z0-9-]{10,}\b")),
]

SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".mp4", ".mkv", ".zip", ".gz",
                 ".pdf", ".ico", ".woff", ".woff2", ".ttf", ".db", ".sqlite", ".bin"}
MAX_FILE_BYTES = 5 * 1024 * 1024


def scan_files(root, rel_paths):
    """Return findings [{file, kind, line}] for the given repo-relative paths."""
    findings = []
    root = Path(root)
    for rel in rel_paths:
        p = root / rel
        if not p.is_file() or p.is_symlink():
            continue
        if p.suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for kind, rx in PATTERNS:
                if rx.search(line):
                    findings.append({"file": rel, "kind": kind, "line": lineno})
    return findings
