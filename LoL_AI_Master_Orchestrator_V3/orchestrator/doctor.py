"""Doctor: capability and environment checks.

Every claim the orchestrator later relies on (git present, registry
valid, provider CLI available with the flags the adapters use, network/
tailscale reachable) is verified here and reported as OK / WARN /
UNVERIFIED / BLOCKED. Anything unverifiable stays UNVERIFIED — never
assumed.
"""
import json, os, shutil, socket, subprocess, sys
from pathlib import Path

from . import test_registry
from .config import Config, ConfigError
from .lock import SingleWriterLock, LockHeldError
from .result_validation import load_schema
from .state_store import StateStore, StateError

OK, WARN, UNVERIFIED, BLOCKED = "OK", "WARN", "UNVERIFIED", "BLOCKED"


def _check(name, status, detail=""):
    return {"name": name, "status": status, "detail": detail}


def _cmd_version(argv, timeout=20):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)
    if r.returncode != 0:
        return None, (r.stderr or r.stdout).strip()[:200]
    return (r.stdout or r.stderr).strip().splitlines()[0], ""


def detect_capabilities(*, assume=()):
    """Evidence-based capability set for test_registry `requires`.
    Only 'none' is free; everything else needs a real probe or an
    explicit operator assertion (--capability)."""
    caps = {"none"} | set(assume)
    if os.name == "nt":
        caps.add("windows")
    if shutil.which("tailscale"):
        try:
            r = subprocess.run(["tailscale", "status", "--json"],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and json.loads(r.stdout or "{}").get("BackendState") == "Running":
                caps.add("tailscale")
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
    if "network" not in caps:
        try:
            with socket.create_connection(("1.1.1.1", 443), timeout=3):
                caps.add("network")
        except OSError:
            pass
    return caps


def run_doctor(root, *, phase_id=None, adapters=(), assume_capabilities=()):
    """Returns (checks, capabilities, blocked: bool)."""
    root = Path(root)
    checks = []

    v = sys.version_info
    checks.append(_check("python", OK if v >= (3, 11) else BLOCKED,
                         f"{v.major}.{v.minor}.{v.micro} (need >= 3.11)"))

    gitv, err = _cmd_version(["git", "--version"])
    checks.append(_check("git", OK if gitv else BLOCKED, gitv or err))

    try:
        cfg = Config.load(root)
        checks.append(_check("config", OK, "ORCHESTRATOR_CONFIG.yaml valid"))
    except ConfigError as e:
        checks.append(_check("config", BLOCKED, str(e)))
        return checks, {"none"}, True

    try:
        StateStore(cfg.state_path).load()
        checks.append(_check("canonical_state", OK, str(cfg.state_path)))
    except StateError as e:
        checks.append(_check("canonical_state", BLOCKED, str(e)))

    try:
        lock = SingleWriterLock(cfg.lock_path)
        exists, info, stale = lock.inspect()
        if not exists:
            checks.append(_check("lock", OK, "no lock held"))
        elif stale:
            checks.append(_check("lock", WARN, f"stale lock present (pid={ (info or {}).get('pid') }); run `unlock`"))
        else:
            checks.append(_check("lock", BLOCKED, f"live lock held: {info}"))
    except LockHeldError as e:
        checks.append(_check("lock", BLOCKED, str(e)))

    try:
        registry = test_registry.load(cfg.registry_path)
        gaps = test_registry.coverage_gaps(registry, phases_dir=root / "phases")
        if gaps:
            checks.append(_check("test_registry", BLOCKED, "coverage gaps: " + ", ".join(gaps)))
        else:
            checks.append(_check("test_registry", OK, f"{len(registry)} tests mapped, no gaps"))
    except (ValueError, OSError) as e:
        checks.append(_check("test_registry", BLOCKED, str(e)))

    try:
        load_schema(root / "schemas" / "agent_result.schema.json")
        load_schema(root / "schemas" / "finding_acceptance.schema.json")
        checks.append(_check("schemas", OK, "agent_result + finding_acceptance valid"))
    except Exception as e:  # jsonschema.SchemaError, OSError, json errors
        checks.append(_check("schemas", BLOCKED, str(e)))

    fake = root / "tests" / "fakes" / "fake_agent.py"
    if fake.exists():
        try:
            r = subprocess.run([sys.executable, str(fake), "--mode", "success"],
                               capture_output=True, text=True, timeout=30)
            ok = r.returncode == 0 and '"status"' in r.stdout
            checks.append(_check("fake_agent", OK if ok else BLOCKED,
                                 "roundtrip ok" if ok else f"exit={r.returncode}"))
        except (OSError, subprocess.TimeoutExpired) as e:
            checks.append(_check("fake_agent", BLOCKED, str(e)))
    else:
        checks.append(_check("fake_agent", BLOCKED, "tests/fakes/fake_agent.py missing"))

    for adapter in adapters:
        doc = adapter.doctor()
        name = f"adapter_{doc.get('provider', '?')}"
        if not doc.get("available"):
            checks.append(_check(name, UNVERIFIED,
                                 f"CLI unavailable: {doc.get('detail', '')} — live phases "
                                 "using this provider stay BLOCKED"))
        elif doc.get("pinned_ok") is False:
            checks.append(_check(name, BLOCKED, f"version drift: {doc.get('detail')}"))
        elif not doc.get("flags_ok", True):
            checks.append(_check(name, BLOCKED, f"capabilities unverified: {doc.get('detail')}"))
        else:
            checks.append(_check(name, OK, str(doc.get("version"))))

    caps = detect_capabilities(assume=assume_capabilities)
    checks.append(_check("capabilities", OK, ", ".join(sorted(caps))))

    if phase_id is not None:
        try:
            from .phases import load_phase
            phase = load_phase(root, phase_id)
            reg = test_registry.load(cfg.registry_path)
            missing = set()
            for t in phase.get("required_tests", []):
                for req in reg.get(t, {}).get("requires", ["none"]):
                    if req != "none" and req not in caps:
                        missing.add(req)
            if missing:
                checks.append(_check(f"phase_{phase_id}_requirements", UNVERIFIED,
                                     "missing capability evidence: " + ", ".join(sorted(missing)) +
                                     " — affected tests will report UNVERIFIED (never skipped-as-pass)"))
            else:
                checks.append(_check(f"phase_{phase_id}_requirements", OK, "all capabilities available"))
        except Exception as e:
            checks.append(_check(f"phase_{phase_id}_requirements", BLOCKED, str(e)))

    blocked = any(c["status"] == BLOCKED for c in checks)
    return checks, caps, blocked
