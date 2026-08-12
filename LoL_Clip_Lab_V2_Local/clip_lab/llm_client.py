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
                except (json.JSONDecodeError, RecursionError):
                    return None
    return None


def _extract_json(text, max_attempts=64):
    """Return the first top-level JSON value in `text`, scanning left to right.

    LLM CLIs wrap JSON in prose and may return either an object OR an array, so
    we start at the EARLIEST bracket (whichever comes first) rather than always
    trying '{' before '['. Trying '{' first would grab the first element of a
    top-level array instead of the array itself.

    max_attempts bounds the number of failed start positions tried: a hostile
    reply of e.g. 100k unbalanced braces would otherwise cost O(n^2) — minutes
    of CPU — while any legitimate reply succeeds within the first few."""
    attempts = 0
    for i, ch in enumerate(text):
        if ch in _CLOSER:
            parsed = _balanced_at(text, i)
            if parsed is not None:
                return parsed
            attempts += 1
            if attempts >= max_attempts:
                return None
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
        """Return parsed JSON (dict/list) or None.

        The prompt goes to the CLI via stdin by default. If the configured
        command contains a "{prompt}" placeholder, it is substituted as an
        ARGUMENT instead (for CLIs that don't read stdin) — note that OS
        argument-length limits make this unsuitable for very long prompts."""
        if self._runner is not None:
            out = self._runner(prompt)
            return _extract_json(out) if isinstance(out, str) else out
        cmd = list(self.cmd)
        kw = {"input": prompt}
        if any("{prompt}" in c for c in cmd):
            cmd = [c.replace("{prompt}", prompt) for c in cmd]
            # closed stdin so a CLI that unexpectedly reads it fails fast
            # instead of hanging on the terminal until the timeout
            kw = {"stdin": subprocess.DEVNULL}
        try:
            p = subprocess.run(cmd, capture_output=True,
                               text=True, timeout=self.timeout_s,
                               encoding="utf-8", errors="replace", **kw)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return None
        if p.returncode != 0:
            return None
        return _extract_json(p.stdout or "")
