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
