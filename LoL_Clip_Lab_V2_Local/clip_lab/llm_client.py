"""Thin, mockable wrapper around a local LLM CLI (default: `claude -p`).

Sends a prompt on stdin, expects JSON back, extracts the first top-level JSON
object/array from the output (CLIs often wrap it in prose). Never raises on a
bad response — returns None so the caller can fall back to signal-only.
"""
import json
import subprocess


class LLMUnavailable(Exception):
    pass


_CLOSER = {"{": "}", "[": "]"}


def _balanced_at(text, start):
    """Parse a balanced {...} or [...] beginning at index `start`. Returns the
    decoded value, or None if it is not a complete, valid JSON block."""
    opener = text[start]
    closer = _CLOSER[opener]
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _extract_json(text):
    """Return the first top-level JSON value in `text`, scanning left to right.

    LLM CLIs wrap JSON in prose and may return either an object OR an array, so
    we start at the EARLIEST bracket (whichever comes first) rather than always
    trying '{' before '['. Trying '{' first would grab the first element of a
    top-level array instead of the array itself."""
    for i, ch in enumerate(text):
        if ch in _CLOSER:
            parsed = _balanced_at(text, i)
            if parsed is not None:
                return parsed
    return None


class LLMClient:
    def __init__(self, cmd, timeout_s=240, runner=None):
        self.cmd = list(cmd)
        self.timeout_s = timeout_s
        self._runner = runner  # for tests: callable(prompt)->str

    def available(self):
        if self._runner is not None:
            return True
        from shutil import which
        return which(self.cmd[0]) is not None

    def ask_json(self, prompt):
        """Return parsed JSON (dict/list) or None."""
        if self._runner is not None:
            out = self._runner(prompt)
            return _extract_json(out) if isinstance(out, str) else out
        try:
            p = subprocess.run(self.cmd, input=prompt, capture_output=True,
                               text=True, timeout=self.timeout_s,
                               encoding="utf-8", errors="replace")
        except (OSError, subprocess.TimeoutExpired):
            return None
        if p.returncode != 0:
            return None
        return _extract_json(p.stdout or "")
