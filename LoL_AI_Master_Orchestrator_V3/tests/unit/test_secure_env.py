"""Secret stripping: tests never see provider secrets; agents never see
the other vendor's credentials."""
from orchestrator.secure_env import env_for_tests, env_for_agent

BASE = {
    "PATH": "/usr/bin", "HOME": "/home/u", "LANG": "C.UTF-8",
    "PYTHONPATH": "/x",
    "ANTHROPIC_API_KEY": "sk-ant-secret", "CLAUDE_CODE_TOKEN": "t",
    "OPENAI_API_KEY": "sk-proj-secret", "CODEX_HOME": "/c",
    "RIOT_API_KEY": "RGAPI-x", "AWS_SECRET_ACCESS_KEY": "aws",
    "GITHUB_TOKEN": "ghp_x", "MY_APP_PASSWORD": "pw",
    "SSH_AUTH_SOCK": "/tmp/agent.sock", "DB_CONNECTION": "postgres://",
}


def test_test_env_strips_all_provider_and_credential_vars():
    env = env_for_tests(BASE)
    for gone in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_TOKEN", "OPENAI_API_KEY",
                 "CODEX_HOME", "RIOT_API_KEY", "AWS_SECRET_ACCESS_KEY",
                 "GITHUB_TOKEN", "MY_APP_PASSWORD", "SSH_AUTH_SOCK"):
        assert gone not in env, gone
    for kept in ("PATH", "HOME", "LANG", "PYTHONPATH", "DB_CONNECTION"):
        assert kept in env, kept


def test_git_config_family_dropped_atomically():
    # stripping only GIT_CONFIG_KEY_n while keeping COUNT/VALUE breaks git
    # ("missing config key GIT_CONFIG_KEY_0") — the family must go entirely.
    env = dict(BASE, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.proxy",
               GIT_CONFIG_VALUE_0="http://user:secret@proxy")
    for fn in (env_for_tests, lambda e: env_for_agent(e, "claude")):
        out = fn(env)
        assert not any(k.startswith("GIT_CONFIG_") for k in out), fn


def test_agent_env_keeps_own_provider_strips_other():
    claude = env_for_agent(BASE, "claude")
    assert claude["ANTHROPIC_API_KEY"] == "sk-ant-secret"
    assert "OPENAI_API_KEY" not in claude
    assert "RIOT_API_KEY" not in claude
    codex = env_for_agent(BASE, "codex")
    assert codex["OPENAI_API_KEY"] == "sk-proj-secret"
    assert "ANTHROPIC_API_KEY" not in codex
    assert "CLAUDE_CODE_TOKEN" not in codex
