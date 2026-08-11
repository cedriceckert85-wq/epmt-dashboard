"""Write-path policy: immutable paths always override allowed paths.

This is the reference implementation Phase 00 must wire into post-run
diff enforcement. Paths are evaluated relative to the worktree root.
"""
from pathlib import PurePosixPath


def normalize(path):
    """Normalize an agent-supplied relative path without touching the
    filesystem. Returns None for anything that escapes the worktree
    (absolute, drive letter, UNC, leading/embedded '..')."""
    if path is None:
        return None
    p=str(path).replace("\\","/").strip()
    if not p:
        return None
    if p.startswith("/") or p.startswith("//") or (len(p)>1 and p[1]==":"):
        return None
    parts=[]
    for part in PurePosixPath(p).parts:
        if part in (".",""):
            continue
        if part=="..":
            if not parts:
                return None          # escapes the worktree
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts) if parts else None


def _matches(norm, prefix):
    pref=prefix.strip("/").replace("\\","/")
    return norm==pref or norm.startswith(pref+"/")


def is_write_allowed(path, *, allowed_paths, immutable_paths):
    """True only if path normalizes cleanly, hits no immutable path (or
    descendant of one), and lies under an allowed path. Fail closed."""
    norm=normalize(path)
    if norm is None:
        return False
    for imm in immutable_paths or []:
        if _matches(norm, imm):
            return False             # immutable ALWAYS wins
    for al in allowed_paths or []:
        if _matches(norm, al):
            return True
    return False
