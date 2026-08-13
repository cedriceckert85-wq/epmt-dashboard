"""LLM-Anbindung: Prompt via stdin (oder {prompt}-Platzhalter) an eine
konfigurierbare CLI.

- Executable wird via shutil.which zum vollen Pfad aufgeloest
  (Windows-.cmd-Shims funktionieren sonst nicht mit subprocess!).
- Timeout; jede Stoerung liefert None (Degradation entscheidet der Aufrufer).
- Ein "Runner" ist einfach ein Callable ``prompt -> str | None`` —
  Tests und der Selftest injizieren deterministische Fakes.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Callable

RunFn = Callable[..., "subprocess.CompletedProcess"]


def resolve_cmd(cmd: list[str] | None, which=shutil.which) -> list[str] | None:
    """Kommandoliste aufloesen; None wenn leer oder Executable fehlt."""
    if not cmd or not isinstance(cmd, list):
        return None
    head = cmd[0]
    if not isinstance(head, str) or not head.strip():
        return None
    exe = which(head)
    if exe is None:
        return None
    return [exe] + [str(a) for a in cmd[1:]]


class CliLLM:
    """Runner um eine externe LLM-CLI (z.B. ``claude -p``)."""

    def __init__(
        self,
        cmd: list[str],
        timeout_s: float = 240.0,
        run_fn: RunFn | None = None,
        which=shutil.which,
    ):
        self.cmd = list(cmd) if cmd else []
        self.timeout_s = timeout_s
        self._run_fn = run_fn or subprocess.run
        self._which = which

    def available(self) -> bool:
        return resolve_cmd(self.cmd, which=self._which) is not None

    def __call__(self, prompt: str) -> str | None:
        return self.run(prompt)

    def run(self, prompt: str) -> str | None:
        argv = resolve_cmd(self.cmd, which=self._which)
        if argv is None:
            return None
        uses_placeholder = any("{prompt}" in a for a in argv[1:])
        if uses_placeholder:
            argv = [a.replace("{prompt}", prompt) for a in argv]
            stdin_text = None
        else:
            stdin_text = prompt
        try:
            proc = self._run_fn(
                argv,
                input=stdin_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_s,
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        out = getattr(proc, "stdout", None)
        if not isinstance(out, str) or not out.strip():
            return None
        if getattr(proc, "returncode", 1) != 0 and not out.strip():
            return None
        return out
