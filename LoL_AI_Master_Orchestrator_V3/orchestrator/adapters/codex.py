"""Codex CLI adapter.

Mode: `codex exec` with an explicit sandbox: reviewer = read-only,
builder = workspace-write. The structured report is read from
--output-last-message (a file the orchestrator owns), falling back to
stdout extraction. As with the Claude adapter, every flag is
capability-checked via doctor() first; if the Codex CLI is not installed
the adapter reports unavailable and the engine blocks fail-closed — a
missing reviewer NEVER skips review.
"""
import os
from pathlib import Path

from .base import AgentAdapter
from ..models import AgentRunResult
from ..process_runner import ProcessRunner
from ..result_validation import extract_structured
from ..secure_env import env_for_agent

REQUIRED_FLAGS = ("--sandbox", "--output-last-message")


class CodexAdapter(AgentAdapter):
    provider = "codex"

    def __init__(self, executable="codex", *, timeout_s=3600, runner=None,
                 pinned_version=None, base_env=None):
        self.executable = executable
        self.timeout_s = timeout_s
        self.runner = runner or ProcessRunner()
        self.pinned_version = pinned_version
        self.base_env = base_env
        self._caps = None

    def doctor(self):
        report = {"provider": self.provider, "available": False, "version": None,
                  "flags_ok": False, "pinned_ok": None, "detail": ""}
        v = self.runner.run([self.executable, "--version"], cwd=".",
                            timeout_s=30, env=self._env())
        if v.timed_out or v.exit_code != 0:
            report["detail"] = f"codex --version failed (exit={v.exit_code}, timeout={v.timed_out}): {v.stderr.strip()[:200]}"
            self._caps = report
            return report
        report["available"] = True
        report["version"] = v.stdout.strip().splitlines()[0] if v.stdout.strip() else "unknown"
        h = self.runner.run([self.executable, "exec", "--help"], cwd=".",
                            timeout_s=30, env=self._env())
        missing = [f for f in REQUIRED_FLAGS if f not in (h.stdout + h.stderr)]
        report["flags_ok"] = not missing
        if missing:
            report["detail"] = "missing capabilities: " + ", ".join(missing)
        if self.pinned_version is not None:
            report["pinned_ok"] = self.pinned_version in report["version"]
            if not report["pinned_ok"]:
                report["detail"] += f" version drift: pinned {self.pinned_version!r} vs {report['version']!r}"
        self._caps = report
        return report

    def _env(self):
        return env_for_agent(self.base_env if self.base_env is not None else dict(os.environ),
                             self.provider)

    def run(self, request):
        caps = self._caps or self.doctor()
        if not caps["available"] or not caps["flags_ok"] or caps.get("pinned_ok") is False:
            return AgentRunResult(self.provider, 127, False, "",
                                  f"codex CLI unavailable/capabilities unverified: {caps['detail']}",
                                  None, 0.0)
        prompt = request.prompt_file.read_text(encoding="utf-8")
        sandbox = "read-only" if str(request.role) == "reviewer" else "workspace-write"
        last_msg = Path(request.workspace) / f".codex-last-{request.run_id}-{request.role}.txt"
        argv = [self.executable, "exec",
                "--sandbox", sandbox,
                "--output-last-message", str(last_msg),
                prompt]
        r = self.runner.run(argv, cwd=str(request.workspace),
                            timeout_s=min(request.timeout_s, self.timeout_s),
                            env=self._env())
        structured = None
        if not r.timed_out:
            try:
                structured = extract_structured(last_msg.read_text(encoding="utf-8"))
            except FileNotFoundError:
                structured = extract_structured(r.stdout)
        try:
            last_msg.unlink(missing_ok=True)
        except OSError:
            pass
        return AgentRunResult(
            provider=self.provider, exit_code=r.exit_code, timed_out=r.timed_out,
            stdout=r.stdout, stderr=r.stderr, structured=structured,
            duration_s=r.duration_s,
        )
