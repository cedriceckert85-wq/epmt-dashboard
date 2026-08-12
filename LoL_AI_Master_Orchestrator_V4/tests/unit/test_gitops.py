"""Git control-plane robustness against hostile-but-legitimate user configs."""
import subprocess

from orchestrator.gitops import GitRepo


def _init(tmp_path):
    repo = GitRepo(tmp_path)
    repo.init("main")
    return repo


def test_init_lands_on_main(tmp_path):
    repo = _init(tmp_path)
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    repo.add_all_and_commit("first")
    assert repo.current_branch() == "main"


def test_commits_ignore_global_gpgsign(tmp_path):
    # a user with commit.gpgsign=true + a broken signer must NOT break the
    # orchestrator's commits (control-plane commits run -c commit.gpgsign=false).
    repo = _init(tmp_path)
    subprocess.run(["git", "config", "commit.gpgsign", "true"], cwd=tmp_path,
                   capture_output=True)
    subprocess.run(["git", "config", "gpg.program", "/nonexistent-signer"],
                   cwd=tmp_path, capture_output=True)
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    sha = repo.add_all_and_commit("must succeed unsigned")
    assert sha and len(sha) >= 7


def test_hooks_are_neutralized(tmp_path):
    repo = _init(tmp_path)
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    (hooks / "pre-commit").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    import os
    os.chmod(hooks / "pre-commit", 0o755)
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    # a failing pre-commit hook would abort the commit if hooks were enabled
    assert repo.add_all_and_commit("hook must not run") is not None
