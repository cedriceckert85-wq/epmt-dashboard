"""Claude CLI adapter.

Mode: non-interactive `claude -p` with --output-format json; the agent is
instructed (via the routed prompt) to end with a single JSON object per
schemas/agent_result.schema.json. The reviewer role runs with write tools
disallowed; builder writes are constrained afterwards by the diff-based
path policy — the adapter NEVER trusts the CLI sandbox alone.

No flag is assumed without a capability check: doctor() greps `--help`
for every flag this adapter uses and run() fails closed if doctor has not
confirmed them.
"""
import os

from .base import AgentAdapter
from ..models import AgentRunResult
from ..process_runner import ProcessRunner
from ..result_validation import extract_structured
from ..secure_env import env_for_agent

REQUIRED_FLAGS = ("--print", "--output-format", "--permission-mode", "--disallowedTools")
WRITE_TOOLS = "Edit Write NotebookEdit Bash"


class ClaudeAdapter(AgentAdapter):
    provider = "claude"

    def __init__(self, executable="claude", *, timeout_s=3600, runner=None,
                 pinned_version=None, base_env=None):
        self.executable = executable
        self.timeout_s = timeout_s
        self.runner = runner or ProcessRunner()
        self.pinned_version = pinned_version
        self.base_env = base_env
        self._caps = None

    # --- doctor ----------------------------------------------------------
    def doctor(self):
        report = {"provider": self.provider, "available": False, "version": None,
                  "flags_ok": False, "pinned_ok": None, "detail": ""}
        v = self.runner.run([self.executable, "--version"], cwd=".",
                            timeout_s=30, env=self._env())
        if v.timed_out or v.exit_code != 0:
            report["detail"] = f"claude --version failed (exit={v.exit_code}, timeout={v.timed_out}): {v.stderr.strip()[:200]}"
            self._caps = report
            return report
        report["available"] = True
        report["version"] = v.stdout.strip().splitlines()[0] if v.stdout.strip() else "unknown"
        h = self.runner.run([self.executable, "--help"], cwd=".",
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

    # --- run -------------------------------------------------------------
    def run(self, request):
        caps = self._caps or self.doctor()
        if not caps["available"] or not caps["flags_ok"] or caps.get("pinned_ok") is False:
            return AgentRunResult(self.provider, 127, False, "",
                                  f"claude CLI unavailable/capabilities unverified: {caps['detail']}",
                                  None, 0.0)
        prompt = request.prompt_file.read_text(encoding="utf-8")
        argv = [self.executable, "-p", prompt, "--output-format", "json"]
        if str(request.role) == "reviewer":
            argv += ["--permission-mode", "default", "--disallowedTools", WRITE_TOOLS]
        else:
            argv += ["--permission-mode", "acceptEdits"]
        r = self.runner.run(argv, cwd=str(request.workspace),
                            timeout_s=min(request.timeout_s, self.timeout_s),
                            env=self._env())
        return AgentRunResult(
            provider=self.provider, exit_code=r.exit_code, timed_out=r.timed_out,
            stdout=r.stdout, stderr=r.stderr,
            structured=extract_structured(r.stdout) if not r.timed_out else None,
            duration_s=r.duration_s,
        )
