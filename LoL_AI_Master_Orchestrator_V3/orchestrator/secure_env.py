"""Subprocess environment sanitization.

Deterministic test runs must never see provider secrets
(config: security.test_env_must_strip_provider_secrets). Agent runs get
their own provider's credentials but never the other vendor's, and never
Riot/production secrets.
"""

# case-insensitive substring match on the variable NAME
SECRET_NAME_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "AUTH")

PROVIDER_PREFIXES = {
    "claude": ("ANTHROPIC_", "CLAUDE_"),
    "codex": ("OPENAI_", "CODEX_", "CHATGPT_"),
}
OTHER_SENSITIVE_PREFIXES = (
    "RIOT_", "AWS_", "AZURE_", "GOOGLE_", "GCP_", "GH_", "GITHUB_",
    "TWITCH_", "YOUTUBE_", "DISCORD_", "TAILSCALE_", "TS_AUTH",
)

# always kept even though the name may contain a marker substring
SAFE_NAMES = {"PATH", "PATHEXT", "PYTHONPATH", "PYTHONHOME", "SYSTEMROOT", "COMSPEC"}

# git's -c pass-through family (GIT_CONFIG_COUNT/KEY_n/VALUE_n) is atomic:
# stripping only the KEY_n members leaves git unable to parse its config,
# and the VALUE_n members may carry credentials — drop the whole family.
ATOMIC_DROP_PREFIXES = ("GIT_CONFIG_",)


def _is_secret_name(name):
    up = name.upper()
    if up in SAFE_NAMES:
        return False
    if any(up.startswith(p) for p in ATOMIC_DROP_PREFIXES):
        return True
    return any(m in up for m in SECRET_NAME_MARKERS)


def env_for_tests(base_env):
    """Environment for deterministic test commands: NO provider secrets,
    no generic credential-looking variables at all."""
    out = {}
    for k, v in (base_env or {}).items():
        up = k.upper()
        if any(up.startswith(p) for prefixes in PROVIDER_PREFIXES.values() for p in prefixes):
            continue
        if any(up.startswith(p) for p in OTHER_SENSITIVE_PREFIXES):
            continue
        if _is_secret_name(k):
            continue
        out[k] = v
    return out


def env_for_agent(base_env, provider):
    """Environment for an agent CLI: keeps the agent's own provider
    variables, strips the other vendor's and all Riot/cloud secrets."""
    own = PROVIDER_PREFIXES.get(provider, ())
    foreign = tuple(p for prov, prefixes in PROVIDER_PREFIXES.items()
                    if prov != provider for p in prefixes)
    out = {}
    for k, v in (base_env or {}).items():
        up = k.upper()
        if any(up.startswith(p) for p in own):
            out[k] = v
            continue
        if any(up.startswith(p) for p in foreign):
            continue
        if any(up.startswith(p) for p in OTHER_SENSITIVE_PREFIXES):
            continue
        if any(up.startswith(p) for p in ATOMIC_DROP_PREFIXES):
            continue
        # defense in depth: don't hand the agent the host's SSH agent socket
        # or any generic credential-looking variable it has no need for.
        if k == "SSH_AUTH_SOCK" or _is_secret_name(k):
            continue
        out[k] = v
    return out
