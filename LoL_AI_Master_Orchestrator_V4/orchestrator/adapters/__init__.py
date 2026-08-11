from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .fake import FakeAdapter


def make_adapter(provider, agent_cfg, *, dry_run=False):
    if dry_run:
        return FakeAdapter(provider, agent_cfg)
    if provider == "claude":
        return ClaudeAdapter(agent_cfg)
    if provider == "codex":
        return CodexAdapter(agent_cfg)
    raise ValueError(f"unknown provider: {provider}")
