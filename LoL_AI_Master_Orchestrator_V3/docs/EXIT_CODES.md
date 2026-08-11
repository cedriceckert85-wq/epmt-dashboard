# Orchestrator Exit Codes

Provider adapters must normalize provider-specific conditions.

Internal classification:
- 0 = completed process; structured result still must validate
- 2 = invalid invocation/config
- 3 = blocked by orchestrator gate/bootstrap
- 4 = operation intentionally not implemented/safe in skeleton
- 75 = RETRYABLE_INFRASTRUCTURE (normalized internal code only)

Raw provider exit codes must never be treated as retryable until the adapter explicitly maps them to an internal classification.
Retry policy comes from ORCHESTRATOR_CONFIG.yaml.


## ProcessResult.cleanup_incomplete
`cleanup_incomplete=true` means the process tree could not be verifiably terminated after a timeout (kill failed, or output pipes had to be abandoned).

Orchestrator handling is mandatory and fail-closed:
- treat the agent run as FAILED/UNVERIFIED regardless of exit code
- set phase status BLOCKED, never retry automatically into a dirty environment
- record the event in the journal
- require environment inspection (orphan processes, locks, worktrees) before any rerun
