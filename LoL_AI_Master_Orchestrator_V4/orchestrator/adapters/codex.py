"""Codex CLI adapter.

Non-interactive mode: `codex exec` with the prompt pointer as argument.
Sandbox is workspace-write for every role — even the reviewer must be able
to write its result file under reports/. Read-only discipline for the
reviewer is enforced afterwards by the orchestrator (writes outside
reports/ are reverted and counted as violations).

All flags are overridable via ORCHESTRATOR_CONFIG.yaml agents.codex.args.
"""
from .base import AgentAdapter


class CodexAdapter(AgentAdapter):
    provider = "codex"

    def build_argv(self, request):
        argv = [self.executable, "exec"]
        extra = self.cfg.get("args")
        if extra:
            argv += list(extra)
        else:
            argv += ["--sandbox", "workspace-write", "--skip-git-repo-check"]
            model = self.cfg.get("model")
            if model:
                argv += ["--model", model]
        argv.append(self.pointer_text(request))
        return argv
