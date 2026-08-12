import json
import os
import tempfile

import pytest

from orchestrator import integrity
from orchestrator.models import Lifecycle
from orchestrator.state import (DEFAULT_STATE, SingleWriterLock, StateError,
                                StateStore)


def _symlinks_work():
    # these tests are the Phase-00 self-check; on a normal (non-admin,
    # Developer-Mode-off) Windows box os.symlink raises OSError [WinError 1314].
    # Skip rather than fail the whole self-check and block the user at phase 00.
    try:
        with tempfile.TemporaryDirectory() as d:
            t = os.path.join(d, "t"); open(t, "w").close()
            os.symlink(t, os.path.join(d, "l"))
            return True
    except (OSError, NotImplementedError, AttributeError):
        return False


requires_symlinks = pytest.mark.skipif(
    not _symlinks_work(),
    reason="symlink creation unavailable (non-admin Windows without Developer Mode)")


def make_store(tmp_path):
    return StateStore(tmp_path / "state/project_state.json",
                      tmp_path / "state/journal.jsonl")


def test_init_and_load(tmp_path):
    store = make_store(tmp_path)
    store.init_if_missing()
    st = store.load()
    assert st["phase_id"] == "00" and st["lifecycle"] == "READY"


def test_corrupt_state_fails_closed(tmp_path):
    store = make_store(tmp_path)
    store.state_file.parent.mkdir(parents=True)
    store.state_file.write_text("{not json", encoding="utf-8")
    with pytest.raises(StateError):
        store.load()


def test_unknown_lifecycle_fails_closed(tmp_path):
    store = make_store(tmp_path)
    store.state_file.parent.mkdir(parents=True)
    bad = dict(DEFAULT_STATE, lifecycle="TOTALLY_FINE")
    store.state_file.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(StateError):
        store.load()


def test_transition_persists_and_journals(tmp_path):
    store = make_store(tmp_path)
    store.init_if_missing()
    st = store.load()
    st = store.transition(st, Lifecycle.BUILDING, run_id="r1")
    again = store.load()
    assert again["lifecycle"] == "BUILDING" and again["run_id"] == "r1"
    lines = [json.loads(l) for l in store.journal_file.read_text().splitlines()]
    assert any(l["event"] == "lifecycle_transition" and l["to"] == "BUILDING" for l in lines)


def test_sequence_increments(tmp_path):
    store = make_store(tmp_path)
    store.init_if_missing()
    st = store.load()
    seq = st["sequence"]
    st = store.save(st)
    assert st["sequence"] == seq + 1


def test_lock_blocks_other_live_process(tmp_path):
    import subprocess
    import sys
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        lf = tmp_path / "o.lock"
        lf.write_text(str(child.pid))
        lock = SingleWriterLock(lf)
        with pytest.raises(StateError):
            lock.acquire()
    finally:
        child.kill()
        child.wait()
    # once the holder is dead the lock is stale and taken over
    lock.acquire()
    assert lf.read_text().strip() == str(os.getpid())
    lock.release()
    assert not lf.exists()


def test_stale_lock_taken_over(tmp_path):
    lf = tmp_path / "o.lock"
    lf.write_text("999999999")  # certainly dead pid
    lock = SingleWriterLock(lf)
    lock.acquire()
    assert lf.read_text().strip() == str(os.getpid())
    lock.release()


def test_integrity_detects_tamper(tmp_path):
    (tmp_path / "state").mkdir()
    f = tmp_path / "state" / "project_state.json"
    f.write_text("{}", encoding="utf-8")
    before = integrity.snapshot(tmp_path)
    f.write_text('{"hacked": true}', encoding="utf-8")
    (tmp_path / "reports" / "human-gates").mkdir(parents=True)
    (tmp_path / "reports" / "human-gates" / "fake.json").write_text("{}", encoding="utf-8")
    diffs = integrity.diff_snapshots(before, integrity.snapshot(tmp_path))
    assert any("modified: state/project_state.json" in d for d in diffs)
    assert any("added: reports/human-gates/fake.json" in d for d in diffs)


def test_integrity_clean_when_untouched(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "x.json").write_text("{}", encoding="utf-8")
    before = integrity.snapshot(tmp_path)
    assert integrity.diff_snapshots(before, integrity.snapshot(tmp_path)) == []


def test_integrity_guards_venv_code_not_caches(tmp_path):
    # every executable-as-source venv file is guarded (real injection surface),
    # but benign non-code lazy caches are not (no false-positive BLOCK).
    sp = tmp_path / ".venv" / "lib" / "site-packages"
    sp.mkdir(parents=True)
    (sp / "yaml").mkdir()
    (sp / "yaml" / "__init__.py").write_text("# ok", encoding="utf-8")
    (sp / "mpl-data").mkdir()
    before = integrity.snapshot(tmp_path)
    # benign non-code cache writes inside .venv -> NOT flagged
    (sp / "mpl-data" / "fontcache.json").write_text("{}", encoding="utf-8")
    (sp / "numba_cache.nbi").write_text("x", encoding="utf-8")
    (sp / "proj.db").write_text("x", encoding="utf-8")
    assert integrity.diff_snapshots(before, integrity.snapshot(tmp_path)) == []
    # overwriting an imported dependency MODULE (the real attack) -> flagged
    before2 = integrity.snapshot(tmp_path)
    (sp / "yaml" / "__init__.py").write_text("import os  # injected", encoding="utf-8")
    assert any("yaml/__init__.py" in d for d in
               integrity.diff_snapshots(before2, integrity.snapshot(tmp_path)))


def test_integrity_guards_git_hooks_and_config(tmp_path):
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    (tmp_path / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    before = integrity.snapshot(tmp_path)
    (tmp_path / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh\nevil\n", encoding="utf-8")
    (tmp_path / ".git" / "config").write_text("[core]\n\thooksPath = /tmp/evil\n", encoding="utf-8")
    diffs = integrity.diff_snapshots(before, integrity.snapshot(tmp_path))
    assert any(".git/hooks/pre-commit" in d for d in diffs)
    assert any(".git/config" in d for d in diffs)


def test_integrity_content_hash_defeats_mtime_reset(tmp_path):
    # same-size overwrite with mtime restored must still be detected
    # (content hash, not size+mtime).
    import os
    (tmp_path / "state").mkdir()
    f = tmp_path / "state" / "x.json"
    f.write_text("AAAA", encoding="utf-8")
    st = f.stat()
    before = integrity.snapshot(tmp_path)
    f.write_text("BBBB", encoding="utf-8")  # same length
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))  # restore mtime
    assert f.stat().st_mtime_ns == st.st_mtime_ns and f.stat().st_size == st.st_size
    assert any("x.json" in d for d in
               integrity.diff_snapshots(before, integrity.snapshot(tmp_path)))


@requires_symlinks
def test_integrity_detects_planted_symlink(tmp_path):
    # a forged record planted as a symlink (not followed) must show up as
    # an added entry, not be silently skipped.
    (tmp_path / "reports" / "human-gates").mkdir(parents=True)
    outside = tmp_path / "forged.json"
    outside.write_text('{"decision":"APPROVE"}', encoding="utf-8")
    before = integrity.snapshot(tmp_path)
    link = tmp_path / "reports" / "human-gates" / "phase-01-abc.json"
    link.symlink_to(outside)
    diffs = integrity.diff_snapshots(before, integrity.snapshot(tmp_path))
    assert any("added: reports/human-gates/phase-01-abc.json" in d for d in diffs)


@requires_symlinks
def test_integrity_symlinked_venv_entrypoint_detected(tmp_path):
    sp = tmp_path / ".venv" / "lib" / "site-packages"
    sp.mkdir(parents=True)
    outside = tmp_path / "evil.py"
    outside.write_text("import os", encoding="utf-8")
    before = integrity.snapshot(tmp_path)
    (sp / "sitecustomize.py").symlink_to(outside)
    diffs = integrity.diff_snapshots(before, integrity.snapshot(tmp_path))
    assert any("sitecustomize.py" in d for d in diffs)


def test_integrity_exclude_exempts_artifact_dir(tmp_path):
    (tmp_path / ".orchestrator" / "artifacts" / "run1").mkdir(parents=True)
    before = integrity.snapshot(tmp_path, exclude=[".orchestrator/artifacts"])
    (tmp_path / ".orchestrator" / "artifacts" / "run1" / "log.txt").write_text("evidence", encoding="utf-8")
    after = integrity.snapshot(tmp_path, exclude=[".orchestrator/artifacts"])
    assert integrity.diff_snapshots(before, after) == []
