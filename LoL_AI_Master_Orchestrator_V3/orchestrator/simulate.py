"""Phase-00 bootstrap simulation.

Runs the FULL engine pipeline (worktree → fake builder → real
deterministic tests → fake cross-vendor review → gate → human gate →
ff-only merge → phase advance) against a throwaway copy of the project,
so the live repository is never touched. This is the executable proof
that the orchestrator machinery works end-to-end before any live agent
is allowed to run.
"""
import shutil, subprocess, tempfile
from pathlib import Path

from . import human_gate
from .adapters.fake import FakeAdapter
from .config import Config
from .engine import PhaseEngine

IGNORE = shutil.ignore_patterns(
    ".git", ".orchestrator", "__pycache__", ".pytest_cache", "*.pyc")


def build_sim_repo(project_root, dest=None):
    """Copy the project into a fresh git repo on branch `main`."""
    dest = Path(dest) if dest else Path(tempfile.mkdtemp(prefix="orch-phase00-sim-"))
    sim = dest / "repo"
    shutil.copytree(project_root, sim, ignore=IGNORE)
    def _git(*args):
        r = subprocess.run(["git", "-c", "user.name=sim", "-c", "user.email=sim@local",
                            *args], cwd=sim, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
        return r
    _git("init", "-b", "main")
    _git("add", "-A")
    _git("commit", "-m", "phase-00 simulation baseline")
    return sim


def run_phase00_simulation(project_root, *, auto_approve=True, keep=False,
                           builder_mode="success", reviewer_mode="reviewer-clean",
                           log=print):
    project_root = Path(project_root)
    sim = build_sim_repo(project_root)
    log(f"[sim] hermetic repo: {sim}")
    try:
        cfg = Config.load(sim)
        fake_script = sim / "tests" / "fakes" / "fake_agent.py"

        def make_engine():
            return PhaseEngine(
                sim, cfg,
                builder=FakeAdapter(fake_script, provider="fake-claude",
                                    mode=builder_mode, timeout_s=120),
                reviewer=FakeAdapter(fake_script, provider="fake-codex",
                                     mode=reviewer_mode, timeout_s=120),
                allow_empty_candidate=True,   # fake builder changes nothing
                capabilities={"none"})

        log("[sim] engine run: phase 00 (fake builder/reviewer, REAL deterministic tests)")
        result = make_engine().run_phase("00")
        if result.status == "AWAITING_HUMAN_GATE" and auto_approve:
            sha = result.state.get("candidate_commit")
            rec, path = human_gate.record_decision(
                cfg.human_gate_dir, phase_id="00", commit_sha=sha,
                approver="SIMULATION-AUTO",
                decision="APPROVE",
                reason="phase-00 bootstrap simulation (hermetic clone; the real "
                       "phase-00 human gate is the Go/No-Go runbook decision)")
            log(f"[sim] human gate: auto-approved {sha} -> {path.name}")
            result = make_engine().run_phase("00", resume=True)
        return result, sim
    finally:
        if not keep:
            shutil.rmtree(sim.parent, ignore_errors=True)
