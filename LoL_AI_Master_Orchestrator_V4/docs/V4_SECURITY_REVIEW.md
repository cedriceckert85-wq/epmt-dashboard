# V4 Security & Logic Review — Findings and Fixes

The V4 orchestrator was put through a multi-lens adversarial review (gate
bypass, write-policy/enforcement holes, state-machine/resume, CLI adapter
realism, cross-platform bootstrap, test-runner honesty). 17 findings were
confirmed (0 refuted) and all were fixed before packaging. Summary:

| # | Sev | Finding | Fix |
|---|-----|---------|-----|
| 1 | blocker | `.venv/`, `.orchestrator/` (gitignored + immutable) were not snapshotted, so agent writes there bypassed both enforcement layers (venv code injection persisting to next run). | `integrity.py` now stat-snapshots these trees too (bytecode caches excluded); tamper ⇒ BLOCKED. |
| 2 | high | Test-execution window ran untrusted candidate code with no integrity snapshot / no write-policy check — a test could forge gitignored control records (strict-mode human-gate bypass). | `_step_testing` snapshots the control plane around the test run and enforces the write policy afterwards. |
| 3 | high | Agent-side `git commit` hid forbidden (even tracked-immutable) edits from working-tree diff; gate `forbidden_changes` was hardcoded `[]`. | HEAD is pinned across every agent run (any move ⇒ BLOCKED); gate now computes `forbidden_changes` from committed diff vs base through the path policy. |
| 4 | high | pytest_junit parser counted SKIPPED as executed — an all-skipped suite passed with zero real assertions. | Parser now requires `tests − skipped > 0`; a wholly-skipped suite fails. |
| 5 | high | Reviewer result with status `unverified` was accepted as a clean cross-vendor review. | Reviewer/builder/fixer must report `completed`; anything else ⇒ BLOCKED. |
| 6 | high | Acceptance record went SHA-stale after a fix rebuild and permanently blocked the phase (even with a clean candidate). | Stale ACCEPT now accepts nothing silently (SHA scoping already prevents leakage) instead of emitting a blocking error. |
| 7 | high | `GitError` escaped `run()`, aborting without a BLOCKED transition or report. | `run()` catches `GitError` (and forces BLOCKED via a hardened `_block`). |
| 8 | high (×2) | Windows: npm `claude.cmd`/`codex.cmd` shims could not be spawned; doctor blocked every run. | `process_runner.resolve_argv` resolves via PATH and wraps `.cmd/.bat` with `cmd /c`; launch failure ⇒ exit 127, not a crash. |
| 9 | high | `SingleWriterLock` used `os.kill(pid,0)`, which on Windows *terminates* the probed process. | Windows liveness now uses `OpenProcess`/`GetExitCodeProcess`; fails closed. |
| 10 | high | `--phases` typo selecting nothing silently ran ALL phases and skipped CLI doctor checks. | `_parse_phase_selection` validates endpoints/order and raises on an empty selection. |
| 11 | medium | Shared retry counter let an infra retry consume the schema-retry budget. | Separate infra / schema / violation counters, each vs its own budget. |
| 12 | medium | `_step_passed` was not resumable across merge+delete (crash ⇒ permanently failing PASSED). | Idempotent: if `candidate_commit` is already an ancestor of main, finish instead of re-merging a deleted branch. |
| 13 | medium | Debian/Ubuntu without `python3-venv` left a poisoned half-venv + misleading "check internet". | Bootstrap detects venv-creation failure, removes the half-venv, prints the correct `apt-get install python3-venv` hint. |
| 14 | medium | Env strip list omitted `ANTHROPIC_AUTH_TOKEN` and other bearer vars. | Explicit list expanded + substring strip (`*TOKEN*`, `*API_KEY*`, `*SECRET*`, …) for test processes. |

All fixes ship with regression tests (91 unit tests green, incl. an
end-to-end dry-run of the whole phase loop). This document is historical;
the normative rules live in `MASTER_ORCHESTRATOR.md`.

---

## Round 2 — second independent verification pass

A second verification workflow re-attacked the round-1 fixes and swept for new
issues. It found several round-1 fixes insufficient and — more importantly for
actually shipping — more one-shot build blockers. All fixed:

| Area | Problem found | Fix |
|------|---------------|-----|
| build-reachability | Phase 07 gated on `stream_dropped_frames_pct_delta` and phase 18 on `cross_tenant_denied_pct` — metrics no required test of that phase produces → the run dead-ends at 07 (and 18). | Removed the misplaced soak metric from 07; added the producing (deferrable) test to 18. Audited all 21 phases: no orphan gate metrics remain. |
| optional phases | `optional`/`enabled_by_default:false` (phase 18) was never honored, so a default run tried it and blocked. | A default run now skips optional phases; they run only when named in `--phases`. |
| junit honesty | An all-skipped suite still passed by (a) per-`<testcase>` `<skipped/>` with suite `skipped=0`, or (b) inflating the suite `tests` attribute above the emitted `<testcase>` count. | Executed count is now derived from real `<testcase>` elements only; failures/errors take max(attr, counted). |
| junit robustness | A non-numeric junit attribute crashed the orchestrator (ValueError escaped). | All attribute parsing is guarded; malformed evidence fails closed. |
| .venv integrity | Guard was narrowed to entrypoint names only, missing the real surface — overwriting an imported dependency module (`yaml/__init__.py`) that runs on the next invocation. | Guard now hashes every executable-as-source file under `.venv` (`.py/.pth/.so/.pyd/.dll/.egg-link`), still excluding regenerable caches (no false positives). |
| .git hooks | A planted `.git/hooks/pre-commit` or `core.hooksPath`/`fsmonitor` in `.git/config` executed as the orchestrator on its next git op. | All git commands run with hooks disabled (`core.hooksPath` → empty dir); `.git/hooks` and `.git/config` are now snapshotted. |
| ref integrity | Ref-pin only bracketed the synchronous agent/test call; a detached process could move `main` between windows. | `main` is pinned to a persisted baseline and re-checked at every phase start. |
| orphan processes | Child process group was reaped only on timeout, not on normal exit. | Process group is reaped on the normal exit path too (POSIX). |
| symlink forgery | Round-1 symlink refusal held, but the same goal was reachable with a plain regular record written while the orchestrator was stopped. | See trust boundary below. |
| docs | CLAUDE.md/AGENTS.md/MASTER_ORCHESTRATOR.md still said `schemas/` fully immutable and omitted `scripts/`. | Corrected everywhere. |

100+ unit tests green including new regressions for each of the above.

## Trust boundary (read this)

The three enforcement layers — git-diff path policy, hash/symlink snapshot of
gitignored control paths, and git-ref pinning — defend against **confused or
prompt-injected agents and single bad writes within a run**. They do **not**
fully defend against:

1. A **deliberately malicious agent that spawns a detached background process**
   (double-fork + `setsid`) which writes to control paths *while the
   orchestrator is stopped* (e.g. forging a strict-mode human-gate approval as
   an ordinary file between runs). The process-group reap, `main` baseline
   check, disabled git hooks and widened venv guard raise the bar but cannot
   fully close a session-detached daemon.
2. A **compromised host** or any other process running as the same user.

For those threat models, run the builder/reviewer CLIs inside an **OS sandbox**
— a container, a dedicated low-privilege user, or a Windows Job Object — so the
agent process cannot outlive its run or touch anything outside the workspace.
The default one-shot `gate_mode: auto` is not a human-trust boundary anyway (it
auto-approves once deterministic criteria hold); the strict human gate is the
one that assumes no attacker-controlled background process on the host.
