"""Tamper detection for control-plane files that git does not track.

Git-diff inspection catches agent writes to tracked immutable paths, but
runtime control files (state/, human-gate + acceptance records, generated
projections, .orchestrator/) are gitignored — invisible to `git status`.
An agent/test write there would bypass the git-diff layer entirely,
including forging approval/acceptance records or injecting code into the
venv that runs on the next `python -m orchestrator` invocation. So the
orchestrator snapshots these paths before/after every agent run and test
run and compares; any difference => BLOCKED.

Design notes (hardened after adversarial review):
- Signatures are CONTENT HASHES, not (size, mtime) — a same-size overwrite
  with the mtime restored via os.utime can no longer evade detection.
- SYMLINKS are recorded as `symlink:<target>` WITHOUT being followed, so
  planting a symlink (e.g. reports/human-gates/x.json -> /tmp/forged.json,
  or .venv/.../sitecustomize.py -> /tmp/evil.py) shows up as an `added`
  entry instead of being silently skipped.
- The venv is NOT snapshotted wholesale (huge, and benign lazy caches like
  font caches / compiled modules would false-positive). Only the files that
  Python AUTO-EXECUTES at interpreter startup — *.pth, sitecustomize.py,
  usercustomize.py — are guarded, which is the actual injection surface.
"""
import hashlib
from pathlib import Path

# small control dirs/files — every regular file hashed, symlinks recorded
HASH_PATHS = [
    "state",
    "reports/human-gates",
    "reports/acceptance",
    ".orchestrator",              # minus the artifact + no-hooks dirs (excluded)
    ".git/hooks",                 # planted hooks execute as the orchestrator
    ".git/config",                # core.hooksPath / core.fsmonitor injection
    "PROJECT_STATE.md",
    "CURRENT_TASK.md",
    "ONE_SHOT_REPORT.md",
]

# Inside the venv we hash importable source files (.py/.pth/native ext) as a
# BEST-EFFORT tripwire for accidental/confused writes into the environment.
# This is NOT a complete defense: a deliberately malicious agent can poison a
# compiled __pycache__/*.pyc (executed on next import when its header matches
# the source) or a .venv/bin console-script shim, neither of which can be
# guarded here without false-positiving on the very Python runs that produce
# them. Comprehensive protection of the venv against a hostile agent requires
# OS sandboxing (see docs/V4_SECURITY_REVIEW.md "Trust boundary"). Data/cache
# files (font caches, proj.db, .nbi, .pyc) are excluded so benign lazy caches
# never wrongly BLOCK a clean build.
VENV_ROOTS = [".venv"]
VENV_CODE_SUFFIXES = (".py", ".pth", ".so", ".pyd", ".dll", ".egg-link")

PROTECTED_RUNTIME_PATHS = HASH_PATHS + VENV_ROOTS


def _hash_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sig(p):
    """Content signature that never follows a symlink."""
    if p.is_symlink():
        try:
            target = p.readlink()
        except OSError:
            target = "?"
        return f"symlink:{target}"
    return f"sha256:{_hash_file(p)}"


def _is_regenerable_cache(rel):
    return ("__pycache__/" in rel or rel.endswith((".pyc", ".pyo"))
            or "/.pytest_cache/" in rel or rel.endswith("/.pytest_cache"))


def _venv_code_file(name):
    return name.endswith(VENV_CODE_SUFFIXES)


def snapshot(root, *, hash_paths=HASH_PATHS, venv_roots=VENV_ROOTS, exclude=()):
    """Map repo-relative path -> signature for every protected file.

    `exclude` is an iterable of repo-relative path prefixes to skip (used to
    exempt the orchestrator's own current-run artifact dir, which it writes
    into during the guarded window)."""
    root = Path(root)
    exclude = tuple(e.replace("\\", "/").rstrip("/") for e in exclude)

    def excluded(rel):
        return any(rel == e or rel.startswith(e + "/") for e in exclude)

    snap = {}

    def add(p, rel):
        if excluded(rel) or _is_regenerable_cache(rel):
            return
        try:
            snap[rel] = _sig(p)
        except OSError:
            snap[rel] = "unreadable"

    def walk(base, keep=lambda rel, name: True):
        if base.is_symlink():                     # a symlinked dir itself
            add(base, str(base.relative_to(root)).replace("\\", "/"))
            return
        if base.is_file():
            add(base, str(base.relative_to(root)).replace("\\", "/"))
            return
        if not base.is_dir():
            return
        for f in sorted(base.rglob("*")):
            rel = str(f.relative_to(root)).replace("\\", "/")
            # do not descend into symlinked dirs; record the link itself
            if f.is_symlink():
                if keep(rel, f.name):
                    add(f, rel)
                continue
            if f.is_file() and keep(rel, f.name):
                add(f, rel)

    for rel in hash_paths:
        walk(root / rel)
    for rel in venv_roots:
        walk(root / rel, keep=lambda rel, name: _venv_code_file(name))
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
