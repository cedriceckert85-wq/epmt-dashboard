# Tailscale + Windows Firewall Runbook

Goal: Central Receiver is reachable through the intended private path only.

Principles:
- Prefer binding receiver to Tailscale interface/IP.
- No broad public inbound rules.
- No automatic router port-forwarding.
- Application authentication remains mandatory.

Verify:
1. approved streamer reaches receiver over Tailscale
2. public WAN path does not expose receiver
3. unrelated host cannot reach receiver unless explicitly intended
4. invalid app credentials fail
5. Tailscale membership alone does not authorize another tenant
