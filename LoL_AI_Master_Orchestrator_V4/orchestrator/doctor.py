"""Preflight doctor: verifies host + CLI capabilities before any live run.

Fail closed: a missing builder/reviewer CLI blocks the run — there is no
fake review, ever. Optional hardware capabilities (gpu/tailscale/obs/...)
only decide which registry tests can produce real evidence; unmet ones
lead to UNVERIFIED/deferred, never to fake passes.
"""
import os
import platform
import shutil
import sys
from dataclasses import dataclass, field

from .process_runner import ProcessRunner


@dataclass
class DoctorReport:
    ok: bool
    problems: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    capabilities: dict = field(default_factory=dict)
    cli_versions: dict = field(default_factory=dict)


def _probe(argv, timeout_s=30):
    """(ok, first_line_of_output)."""
    exe = shutil.which(argv[0])
    if not exe:
        return False, f"{argv[0]} not found on PATH"
    try:
        res = ProcessRunner().run(argv, cwd=os.getcwd(), timeout_s=timeout_s,
                                  env=dict(os.environ))
    except OSError as e:
        return False, str(e)
    if res.timed_out or res.exit_code != 0:
        detail = (res.stderr or res.stdout or "").strip().splitlines()
        return False, detail[0] if detail else f"exit {res.exit_code}"
    out = (res.stdout or res.stderr).strip().splitlines()
    return True, out[0] if out else "ok"


def run_doctor(cfg, *, providers_needed=("claude", "codex"), dry_run=False,
               smoke=False):
    rep = DoctorReport(ok=True)

    if sys.version_info < (3, 10):
        rep.problems.append(f"Python >= 3.10 required (found {platform.python_version()})")

    ok, ver = _probe(["git", "--version"])
    if ok:
        rep.cli_versions["git"] = ver
    else:
        rep.problems.append(f"git not usable: {ver}")

    if not dry_run:
        for provider in providers_needed:
            agent = cfg.agent_cfg(provider)
            exe = agent.get("executable", provider)
            ok, ver = _probe([exe, "--version"], timeout_s=60)
            if ok:
                rep.cli_versions[provider] = ver
            else:
                rep.problems.append(
                    f"{provider} CLI not usable ({exe} --version): {ver}. "
                    f"Install it and log in before starting (see README).")
        if smoke and not rep.problems:
            for provider in providers_needed:
                agent = cfg.agent_cfg(provider)
                exe = agent.get("executable", provider)
                if provider == "claude":
                    ok, out = _probe([exe, "-p", "Reply with exactly: OK"], timeout_s=180)
                else:
                    ok, out = _probe([exe, "exec", "--skip-git-repo-check",
                                      "Reply with exactly: OK"], timeout_s=180)
                if not ok:
                    rep.problems.append(
                        f"{provider} smoke test failed (is the CLI logged in?): {out}")

    # optional capabilities — decide deferral, never block by themselves
    caps = {
        "windows": os.name == "nt",
        "network": True,
        "gpu": _probe(["nvidia-smi", "-L"])[0],
        "tailscale": _probe(["tailscale", "version"])[0],
        "obs": False,          # cannot be probed reliably; enable via override
        "riot_live": False,    # needs a running game; enable via override
        "real_stream": False,  # needs a real stream setup; enable via override
        "long_run": False,     # 8h soak etc.; enable via override deliberately
    }
    caps.update(cfg.data.get("execution", {}).get("capabilities_override", {}) or {})
    rep.capabilities = caps
    for cap, present in sorted(caps.items()):
        if not present:
            rep.warnings.append(f"capability '{cap}' unavailable — dependent tests "
                                f"will be UNVERIFIED/deferred, never faked")

    rep.ok = not rep.problems
    return rep


def format_report(rep):
    lines = ["== Orchestrator Doctor =="]
    for name, ver in sorted(rep.cli_versions.items()):
        lines.append(f"  [ok] {name}: {ver}")
    for w in rep.warnings:
        lines.append(f"  [warn] {w}")
    for p in rep.problems:
        lines.append(f"  [FAIL] {p}")
    lines.append(f"Result: {'OK' if rep.ok else 'NOT READY'}")
    return "\n".join(lines)
