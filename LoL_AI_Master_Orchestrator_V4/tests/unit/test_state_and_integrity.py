import json
import os

import pytest

from orchestrator import integrity
from orchestrator.models import Lifecycle
from orchestrator.state import (DEFAULT_STATE, SingleWriterLock, StateError,
                                StateStore)


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


def test_integrity_covers_gitignored_immutable_trees(tmp_path):
    # .venv and .orchestrator are gitignored (invisible to git status) but
    # immutable — a write there must be detected by the snapshot.
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "sitecustomize.py").write_text("# ok", encoding="utf-8")
    before = integrity.snapshot(tmp_path)
    (tmp_path / ".venv" / "lib" / "sitecustomize.py").write_text("import os  # injected", encoding="utf-8")
    (tmp_path / ".orchestrator" / "evil").mkdir(parents=True)
    (tmp_path / ".orchestrator" / "evil" / "x").write_text("y", encoding="utf-8")
    diffs = integrity.diff_snapshots(before, integrity.snapshot(tmp_path))
    assert any("sitecustomize.py" in d for d in diffs)
    assert any(".orchestrator/evil/x" in d for d in diffs)


def test_integrity_exclude_exempts_artifact_dir(tmp_path):
    (tmp_path / ".orchestrator" / "artifacts" / "run1").mkdir(parents=True)
    before = integrity.snapshot(tmp_path, exclude=[".orchestrator/artifacts"])
    (tmp_path / ".orchestrator" / "artifacts" / "run1" / "log.txt").write_text("evidence", encoding="utf-8")
    after = integrity.snapshot(tmp_path, exclude=[".orchestrator/artifacts"])
    assert integrity.diff_snapshots(before, after) == []
