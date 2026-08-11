"""Adapter contract: run a provider CLI as an isolated child process on a
prompt file and hand back the raw process result. Reading/validating the
structured agent_result.json is done by the caller (resultio) — adapters
never interpret model output as authority.
"""
import os
from abc import ABC, abstractmethod

from ..models import AgentRunResult
from ..process_runner import ProcessRunner

RETRYABLE_INFRASTRUCTURE = 75


class AgentAdapter(ABC):
    provider = "base"

    def __init__(self, agent_cfg):
        self.cfg = agent_cfg or {}
        self.runner = ProcessRunner()

    @property
    def executable(self):
        return self.cfg.get("executable", self.provider)

    @property
    def timeout_s(self):
        return int(self.cfg.get("timeout_s", 3600))

    def env(self):
        return dict(os.environ)

    @abstractmethod
    def build_argv(self, request):
        """argv for the CLI invocation. May reference the prompt pointer."""

    def stdin_text(self, request):
        """Text piped to stdin (None if the CLI takes the prompt as arg)."""
        return None

    def pointer_text(self, request):
        rel = request.prompt_file
        try:
            rel = request.prompt_file.relative_to(request.workspace)
        except ValueError:
            pass
        return (f"Read the file '{rel}' in the current working directory and follow "
                f"the instructions in it exactly. It defines your role, your allowed "
                f"write paths and the required result file.")

    def run(self, request):
        res = self.runner.run(
            self.build_argv(request),
            cwd=request.workspace,
            timeout_s=min(self.timeout_s, request.timeout_s or self.timeout_s),
            env=self.env(),
            stdin_text=self.stdin_text(request),
        )
        return AgentRunResult(
            provider=self.provider, exit_code=res.exit_code, timed_out=res.timed_out,
            stdout=res.stdout, stderr=res.stderr, structured=None,
            duration_s=res.duration_s, cleanup_incomplete=res.cleanup_incomplete,
        )
