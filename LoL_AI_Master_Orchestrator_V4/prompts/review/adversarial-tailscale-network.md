# ADVERSARIAL TAILSCALE NETWORK REVIEW

READ-ONLY.

Check for:
- accidental public receiver exposure
- insecure fallback
- Tailscale used as sole tenant auth
- stale IP assumptions
- MagicDNS failure handling
- receiver bound to 0.0.0.0
- broad firewall rules
- reconnect/resume corruption
- queue loss after service restart
- cross-tenant access from another tailnet device
- bandwidth spike on reconnect
- poor observability when tunnel is down

Return findings with a stable unique id, severity, evidence, reproduction and required test. Do not fix.
