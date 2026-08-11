"""Single-writer lock: two orchestrators, stale lock, safe takeover."""
import json, os
import pytest

from orchestrator.lock import SingleWriterLock, LockHeldError, LockError


def test_acquire_release_roundtrip(tmp_path):
    lock = SingleWriterLock(tmp_path / "o.lock")
    lock.acquire()
    assert lock.owned and (tmp_path / "o.lock").exists()
    lock.release()
    assert not (tmp_path / "o.lock").exists()


def test_two_orchestrators_simultaneously_blocked(tmp_path):
    a = SingleWriterLock(tmp_path / "o.lock")
    b = SingleWriterLock(tmp_path / "o.lock")
    a.acquire()
    with pytest.raises(LockHeldError) as e:
        b.acquire()
    assert e.value.stale is False
    a.release()
    b.acquire()   # free after release
    b.release()


def _write_stale(path, pid=99999999):
    import socket
    path.write_text(json.dumps({"pid": pid, "host": socket.gethostname(),
                                "created_utc": "2026-01-01T00:00:00Z"}))


def test_stale_lock_detected_and_not_silently_stolen(tmp_path):
    p = tmp_path / "o.lock"
    _write_stale(p)
    lock = SingleWriterLock(p)
    exists, info, stale = lock.inspect()
    assert exists and stale
    with pytest.raises(LockHeldError) as e:
        lock.acquire()               # default: NEVER silently steals
    assert e.value.stale is True


def test_stale_lock_explicit_takeover(tmp_path):
    p = tmp_path / "o.lock"
    _write_stale(p)
    lock = SingleWriterLock(p)
    lock.acquire(takeover_stale=True)
    assert lock.owned
    lock.release()


def test_break_refuses_live_lock(tmp_path):
    p = tmp_path / "o.lock"
    _write_stale(p, pid=os.getpid())   # our own pid == alive
    with pytest.raises(LockError):
        SingleWriterLock(p).break_stale()


def test_unreadable_lock_is_not_stale(tmp_path):
    p = tmp_path / "o.lock"
    p.write_text("{corrupt")
    exists, info, stale = SingleWriterLock(p).inspect()
    assert exists and info is None and stale is False   # fail closed
