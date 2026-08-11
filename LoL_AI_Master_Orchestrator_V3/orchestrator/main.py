"""Orchestrator CLI.

Commands:
  doctor      capability/environment checks (optionally scoped to a phase)
  status      print canonical state
  run-phase00 full bootstrap simulation in a hermetic repo copy
  run         drive a phase through the engine (fake or live agents)
  approve     record a SHA-bound human-gate decision
  unlock      remove a verifiably stale single-writer lock
  recover     clear a BLOCKED/interrupted phase back to READY

Exit codes (docs/EXIT_CODES.md): 0 ok, 2 invalid invocation/config,
3 blocked by gate/bootstrap, 4 intentionally unimplemented.
"""
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_cfg():
    from .config import Config, ConfigError
    try:
        return Config.load(ROOT), None
    except ConfigError as e:
        return None, str(e)


def _adapters_for(cfg, phase, *, fake=False):
    from .adapters.fake import FakeAdapter
    fake_script = ROOT / "tests" / "fakes" / "fake_agent.py"
    if fake:
        return (FakeAdapter(fake_script, provider="fake-claude", timeout_s=120),
                FakeAdapter(fake_script, provider="fake-codex",
                            mode="reviewer-clean", timeout_s=120))
    from .adapters.claude import ClaudeAdapter
    from .adapters.codex import CodexAdapter
    made = {}
    for role_name in ("builder", "reviewer"):
        provider = phase.get(role_name)
        a = cfg.agent(provider)
        if provider == "claude":
            made[role_name] = ClaudeAdapter(a["executable"], timeout_s=a["timeout_s"],
                                            pinned_version=a.get("pinned_version"))
        elif provider == "codex":
            made[role_name] = CodexAdapter(a["executable"], timeout_s=a["timeout_s"],
                                           pinned_version=a.get("pinned_version"))
        else:
            raise SystemExit(f"unknown provider for {role_name}: {provider!r}")
    return made["builder"], made["reviewer"]


def main(argv=None):
    p = argparse.ArgumentParser(prog="orchestrator")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("doctor", help="capability checks")
    d.add_argument("--phase")
    d.add_argument("--capability", action="append", default=[],
                   help="assert an externally verified capability (e.g. obs)")
    d.add_argument("--json", action="store_true")

    s = sub.add_parser("status", help="print canonical state")
    s.add_argument("--json", action="store_true")

    r0 = sub.add_parser("run-phase00", help="hermetic phase-00 bootstrap simulation")
    r0.add_argument("--keep-sim", action="store_true")
    r0.add_argument("--no-auto-approve", action="store_true")

    r = sub.add_parser("run", help="run a phase through the engine")
    r.add_argument("--phase", required=True)
    r.add_argument("--fake-agents", action="store_true")
    r.add_argument("--resume", action="store_true")
    r.add_argument("--capability", action="append", default=[])

    a = sub.add_parser("approve", help="record human-gate decision")
    a.add_argument("--commit", required=True)
    a.add_argument("--approver", required=True)
    a.add_argument("--decision", required=True, choices=["APPROVE", "REJECT"])
    a.add_argument("--reason", default="")
    a.add_argument("--phase")

    sub.add_parser("unlock", help="remove a verifiably stale lock")

    rec = sub.add_parser("recover", help="clear BLOCKED/interrupted phase to READY")
    rec.add_argument("--reason", default="operator recovery")

    args = p.parse_args(argv)
    cfg, cfg_err = _load_cfg()

    # ---------------------------------------------------------------- doctor
    if args.command == "doctor":
        from .doctor import run_doctor
        adapters = []
        if cfg:
            from .adapters.claude import ClaudeAdapter
            from .adapters.codex import CodexAdapter
            try:
                ca = cfg.agent("claude"); adapters.append(ClaudeAdapter(ca["executable"]))
            except Exception:
                pass
            try:
                co = cfg.agent("codex"); adapters.append(CodexAdapter(co["executable"]))
            except Exception:
                pass
        checks, caps, blocked = run_doctor(ROOT, phase_id=args.phase,
                                           adapters=adapters,
                                           assume_capabilities=args.capability)
        if args.json:
            print(json.dumps({"checks": checks, "capabilities": sorted(caps),
                              "blocked": blocked}, indent=2))
        else:
            for c in checks:
                print(f"{c['status']:>10}  {c['name']}: {c['detail']}")
            print(f"\ndoctor: {'BLOCKED' if blocked else 'OK'}")
        return 3 if blocked else 0

    if cfg is None:
        print(f"BLOCKED: {cfg_err}", file=sys.stderr)
        return 2

    from .journal import Journal
    from .state_store import StateStore, StateError
    journal = Journal(cfg.journal_path)
    store = StateStore(cfg.state_path, journal=journal,
                       current_task_path=cfg.current_task_path,
                       state_md_path=cfg.state_md_path,
                       task_md_path=cfg.task_md_path)
    try:
        st = store.load()
    except StateError as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        return 3

    # ---------------------------------------------------------------- status
    if args.command == "status":
        print(json.dumps(st, indent=2))
        return 0

    # ----------------------------------------------------------- run-phase00
    if args.command == "run-phase00":
        if st.get("phase_id") != "00":
            print("BLOCKED: run-phase00 only valid while canonical phase is 00",
                  file=sys.stderr)
            return 3
        from .simulate import run_phase00_simulation
        result, sim = run_phase00_simulation(
            ROOT, auto_approve=not args.no_auto_approve, keep=args.keep_sim)
        print(f"\nphase-00 simulation: {result.status}")
        for reason in result.reasons:
            print(f"  - {reason}")
        if args.keep_sim:
            print(f"  sim repo kept at: {sim}")
        if result.status == "MERGED":
            print("\nBootstrap pipeline PROVEN in simulation. The real phase-00 "
                  "human gate (runbooks/PHASE_00_GO_NO_GO.md) remains a human decision.")
            return 0
        return 3

    # -------------------------------------------------------------------- run
    if args.command == "run":
        from .doctor import run_doctor, detect_capabilities
        from .engine import PhaseEngine
        from .phases import load_phase, PhaseError
        try:
            phase = load_phase(ROOT, args.phase)
        except PhaseError as e:
            print(f"BLOCKED: {e}", file=sys.stderr)
            return 3
        if st.get("phase_id") == "00" and st.get("last_gate") != "PASS" \
                and not args.fake_agents:
            print("BLOCKED: Phase 00 not passed. Use run-phase00 / --fake-agents "
                  "for bootstrap work.", file=sys.stderr)
            return 3
        try:
            builder, reviewer = _adapters_for(cfg, phase, fake=args.fake_agents)
        except SystemExit as e:
            print(f"BLOCKED: {e}", file=sys.stderr)
            return 2
        checks, caps, blocked = run_doctor(
            ROOT, phase_id=args.phase,
            adapters=() if args.fake_agents else (builder, reviewer),
            assume_capabilities=args.capability)
        if blocked:
            for c in checks:
                if c["status"] == "BLOCKED":
                    print(f"BLOCKED (doctor): {c['name']}: {c['detail']}", file=sys.stderr)
            return 3
        engine = PhaseEngine(ROOT, cfg, builder, reviewer, capabilities=caps,
                             journal=journal, store=store,
                             allow_empty_candidate=args.fake_agents)
        result = engine.run_phase(args.phase, resume=args.resume)
        print(f"\nrun: {result.status}")
        for reason in result.reasons:
            print(f"  - {reason}")
        return result.exit_code

    # ---------------------------------------------------------------- approve
    if args.command == "approve":
        from .human_gate import record_decision, HumanGateError
        phase_id = args.phase or st.get("phase_id")
        try:
            rec, path = record_decision(cfg.human_gate_dir, phase_id=phase_id,
                                        commit_sha=args.commit, approver=args.approver,
                                        decision=args.decision, reason=args.reason)
        except HumanGateError as e:
            print(f"BLOCKED: {e}", file=sys.stderr)
            return 2
        journal.append("human_gate_recorded", **rec)
        print(json.dumps(rec, indent=2))
        print(f"recorded: {path}")
        if st.get("lifecycle") == "HUMAN_GATE" and \
                st.get("candidate_commit") == args.commit:
            print("state is HUMAN_GATE for this SHA — continue with: "
                  f"run --phase {phase_id} --resume"
                  + (" --fake-agents" if phase_id == "00" else ""))
        return 0

    # ----------------------------------------------------------------- unlock
    if args.command == "unlock":
        from .lock import SingleWriterLock, LockError
        lock = SingleWriterLock(cfg.lock_path)
        exists, info, stale = lock.inspect()
        if not exists:
            print("no lock present")
            return 0
        try:
            lock.break_stale()
        except LockError as e:
            print(f"BLOCKED: {e}", file=sys.stderr)
            return 3
        journal.append("stale_lock_broken", previous=info)
        print(f"stale lock removed (was: {info})")
        return 0

    # ---------------------------------------------------------------- recover
    if args.command == "recover":
        # Delegate to the engine: fresh state read under the lock, and
        # crash-between-merge-and-state reconciliation. Never crashes.
        from .engine import PhaseEngine
        from .phases import load_phase, PhaseError
        try:
            phase = load_phase(ROOT, st["phase_id"])
            builder, reviewer = _adapters_for(cfg, phase, fake=True)
        except (PhaseError, SystemExit) as e:
            print(f"BLOCKED: {e}", file=sys.stderr)
            return 3
        engine = PhaseEngine(ROOT, cfg, builder, reviewer, journal=journal, store=store)
        result = engine.recover(reason=args.reason)
        print(f"recover: {result.status}")
        for reason in result.reasons:
            print(f"  - {reason}")
        if result.status in ("READY", "RECOVERED"):
            print("inspect worktrees/artifacts under .orchestrator/ before rerunning.")
        return result.exit_code

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
