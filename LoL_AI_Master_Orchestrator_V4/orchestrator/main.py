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
import os
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
        if not part:
            continue
        if "-" in part:
            lo, hi = (x.strip() for x in part.split("-", 1))
            if not lo or not hi:
                raise ConfigError(f"invalid phase range '{part}' (use e.g. 03-05)")
            lo, hi = lo.zfill(2), hi.zfill(2)
            if lo not in all_ids or hi not in all_ids:
                raise ConfigError(f"phase range '{part}' out of bounds "
                                  f"({all_ids[0]}..{all_ids[-1]})")
            if lo > hi:
                raise ConfigError(f"phase range '{part}' is reversed (low > high)")
            picked += [p for p in all_ids if lo <= p <= hi]
        else:
            if part.zfill(2) not in all_ids:
                raise ConfigError(f"unknown phase: {part}")
            picked.append(part.zfill(2))
    result = sorted(set(picked))
    if not result:
        raise ConfigError(f"--phases '{spec}' selected no phases")
    return result


def _write_final_report(cfg, st, status):
    lines = [
        "# ONE-SHOT RUN REPORT",
        "",
        f"- Finished: {utc_now_iso()}",
        f"- Overall status: **{status.upper()}**",
        f"- Current phase: {st['phase_id']} ({st['lifecycle']})",
    ]
    if st.get("blocked_reason"):
        launcher = "START.bat" if os.name == "nt" else "./start.sh"
        lines += ["", "## Blocked reason", "", "```", str(st["blocked_reason"]), "```",
                  "",
                  "This phase is BLOCKED (fail-closed). To continue:",
                  f"1. Fix the cause described above.",
                  f"2. Clear the block:  `{launcher} unblock`   "
                  f"(or `{launcher} reset-phase` to rebuild the phase from scratch).",
                  f"3. Run `{launcher}` again to resume.",
                  "",
                  "Note: simply re-running START without `unblock`/`reset-phase` will "
                  "NOT clear a BLOCKED phase — that is deliberate."]
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
    if not args.phases:
        # a default run skips phases marked optional / enabled_by_default:false
        # (e.g. multi-streamer). They run only when named explicitly in --phases.
        kept = []
        for pid in phase_ids:
            ph = load_phase(cfg.root, pid)
            if ph.get("optional") and not ph.get("enabled_by_default", True):
                print(f"[skip] phase {pid} ({ph.get('name')}) is optional "
                      f"(enabled_by_default: false) — run it explicitly with "
                      f"--phases {pid} to include it")
                continue
            kept.append(pid)
        phase_ids = kept
    providers = set()
    for pid in phase_ids:
        ph = load_phase(cfg.root, pid)
        if not ph.get("agentless"):
            providers.update((ph["builder"], ph["reviewer"]))

    rep = doctor_mod.run_doctor(cfg, providers_needed=sorted(providers),
                                dry_run=args.dry_run, smoke=args.smoke)
    print(doctor_mod.format_report(rep))
    if not rep.ok:
        # honor the docs' promise that ONE_SHOT_REPORT.md always says why
        _write_doctor_block_report(cfg, rep)
        print("\nBLOCKED: fix the doctor failures above, then run START again. "
              "See ONE_SHOT_REPORT.md.", file=sys.stderr)
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


def _write_doctor_block_report(cfg, rep):
    lines = [
        "# ONE-SHOT RUN REPORT",
        "",
        f"- Finished: {utc_now_iso()}",
        "- Overall status: **BLOCKED (preflight)**",
        "",
        "## The run could not start — the doctor found problems:",
        "",
    ]
    lines += [f"- [FAIL] {p}" for p in rep.problems]
    lines += ["", "## What to do",
              "1. Install/log in to the tools named above (see README.md).",
              "2. Run START again — it resumes automatically.",
              ""]
    if rep.cli_versions:
        lines += ["## Detected", ""] + [f"- {k}: {v}" for k, v in sorted(rep.cli_versions.items())]
    (cfg.root / "ONE_SHOT_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_status(cfg, args):
    store = StateStore(cfg.state_file, cfg.journal_file)
    print(json.dumps(store.load(), indent=2, sort_keys=True))
    return 0


def cmd_doctor(cfg, args):
    rep = doctor_mod.run_doctor(cfg, dry_run=args.dry_run, smoke=args.smoke)
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
    # .orchestrator/artifacts and the journal) so READY can start.
    # Clean the CURRENT (candidate) branch FIRST — a fix-cycle block leaves
    # uncommitted edits to tracked files, and git refuses to switch branches
    # over them; without this the recovery command itself crashes.
    repo = GitRepo(cfg.root)
    repo.hard_reset_clean()
    repo.checkout(cfg.project["main_branch"])
    repo.hard_reset_clean()
    # Re-derive the ref baseline from wherever main is NOW: the operator may
    # have legitimately committed a fix to main (e.g. correcting an immutable
    # config) as part of the recovery. Without this, the cross-window check
    # would treat that expected move as tampering and block forever.
    new_baseline = repo.branch_sha(cfg.project["main_branch"])
    st = store.transition(st, "READY", blocked_reason=None, main_baseline=new_baseline)
    render_projections(cfg.root, st, load_phase(cfg.root, st["phase_id"]))
    print(f"phase {st['phase_id']} reset to READY (BLOCKED->READY), main baseline "
          f"re-pinned to {str(new_baseline)[:12]}. Run START to retry.")
    return 0


def cmd_reset_phase(cfg, args):
    store = StateStore(cfg.state_file, cfg.journal_file)
    repo = GitRepo(cfg.root)
    st = store.load()
    branch = st.get("candidate_branch")
    main = cfg.project["main_branch"]
    # clean the current branch before switching (a block can leave a dirty tree)
    repo.hard_reset_clean()
    repo.checkout(main)
    repo.hard_reset_clean()
    if branch:
        repo.delete_branch(branch)
    # re-pin the ref baseline to current main (operator may have committed a
    # fix); otherwise a restarted phase would block on the stale baseline.
    new_baseline = repo.branch_sha(main)
    # "restart from scratch" means this phase is no longer done: drop it from
    # history so the resume logic actually re-runs it.
    history = dict(st.get("phase_history", {}))
    history.pop(st["phase_id"], None)
    st = store.save({**st, "lifecycle": "READY", "candidate_branch": None,
                     "candidate_commit": None, "tested_commit": None,
                     "reviewed_commit": None, "approved_commit": None,
                     "main_baseline": new_baseline, "phase_history": history,
                     "blocked_reason": None, "fix_cycles": 0,
                     "review_findings": [], "evidence": {}})
    store.journal("phase_reset", {"phase_id": st["phase_id"]})
    print(f"phase {st['phase_id']} reset to READY; candidate branch dropped, "
          f"main baseline re-pinned to {str(new_baseline)[:12]}.")
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
    sp_run.add_argument("--smoke", action="store_true",
                        help="also run live CLI smoke prompts in doctor "
                             "(off by default — --version + first real agent run verify login)")
    sub.add_parser("status", help="print canonical state")
    sp_doc = sub.add_parser("doctor", help="preflight checks")
    sp_doc.add_argument("--dry-run", action="store_true")
    sp_doc.add_argument("--smoke", action="store_true")
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
