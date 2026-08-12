"""Git control: only the orchestrator commits/merges. Agents never touch git.

Adaptation vs V3: instead of separate worktrees, each phase works on a
candidate branch in the single project checkout (phase/NN). Merges into
main are ff-only and SHA-verified.
"""
import subprocess
from pathlib import Path


class GitError(Exception):
    pass


class GitRepo:
    def __init__(self, root):
        self.root = Path(root)
        # every git invocation runs with hooks disabled: a builder that plants
        # .git/hooks/pre-commit (or core.hooksPath) must never get it executed
        # as the orchestrator on the next commit/checkout/merge.
        self._no_hooks_dir = self.root / ".orchestrator" / "no-hooks"

    def _base(self):
        try:
            self._no_hooks_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        # hooks disabled (planted-hook protection) AND signing disabled: the
        # orchestrator's control-plane commits must never invoke a GPG/SSH
        # signer, which fails headless (no TTY/pinentry) and would abort every
        # commit when the user has commit.gpgsign=true globally.
        return ["git", "-c", f"core.hooksPath={self._no_hooks_dir}",
                "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]

    def _run(self, *args, check=True, capture=True):
        p = subprocess.run([*self._base(), *args], cwd=self.root,
                           capture_output=capture, text=True)
        if check and p.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed (exit {p.returncode}): "
                           f"{(p.stderr or p.stdout or '').strip()}")
        return p

    # -- setup -----------------------------------------------------------
    def is_repo(self):
        p = self._run("rev-parse", "--is-inside-work-tree", check=False)
        return p.returncode == 0 and p.stdout.strip() == "true"

    def init(self, main_branch="main"):
        if not self.is_repo():
            # `git init -b <branch>` needs git >= 2.28; fall back to plain init
            # + repointing the unborn HEAD so older LTS git (RHEL/Rocky 8,
            # Ubuntu 20.04, git 2.20-2.27) still starts on `main`.
            if self._run("init", "-b", main_branch, check=False).returncode != 0:
                self._run("init")
                self._run("symbolic-ref", "HEAD", f"refs/heads/{main_branch}", check=False)
        # commits need an identity; set a repo-local one if none configured
        for key, val in (("user.name", "LoL Orchestrator"),
                         ("user.email", "orchestrator@localhost")):
            if self._run("config", "--get", key, check=False).returncode != 0:
                self._run("config", key, val)
        # repo-local signing OFF, unconditionally: makes EVERY commit in this
        # repo unsigned regardless of the user's global commit.gpgsign, so a
        # headless-failing signer can never abort a commit (belt-and-suspenders
        # beyond the per-invocation -c flags).
        self._run("config", "commit.gpgsign", "false", check=False)
        self._run("config", "tag.gpgsign", "false", check=False)

    def has_commits(self):
        return self._run("rev-parse", "HEAD", check=False).returncode == 0

    # -- info ------------------------------------------------------------
    def head_sha(self):
        return self._run("rev-parse", "HEAD").stdout.strip()

    def current_branch(self):
        return self._run("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def branch_exists(self, name):
        return self._run("rev-parse", "--verify", "--quiet", f"refs/heads/{name}",
                         check=False).returncode == 0

    def branch_sha(self, name):
        p = self._run("rev-parse", f"refs/heads/{name}", check=False)
        return p.stdout.strip() if p.returncode == 0 else None

    def is_ancestor(self, maybe_ancestor, ref):
        """True if maybe_ancestor is reachable from ref (already merged)."""
        if not maybe_ancestor:
            return False
        return self._run("merge-base", "--is-ancestor", maybe_ancestor, ref,
                         check=False).returncode == 0

    def all_refs(self):
        """Map every local ref (branches, tags, HEAD) -> sha. Used to pin the
        repo across an agent/test run: agents must move NO refs, so a commit
        to main (even via checkout-main-commit-checkout-back, which leaves the
        current HEAD sha unchanged) is detected as a ref change."""
        out = self._run("show-ref", "--head", check=False).stdout
        refs = {}
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            sha, _, name = line.partition(" ")
            if name:
                refs[name] = sha
        return refs

    def status_porcelain(self):
        """[(status, path)] of pending changes. Rename entries yield the new path."""
        out = self._run("status", "--porcelain").stdout
        entries = []
        for line in out.splitlines():
            if not line.strip():
                continue
            code, rest = line[:2], line[3:]
            if " -> " in rest:
                rest = rest.split(" -> ", 1)[1]
            path = rest.strip()
            if path.startswith('"') and path.endswith('"'):
                path = path[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape")
            entries.append((code.strip() or "??", path))
        return entries

    def is_clean(self):
        return not self.status_porcelain()

    def changed_paths_since(self, base_sha):
        out = self._run("diff", "--name-only", base_sha, "HEAD").stdout
        return [l.strip() for l in out.splitlines() if l.strip()]

    # -- actions ---------------------------------------------------------
    def checkout(self, branch):
        self._run("checkout", "--quiet", branch)

    def create_branch(self, name, start_point):
        self._run("checkout", "--quiet", "-B", name, start_point)

    def add_all_and_commit(self, message):
        self._run("add", "-A")
        if self.is_clean():
            return None
        self._run("commit", "--quiet", "-m", message)
        return self.head_sha()

    def restore_paths(self, paths):
        """Revert the given paths to HEAD; untracked ones are deleted."""
        tracked, untracked = [], []
        for st, path in self.status_porcelain():
            if path in paths:
                (untracked if st == "??" else tracked).append(path)
        if tracked:
            self._run("checkout", "HEAD", "--", *tracked)
        for path in untracked:
            target = self.root / path
            try:
                if target.is_dir() and not target.is_symlink():
                    import shutil
                    shutil.rmtree(target)
                else:
                    target.unlink(missing_ok=True)
            except OSError as e:
                raise GitError(f"could not remove untracked forbidden path {path}: {e}")

    def hard_reset_clean(self):
        self._run("reset", "--hard", "--quiet")
        self._run("clean", "-fdq")

    def merge_ff_only(self, main_branch, candidate_branch):
        self.checkout(main_branch)
        if not self.is_clean():
            raise GitError("main branch working tree not clean before merge")
        self._run("merge", "--ff-only", "--quiet", candidate_branch)
        return self.head_sha()

    def delete_branch(self, name):
        self._run("branch", "-D", name, check=False)
