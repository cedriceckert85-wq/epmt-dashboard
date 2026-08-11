"""Phase execution engine — the deterministic control plane.

Drives one phase through the full lifecycle:

  READY→BUILDING→TESTING→[FIXING→RETESTING]→CHECKPOINTED→REVIEWING
  →[FIXING→RETESTING→CHECKPOINTED→REVIEWING]→GATE_EVALUATION
  →[HUMAN_GATE]→PASSED→MERGED→READY(next phase)

Every transition goes through gates.validate_lifecycle_transition via the
StateStore; PASS comes exclusively from gates.evaluate_completion_gate fed
with real exit codes, parsed evidence, diff-based policy checks, secret
scans and SHA-bound approval records. No agent statement can release a
phase.
"""
import hashlib, json, random, time
from dataclasses import dataclass
from pathlib import Path

from . import acceptance, gates, human_gate, phases, secret_scan, test_registry
from .config import ORCHESTRATOR_OWNED_PREFIXES
from .gitops import GitOps, GitError
from .journal import Journal, utc_now
from .lock import SingleWriterLock, LockHeldError
from .models import AgentRequest, AgentRole
from .path_policy import is_write_allowed
from .phases import PhaseError
from .result_validation import load_schema, validate_agent_result
from .state_store import StateStore, StateError
from .testexec import run_required_tests


@dataclass
class EngineResult:
    status: str                # MERGED | AWAITING_HUMAN_GATE | BLOCKED
    exit_code: int
    reasons: tuple
    state: dict


class _Blocked(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class PhaseEngine:
    def __init__(self, root, config, builder, reviewer, *,
                 capabilities=frozenset({"none"}), sleep=time.sleep,
                 journal=None, store=None, git=None, base_env=None,
                 allow_empty_candidate=False):
        self.root = Path(root)
        self.config = config
        self.builder = builder
        self.reviewer = reviewer
        self.capabilities = set(capabilities) | {"none"}
        self.sleep = sleep
        self.base_env = base_env
        self.allow_empty_candidate = allow_empty_candidate
        self.journal = journal or Journal(config.journal_path)
        self.store = store or StateStore(
            config.state_path, journal=self.journal,
            current_task_path=config.current_task_path,
            state_md_path=config.state_md_path,
            task_md_path=config.task_md_path)
        self.git = git or GitOps(root, main_branch=config.main_branch)
        self.schema = load_schema(self.root / "schemas" / "agent_result.schema.json")

    # ------------------------------------------------------------------ util
    def _artifact_dir(self, run_id):
        d = self.config.artifact_root / run_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _new_run_id(self, phase_id):
        return f"run-{phase_id}-{int(time.time())}-{random.randrange(16**4):04x}"

    def _write_prompt(self, run_id, name, body, *, phase_id, role):
        p = self._artifact_dir(run_id) / name
        contract = (
            "\n\n---\n## Orchestrator result contract (mandatory)\n"
            "Finish with EXACTLY ONE JSON object matching "
            "schemas/agent_result.schema.json with these bindings:\n"
            f'- "run_id": "{run_id}"\n- "phase_id": "{phase_id}"\n- "role": "{role}"\n'
            "Status must be one of completed|blocked|failed|unverified. "
            "Never claim PASS for a gate; gates are decided by the orchestrator only.\n")
        p.write_text(body + contract, encoding="utf-8")
        return p

    def _evidence_path(self, run_id):
        return self._artifact_dir(run_id) / "evidence.json"

    # ------------------------------------------------- control-plane integrity
    def _snapshot_protected(self):
        """Content-hash manifest {path: sha256} of the orchestrator-owned
        gate trust stores (acceptance + human-gate records) and the
        canonical state file, so a forged acceptance/approval record or a
        state tamper written by an agent is detected regardless of where
        the write came from. Deliberately EXCLUDES the journal, which the
        orchestrator itself appends to during an agent run."""
        manifest = {}
        targets = []
        for d in (self.config.acceptance_dir, self.config.human_gate_dir):
            d = Path(d)
            if d.exists():
                targets.extend(sorted(f for f in d.rglob("*") if f.is_file()))
        if Path(self.config.state_path).is_file():
            targets.append(Path(self.config.state_path))
        for f in targets:
            try:
                manifest[str(f)] = hashlib.sha256(f.read_bytes()).hexdigest()
            except OSError as e:
                manifest[str(f)] = f"__unreadable__:{type(e).__name__}"
        return manifest

    def _verify_protected(self, before, *, who):
        after = self._snapshot_protected()
        if before != after:
            added = sorted(set(after) - set(before))
            removed = sorted(set(before) - set(after))
            changed = sorted(k for k in before if k in after and before[k] != after[k])
            detail = []
            if added:
                detail.append("added " + ", ".join(Path(p).name for p in added[:5]))
            if removed:
                detail.append("removed " + ", ".join(Path(p).name for p in removed[:5]))
            if changed:
                detail.append("modified " + ", ".join(Path(p).name for p in changed[:5]))
            raise _Blocked(f"{who} tampered with orchestrator-owned trust store "
                           f"(acceptance/human-gate/state): {'; '.join(detail)}")

    # ------------------------------------------------------------- agent run
    def _run_agent(self, adapter, *, run_id, phase_id, role, workspace,
                   prompt_file, allowed_write_paths=()):
        """Runs one agent with the configured retry policy. Returns the
        validated structured report or raises _Blocked (fail closed).
        The orchestrator-owned trust stores are hashed before and after the
        run — an agent can never forge an acceptance/approval record, even
        by writing outside its worktree."""
        protected_before = self._snapshot_protected()
        timeout_s = getattr(adapter, "timeout_s", None) or 3600
        request = AgentRequest(
            run_id=run_id, phase_id=phase_id, role=role, workspace=Path(workspace),
            prompt_file=Path(prompt_file),
            output_schema_file=self.root / "schemas" / "agent_result.schema.json",
            timeout_s=timeout_s, allowed_write_paths=tuple(allowed_write_paths))

        backoff = list(self.config.backoff_s)
        schema_retries = self.config.invalid_schema_retries
        infra_used = 0
        while True:
            result = adapter.run(request)
            self.journal.append("agent_run", provider=adapter.provider, role=str(role),
                               run_id=run_id, exit_code=result.exit_code,
                               timed_out=result.timed_out,
                               duration_s=round(result.duration_s, 3))
            if result.timed_out:
                # EXIT_CODES.md: timeout (and any incomplete cleanup) is
                # fail-closed — no automatic retry into a dirty environment.
                raise _Blocked(f"{role} agent timed out (provider={adapter.provider})")
            if result.exit_code in self.config.retryable_exit_codes:
                if infra_used < len(backoff):
                    delay = backoff[infra_used]
                    infra_used += 1
                    self.journal.append("agent_retry_infrastructure",
                                       provider=adapter.provider, delay_s=delay,
                                       attempt=infra_used, run_id=run_id)
                    self.sleep(delay)
                    continue
                raise _Blocked(f"{role} agent infrastructure/quota failure persisted "
                               f"after {infra_used} retries (provider={adapter.provider})")
            if result.exit_code != 0:
                raise _Blocked(f"{role} agent process failed exit={result.exit_code} "
                               f"(provider={adapter.provider}): "
                               f"{secret_scan.redact(result.stderr.strip()[:300])}")
            errors = validate_agent_result(result.structured, schema=self.schema,
                                           request=request)
            if errors:
                if schema_retries > 0:
                    schema_retries -= 1
                    self.journal.append("agent_retry_invalid_schema",
                                       provider=adapter.provider, errors=errors[:5],
                                       run_id=run_id)
                    continue
                raise _Blocked(f"{role} agent structured result invalid: " +
                               "; ".join(errors[:5]))
            status = result.structured.get("status")
            if status != "completed":
                raise _Blocked(f"{role} agent reported status={status}")
            # fail closed if the agent touched any orchestrator-owned trust
            # store (forged acceptance/approval, state tamper) — regardless
            # of whether the write escaped the worktree.
            self._verify_protected(protected_before, who=f"{role} agent")
            return result.structured

    # ----------------------------------------------------------- policy check
    def _enforce_write_policy(self, worktree, base_sha, allowed_paths):
        changed = self.git.changed_paths(worktree, base_sha)
        forbidden = [p for p in changed
                     if not is_write_allowed(p, allowed_paths=allowed_paths,
                                             immutable_paths=self.config.immutable_paths)]
        return changed, forbidden

    # ------------------------------------------------------------------ main
    def run_phase(self, phase_id, *, resume=False):
        lock = SingleWriterLock(self.config.lock_path)
        try:
            lock.acquire()
        except LockHeldError as e:
            return EngineResult("BLOCKED", 3,
                                (f"single-writer lock unavailable: {e}",), {})
        try:
            return self._run_phase_locked(phase_id, resume=resume)
        finally:
            lock.release()

    # --------------------------------------------------------------- recover
    def recover(self, *, reason="operator recovery"):
        """Clear an interrupted/BLOCKED/wedged phase back to a runnable
        state, under the lock, from a FRESH state read (never a snapshot
        taken before locking). Reconciles a crash between git merge and the
        MERGED state write so a completed merge is never lost and never
        deadlocks. Never raises — always returns an EngineResult."""
        lock = SingleWriterLock(self.config.lock_path)
        try:
            lock.acquire(takeover_stale=True)
        except LockHeldError as e:
            return EngineResult("BLOCKED", 3,
                                (f"a live orchestrator holds the lock: {e}",), {})
        try:
            st = self.store.load()                     # CONC-04: read AFTER lock
            phase = phases.load_phase(self.root, st["phase_id"])
            frm = st["lifecycle"]

            if frm == "READY":
                return EngineResult("READY", 0, ("state already READY",), st)

            # CONC-03: reconcile against git before wiping anything.
            main_head = self.git.rev_parse(self.config.main_branch)
            candidate = st.get("candidate_commit")

            if frm == "MERGED" or (frm == "PASSED" and candidate and main_head == candidate):
                # The merge is (or should be) on main. If main HEAD == candidate,
                # the merge succeeded; finalize forward to READY(next phase).
                if candidate and main_head == candidate:
                    st = self._finalize_merged(st, phase, candidate, reason)
                    self.journal.append("recovered_merge_finalized", frm=frm,
                                       merged_commit=candidate, reason=reason)
                    return EngineResult("RECOVERED", 0,
                                        (f"reconciled {frm}: merge {candidate} finalized, "
                                         f"phase advanced",), st)
                # PASSED but main HEAD is not the candidate: merge never landed.
                # Safe to roll back to READY and rebuild; no work on main to lose.
                if frm == "MERGED":
                    return EngineResult(
                        "BLOCKED", 3,
                        (f"state MERGED but main HEAD {main_head[:8]} != candidate "
                         f"{str(candidate)[:8]}: manual git inspection required",), st)

            # ordinary interrupted/BLOCKED phase: document then reset to READY
            if frm != "BLOCKED":
                st = self.store.transition(st, phase, "BLOCKED",
                                           reason=f"operator recovery from {frm}: {reason}",
                                           task_note=f"recovered from interrupted {frm}")
            st = self.store.transition(
                st, phase, "READY", run_id=None, candidate_commit=None,
                tested_commit=None, reviewed_commit=None, approved_commit=None,
                merged_commit=None, test_evidence_id=None, review_evidence_id=None,
                human_approval_id=None, last_gate=None, reason=reason,
                task_note="operator recovery -> READY")
            self.journal.append("recovered", frm=frm, reason=reason)
            return EngineResult("RECOVERED", 0, (f"{frm} -> READY",), st)
        except (StateError, PhaseError, GitError, OSError) as e:
            return EngineResult("BLOCKED", 3,
                                (f"recovery blocked: {type(e).__name__}: {e}",), {})
        finally:
            lock.release()

    def _finalize_merged(self, st, phase, merged, reason):
        """Complete a confirmed merge forward to READY(next phase). Used by
        the normal path and by recover reconciliation."""
        if st["lifecycle"] == "PASSED":
            st = self.store.transition(st, phase, "MERGED", merged_commit=merged,
                                       reason=reason, task_note=f"merged {merged}")
        # clean up any leftover worktree for this run
        run_id = st.get("run_id")
        if run_id:
            wt = self.config.worktree_root / run_id
            if Path(wt).exists():
                self.git.remove_worktree(wt, branch=f"candidate/phase-{phase['id']}/{run_id}")
        nxt = phases.next_phase_id(self.root, phase["id"])
        st = self.store.transition(
            st, phase, "READY",
            phase_id=nxt if nxt is not None else st["phase_id"],
            run_id=None, attempt=0, builder=None, candidate_commit=None,
            test_evidence_id=None, review_evidence_id=None, human_gate_required=None,
            last_gate="PASS", reviewer_provider=None, builder_provider=None,
            approved_commit=None, reviewed_commit=None, tested_commit=None,
            human_approval_id=None,
            task_note=(f"phase {phase['id']} merged; next phase {nxt} ready"
                       if nxt else f"phase {phase['id']} merged; no further phases"))
        return st

    def _run_phase_locked(self, phase_id, *, resume):
        try:
            st = self.store.load()
        except StateError as e:
            return EngineResult("BLOCKED", 3, (str(e),), {})
        try:
            phase = phases.load_phase(self.root, phase_id)
        except PhaseError as e:
            return EngineResult("BLOCKED", 3, (str(e),), st)

        if str(st.get("phase_id")) != str(phase_id):
            return EngineResult("BLOCKED", 3,
                                (f"canonical state is at phase {st.get('phase_id')}, "
                                 f"not {phase_id}",), st)
        if resume:
            return self._resume_human_gate(st, phase)
        if st["lifecycle"] != "READY":
            return self._block(
                st, phase,
                f"phase {phase_id} is mid-flight (lifecycle={st['lifecycle']}); "
                "an interrupted run requires explicit `recover` before rerun")

        try:
            registry = test_registry.load(self.config.registry_path)
            gaps = test_registry.coverage_gaps(registry, phases_dir=self.root / "phases")
            if gaps:
                raise _Blocked("test registry coverage gaps: " + ", ".join(gaps))

            # preflight: git posture
            branch = self.git.current_branch()
            if branch != self.config.main_branch:
                raise _Blocked(f"wrong branch: on {branch!r}, main is "
                               f"{self.config.main_branch!r}")
            if self.config.require_clean_main:
                dirty = self.git.dirty_paths(exclude_prefixes=ORCHESTRATOR_OWNED_PREFIXES)
                if dirty:
                    raise _Blocked("dirty main: " + ", ".join(dirty[:10]))

            # preflight: adapters
            b_doc = self.builder.doctor()
            if not b_doc.get("available"):
                raise _Blocked(f"builder unavailable: {b_doc.get('detail')}")
            r_doc = self.reviewer.doctor()
            if not r_doc.get("available"):
                raise _Blocked(f"reviewer unavailable: {r_doc.get('detail')}")
            if phase.get("cross_vendor_review") and \
                    self.builder.provider == self.reviewer.provider:
                raise _Blocked("cross-vendor review required: builder and reviewer "
                               f"are the same provider ({self.builder.provider}) — "
                               "the same agent is never an independent reviewer")

            run_id = self._new_run_id(phase_id)
            base_sha = self.git.rev_parse(self.config.main_branch)
            wt_branch = f"candidate/phase-{phase_id}/{run_id}"
            worktree = self.git.create_worktree(
                self.config.worktree_root / run_id, wt_branch, base_sha)
            self.journal.append("run_started", run_id=run_id, phase_id=phase_id,
                               base_sha=base_sha, builder=self.builder.provider,
                               reviewer=self.reviewer.provider)

            st = self.store.transition(
                st, phase, "BUILDING", run_id=run_id, attempt=st["attempt"] + 1,
                builder=self.builder.provider, builder_provider=self.builder.provider,
                reviewer_provider=self.reviewer.provider,
                human_gate_required=bool(phase.get("human_gate")), last_gate=None,
                candidate_commit=None, tested_commit=None, reviewed_commit=None,
                approved_commit=None, merged_commit=None, human_approval_id=None,
                task_note=f"builder {self.builder.provider} working")

            allowed = tuple(phase.get("allowed_write_paths", []))
            build_prompt_src = self.root / "prompts" / "build" / f"phase-{phase_id}.md"
            if not build_prompt_src.exists():
                raise _Blocked(f"build prompt missing: {build_prompt_src}")
            prompt = self._write_prompt(run_id, "builder_prompt.md",
                                        build_prompt_src.read_text(encoding="utf-8"),
                                        phase_id=phase_id, role="builder")
            self._run_agent(self.builder, run_id=run_id, phase_id=phase_id,
                            role=AgentRole.BUILDER, workspace=worktree,
                            prompt_file=prompt, allowed_write_paths=allowed)

            if self.git.rev_parse("HEAD", cwd=worktree) != base_sha:
                raise _Blocked("agent created commits itself (agents_may_commit=false)")
            changed, forbidden = self._enforce_write_policy(worktree, base_sha, allowed)
            if forbidden:
                raise _Blocked("forbidden write paths from builder: " +
                               ", ".join(forbidden[:10]))
            candidate = self.git.commit_all(
                worktree, f"phase {phase_id} candidate ({run_id})",
                allow_empty=self.allow_empty_candidate)
            if candidate is None:
                raise _Blocked("builder produced no changes — nothing to checkpoint")

            st = self.store.transition(st, phase, "TESTING",
                                       candidate_commit=candidate,
                                       task_note="deterministic tests running")

            fix_cycles = 0
            findings = []
            gate_cfg = phase.get("gate", {})
            max_blockers = int(gate_cfg.get("max_blockers", 0))
            max_high = int(gate_cfg.get("max_unaccepted_high", 0))

            while True:
                exit_codes, metrics, outcomes = run_required_tests(
                    phase, registry, run_id=run_id, workdir=worktree,
                    capabilities=self.capabilities, base_env=self.base_env,
                    journal=self.journal)
                failed = [t for t, c in exit_codes.items() if c != 0]
                if failed:
                    detail = "; ".join(f"{o.test_id}: {o.status} ({o.detail})"
                                       for o in outcomes if o.exit_code != 0)
                    if st["lifecycle"] == "RETESTING":
                        raise _Blocked(f"regression after fix — tests still failing: {detail}")
                    if fix_cycles >= self.config.max_fix_cycles:
                        raise _Blocked(f"fix cycle budget exhausted with failing tests: {detail}")
                    st, candidate = self._fix_cycle(
                        st, phase, run_id, worktree, candidate, allowed,
                        reason=f"tests failing: {detail}", findings=())
                    fix_cycles += 1
                    continue

                st = self.store.transition(st, phase, "CHECKPOINTED",
                                           tested_commit=candidate,
                                           test_evidence_id=run_id,
                                           task_note="tests green at candidate")
                st = self.store.transition(st, phase, "REVIEWING",
                                           task_note=f"reviewer {self.reviewer.provider} (read-only)")
                findings = self._review(run_id, phase, worktree, candidate)
                st = self.store.save({**st, "review_evidence_id": run_id,
                                      "reviewed_commit": candidate})

                accepted, _acc_reasons = acceptance.accepted_ids(
                    acceptance.load_records(self.config.acceptance_dir),
                    phase_id=str(phase.get("id")), candidate_commit=candidate)
                blockers = sum(1 for f in findings if f.get("severity") == "blocker")
                unaccepted_high = sum(
                    1 for f in findings if f.get("severity") == "high"
                    and (f.get("id") or f.get("finding_id")) not in accepted)
                if blockers > max_blockers or unaccepted_high > max_high:
                    if fix_cycles >= self.config.max_fix_cycles:
                        # let the completion gate document the failure
                        st = self.store.transition(st, phase, "GATE_EVALUATION",
                                                   task_note="gate evaluation (findings over budget)")
                        break
                    st, candidate = self._fix_cycle(
                        st, phase, run_id, worktree, candidate, allowed,
                        reason=f"review findings: {blockers} blocker / "
                               f"{unaccepted_high} unaccepted high",
                        findings=findings)
                    fix_cycles += 1
                    continue

                st = self.store.transition(st, phase, "GATE_EVALUATION",
                                           task_note="gate evaluation")
                break

            # ---------------- completion gate inputs (all real evidence)
            diff_paths = self.git.changed_paths(worktree, base_sha)
            secrets = secret_scan.scan_paths(worktree, diff_paths)
            _, forbidden = self._enforce_write_policy(worktree, base_sha, tuple(phase.get("allowed_write_paths", [])))
            clean_main = self.git.is_clean(exclude_prefixes=ORCHESTRATOR_OWNED_PREFIXES)
            evidence = {
                "run_id": run_id, "phase_id": phase_id,
                "candidate_commit": candidate,
                "tested_commit": st["tested_commit"],
                "reviewed_commit": st["reviewed_commit"],
                "base_sha": base_sha, "worktree": str(worktree),
                "worktree_branch": wt_branch,
                "test_exit_codes": exit_codes, "metrics": metrics,
                "findings": findings, "secret_findings": secrets,
                "forbidden_changes": forbidden, "clean_main": clean_main,
                "recorded_utc": utc_now(),
            }
            self._evidence_path(run_id).write_text(
                json.dumps(evidence, indent=2, default=str), encoding="utf-8")

            return self._gate_and_finish(st, phase, evidence)

        except _Blocked as e:
            return self._block(st, phase, e.reason)
        except (GitError, StateError, PhaseError, ValueError, OSError) as e:
            return self._block(st, phase, f"{type(e).__name__}: {e}")

    # ------------------------------------------------------------- fix cycle
    def _fix_cycle(self, st, phase, run_id, worktree, candidate, allowed, *,
                   reason, findings):
        st = self.store.transition(st, phase, "FIXING", reason=reason,
                                   task_note=f"fixer addressing: {reason[:120]}")
        fix_src = self.root / "prompts" / "fix" / "verified-findings-fix.md"
        body = (fix_src.read_text(encoding="utf-8") if fix_src.exists() else
                "Fix the verified findings/failures below. Smallest coherent change.\n")
        body += "\n\n## Verified failures/findings\n```json\n" + \
                json.dumps({"reason": reason, "findings": list(findings)}, indent=2) + "\n```\n"
        prompt = self._write_prompt(run_id, f"fix_prompt_{st['sequence']}.md", body,
                                    phase_id=phase["id"], role="fixer")
        pre_fix_head = self.git.rev_parse("HEAD", cwd=worktree)
        self._run_agent(self.builder, run_id=run_id, phase_id=str(phase["id"]),
                        role=AgentRole.FIXER, workspace=worktree,
                        prompt_file=prompt, allowed_write_paths=allowed)
        if self.git.rev_parse("HEAD", cwd=worktree) != pre_fix_head:
            raise _Blocked("fixer created commits itself (agents_may_commit=false)")
        _, forbidden = self._enforce_write_policy(worktree, pre_fix_head, allowed)
        if forbidden:
            raise _Blocked("forbidden write paths from fixer: " + ", ".join(forbidden[:10]))
        new_candidate = self.git.commit_all(
            worktree, f"phase {phase['id']} fix ({run_id})",
            allow_empty=self.allow_empty_candidate)
        if new_candidate is None:
            raise _Blocked("fixer produced no changes while failures persist")
        st = self.store.transition(st, phase, "RETESTING",
                                   candidate_commit=new_candidate,
                                   tested_commit=None, reviewed_commit=None,
                                   task_note="re-testing fixed candidate")
        return st, new_candidate

    # ---------------------------------------------------------------- review
    def _review(self, run_id, phase, worktree, candidate):
        review_dir = self.root / "prompts" / "review"
        parts = [p.read_text(encoding="utf-8")
                 for p in sorted(review_dir.glob("*.md"))] or \
                ["Review the candidate adversarially. Report findings honestly."]
        prompt = self._write_prompt(run_id, "review_prompt.md",
                                    "\n\n---\n\n".join(parts),
                                    phase_id=phase["id"], role="reviewer")
        structured = self._run_agent(
            self.reviewer, run_id=run_id, phase_id=str(phase["id"]),
            role=AgentRole.REVIEWER, workspace=worktree, prompt_file=prompt)
        # read-only enforcement: ANY write (tracked change, untracked file,
        # or a commit) by the reviewer blocks the phase.
        if self.git.rev_parse("HEAD", cwd=worktree) != candidate:
            raise _Blocked("reviewer moved HEAD — write attempt in read-only review")
        dirty = self.git.dirty_paths(cwd=worktree)
        if dirty:
            raise _Blocked("reviewer write attempt (read-only role): " +
                           ", ".join(dirty[:10]))
        return list(structured.get("findings", []))

    # ------------------------------------------------------------------ gate
    def _gate_and_finish(self, st, phase, evidence):
        candidate = evidence["candidate_commit"]
        approval = human_gate.latest_decision(
            self.config.human_gate_dir, phase_id=str(phase["id"]),
            commit_sha=candidate)
        needs_human = bool(phase.get("human_gate"))
        if needs_human:
            if st["lifecycle"] == "GATE_EVALUATION":
                st = self.store.transition(
                    st, phase, "HUMAN_GATE",
                    task_note=f"human gate for SHA {candidate}")
                self.journal.append("human_gate_requested", phase_id=phase["id"],
                                   candidate_commit=candidate, run_id=st["run_id"])
            if approval is None:
                return EngineResult(
                    "AWAITING_HUMAN_GATE", 3,
                    (f"human gate: approve candidate {candidate} via "
                     f"`approve --commit {candidate} --approver <you> --decision APPROVE`, "
                     "then rerun with --resume",), st)

        decision = gates.evaluate_completion_gate(
            phase,
            test_exit_codes=evidence["test_exit_codes"],
            metrics=evidence["metrics"],
            review_findings=evidence["findings"],
            forbidden_changes=evidence["forbidden_changes"],
            secret_findings=evidence["secret_findings"],
            clean_main=evidence["clean_main"],
            candidate_commit=candidate,
            tested_commit=evidence["tested_commit"],
            reviewed_commit=evidence["reviewed_commit"],
            approved_commit=candidate if (approval and approval.get("decision") == "APPROVE") else None,
            human_approval_record=approval,
            acceptance_records=acceptance.load_records(self.config.acceptance_dir),
        )
        self.journal.append("gate_decision", phase_id=phase["id"],
                           passed=decision.passed, reasons=list(decision.reasons),
                           candidate_commit=candidate, run_id=st["run_id"])
        if not decision.passed:
            st = self.store.transition(st, phase, "BLOCKED",
                                       last_gate="FAIL",
                                       reason="; ".join(decision.reasons),
                                       task_note="gate FAILED")
            return EngineResult("BLOCKED", 3, decision.reasons, st)

        st = self.store.transition(
            st, phase, "PASSED", last_gate="PASS",
            approved_commit=candidate if approval else st.get("approved_commit"),
            human_approval_id=(approval or {}).get("approval_id"),
            task_note="gate PASSED — merging ff-only")

        # Journal the merge INTENT before touching main, so a crash between
        # the git merge and the MERGED state write is reconcilable by
        # `recover` (which compares main HEAD against candidate/base).
        base_for_merge = self.git.rev_parse(self.config.main_branch)
        self.journal.append("merging_intent", phase_id=phase["id"],
                           candidate_commit=candidate, base_sha=base_for_merge,
                           run_id=st["run_id"])
        merged = self.git.merge_ff_only(candidate)
        merge_check = gates.validate_merge_commit(
            candidate_commit=candidate, merged_commit=merged)
        if not merge_check.passed:
            st = self.store.transition(st, phase, "BLOCKED",
                                       reason="; ".join(merge_check.reasons),
                                       task_note="merge integrity failure")
            return EngineResult("BLOCKED", 3, merge_check.reasons, st)
        st = self._finalize_merged(st, phase, merged, reason="normal completion")
        return EngineResult("MERGED", 0,
                            (f"phase {phase['id']} merged as {merged}",), st)

    # ------------------------------------------------------------- resume
    def _resume_human_gate(self, st, phase):
        if st["lifecycle"] != "HUMAN_GATE":
            return EngineResult("BLOCKED", 3,
                                (f"--resume only valid in HUMAN_GATE "
                                 f"(lifecycle={st['lifecycle']})",), st)
        run_id = st.get("run_id")
        try:
            evidence = json.loads(self._evidence_path(run_id).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return self._block(st, phase, f"gate evidence unreadable for {run_id}: {e}")
        if evidence.get("candidate_commit") != st.get("candidate_commit"):
            return self._block(st, phase, "evidence/candidate SHA mismatch on resume")
        try:
            self.git.rev_parse(evidence["candidate_commit"])
        except GitError:
            return self._block(st, phase, "candidate commit vanished — rollback/recover required")
        try:
            return self._gate_and_finish(st, phase, evidence)
        except _Blocked as e:
            return self._block(st, phase, e.reason)
        except (GitError, StateError) as e:
            return self._block(st, phase, f"{type(e).__name__}: {e}")

    # ------------------------------------------------------------------ block
    def _block(self, st, phase, reason):
        reason = secret_scan.redact(reason)
        self.journal.append("blocked", phase_id=st.get("phase_id"),
                           run_id=st.get("run_id"), reason=reason)
        try:
            if st.get("lifecycle") != "BLOCKED":
                st = self.store.transition(st, phase, "BLOCKED", reason=reason,
                                           task_note=f"BLOCKED: {reason[:160]}")
        except StateError:
            # transition to BLOCKED not legal from here (e.g. MERGED) —
            # journal already has the event; state stays as-is, fail closed.
            pass
        return EngineResult("BLOCKED", 3, (reason,), st)
