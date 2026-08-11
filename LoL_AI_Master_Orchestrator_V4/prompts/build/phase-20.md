# BUILD PHASE 20 — POC/Go-No-Go

Read persistent instructions (CLAUDE.md/AGENTS.md), MASTER_ORCHESTRATOR.md and the orchestrator-generated current task.

## Preconditions
- Phases 01–17 + 19 gates PASS.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Scope
- ONE real ~8 h stream through the ENTIRE chain: record → upload → reconstruct → rank → EDL → render → dashboard review → publish (unlisted) → analytics ingest

## Tests / metrics
- e2e_real_stream → end_to_end_success == 1, human_minutes_per_published_video ≤ 10
- phase_20_tests: e2e harness checks

## Human review criteria (Go/No-Go)
- Output quality the user would actually publish; total manual effort acceptable; storage/GPU headroom confirmed; go/no-go record with exact SHA.
- **Editorial/humor quality (V4 — core mechanic, explicitly judged):**
  of the top 10 clips of the POC session: ≥ 6 rated "would publish as-is",
  0 clips with the punchline cut off, ≥ 2 clips that contain NO game event
  (pure comedy/talk moments found by the editorial layer — if the session
  plausibly contained such moments), captions/zooms/SFX land on the punchline
  not just on kills. Run tests/harness/editorial_eval.py (built in phase 10)
  against hand labels of THIS session; attach its report (found-rate,
  punchline offset median) to the Go/No-Go record. These numbers are recorded
  evidence for the human decision, not auto-gates — humor is judged by you.
## Concrete files
- tests/harness/e2e_real_stream.py (orchestrates checks + collects metrics), runbooks/POC_RUNBOOK.md (written in this phase)

## Failure modes to observe and report (not fix here)
- any manual intervention (counts into human_minutes), storage/GPU contention during live recording, publish delays

## Real vs mock
- Real only. No mocked step is acceptable as Go/No-Go evidence; every artifact (segments, sync map, EDLs, renders, ledger rows, analytics rows) is attached to the human-gate record with the exact SHA.

## Go/No-Go decision record
- HUMAN_GATE record per reports/templates/HUMAN_GATE.md, bound to the exact candidate SHA; a NO-GO lists the blocking findings with ids.

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 20 gate.
