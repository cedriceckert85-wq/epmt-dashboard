# Architecture

Python Orchestrator is the control plane.
Claude/Codex are workers, never the authority for gates.

Flow:
Human → Orchestrator → Builder → deterministic tests → candidate commit → other-vendor read-only review → gate engine → fix/human gate → ff-only merge.


## MVP Network
Streamer Agent → Tailscale → Central Receiver. Application auth and resumable upload remain separate layers.
