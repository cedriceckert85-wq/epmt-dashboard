"""Single-writer lock (state/orchestrator.lock).

Exactly one orchestrator process may mutate canonical state. The lock is
a JSON file created with O_CREAT|O_EXCL (atomic on POSIX and Windows).
A lock whose PID is provably dead on the same host is *stale*; stealing
it is only allowed as an explicit takeover (recover/unlock path), never
silently.
"""
import json, os, socket
from pathlib import Path

from .journal import utc_now


class LockError(Exception):
    pass


class LockHeldError(LockError):
    def __init__(self, msg, *, stale):
        super().__init__(msg)
        self.stale = stale


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class SingleWriterLock:
    def __init__(self, path):
        self.path = Path(path)
        self._owned = False

    @property
    def owned(self):
        return self._owned

    def _payload(self):
        return json.dumps({
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "created_utc": utc_now(),
        }, indent=2)

    def inspect(self):
        """Returns (exists, info_dict|None, stale:bool)."""
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return False, None, False
        try:
            info = json.loads(raw)
        except json.JSONDecodeError:
            # unreadable lock: treat as held-but-unverifiable => NOT stale
            return True, None, False
        same_host = info.get("host") == socket.gethostname()
        pid = info.get("pid")
        stale = bool(same_host and isinstance(pid, int) and not _pid_alive(pid))
        return True, info, stale

    def acquire(self, *, takeover_stale=False):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            exists, info, stale = self.inspect()
            if not exists:
                # raced a release; try once more, still fail closed
                return self.acquire(takeover_stale=takeover_stale)
            if stale and takeover_stale:
                self.break_stale()
                return self.acquire(takeover_stale=False)
            holder = (info or {}).get("pid", "unknown")
            raise LockHeldError(
                f"orchestrator lock held (pid={holder}, stale={stale})", stale=stale)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(self._payload())
            f.flush()
            os.fsync(f.fileno())
        self._owned = True
        return self

    def break_stale(self):
        """Remove a lock only after verifying it is stale. Fail closed."""
        exists, info, stale = self.inspect()
        if not exists:
            return False
        if not stale:
            raise LockError("refusing to break a non-stale lock")
        self.path.unlink(missing_ok=True)
        return True

    def release(self):
        if not self._owned:
            return
        exists, info, _ = self.inspect()
        if exists and info and info.get("pid") == os.getpid():
            self.path.unlink(missing_ok=True)
        self._owned = False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False
