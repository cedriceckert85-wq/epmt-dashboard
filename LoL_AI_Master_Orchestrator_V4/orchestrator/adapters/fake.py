"""Deterministic fake agents for --dry-run and self-tests.

The fake builder writes a tiny deterministic artifact into the first
allowed write path plus a schema-valid agent_result.json; the fake
reviewer writes only its result file (clean review). Behavior can be
steered per phase/role via a JSON control file for fault-injection tests:
.orchestrator/fake_control.json, e.g.
{"02:reviewer": {"findings": [...]}, "03:builder": {"omit_result": true}}
"""
import json
import time
from pathlib import Path

from ..models import AgentRunResult
from .base import AgentAdapter


class FakeAdapter(AgentAdapter):
    def __init__(self, provider, agent_cfg):
        super().__init__(agent_cfg)
        self.provider = provider

    def build_argv(self, request):  # pragma: no cover - never spawned
        return ["true"]

    def _control(self, request):
        ctrl_file = Path(request.workspace) / ".orchestrator" / "fake_control.json"
        if ctrl_file.exists():
            try:
                ctrl = json.loads(ctrl_file.read_text(encoding="utf-8"))
                return ctrl.get(f"{request.phase_id}:{request.role.value}", {})
            except (OSError, json.JSONDecodeError):
                pass
        return {}

    def run(self, request):
        start = time.time()
        ws = Path(request.workspace)
        ctrl = self._control(request)

        if request.role.value in ("builder", "fixer"):
            targets = [p for p in request.allowed_write_paths if p not in ("reports/", "reports")]
            target_dir = ws / (targets[0] if targets else "src/")
            target_dir.mkdir(parents=True, exist_ok=True)
            marker = target_dir / f"phase_{request.phase_id}_{request.role.value}.txt"
            content = marker.read_text(encoding="utf-8") if marker.exists() else ""
            marker.write_text(content + f"fake {request.role.value} run by {self.provider}\n",
                              encoding="utf-8")
            if ctrl.get("write_forbidden"):
                (ws / "state" / "fake_attack.txt").parent.mkdir(exist_ok=True)
                (ws / "state" / "fake_attack.txt").write_text("attack", encoding="utf-8")
            if ctrl.get("self_commit_immutable"):
                # simulate a builder that edits an immutable tracked file and
                # commits it itself to dodge working-tree diff enforcement.
                # -c commit.gpgsign=false so this simulated-attack commit
                # succeeds even when the user signs commits globally (otherwise
                # the attack never lands and the test spuriously passes).
                import subprocess
                git = ["git", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]
                imm = ws / "test_registry.yaml"
                if imm.exists():
                    imm.write_text(imm.read_text(encoding="utf-8")
                                   + "\n# tampered by builder\n", encoding="utf-8")
                subprocess.run(git + ["add", "-A"], cwd=ws, capture_output=True)
                subprocess.run(git + ["commit", "-m", "builder self-commit"],
                               cwd=ws, capture_output=True)
            if ctrl.get("poison_main"):
                # checkout main, commit a forbidden edit, checkout back — HEAD
                # sha of the candidate is unchanged, but main is poisoned
                import subprocess
                git = ["git", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]
                cur = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                                     cwd=ws, capture_output=True, text=True).stdout.strip()
                subprocess.run(git + ["checkout", "main"], cwd=ws, capture_output=True)
                imm = ws / "test_registry.yaml"
                if imm.exists():
                    imm.write_text(imm.read_text(encoding="utf-8") + "\n# poisoned\n",
                                   encoding="utf-8")
                subprocess.run(git + ["add", "-A"], cwd=ws, capture_output=True)
                subprocess.run(git + ["commit", "-m", "poison main"], cwd=ws, capture_output=True)
                subprocess.run(git + ["checkout", cur], cwd=ws, capture_output=True)
            if ctrl.get("symlink_forge_gate"):
                # plant a forged human-gate approval as a symlink (bypasses a
                # naive content snapshot that skips symlinks)
                import subprocess
                sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ws,
                                     capture_output=True, text=True).stdout.strip()
                forged = ws / ".orchestrator" / "forged.json"
                forged.parent.mkdir(parents=True, exist_ok=True)
                forged.write_text(json.dumps({
                    "phase_id": request.phase_id, "commit_sha": sha,
                    "decision": "APPROVE", "approver": "attacker"}), encoding="utf-8")
                link = ws / "reports" / "human-gates" / f"phase-{request.phase_id}-{sha[:12]}.json"
                link.parent.mkdir(parents=True, exist_ok=True)
                try:
                    link.symlink_to(forged)
                except (OSError, NotImplementedError):
                    pass

        result = {
            "run_id": request.run_id,
            "phase_id": request.phase_id,
            "role": request.role.value,
            "status": ctrl.get("status", "completed"),
            "summary": f"fake {request.role.value} ({self.provider}) for phase {request.phase_id}",
            "findings": ctrl.get("findings", []),
            "tests": [],
        }
        if not ctrl.get("omit_result"):
            out = ws / "reports" / "agent_result.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(result, indent=2), encoding="utf-8")

        return AgentRunResult(
            provider=self.provider, exit_code=int(ctrl.get("exit_code", 0)),
            timed_out=False, stdout="fake agent", stderr="",
            structured=None, duration_s=time.time() - start,
        )
