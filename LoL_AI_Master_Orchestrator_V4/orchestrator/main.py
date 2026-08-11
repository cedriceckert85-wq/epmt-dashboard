"""Orchestrator CLI.

Commands:
  run          drive all (or --phases) phases; resumable; the one-shot core
  status       print canonical state
  doctor       preflight checks (CLIs, git, capabilities)
  approve      write a human-gate approval record (strict mode)
  unblock      clear BLOCKED back to a re-runnable lifecycle
  reset-phase  restart the current phase from READY (drops its candidate)
"""
import argparse
import json
import sys
from pathlib import Path

from . import doctor as doctor_mod
from . import human_gate
from .config import ConfigError, load_config, load_phase, list_phase_ids
from .gitops import GitError, GitRepo
from .phase_loop import PhaseEngine
from .state import SingleWriterLock, StateError, StateStore, render_projections
from .util import utc_now_iso


def _parse_phase_selection(spec, all_ids):
    if not spec:
        return list(all_ids)
    picked = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            picked += [p for p in all_ids if lo.zfill(2) <= p <= hi.zfill(2)]
        elif part:
            if part.zfill(2) not in all_ids:
                raise ConfigError(f"unknown phase: {part}")
            picked.append(part.zfill(2))
    return sorted(set(picked))


def _write_final_report(cfg, st, status):
    lines = [
        "# ONE-SHOT RUN REPORT",
        "",
        f"- Finished: {utc_now_iso()}",
        f"- Overall status: **{status.upper()}**",
        f"- Current phase: {st['phase_id']} ({st['lifecycle']})",
    ]
    if st.get("blocked_reason"):
        lines += ["", "## Blocked reason", "", "```", str(st["blocked_reason"]), "```",
                  "", "Fix the cause, then run START again — the run resumes. ",
                  "Use `python -m orchestrator reset-phase` to restart the phase from scratch."]
    lines += ["", "## Phases", ""]
    for pid in sorted(st.get("phase_history", {})):
        h = st["phase_history"][pid]
        row = f"- {pid}: {h.get('gate')} @ {str(h.get('merged_commit'))[:12]}"
        if h.get("deferred"):
            row += f"  (deferred/UNVERIFIED tests: {', '.join(h['deferred'])})"
        lines.append(row)
    deferred = st.get("deferred_tests", {})
    if deferred:
        lines += ["", "## Deferred (UNVERIFIED) tests — need real hardware/network", ""]
        for pid in sorted(deferred):
            lines.append(f"- phase {pid}: {', '.join(deferred[pid])}")
        lines += ["", "These were NOT faked as passes. Re-run them on the target",
                  "hardware via their commands in test_registry.yaml."]
    report = "\n".join(lines) + "\n"
    (cfg.root / "ONE_SHOT_REPORT.md").write_text(report, encoding="utf-8")
    return report


def cmd_run(cfg, args):
    store = StateStore(cfg.state_file, cfg.journal_file)
    store.init_if_missing()
    repo = GitRepo(cfg.root)

    all_ids = list_phase_ids(cfg.root)
    phase_ids = _parse_phase_selection(args.phases, all_ids)
    providers = set()
    for pid in phase_ids:
        ph = load_phase(cfg.root, pid)
        if not ph.get("agentless"):
            providers.update((ph["builder"], ph["reviewer"]))

    rep = doctor_mod.run_doctor(cfg, providers_needed=sorted(providers),
                                dry_run=args.dry_run, smoke=not args.skip_smoke)
    print(doctor_mod.format_report(rep))
    if not rep.ok:
        print("\nBLOCKED: fix the doctor failures above, then run START again.",
              file=sys.stderr)
        return 3

    with SingleWriterLock(cfg.lock_file):
        engine = PhaseEngine(cfg, store, repo, dry_run=args.dry_run,
                             gate_mode=("strict" if args.strict_gates else None))
        status, st = engine.run(phases=phase_ids, capabilities=rep.capabilities)

    report = _write_final_report(cfg, st, status)
    print("\n" + report)
    if status == "done":
        print("ALL REQUESTED PHASES MERGED.")
        return 0
    if status == "waiting_human":
        return 0
    return 3


def cmd_status(cfg, args):
    store = StateStore(cfg.state_file, cfg.journal_file)
    print(json.dumps(store.load(), indent=2, sort_keys=True))
    return 0


def cmd_doctor(cfg, args):
    rep = doctor_mod.run_doctor(cfg, dry_run=args.dry_run, smoke=not args.skip_smoke)
    print(doctor_mod.format_report(rep))
    return 0 if rep.ok else 3


def cmd_approve(cfg, args):
    if not (args.phase and args.commit and args.approver and args.decision):
        print("approve requires --phase --commit --approver --decision", file=sys.stderr)
        return 2
    store = StateStore(cfg.state_file, cfg.journal_file)
    st = store.load()
    if st.get("candidate_commit") != args.commit:
        print(f"refusing: --commit does not match current candidate "
              f"{st.get('candidate_commit')}", file=sys.stderr)
        return 3
    rec = human_gate.write_approval(
        cfg.root / cfg.data["human_gates"]["record_dir"],
        phase_id=args.phase.zfill(2), commit_sha=args.commit,
        approver=args.approver, decision=args.decision, mode="strict")
    store.journal("human_approval_recorded", {"phase_id": rec["phase_id"],
                                              "commit": rec["commit_sha"],
                                              "decision": rec["decision"]})
    print(json.dumps(rec, indent=2))
    print("Recorded. Run START again to resume.")
    return 0


def cmd_unblock(cfg, args):
    store = StateStore(cfg.state_file, cfg.journal_file)
    st = store.load()
    if st["lifecycle"] != "BLOCKED":
        print("state is not BLOCKED", file=sys.stderr)
        return 2
    # the operator chose to retry: clean the tree (evidence lives in
    # .orchestrator/artifacts and the journal) so READY can start
    repo = GitRepo(cfg.root)
    repo.hard_reset_clean()
    st = store.transition(st, "READY", blocked_reason=None)
    render_projections(cfg.root, st, load_phase(cfg.root, st["phase_id"]))
    print(f"phase {st['phase_id']} reset to READY (BLOCKED->READY). Run START to retry.")
    return 0


def cmd_reset_phase(cfg, args):
    store = StateStore(cfg.state_file, cfg.journal_file)
    repo = GitRepo(cfg.root)
    st = store.load()
    branch = st.get("candidate_branch")
    repo.checkout(cfg.project["main_branch"])
    repo.hard_reset_clean()
    if branch:
        repo.delete_branch(branch)
    st = store.save({**st, "lifecycle": "READY", "candidate_branch": None,
                     "candidate_commit": None, "tested_commit": None,
                     "reviewed_commit": None, "approved_commit": None,
                     "blocked_reason": None, "fix_cycles": 0,
                     "review_findings": [], "evidence": {}})
    store.journal("phase_reset", {"phase_id": st["phase_id"]})
    print(f"phase {st['phase_id']} reset to READY; candidate branch dropped.")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="orchestrator")
    p.add_argument("--root", default=None, help="project root (default: auto-detect)")
    sub = p.add_subparsers(dest="command", required=True)

    sp_run = sub.add_parser("run", help="run phases (resumable one-shot core)")
    sp_run.add_argument("--phases", help="e.g. 00-05 or 02,03")
    sp_run.add_argument("--dry-run", action="store_true", help="fake agents, no CLIs")
    sp_run.add_argument("--strict-gates", action="store_true",
                        help="pause at human gates instead of auto-approving")
    sp_run.add_argument("--skip-smoke", action="store_true",
                        help="skip live CLI smoke prompts in doctor")
    sub.add_parser("status", help="print canonical state")
    sp_doc = sub.add_parser("doctor", help="preflight checks")
    sp_doc.add_argument("--dry-run", action="store_true")
    sp_doc.add_argument("--skip-smoke", action="store_true")
    sp_app = sub.add_parser("approve", help="record a human-gate decision")
    sp_app.add_argument("--phase")
    sp_app.add_argument("--commit")
    sp_app.add_argument("--approver")
    sp_app.add_argument("--decision", choices=["APPROVE", "REJECT"])
    sub.add_parser("unblock", help="BLOCKED -> READY for the current phase")
    sub.add_parser("reset-phase", help="restart current phase from scratch")

    args = p.parse_args(argv)

    root = Path(args.root) if args.root else Path(__file__).resolve().parents[1]
    try:
        cfg = load_config(root)
    except ConfigError as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        return 3

    handlers = {"run": cmd_run, "status": cmd_status, "doctor": cmd_doctor,
                "approve": cmd_approve, "unblock": cmd_unblock,
                "reset-phase": cmd_reset_phase}
    try:
        return handlers[args.command](cfg, args)
    except (StateError, GitError, ConfigError) as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
