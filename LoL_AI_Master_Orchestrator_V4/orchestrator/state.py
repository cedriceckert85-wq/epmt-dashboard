"""Canonical state store + journal + generated markdown projections.

Canonical truth: state/project_state.json + state/journal.jsonl (+ git SHAs).
PROJECT_STATE.md / CURRENT_TASK.md are generated projections, never inputs.
"""
import json
import os
from pathlib import Path

from .models import Lifecycle
from .util import append_jsonl, atomic_write_json, atomic_write_text, utc_now_iso


class StateError(Exception):
    pass


SCHEMA_VERSION = 4

DEFAULT_STATE = {
    "schema_version": SCHEMA_VERSION,
    "run_id": None,
    "sequence": 0,
    "phase_id": "00",
    "lifecycle": "READY",
    "attempt": 0,
    "fix_cycles": 0,
    "candidate_branch": None,
    "candidate_commit": None,
    "tested_commit": None,
    "reviewed_commit": None,
    "approved_commit": None,
    "merged_commit": None,
    "builder_provider": None,
    "reviewer_provider": None,
    "last_gate": None,
    "human_approval_id": None,
    "blocked_reason": None,
    "deferred_tests": {},          # phase_id -> [test names deferred as UNVERIFIED]
    "phase_history": {},           # phase_id -> {"gate": "PASS", "merged_commit": ...}
}


class StateStore:
    def __init__(self, state_file, journal_file):
        self.state_file = Path(state_file)
        self.journal_file = Path(journal_file)

    def exists(self):
        return self.state_file.exists()

    def init_if_missing(self):
        if not self.exists():
            atomic_write_json(self.state_file, DEFAULT_STATE)
            self.journal("state_initialized", {})

    def load(self):
        try:
            raw = self.state_file.read_text(encoding="utf-8")
        except FileNotFoundError as e:
            raise StateError("canonical state file missing") from e
        try:
            st = json.loads(raw)
        except json.JSONDecodeError as e:
            raise StateError(f"canonical state JSON invalid: {e}") from e
        if not isinstance(st, dict) or "phase_id" not in st or "lifecycle" not in st:
            raise StateError("canonical state schema incomplete")
        if st.get("lifecycle") not in {l.value for l in Lifecycle}:
            raise StateError(f"canonical state has unknown lifecycle: {st.get('lifecycle')}")
        return st

    def save(self, st):
        st = dict(st)
        st["sequence"] = int(st.get("sequence", 0)) + 1
        atomic_write_json(self.state_file, st)
        return st

    def journal(self, event, payload):
        append_jsonl(self.journal_file, {
            "ts": utc_now_iso(),
            "pid": os.getpid(),
            "event": event,
            **payload,
        })

    def transition(self, st, new_lifecycle, **extra):
        """Persist a lifecycle transition + journal it. Legality is checked
        by gates.validate_lifecycle_transition at the call site."""
        old = st["lifecycle"]
        st = dict(st)
        st["lifecycle"] = new_lifecycle.value if isinstance(new_lifecycle, Lifecycle) else str(new_lifecycle)
        st.update(extra)
        st = self.save(st)
        self.journal("lifecycle_transition", {
            "phase_id": st["phase_id"], "from": old, "to": st["lifecycle"],
            "candidate_commit": st.get("candidate_commit"), **{k: v for k, v in extra.items() if isinstance(v, (str, int, float, bool, type(None)))},
        })
        return st


def render_projections(root, st, phase):
    """Regenerate PROJECT_STATE.md and CURRENT_TASK.md from canonical state."""
    root = Path(root)
    lines = [
        "# PROJECT STATE (generated — do not edit)",
        "",
        f"- Updated: {utc_now_iso()}",
        f"- Phase: {st['phase_id']} — {phase.get('name', '?')}",
        f"- Lifecycle: {st['lifecycle']}",
        f"- Attempt: {st.get('attempt', 0)}  Fix-Cycles: {st.get('fix_cycles', 0)}",
        f"- Candidate: {st.get('candidate_commit')}",
        f"- Last gate: {st.get('last_gate')}",
        f"- Blocked reason: {st.get('blocked_reason')}",
        "",
        "## Phase history",
    ]
    for pid in sorted(st.get("phase_history", {})):
        h = st["phase_history"][pid]
        lines.append(f"- {pid}: gate={h.get('gate')} merged={h.get('merged_commit')}"
                     + (f" deferred={h.get('deferred')}" if h.get("deferred") else ""))
    atomic_write_text(root / "PROJECT_STATE.md", "\n".join(lines) + "\n")

    task = {
        "phase_id": st["phase_id"],
        "phase_name": phase.get("name"),
        "lifecycle": st["lifecycle"],
        "builder": phase.get("builder"),
        "reviewer": phase.get("reviewer"),
        "allowed_write_paths": phase.get("allowed_write_paths", []),
        "required_tests": phase.get("required_tests", []),
        "candidate_commit": st.get("candidate_commit"),
    }
    atomic_write_json(root / "state" / "current_task.json", task)
    atomic_write_text(root / "CURRENT_TASK.md",
                      "# CURRENT TASK (generated — do not edit)\n\n```json\n"
                      + json.dumps(task, indent=2) + "\n```\n")


class SingleWriterLock:
    """PID lock file. Stale locks (dead pid) are taken over."""

    def __init__(self, lock_file):
        self.lock_file = Path(lock_file)
        self.acquired = False

    def _pid_alive(self, pid):
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def acquire(self):
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        if self.lock_file.exists():
            try:
                pid = int(self.lock_file.read_text().strip() or "0")
            except ValueError:
                pid = 0
            if pid and pid != os.getpid() and self._pid_alive(pid):
                raise StateError(
                    f"another orchestrator instance appears to be running (pid {pid}). "
                    f"If that is wrong, delete {self.lock_file} and retry.")
        atomic_write_text(self.lock_file, str(os.getpid()))
        self.acquired = True

    def release(self):
        if self.acquired and self.lock_file.exists():
            try:
                self.lock_file.unlink()
            except OSError:
                pass
        self.acquired = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
