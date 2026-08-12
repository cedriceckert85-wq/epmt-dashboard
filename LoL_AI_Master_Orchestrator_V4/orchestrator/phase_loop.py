"""The phase engine: drives one phase after another through the V3
lifecycle with deterministic gates, cross-vendor review and fix loops.

READY -> BUILDING -> TESTING -> CHECKPOINTED -> REVIEWING
      -> GATE_EVALUATION [-> HUMAN_GATE] -> PASSED -> MERGED -> next READY
Failure loop: FIXING -> RETESTING -> CHECKPOINTED -> REVIEWING (max cycles)
Anything unverifiable: BLOCKED (fail closed, resumable).
"""
import shutil
import time
from pathlib import Path

from . import gates, human_gate, integrity, path_policy, secret_scan
from .adapters import make_adapter
from .config import load_phase
from .gitops import GitError
from .models import AgentRequest, AgentRole, Lifecycle
from .resultio import RESULT_REL_PATH, clear_agent_result, read_agent_result
from .state import render_projections
from .test_registry import load as load_registry
from .test_runner import run_phase_tests
from .util import atomic_write_json, new_id, utc_now_iso
from .prompt_builder import build_prompt, write_prompt_file
from . import acceptance as acceptance_mod


class PhaseRunError(Exception):
    """Internal control-flow error => phase becomes BLOCKED."""


class WaitingForHuman(Exception):
    """Strict gate mode: run must pause until a human approves."""


class PhaseEngine:
    def __init__(self, cfg, store, repo, *, dry_run=False, gate_mode=None, log=print):
        self.cfg = cfg
        self.store = store
        self.repo = repo
        self.dry_run = dry_run
        self.gate_mode = gate_mode or cfg.gate_mode
        self.log = log
        self.registry = load_registry(cfg.root / cfg.data["test_registry"])
        self.capabilities = {}

    # ------------------------------------------------------------------ utils
    def _artifact_dir(self, st):
        d = self.cfg.artifact_root / (st.get("run_id") or "bootstrap")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _phase(self, st):
        return load_phase(self.cfg.root, st["phase_id"])

    def _transition(self, st, phase, to, **extra):
        dec = gates.validate_lifecycle_transition(
            phase, lifecycle_from=st["lifecycle"], lifecycle_to=to.value)
        if not dec.passed:
            raise PhaseRunError("; ".join(dec.reasons))
        st = self.store.transition(st, to, **extra)
        render_projections(self.cfg.root, st, phase)
        self.log(f"[phase {st['phase_id']}] {to.value}"
                 + (f" ({extra.get('blocked_reason')})" if to == Lifecycle.BLOCKED else ""))
        return st

    def _block(self, st, phase, reason):
        # BLOCKED is the universal fail-closed sink; force it even from states
        # that don't list it as a legal transition (e.g. MERGED) so a failure
        # can never escape the state machine.
        self.store.journal("blocked", {
            "phase_id": st["phase_id"], "from": st["lifecycle"], "reason": reason})
        st = self.store.save({**st, "lifecycle": Lifecycle.BLOCKED.value,
                              "blocked_reason": reason})
        render_projections(self.cfg.root, st, phase)
        self.log(f"[phase {st['phase_id']}] BLOCKED ({reason.splitlines()[0] if reason else ''})")
        return st

    # ------------------------------------------------------------------ agents
    def _run_agent(self, st, phase, role, prompt_files, extra_sections=()):
        """Run one agent with policy enforcement. Returns (result_dict, findings)."""
        provider = phase["builder"] if role in (AgentRole.BUILDER, AgentRole.FIXER) else phase["reviewer"]
        agent_cfg = self.cfg.agent_cfg(provider)
        adapter = make_adapter(provider, agent_cfg, dry_run=self.dry_run)

        allowed = tuple(phase.get("allowed_write_paths", []))
        if role == AgentRole.REVIEWER:
            allowed = ("reports/",)

        task = {
            "run_id": st["run_id"], "phase_id": st["phase_id"],
            "phase_name": phase.get("name"), "role": role.value,
            "lifecycle": st["lifecycle"], "candidate_commit": st.get("candidate_commit"),
            "allowed_write_paths": list(allowed),
            "required_tests": phase.get("required_tests", []),
        }
        prompt_text = build_prompt(
            root=self.cfg.root, run_id=st["run_id"], phase=phase, role=role.value,
            task=task, immutable_paths=self.cfg.immutable_paths,
            allowed_paths=list(allowed), phase_prompt_files=prompt_files,
            extra_sections=extra_sections)
        prompt_file = write_prompt_file(
            self._artifact_dir(st), f"prompt_{st['phase_id']}_{role.value}_{int(time.time())}.md",
            prompt_text)

        request = AgentRequest(
            run_id=st["run_id"], phase_id=st["phase_id"], role=role,
            workspace=self.cfg.root, prompt_file=prompt_file,
            timeout_s=int(agent_cfg.get("timeout_s", 3600)),
            allowed_write_paths=allowed)

        # each failure kind has its OWN budget — an infra retry must not
        # silently consume the schema-retry allowance and vice versa
        schema_retries = self.cfg.invalid_schema_retries
        infra_retries = int(agent_cfg.get("max_retries", 2))
        violation_retries = 1
        backoffs = list(self.cfg.infra_backoff)
        infra_failures = schema_failures = violation_failures = 0
        # the orchestrator legitimately writes prompts/logs/evidence under
        # its own artifact dir; exempt it so it is not seen as tampering
        artifact_exclude = [str((self.cfg.artifact_root)
                                .relative_to(self.cfg.root)).replace("\\", "/")]
        attempt = 0
        while True:
            attempt += 1
            clear_agent_result(self.cfg.root)
            refs_before = self.repo.all_refs()
            pre_snap = integrity.snapshot(self.cfg.root, exclude=artifact_exclude)
            self.log(f"[phase {st['phase_id']}] running {role.value} ({provider}), attempt {attempt} …")
            run_res = adapter.run(request)
            # snapshot BEFORE the orchestrator itself writes journal/logs,
            # otherwise our own writes would look like agent tampering
            post_snap = integrity.snapshot(self.cfg.root, exclude=artifact_exclude)
            self.store.journal("agent_run", {
                "phase_id": st["phase_id"], "role": role.value, "provider": provider,
                "exit_code": run_res.exit_code, "timed_out": run_res.timed_out,
                "duration_s": round(run_res.duration_s, 1),
                "cleanup_incomplete": run_res.cleanup_incomplete})
            (self._artifact_dir(st) / f"agent_{st['phase_id']}_{role.value}_{attempt}.log").write_text(
                f"# exit={run_res.exit_code} timed_out={run_res.timed_out}\n"
                f"## STDOUT\n{run_res.stdout}\n## STDERR\n{run_res.stderr}\n",
                encoding="utf-8")

            if run_res.cleanup_incomplete:
                raise PhaseRunError(
                    f"{role.value} process tree cleanup incomplete after timeout — "
                    f"environment must be inspected before rerun")

            tamper = integrity.diff_snapshots(pre_snap, post_snap)
            if tamper:
                self.repo.hard_reset_clean()
                raise PhaseRunError(
                    f"{role.value} modified protected runtime files: {', '.join(tamper[:10])}")

            # agents must never move ANY git ref — only the orchestrator
            # commits. Comparing all refs (not just current HEAD) catches a
            # `git checkout main && commit && git checkout candidate` that
            # leaves the current HEAD sha unchanged but poisons main.
            refs_after = self.repo.all_refs()
            if refs_after != refs_before:
                moved = sorted(set(refs_before) | set(refs_after))
                changed = [r for r in moved if refs_before.get(r) != refs_after.get(r)]
                self.repo.checkout(st["candidate_branch"])
                # restore any moved local branch to its pre-run sha
                for ref in changed:
                    if ref.startswith("refs/heads/") and ref in refs_before:
                        self.repo._run("update-ref", ref, refs_before[ref], check=False)
                self.repo.hard_reset_clean()
                raise PhaseRunError(
                    f"{role.value} moved git refs ({', '.join(changed[:5])}); "
                    f"agents must not commit/branch/merge")

            violations = self._enforce_write_policy(st, allowed)
            if violations and role == AgentRole.REVIEWER:
                self.store.journal("reviewer_write_violation", {
                    "phase_id": st["phase_id"], "paths": violations[:50]})
                violation_failures += 1
                if violation_failures <= violation_retries:
                    continue
                raise PhaseRunError("reviewer modified files outside reports/ twice")

            if run_res.timed_out or (run_res.exit_code != 0 and not (self.cfg.root / RESULT_REL_PATH).exists()):
                infra_failures += 1
                if infra_failures <= infra_retries:
                    delay = backoffs[min(infra_failures - 1, len(backoffs) - 1)] if backoffs else 5
                    self.log(f"[phase {st['phase_id']}] {role.value} infra failure "
                             f"(exit {run_res.exit_code}, timeout={run_res.timed_out}) — retry in {delay}s")
                    time.sleep(0 if self.dry_run else delay)
                    continue
                raise PhaseRunError(
                    f"{role.value} agent ({provider}) failed after {infra_failures} infra "
                    f"attempts (exit {run_res.exit_code}, timed_out={run_res.timed_out}). "
                    f"Most common cause: the {provider} CLI is installed but NOT logged in — "
                    f"run `{provider}` once in a terminal and sign in, then retry. "
                    f"(Other causes: rate limit / quota / network.)")

            result, problems = read_agent_result(
                self.cfg.root, expected_phase=st["phase_id"], expected_role=role.value)
            if problems:
                self.store.journal("agent_result_invalid", {
                    "phase_id": st["phase_id"], "role": role.value, "problems": problems})
                schema_failures += 1
                if schema_failures <= schema_retries:
                    extra_sections = list(extra_sections) + [(
                        "RESULT FILE PROBLEMS (fix these)",
                        "Your previous run produced an invalid result file:\n- "
                        + "\n- ".join(problems))]
                    prompt_text = build_prompt(
                        root=self.cfg.root, run_id=st["run_id"], phase=phase, role=role.value,
                        task=task, immutable_paths=self.cfg.immutable_paths,
                        allowed_paths=list(allowed), phase_prompt_files=prompt_files,
                        extra_sections=extra_sections)
                    prompt_file.write_text(prompt_text, encoding="utf-8")
                    continue
                raise PhaseRunError(
                    f"{role.value} result invalid after retry: {'; '.join(problems[:5])}")

            # archive the result and clean reports/ scratch out of the worktree
            dst = self._artifact_dir(st) / f"result_{st['phase_id']}_{role.value}_{attempt}.json"
            shutil.copyfile(self.cfg.root / RESULT_REL_PATH, dst)
            clear_agent_result(self.cfg.root)
            if role == AgentRole.REVIEWER:
                # reviewer writes never enter git history; evidence lives in artifacts
                self._archive_and_drop_report_writes(st)
            # fail closed on anything that is not an affirmatively completed
            # run. An 'unverified' review is NOT a clean review — treating it
            # as one would let a degraded/evasive cross-vendor reviewer pass a
            # phase with an empty findings list.
            if result.get("status") != "completed":
                raise PhaseRunError(
                    f"{role.value} reported status={result.get('status')!r} (not 'completed'): "
                    f"{result.get('summary', '')[:300]}")
            return result

    def _enforce_write_policy(self, st, allowed):
        """Revert changes outside allowed/immutable policy. Returns violations."""
        violations = []
        for _, path in self.repo.status_porcelain():
            if not path_policy.is_write_allowed(
                    path, allowed_paths=allowed, immutable_paths=self.cfg.immutable_paths):
                violations.append(path)
        if violations:
            self.repo.restore_paths(set(violations))
            still = [p for _, p in self.repo.status_porcelain() if p in set(violations)]
            if still:
                raise PhaseRunError(f"could not revert forbidden writes: {', '.join(still[:10])}")
            self.store.journal("write_policy_violation", {
                "phase_id": st["phase_id"], "reverted_paths": violations[:100]})
        return violations

    def _archive_and_drop_report_writes(self, st):
        moved = []
        for status, path in self.repo.status_porcelain():
            if path.replace("\\", "/").startswith("reports/"):
                src = self.cfg.root / path
                if src.is_file():
                    dst = self._artifact_dir(st) / "review" / path.replace("\\", "/")
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dst)
                moved.append(path)
        if moved:
            self.repo.restore_paths(set(moved))

    # ------------------------------------------------------------------ steps
    def _step_ready(self, st, phase):
        if not self.repo.is_clean():
            raise PhaseRunError("working tree not clean at phase start — inspect and rerun")
        main = self.cfg.project["main_branch"]
        self.repo.checkout(main)
        base_sha = self.repo.head_sha()
        # cross-window ref integrity: main must be exactly where the last merge
        # left it. A detached process that moved main BETWEEN snapshot windows
        # (outside any agent/test run) is caught here, fail closed.
        expected_main = st.get("main_baseline")
        if expected_main and base_sha != expected_main:
            raise PhaseRunError(
                f"main HEAD moved outside orchestrator control "
                f"(expected {expected_main[:12]}, found {base_sha[:12]})")
        branch = f"phase/{st['phase_id']}"
        self.repo.create_branch(branch, main)
        run_id = new_id(f"run-{st['phase_id']}")
        return self._transition(
            st, phase, Lifecycle.BUILDING,
            run_id=run_id, candidate_branch=branch, base_commit=base_sha,
            main_baseline=base_sha,
            attempt=int(st.get("attempt", 0)) + 1, fix_cycles=0,
            builder_provider=phase["builder"], reviewer_provider=phase["reviewer"],
            candidate_commit=None, tested_commit=None, reviewed_commit=None,
            approved_commit=None, merged_commit=None, blocked_reason=None,
            review_findings=[], evidence={})

    def _step_building(self, st, phase):
        self.repo.checkout(st["candidate_branch"])
        self.repo.hard_reset_clean()   # partial writes from a crashed run must not linger
        if phase.get("agentless"):
            report = {"phase_id": st["phase_id"], "kind": "orchestrator-self-check",
                      "ts": utc_now_iso(), "capabilities": self.capabilities}
            p = self.cfg.root / "reports" / f"phase-{st['phase_id']}-selfcheck.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(p, report)
        else:
            self._run_agent(st, phase, AgentRole.BUILDER,
                            [f"prompts/build/phase-{st['phase_id']}.md"])
        sha = self.repo.add_all_and_commit(
            f"phase {st['phase_id']}: builder candidate (attempt {st['attempt']})")
        if sha is None:
            raise PhaseRunError("builder produced no committable changes")
        return self._transition(st, phase, Lifecycle.TESTING,
                                candidate_commit=sha, tested_commit=None)

    def _step_testing(self, st, phase, *, retest=False):
        self.repo.checkout(st["candidate_branch"])
        if not self.repo.is_clean():
            raise PhaseRunError("working tree dirty before testing")
        # candidate test code is untrusted and runs with FS access. Guard the
        # control plane (state/, records, projections, .venv, .orchestrator
        # minus its own evidence dir) so a malicious test cannot plant a forged
        # approval/acceptance record or poison the venv during the test window.
        artifact_exclude = [str(self.cfg.artifact_root.relative_to(self.cfg.root)).replace("\\", "/")]
        refs_before = self.repo.all_refs()
        pre_snap = integrity.snapshot(self.cfg.root, exclude=artifact_exclude)
        outcomes, exit_codes, metrics, deferred = run_phase_tests(
            phase, self.registry, root=self.cfg.root, run_id=st["run_id"],
            capabilities=self.capabilities,
            strip_env_extra=self.cfg.secret_env_vars)
        tamper = integrity.diff_snapshots(pre_snap, integrity.snapshot(self.cfg.root, exclude=artifact_exclude))
        if tamper:
            self.repo.hard_reset_clean()
            raise PhaseRunError(
                f"candidate test run modified protected control-plane files: {', '.join(tamper[:10])}")
        if self.repo.all_refs() != refs_before:
            self.repo.checkout(st["candidate_branch"])
            self.repo.hard_reset_clean()
            raise PhaseRunError("candidate test run moved git refs (must not commit/merge)")
        # tests may only touch their allowed write paths in the worktree
        test_violations = self._enforce_write_policy(st, tuple(phase.get("allowed_write_paths", [])))
        if test_violations:
            raise PhaseRunError(
                f"candidate test run wrote outside allowed paths: {', '.join(test_violations[:10])}")
        changed = self.repo.changed_paths_since(st["base_commit"])
        secrets = secret_scan.scan_files(self.cfg.root, changed)
        evidence = {
            "test_exit_codes": exit_codes,
            "metrics": metrics,
            "deferred_tests": deferred,
            "secret_findings": secrets,
            "outcomes": [vars(o) for o in outcomes],
        }
        atomic_write_json(self._artifact_dir(st) / f"tests_{st['phase_id']}_{st.get('fix_cycles',0)}.json",
                          evidence)
        self.store.journal("tests_run", {
            "phase_id": st["phase_id"],
            "results": {o.name: o.status + (" (deferred)" if o.deferred else "") for o in outcomes},
            "secret_findings": len(secrets)})
        for o in outcomes:
            mark = {"pass": "ok", "fail": "FAIL", "unverified": "UNVERIFIED"}[o.status]
            self.log(f"  test {o.name}: {mark}"
                     + (" [deferred]" if o.deferred else "")
                     + (f" — {o.reason}" if o.reason else ""))

        failed = [n for n, c in exit_codes.items() if c != 0]
        non_deferrable_unverified = [
            o.name for o in outcomes
            if o.status == "unverified" and not o.deferred]
        if secrets:
            raise PhaseRunError(
                "secret scan findings in candidate: "
                + ", ".join(f"{s['file']}:{s['line']}({s['kind']})" for s in secrets[:5]))
        if failed or non_deferrable_unverified:
            detail = []
            for o in outcomes:
                if o.name in failed or o.name in non_deferrable_unverified:
                    detail.append(f"{o.name}: {o.status} — {o.reason}")
            if phase.get("agentless"):
                # No agent can fix the orchestrator's OWN test suite — routing
                # into the fix-loop would just re-fail and BLOCK with a
                # misleading "max fix cycles" reason. Fail directly with the
                # real cause.
                raise PhaseRunError(
                    "Orchestrator self-check failed (this is the shipped test suite, "
                    "not your project). This means the package hit a bug or an "
                    "unsupported environment. Details:\n" + "\n".join(detail)
                    + "\nSee the junit evidence under .orchestrator/artifacts/. "
                    "Do NOT edit the orchestrator; report this or try a supported "
                    "Python (3.10+) on a supported OS.")
            return self._to_fixing(st, phase, "failing tests:\n" + "\n".join(detail))
        return self._transition(st, phase, Lifecycle.CHECKPOINTED,
                                tested_commit=st["candidate_commit"], evidence=evidence)

    def _step_checkpointed(self, st, phase):
        return self._transition(st, phase, Lifecycle.REVIEWING)

    def _step_reviewing(self, st, phase):
        self.repo.checkout(st["candidate_branch"])
        self.repo.hard_reset_clean()
        if phase.get("agentless"):
            findings = []
        else:
            review_files = phase.get("review_prompts", [])
            evidence_note = (
                "Candidate commit under review: " + str(st["candidate_commit"]) + "\n"
                "Changed files vs base:\n- "
                + "\n- ".join(self.repo.changed_paths_since(st["base_commit"])[:200]))
            result = self._run_agent(
                st, phase, AgentRole.REVIEWER, review_files,
                extra_sections=[("REVIEW TARGET", evidence_note)])
            findings = result.get("findings", [])
        if not self.repo.is_clean():
            self.repo.hard_reset_clean()
        return self._transition(st, phase, Lifecycle.GATE_EVALUATION,
                                reviewed_commit=st["candidate_commit"],
                                review_findings=findings)

    def _deferred_metrics(self, st):
        deferred = set(st.get("evidence", {}).get("deferred_tests", []))
        out = set()
        for tname in deferred:
            spec = self.registry.get(tname, {})
            for m in spec.get("produces_metrics", []) or []:
                out.add(m)
        return out

    def _forbidden_committed_changes(self, st, phase):
        """Paths committed into the candidate (vs base) that violate the
        write policy — defense in depth against any change that reached
        history without going through the per-run working-tree enforcement."""
        allowed = tuple(phase.get("allowed_write_paths", []))
        bad = []
        for path in self.repo.changed_paths_since(st["base_commit"]):
            if not path_policy.is_write_allowed(
                    path, allowed_paths=allowed, immutable_paths=self.cfg.immutable_paths):
                bad.append(path)
        return bad

    def _evaluate_gate(self, st, phase, *, approval):
        ev = st.get("evidence", {})
        acc_records = acceptance_mod.load_records(
            self.cfg.root / self.cfg.data["acceptance"]["record_dir"])
        forbidden = self._forbidden_committed_changes(st, phase)
        if forbidden:
            self.store.journal("forbidden_committed_changes", {
                "phase_id": st["phase_id"], "paths": forbidden[:100]})
        return gates.evaluate_completion_gate(
            phase,
            test_exit_codes=ev.get("test_exit_codes", {}),
            metrics=ev.get("metrics", {}),
            review_findings=st.get("review_findings", []),
            forbidden_changes=forbidden,
            secret_findings=ev.get("secret_findings", []),
            clean_main=self.repo.is_clean(),
            candidate_commit=st.get("candidate_commit"),
            tested_commit=st.get("tested_commit"),
            reviewed_commit=st.get("reviewed_commit"),
            approved_commit=(st.get("candidate_commit") if approval else st.get("approved_commit")),
            human_approval_record=approval,
            acceptance_records=acc_records,
            deferred_tests=ev.get("deferred_tests", []),
            deferred_metrics=self._deferred_metrics(st),
        )

    def _step_gate_evaluation(self, st, phase):
        gate_dir = self.cfg.root / self.cfg.data["human_gates"]["record_dir"]
        needs_human = bool(phase.get("human_gate", False))
        candidate = st["candidate_commit"]

        if not needs_human:
            dec = self._evaluate_gate(st, phase, approval=None)
            self.store.journal("gate_evaluated", {
                "phase_id": st["phase_id"], "passed": dec.passed, "reasons": list(dec.reasons)})
            if dec.passed:
                return self._transition(st, phase, Lifecycle.PASSED, last_gate="PASS")
            return self._gate_failure(st, phase, dec)

        # human-gated phase: first verify everything deterministic holds
        probe = {"decision": "APPROVE", "commit_sha": candidate}
        dec = self._evaluate_gate(st, phase, approval=probe)
        self.store.journal("gate_evaluated", {
            "phase_id": st["phase_id"], "passed": dec.passed,
            "reasons": list(dec.reasons), "pre_human_probe": True})
        if not dec.passed:
            return self._gate_failure(st, phase, dec)
        return self._transition(st, phase, Lifecycle.HUMAN_GATE)

    def _step_human_gate(self, st, phase):
        gate_dir = self.cfg.root / self.cfg.data["human_gates"]["record_dir"]
        candidate = st["candidate_commit"]
        approval = human_gate.load_approval(gate_dir, st["phase_id"], candidate)
        if approval is None:
            if self.gate_mode == "auto":
                ev = st.get("evidence", {})
                approval = human_gate.write_approval(
                    gate_dir, phase_id=st["phase_id"], commit_sha=candidate,
                    approver="AUTO_GATE (operator pre-authorized via one-shot mode)",
                    decision="APPROVE", mode="auto",
                    evidence={
                        "tests": ev.get("test_exit_codes", {}),
                        "deferred_tests": ev.get("deferred_tests", []),
                        "review_findings": len(st.get("review_findings", [])),
                    })
                self.store.journal("auto_gate_approved", {
                    "phase_id": st["phase_id"], "commit": candidate,
                    "approval_id": approval["approval_id"]})
            else:
                import os as _os
                launcher = "START.bat" if _os.name == "nt" else "./start.sh"
                raise WaitingForHuman(
                    f"Phase {st['phase_id']} waits for human approval of commit {candidate}.\n"
                    f"Approve by running (from this folder):\n"
                    f"  {launcher} approve --phase {st['phase_id']} "
                    f"--commit {candidate} --approver YOUR_NAME --decision APPROVE\n"
                    f"then run {launcher} again to resume.\n"
                    f"(The {launcher} launcher forwards the command into the .venv; a bare "
                    f"'python -m orchestrator' on your system Python may lack dependencies.)")
        if approval.get("decision") != "APPROVE":
            raise PhaseRunError(f"human gate rejected for commit {candidate}")
        st = self.store.save({**st, "approved_commit": candidate,
                              "human_approval_id": approval.get("approval_id")})
        dec = self._evaluate_gate(st, phase, approval=approval)
        if not dec.passed:
            return self._gate_failure(st, phase, dec)
        return self._transition(st, phase, Lifecycle.PASSED, last_gate="PASS",
                                approved_commit=candidate)

    def _gate_failure(self, st, phase, dec):
        fixable = all(("test failed" in r) or ("findings" in r) or ("metric" in r)
                      for r in dec.reasons) and dec.reasons
        if fixable:
            return self._to_fixing(st, phase, "gate failed:\n- " + "\n- ".join(dec.reasons))
        raise PhaseRunError("gate failed: " + "; ".join(dec.reasons))

    def _to_fixing(self, st, phase, reason):
        if int(st.get("fix_cycles", 0)) >= self.cfg.max_fix_cycles:
            raise PhaseRunError(
                f"max fix cycles ({self.cfg.max_fix_cycles}) exhausted; last failure:\n{reason}")
        st = self._transition(st, phase, Lifecycle.FIXING,
                              fix_cycles=int(st.get("fix_cycles", 0)) + 1,
                              fix_reason=reason)
        return st

    def _step_fixing(self, st, phase):
        self.repo.checkout(st["candidate_branch"])
        self.repo.hard_reset_clean()
        findings = st.get("review_findings", [])
        sections = [("VERIFIED FAILURES TO FIX", st.get("fix_reason", "(see findings)"))]
        if findings:
            import json as _json
            sections.append(("REVIEW FINDINGS", _json.dumps(findings, indent=2)))
        self._run_agent(st, phase, AgentRole.FIXER,
                        ["prompts/fix/verified-findings-fix.md"], extra_sections=sections)
        sha = self.repo.add_all_and_commit(
            f"phase {st['phase_id']}: fix cycle {st['fix_cycles']}")
        if sha is None:
            raise PhaseRunError("fixer produced no committable changes")
        return self._transition(st, phase, Lifecycle.RETESTING,
                                candidate_commit=sha, tested_commit=None,
                                reviewed_commit=None, review_findings=[])

    def _step_passed(self, st, phase):
        main = self.cfg.project["main_branch"]
        candidate = st["candidate_commit"]
        # Idempotent / resumable across the merge+delete boundary: if a crash
        # landed after the ff-merge (and possibly after branch deletion) but
        # before the MERGED state was saved, main already contains the
        # candidate commit. Detect that and finish instead of re-merging a
        # (possibly deleted) branch.
        self.repo.checkout(main)
        if self.repo.is_ancestor(candidate, "HEAD"):
            merged = self.repo.head_sha()
            if merged != candidate:
                raise PhaseRunError(
                    f"main advanced past candidate {candidate[:12]} (head {merged[:12]}); "
                    f"cannot verify clean ff-merge")
        else:
            merged = self.repo.merge_ff_only(main, st["candidate_branch"])
            dec = gates.validate_merge_commit(candidate_commit=candidate, merged_commit=merged)
            if not dec.passed:
                raise PhaseRunError("merge validation failed: " + "; ".join(dec.reasons))
        if st.get("candidate_branch"):
            self.repo.delete_branch(st["candidate_branch"])
        history = dict(st.get("phase_history", {}))
        history[st["phase_id"]] = {
            "gate": "PASS",
            "merged_commit": merged,
            "deferred": st.get("evidence", {}).get("deferred_tests", []),
        }
        deferred_all = dict(st.get("deferred_tests", {}))
        if st.get("evidence", {}).get("deferred_tests"):
            deferred_all[st["phase_id"]] = st["evidence"]["deferred_tests"]
        return self._transition(st, phase, Lifecycle.MERGED,
                                merged_commit=merged, phase_history=history,
                                deferred_tests=deferred_all, main_baseline=merged)

    def _enter_phase(self, st, pid):
        """Reset run-scoped fields and move to phase `pid` in READY."""
        st = self.store.transition(st, Lifecycle.READY, phase_id=pid, attempt=0,
                                   fix_cycles=0, run_id=None, candidate_branch=None,
                                   candidate_commit=None, tested_commit=None,
                                   reviewed_commit=None, approved_commit=None,
                                   merged_commit=None, last_gate=None,
                                   blocked_reason=None, review_findings=[], evidence={})
        render_projections(self.cfg.root, st, self._phase(st))
        return st

    def _next_todo(self, st, phase_ids):
        """The first REQUESTED phase not yet merged (in phase_history), by
        registry order. History-driven so it works regardless of the saved
        phase's position — never skips an earlier requested phase and never
        re-runs an already-merged one."""
        history = st.get("phase_history", {})
        todo = [p for p in phase_ids if p not in history]
        return todo[0] if todo else None

    def _advance(self, st, phase, phase_ids):
        nxt = self._next_todo(st, phase_ids)
        if nxt is None:
            return None
        return self._enter_phase(st, nxt)

    # ------------------------------------------------------------------ main
    STEPS = {
        Lifecycle.READY: "_step_ready",
        Lifecycle.BUILDING: "_step_building",
        Lifecycle.CHECKPOINTED: "_step_checkpointed",
        Lifecycle.REVIEWING: "_step_reviewing",
        Lifecycle.GATE_EVALUATION: "_step_gate_evaluation",
        Lifecycle.HUMAN_GATE: "_step_human_gate",
        Lifecycle.PASSED: "_step_passed",
        Lifecycle.FIXING: "_step_fixing",
    }

    def run(self, *, phases=None, capabilities=None):
        """Drive phases until done/blocked/waiting. Returns (status, state).
        status: 'done' | 'blocked' | 'waiting_human' | 'stopped'"""
        self.capabilities = capabilities or {}
        st = self.store.load()
        phase_ids = phases or self._all_phase_ids()
        lc = st["lifecycle"]

        # A phase mid-flight AND inside the requested window continues exactly
        # where it stopped (resume). Anything else — a completed/READY phase, or
        # a saved phase outside the window — is reconciled against phase_history:
        # jump to the first REQUESTED phase not yet merged. This never restarts
        # the whole pipeline, never skips an earlier requested phase, and never
        # silently re-runs an already-merged one (e.g. re-including phase 18 via
        # a range that also contains the parked final phase).
        midflight_inwindow = (lc not in ("READY", "MERGED", "BLOCKED")
                              and st["phase_id"] in phase_ids)
        if lc == "BLOCKED" and st["phase_id"] not in phase_ids:
            return "blocked", self.store.save({
                **st, "blocked_reason":
                f"state is BLOCKED at phase {st['phase_id']} but that phase was excluded "
                f"— include it in --phases to recover, then unblock"})
        if not midflight_inwindow and lc != "BLOCKED":
            nxt = self._next_todo(st, phase_ids)
            if nxt is None:
                return "done", st
            if st["phase_id"] != nxt or lc != "READY":
                st = self._enter_phase(st, nxt)

        while True:
            phase = self._phase(st)
            lc = Lifecycle(st["lifecycle"])
            try:
                if lc == Lifecycle.BLOCKED:
                    return "blocked", st
                if lc == Lifecycle.MERGED:
                    nxt = self._advance(st, phase, phase_ids)
                    if nxt is None:
                        return "done", st
                    st = nxt
                    continue
                if lc == Lifecycle.TESTING:
                    st = self._step_testing(st, phase)
                    continue
                if lc == Lifecycle.RETESTING:
                    st = self._step_testing(st, phase, retest=True)
                    continue
                step = self.STEPS.get(lc)
                if step is None:
                    raise PhaseRunError(f"no handler for lifecycle {lc}")
                st = getattr(self, step)(st, phase)
            except WaitingForHuman as w:
                self.log(str(w))
                return "waiting_human", st
            except PhaseRunError as e:
                st = self._block(st, phase, str(e))
                return "blocked", st
            except GitError as e:
                # a git-level failure is "unverifiable" per the module
                # contract — record it as BLOCKED (fail closed, resumable),
                # never let it escape and abort the run silently.
                st = self._block(st, phase, f"git failure: {e}")
                return "blocked", st

    def _all_phase_ids(self):
        from .config import list_phase_ids
        return list_phase_ids(self.cfg.root)
