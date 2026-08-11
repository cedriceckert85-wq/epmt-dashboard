# Test Spec — Tailscale Disconnect / Resume

Required integration cases:
- healthy tunnel → upload active
- Tailscale service stopped mid-chunk
- network briefly disconnected
- Central Receiver disappears
- tunnel returns with same receiver identity
- local queue survives Agent restart
- no insecure public fallback
- resume continues from verified state
- checksum correct
- no duplicate logical object
- no upload spike on reconnect

PASS requires logs, byte/hash validation and measured resume behavior.
