"""Fake agent adapter — drives tests/fakes/fake_agent.py as a real child
process through ProcessRunner. Used for dry-run/fake-agent mode and for
every orchestrator test. Behaves exactly like a provider adapter
(same result type, same timeout/kill semantics), so the engine under test
is the engine that runs live."""
import sys
from pathlib import Path

from .base import AgentAdapter
from ..models import AgentRunResult
from ..process_runner import ProcessRunner
from ..result_validation import extract_structured
from ..secure_env import env_for_tests


class FakeAdapter(AgentAdapter):
    def __init__(self, script_path, *, provider="fake", mode="success",
                 runner=None, base_env=None, extra_args=(), timeout_s=120):
        self.script_path = Path(script_path)
        self.provider = provider
        self.mode = mode
        self.runner = runner or ProcessRunner()
        self.base_env = base_env
        self.extra_args = tuple(extra_args)
        self.timeout_s = timeout_s

    def doctor(self):
        ok = self.script_path.exists()
        return {"provider": self.provider, "available": ok,
                "version": "fake-1" if ok else None,
                "detail": str(self.script_path)}

    def run(self, request):
        import os
        argv = [sys.executable, str(self.script_path),
                "--mode", self.mode,
                "--run-id", request.run_id,
                "--phase", request.phase_id,
                "--role", str(request.role),
                *self.extra_args]
        env = env_for_tests(self.base_env if self.base_env is not None else dict(os.environ))
        r = self.runner.run(argv, cwd=str(request.workspace),
                            timeout_s=request.timeout_s, env=env)
        return AgentRunResult(
            provider=self.provider, exit_code=r.exit_code, timed_out=r.timed_out,
            stdout=r.stdout, stderr=r.stderr,
            structured=extract_structured(r.stdout) if not r.timed_out else None,
            duration_s=r.duration_s,
        )
