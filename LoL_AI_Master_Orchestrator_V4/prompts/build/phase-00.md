# PHASE 00 — Orchestrator Self-Check (agentless)

V4 note: this phase runs WITHOUT agents. The orchestrator that ships in
this package validates itself:

1. doctor: git + Claude CLI + Codex CLI usable (and logged in), host
   capabilities probed (gpu/tailscale/…)
2. phase_00_tests: the full orchestrator unit test suite
   (tests/unit — gates, path policy, acceptance, state machine, test
   runner, secret scan, result contract, process runner)
3. baseline git integrity

Only after this gate PASSes do live agent phases (01+) start.

If you are an agent reading this: you were routed here by mistake —
report a blocker finding and stop.
