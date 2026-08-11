# Tailscale Network Architecture — MVP

## Decision
For the MVP with 1–3 trusted streamers, Tailscale is the default private network transport between each Streamer Agent and the Central Receiver.

Tailscale is the NETWORK LAYER only.

It does NOT replace:
- resumable upload
- chunking
- checksums
- idempotency
- tenant/device authentication
- upload queue persistence
- bandwidth throttling
- retry/recovery

## Topology
Streamer PC → Tailscale encrypted tunnel → Central Receiver → local storage / ingest.

No public port forwarding is required for the MVP.

## Security
- Prefer receiver binding to localhost/Tailscale interface/IP where practical.
- Do not expose receiver publicly unless explicitly required and separately secured.
- Each Streamer Agent still uses its own application credential/device identity.
- Tailscale identity is defense-in-depth, not the sole tenant boundary.
- Tenant identity must never come from an arbitrary client-supplied path alone.

## Preflight
Streamer Agent checks:
- Tailscale installed
- service running
- authenticated
- Central Receiver reachable
- expected receiver hostname/IP configured
- upload endpoint reachable
- no public fallback silently used

Central Receiver checks:
- tunnel connectivity available
- intended interface binding
- firewall rules appropriate
- app authentication still required

## Failure behavior
If Tailscale is offline:
- no automatic insecure public fallback
- queue remains local
- upload state = PAUSED_NETWORK
- bounded retry/backoff
- resume after tunnel recovery

## Multi-streamer
Each streamer gets its own:
- Tailscale device
- Streamer Agent device identity
- app credential
- upload queue
- tenant storage

A compromised streamer must not gain access to another tenant.

## Bandwidth
Tailscale does not solve bufferbloat.
Adaptive uploader remains mandatory:
Gameplay > Livestream > Content Upload.

Router SQM/QoS remains recommended where uplink bufferbloat exists.

## Addressing
Prefer MagicDNS hostname or configured Tailscale IP. Do not hard-code temporary LAN IPs.
