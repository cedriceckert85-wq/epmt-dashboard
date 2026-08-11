"""Tamper detection for control-plane files that git does not track.

Git-diff inspection catches agent writes to tracked immutable paths, but
runtime control files (state/, human-gate + acceptance records, generated
projections) are gitignored — an agent write there would be invisible to
`git status`. So the orchestrator snapshots their hashes before every
agent run and compares afterwards. Any difference => BLOCKED.
"""
import hashlib
from pathlib import Path

# repo-relative paths (files or directories) snapshotted around agent runs
PROTECTED_RUNTIME_PATHS = [
    "state",
    "reports/human-gates",
    "reports/acceptance",
    "PROJECT_STATE.md",
    "CURRENT_TASK.md",
]


def _hash_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(root, paths=PROTECTED_RUNTIME_PATHS):
    root = Path(root)
    snap = {}
    for rel in paths:
        p = root / rel
        if p.is_file():
            snap[rel] = _hash_file(p)
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file():
                    snap[str(f.relative_to(root)).replace("\\", "/")] = _hash_file(f)
    return snap


def diff_snapshots(before, after):
    """List of human-readable differences (added/removed/modified)."""
    diffs = []
    for rel in sorted(set(before) | set(after)):
        if rel not in after:
            diffs.append(f"removed: {rel}")
        elif rel not in before:
            diffs.append(f"added: {rel}")
        elif before[rel] != after[rel]:
            diffs.append(f"modified: {rel}")
    return diffs
