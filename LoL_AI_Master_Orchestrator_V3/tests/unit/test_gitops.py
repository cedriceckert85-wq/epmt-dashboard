"""Git control plane: worktrees, orchestrator commits, diff enumeration,
ff-only merge integrity, dirty/wrong-branch detection."""
import pytest

from orchestrator.gitops import GitOps, GitError
from tests.util.fixture_project import make_fixture_project


@pytest.fixture
def repo(tmp_path):
    root = make_fixture_project(tmp_path)
    return root, GitOps(root, main_branch="main")


def test_clean_and_dirty_detection(repo):
    root, git = repo
    assert git.is_clean()
    (root / "junk.txt").write_text("x")
    assert not git.is_clean()
    assert "junk.txt" in git.dirty_paths()
    # orchestrator-owned prefix exclusion
    assert git.is_clean(exclude_prefixes=("junk.txt",))


def test_wrong_branch_detection_and_merge_refusal(repo):
    root, git = repo
    git._git("checkout", "-b", "feature")
    assert git.current_branch() == "feature"
    with pytest.raises(GitError):
        git.merge_ff_only("HEAD")


def test_worktree_commit_diff_merge_roundtrip(repo):
    root, git = repo
    base = git.rev_parse("main")
    wt = git.create_worktree(root / ".orchestrator" / "worktrees" / "r1",
                             "candidate/r1", base)
    (wt / "src").mkdir()
    (wt / "src" / "new.py").write_text("x = 1\n")
    assert git.commit_all(wt, "empty check") is not None
    sha = git.rev_parse("HEAD", cwd=wt)
    assert git.changed_paths(wt, base) == ["src/new.py"]
    merged = git.merge_ff_only(sha)
    assert merged == sha                       # merged SHA == candidate SHA
    git.remove_worktree(wt, branch="candidate/r1")
    assert not wt.exists()


def test_commit_all_returns_none_without_changes(repo):
    root, git = repo
    base = git.rev_parse("main")
    wt = git.create_worktree(root / ".orchestrator" / "worktrees" / "r2",
                             "candidate/r2", base)
    assert git.commit_all(wt, "nothing") is None
    assert git.commit_all(wt, "forced", allow_empty=True) is not None


def test_untracked_files_count_as_changed(repo):
    root, git = repo
    base = git.rev_parse("main")
    wt = git.create_worktree(root / ".orchestrator" / "worktrees" / "r3",
                             "candidate/r3", base)
    (wt / "loose.txt").write_text("untracked")
    assert "loose.txt" in git.changed_paths(wt, base)
