# Architecture (V4)

The Python orchestrator (shipped, self-tested) is the control plane.
Claude/Codex are workers, never the authority for gates.

Flow per phase:
START (one action) → bootstrap/doctor → builder agent → orchestrator
candidate commit → deterministic registry tests (secrets stripped) →
checkpoint → other-vendor review (report-only writes) → deterministic
gate engine → auto/human gate record (SHA-bound) → ff-only merge → next
phase. Failures: max 2 fix cycles, then BLOCKED (resumable).

Enforcement after every agent run: git-diff path policy (immutable beats
allowed) + hash snapshots for gitignored control files.

## MVP Network
Streamer Agent → Tailscale → Central Receiver. Application auth and
resumable upload remain separate layers. Without the tailscale capability
the affected tests run as deferred/UNVERIFIED, never as fake passes.
