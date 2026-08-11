"""Claude Code CLI adapter.

Non-interactive mode: `claude -p` with the prompt pointer on stdin.
Builder runs with --dangerously-skip-permissions inside the project
workspace (the workspace is the sandbox); write-path discipline is
enforced afterwards by the orchestrator's git-diff inspection, which is
the actual security boundary. Reviewer runs the same way but every write
outside reports/ is reverted and counted as a violation.

All flags are overridable via ORCHESTRATOR_CONFIG.yaml agents.claude.args.
"""
from .base import AgentAdapter


class ClaudeAdapter(AgentAdapter):
    provider = "claude"

    def build_argv(self, request):
        argv = [self.executable, "-p", "--output-format", "json"]
        extra = self.cfg.get("args")
        if extra:
            argv += list(extra)
        else:
            argv += ["--dangerously-skip-permissions"]
            model = self.cfg.get("model")
            if model:
                argv += ["--model", model]
        return argv

    def stdin_text(self, request):
        return self.pointer_text(request)
