# BUILD PHASE 09 — Whisper/Reactions

Read persistent instructions (CLAUDE.md/AGENTS.md), MASTER_ORCHESTRATOR.md and the orchestrator-generated current task.

## Preconditions
- Phase 08 gate PASS.
- Candidate branch/worktree clean and correct.
- Do not start future phases. Do not weaken tests, thresholds, gates.
- Every symbolic test you must satisfy is defined in test_registry.yaml — build exactly those harnesses/commands.
- Report UNVERIFIED instead of guessing; real-hardware evidence cannot be mocked away.

## Inputs
- Mic-only track (T2) per session, RTX 2080 (CUDA), faster-whisper

## Architecture
- ASR: faster-whisper medium int8_float16 on GPU, VAD (silero) pre-filter, word-level timestamps, language de+en auto
- Chunked processing aligned to segments; transcripts stored with mono_ns mapping
- Reaction detector: mic RMS/pitch spike events (laugh/scream candidates) + keyword spotting from transcript (configurable list); events scored, stored like riot events (clock_domain AGENT_MONO)

## Concrete files
- src/pipeline/asr.py, src/pipeline/reactions.py, tests/harness/{asr_eval,reaction_eval}.py, labeled fixture set (≥ 30 min mic audio, hand-labeled reactions)

## Failure modes
- music bleed into mic, silence-heavy streams, VRAM pressure alongside NVENC (Phase 12 co-existence documented), model download offline

## Tests / metrics
- asr_fixture_suite → asr_rtf_gpu ≤ 0.35, transcript_coverage_pct ≥ 95
- reaction_precision_fixture → reaction_precision_fixture ≥ 0.7 (precision on labeled set; recall reported, not gated)
- phase_09_tests

## Real vs mock
- Fixtures from real recorded streams (with consent); GPU required — no CPU fallback pretending to meet RTF.

## Human review criteria
- Spot-listen 10 detected reactions; false-positive character acceptable for ranking use.

## Output
Implementation report (schema-valid, findings with stable unique ids) + changed files + commands + evidence artifacts + failures + risks.
STOP at the Phase 09 gate.
