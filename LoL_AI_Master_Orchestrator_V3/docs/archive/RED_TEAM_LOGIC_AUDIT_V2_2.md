# V2.2 Logic Audit Fixes

Fixed:
1 reviewer self-accept removed
2 human-gate path immutable
3 SHA/clean-main/lifecycle enforced in gate evaluator
4 phase gate config consumed
5 phase-00 bootstrap deadlock removed via run-phase00
6 phase-00 writable paths include orchestrator
7 no prior-gate requirement for phase 00
8 approve no longer fake-success
9 Windows taskkill /T /F
10 communicate after kill bounded
11 process-group intent now used via tree-kill design
12 empty stdin handled
13 phase IDs normalized as strings
14 backoff aligned to retries
15 one global max_fix_cycles
16 project_state lifecycle is sole canonical status
17 projections immutable
18 receiver/security precedes safe uploader
19 read-only reviews no longer perform fault injection
20 human-gate schema bound to exact SHA
21 Obsidian uses repo root vault
22 fake hang safely exceeds timeout
23 retryable exit code defined/normalized
24 Researcher role aligned
25 multi-streamer optional/disabled by default
