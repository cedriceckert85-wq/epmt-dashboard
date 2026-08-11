"""Single-writer lock (state/orchestrator.lock).

Exactly one orchestrator process may mutate canonical state. The lock is
a JSON file created with O_CREAT|O_EXCL (atomic on POSIX and Windows).
A lock whose PID is provably dead on the same host is *stale*; stealing
it is only allowed as an explicit takeover (recover/unlock path), never
silently.
"""
import json, os, socket
from contextlib import contextmanager
from pathlib import Path

from .journal import utc_now

try:
    import fcntl
    _HAVE_FLOCK = True
except ImportError:                         # Windows
    fcntl = None
    _HAVE_FLOCK = False

try:
    import msvcrt
except ImportError:
    msvcrt = None


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

    @contextmanager
    def _guard(self):
        """Cross-process guard mutex serializing the check-then-act window
        of stale takeover, so two processes can never both conclude the
        lock is stale and both delete/recreate it. Held only for the brief
        inspect+unlink+create sequence, never for a whole phase."""
        guard_path = self.path.with_name(self.path.name + ".guard")
        guard_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(guard_path, os.O_CREAT | os.O_RDWR)
        try:
            if _HAVE_FLOCK:
                fcntl.flock(fd, fcntl.LOCK_EX)
            elif msvcrt is not None:
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            yield
        finally:
            try:
                if _HAVE_FLOCK:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                elif msvcrt is not None:
                    try:
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
            finally:
                os.close(fd)

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
            if takeover_stale:
                # Serialize the entire takeover (inspect + unlink + create)
                # under the guard so a second process cannot slip a live
                # lock into the gap. atomically_takeover creates the new
                # lock itself when it wins.
                fd = self._atomically_takeover_stale()
                if fd is None:
                    exists, info, stale = self.inspect()
                    holder = (info or {}).get("pid", "unknown")
                    raise LockHeldError(
                        f"orchestrator lock held (pid={holder}, stale={stale})",
                        stale=stale)
            else:
                exists, info, stale = self.inspect()
                if not exists:
                    return self.acquire(takeover_stale=False)   # raced a release
                holder = (info or {}).get("pid", "unknown")
                raise LockHeldError(
                    f"orchestrator lock held (pid={holder}, stale={stale})", stale=stale)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(self._payload())
            f.flush()
            os.fsync(f.fileno())
        self._owned = True
        return self

    def _atomically_takeover_stale(self):
        """Under the guard mutex: re-inspect; if (still) stale, unlink and
        O_EXCL-create in one uninterrupted critical section. Returns the
        open fd of the freshly created lock, or None if not takeable."""
        with self._guard():
            exists, info, stale = self.inspect()
            if exists and not stale:
                return None                    # someone holds a LIVE lock — refuse
            if exists:                          # stale — remove before recreating
                self.path.unlink(missing_ok=True)
            try:
                return os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                # lost the create race despite the guard (belt-and-suspenders):
                # treat as held, fail closed rather than clobber.
                return None

    def break_stale(self):
        """Remove a lock only after verifying it is stale, under the guard
        mutex so the check-then-act window is not racy. Fail closed."""
        with self._guard():
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
