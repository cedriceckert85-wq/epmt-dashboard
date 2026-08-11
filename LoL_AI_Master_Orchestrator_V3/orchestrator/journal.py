"""Append-only audit journal (state/journal.jsonl).

Every lifecycle transition, agent run, gate decision and recovery action
is appended here with a UTC timestamp and a monotonically increasing
per-process counter. The journal is orchestrator-owned; agents may never
write it (immutable path 'state').
"""
import json, os, time
from pathlib import Path


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Journal:
    def __init__(self, path):
        self.path = Path(path)
        self._counter = 0

    def append(self, event, **fields):
        self._counter += 1
        rec = {"ts_utc": utc_now(), "n": self._counter, "event": str(event)}
        rec.update(fields)
        line = json.dumps(rec, ensure_ascii=False, sort_keys=True, default=str)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        return rec

    def read_all(self):
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"__corrupt__": line})
        return out
