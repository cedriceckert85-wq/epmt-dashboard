"""Tamper detection for control-plane files that git does not track.

Git-diff inspection catches agent writes to tracked immutable paths, but
runtime control files (state/, human-gate + acceptance records, generated
projections) AND gitignored immutable trees (.venv/, .orchestrator/) are
invisible to `git status`. An agent write there would bypass the git-diff
layer entirely — including planting forged approval/acceptance records or
injecting code into the venv that runs on the next `python -m orchestrator`
invocation. So the orchestrator snapshots these paths before every agent
run / test run and compares afterwards. Any difference => BLOCKED.

Two snapshot modes:
- HASH  : small control files/dirs — full sha256 (exact content check).
- STAT  : large trees (.venv, .orchestrator) — (size, mtime_ns) per file,
          fast, still detects any add/remove/modify.
"""
import hashlib
from pathlib import Path

# small, hashed exactly
HASH_PATHS = [
    "state",
    "reports/human-gates",
    "reports/acceptance",
    "PROJECT_STATE.md",
    "CURRENT_TASK.md",
    "ONE_SHOT_REPORT.md",
]

# large trees, stat-based (immutable but gitignored — must still be guarded)
STAT_PATHS = [
    ".venv",
    ".orchestrator",
]

PROTECTED_RUNTIME_PATHS = HASH_PATHS + STAT_PATHS


def _hash_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _stat_sig(p):
    st = p.stat()
    return f"stat:{st.st_size}:{st.st_mtime_ns}"


def _is_regenerable_cache(rel):
    # bytecode caches are rewritten by any import and are NOT an injection
    # vector on their own (CPython refuses a .pyc whose source hash/mtime
    # does not match), so exclude them to avoid false tamper positives.
    return ("__pycache__/" in rel or rel.endswith((".pyc", ".pyo"))
            or rel.endswith(".pytest_cache") or "/.pytest_cache/" in rel)


def snapshot(root, *, hash_paths=HASH_PATHS, stat_paths=STAT_PATHS,
             exclude=()):
    """Map repo-relative path -> signature for every protected file.

    `exclude` is an iterable of repo-relative path prefixes to skip (used to
    exempt the orchestrator's own current-run artifact subdir when it must
    write there during the guarded window)."""
    root = Path(root)
    exclude = tuple(e.replace("\\", "/").rstrip("/") for e in exclude)

    def excluded(rel):
        return any(rel == e or rel.startswith(e + "/") for e in exclude)

    snap = {}

    def add(rel, sig):
        if not excluded(rel):
            snap[rel] = sig

    for rel in hash_paths:
        p = root / rel
        if p.is_file():
            add(rel, _hash_file(p))
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and not f.is_symlink():
                    add(str(f.relative_to(root)).replace("\\", "/"), _hash_file(f))
    for rel in stat_paths:
        p = root / rel
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and not f.is_symlink():
                    frel = str(f.relative_to(root)).replace("\\", "/")
                    if _is_regenerable_cache(frel):
                        continue
                    try:
                        add(frel, _stat_sig(f))
                    except OSError:
                        pass
        elif p.is_file():
            add(rel, _stat_sig(p))
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
