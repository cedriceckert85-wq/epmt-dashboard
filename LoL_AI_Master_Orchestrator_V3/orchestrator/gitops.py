"""Git control plane: worktrees, orchestrator-only checkpoint commits,
diff enumeration for path-policy enforcement, ff-only merges, rollback.

Agents never run git (agents_may_commit=false). Every commit here is
authored by the orchestrator identity, and a worktree whose HEAD moved
without the orchestrator committing is treated as tampering.
"""
import subprocess
from pathlib import Path

ORCH_AUTHOR = "orchestrator"
ORCH_EMAIL = "orchestrator@local"


class GitError(Exception):
    pass


class GitOps:
    def __init__(self, root, main_branch="main", timeout_s=120):
        self.root = Path(root)
        self.main_branch = main_branch
        self.timeout_s = timeout_s

    # --- plumbing --------------------------------------------------------
    def _git(self, *args, cwd=None, check=True):
        try:
            r = subprocess.run(
                ["git", "-c", f"user.name={ORCH_AUTHOR}", "-c", f"user.email={ORCH_EMAIL}",
                 *args],
                cwd=str(cwd or self.root), capture_output=True, text=True,
                timeout=self.timeout_s)
        except subprocess.TimeoutExpired as e:
            raise GitError(f"git {' '.join(args)} timed out") from e
        if check and r.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {r.stderr.strip() or r.stdout.strip()}")
        return r

    # --- queries ---------------------------------------------------------
    def current_branch(self, cwd=None):
        return self._git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd).stdout.strip()

    def rev_parse(self, ref="HEAD", cwd=None):
        return self._git("rev-parse", ref, cwd=cwd).stdout.strip()

    def dirty_paths(self, cwd=None, exclude_prefixes=()):
        out = self._git("status", "--porcelain", cwd=cwd).stdout
        dirty = []
        for line in out.splitlines():
            if not line.strip():
                continue
            path = line[3:].strip().strip('"')
            # rename entries look like "old -> new"
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if any(path.startswith(p) or path == p.rstrip("/") for p in exclude_prefixes):
                continue
            dirty.append(path)
        return dirty

    def is_clean(self, cwd=None, exclude_prefixes=()):
        return not self.dirty_paths(cwd=cwd, exclude_prefixes=exclude_prefixes)

    def changed_paths(self, worktree, base_sha):
        """All paths differing from base: committed + staged + untracked."""
        paths = set()
        r = self._git("diff", "--name-only", f"{base_sha}..HEAD", cwd=worktree, check=False)
        if r.returncode == 0:
            paths.update(l.strip() for l in r.stdout.splitlines() if l.strip())
        paths.update(self.dirty_paths(cwd=worktree))
        return sorted(paths)

    # --- worktrees -------------------------------------------------------
    def create_worktree(self, path, branch, base_ref):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._git("worktree", "add", "-b", branch, str(path), base_ref)
        return Path(path)

    def remove_worktree(self, path, branch=None):
        self._git("worktree", "remove", "--force", str(path), check=False)
        self._git("worktree", "prune", check=False)
        if branch:
            self._git("branch", "-D", branch, check=False)

    # --- commits ---------------------------------------------------------
    def commit_all(self, worktree, message, *, allow_empty=False):
        """Orchestrator checkpoint commit of everything in the worktree.
        Returns the new SHA, or None when there is nothing to commit."""
        self._git("add", "-A", cwd=worktree)
        staged = self._git("diff", "--cached", "--name-only", cwd=worktree).stdout.strip()
        if not staged and not allow_empty:
            return None
        args = ["commit", "-m", message]
        if allow_empty:
            args.append("--allow-empty")
        self._git(*args, cwd=worktree)
        return self.rev_parse("HEAD", cwd=worktree)

    # --- merge -----------------------------------------------------------
    def merge_ff_only(self, sha):
        """Fast-forward the main checkout to sha. Refuses on wrong branch."""
        branch = self.current_branch()
        if branch != self.main_branch:
            raise GitError(f"refusing merge: on branch {branch!r}, expected {self.main_branch!r}")
        self._git("merge", "--ff-only", sha)
        return self.rev_parse("HEAD")
