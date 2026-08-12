# BUILD_PASS vs RELEASE_CERTIFIED (V4.1)

An external logic audit correctly pointed out that a green one-shot run did
NOT mean "the product was proven" — it meant "everything checkable passed."
The most serious case: Phase 20 (POC/Go-No-Go) could report PASS even when the
real end-to-end stream never ran, because `e2e_real_stream` is deferrable and
was the sole producer of both final metrics. This document describes the fix.

## Two distinct outcomes

**BUILD_PASS** — the default one-shot result. Every phase merged; every
mock/fixture test passed; deterministic gates held. Real-world tests that need
hardware you don't have (GPU, OBS, a live game, Tailscale, the 8h soak) were
**deferred** (recorded as UNVERIFIED, never faked as passing), and subjective
quality gates were auto-approved so the build could proceed unattended.

**RELEASE_CERTIFIED** — the real Go/No-Go. Additionally requires:
1. **No deferred real-world test** — every `release_required_tests` entry
   actually ran on the target hardware.
2. **Real human quality sign-off** — every `human_review_required` gate
   (phases 12 render, 14 dashboard, 16 publishing, 20 POC) was approved by a
   human via `orchestrator approve`, not by AUTO_GATE.

The final report and the exit line always state which one you reached, and
list exactly what is still open for certification.

## How to certify

Run the build one-shot normally (any machine) to reach BUILD_PASS. Then, on the
**target hardware** (RTX 2080 + Tailscale + OBS + a real LoL game), run:

```
START.bat --certify            # Windows   (./start.sh --certify on Linux/macOS)
```

In `--certify` mode:
- deferrable real-world tests may **not** defer — a missing capability BLOCKS
  the phase with a clear "certification requires <capability>" message instead
  of silently passing;
- `human_review_required` gates **pause** for a real human approval instead of
  auto-approving.

## Machine-enforced dependencies

Phase preconditions are no longer prose-only. Each phase declares `depends_on`
(machine-checked): a phase cannot start until every dependency is MERGED with
gate PASS. So `--phases 20` on a fresh project now BLOCKS ("phase 20 depends on
19, which is not PASSED yet") instead of building Phase 20 against nothing.

## Downstream invalidation

If an optional or earlier phase is merged after a later phase was already
certified (the "enable Phase 18 multi-streamer after Phase 20 Go/No-Go" case),
the later phase is dropped from history via `invalidated_by` and must be
re-run / re-certified. The system Phase 20 certified against no longer silently
diverges from `main`.

## The plan linter

`orchestrator/plan_linter.py` runs inside the Phase-00 self-check and statically
rejects the whole class of contradiction that produced these findings:
- a produced numeric metric that no phase gates (caught `stream_dropped_frames_pct_delta`);
- a gate metric with no in-phase `metrics_json` producer (dead-end);
- a hardware-deferrable test missing from `release_required_tests`;
- a missing/circular `depends_on`;
- a dangling `invalidated_by`;
- a subjective quality gate not marked `human_review_required`.

If any of these regress, the self-check fails before a single agent runs.
