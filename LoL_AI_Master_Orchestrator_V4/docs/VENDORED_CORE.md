# VENDORED_CORE — the field-tested creative core (vendor/clip_lab_core/)

`vendor/clip_lab_core/` contains **LoL Clip Lab V2**, the LOCAL test edition of
exactly the creative pipeline that phases 09–13 of this orchestrator specify.
It is not a sketch: it was built, adversarially fuzzed and audited across many
verification rounds, exercised against REAL ffmpeg and a REAL `claude -p`
editorial loop, and ships with **222 passing unit/integration tests**.

## The rule for builders (phases 09–13)

**ADOPT AND EXTEND — do not re-derive.** Start `src/pipeline/` from the
vendored `clip_lab/` package (rename/move as the architecture requires), keep
its tests running against your adaptation, and preserve every mechanic below.
Re-implementing any of this from scratch throws away hundreds of verified
fixes and is a review blocker.

## Proven mechanics that MUST survive into the product

1. **Whole-script session pass** (`editorial.py`): the ENTIRE transcript goes
   to the LLM — long sessions in line-aligned chunks with findings carried
   forward and merged; never head-truncate the script.
2. **Two-pass editorial brain**: session pass (gags/callbacks/arcs) feeds a
   batched moment pass; candidate-focused log windows with an even discovery
   sample; every LLM field sanitized (validated tags, bounded strings, no
   NaN/Infinity, no path-hostile text in filenames/CSV).
3. **Channel memory** (`memory.py`): persistent gag/lore brain across
   sessions; injected into prompts; LLM consolidation with mechanical
   fallback; re-analysis of the same VOD must NOT inflate counters;
   lore-recognized gags bump `times_seen`.
4. **Multi-style references** (`style.py`): one profile per
   `references/<channel>/<flavor>/` folder; whole-video references become
   FORMAT profiles (target runtime for the channel plan), only short-clip
   references become per-moment CUT styles; `<channel>_<flavor>` style names
   imply their channel.
5. **Channel routing**: per-moment `channels` tags validated against the
   configured channels (`insta`/`yt`/`uncut` model — names, `kind=full`,
   `max_s`, `vertical` are config-driven); chronological per-channel plans
   with timecodes; `chapters.txt` obeying YouTube rules (00:00 first, >=10s
   spacing).
6. **Dual editorial brain** (`llm_client.py` + `_blend_second_opinion`):
   Claude primary + optional second CLI on IDENTICAL evidence; scores
   averaged, extra finds adopted, the primary's work never overwritten;
   executable resolved via `shutil.which` (Windows .cmd shims).
7. **Punchline-aware EDL** (`edl.py`): setup preroll only when the window is
   not already the LLM's; end anchored after the punchline; fixed-length
   window slid into media bounds (min-length holds at VOD edges); learned
   style targets may exceed the generic `clip_max_s`.
8. **Signal safety net** (`reactions.py`, `timeline.py`, `rank.py`):
   deterministic reactions (robust z-score + MAD floor + −50 dBFS floor),
   event weighting, co-occurrence boost, duration-scaled `top_k` — the
   pipeline must produce a useful sheet with NO LLM at all.
9. **Language & hosts**: output language mirrors the streamers' speech
   (config-forceable); multi-host attribution hint.
10. **Graceful degradation everywhere**: friendly operational errors (whisper
    model download failure names the fix), never a stacktrace for an expected
    failure; AMD-safe defaults (CPU whisper, AMF/x264, never NVENC/CUDA).

## What the online edition ADDS on top (unchanged phase goals)

Live capture (OBS agent), Riot live data, sync engine, segmentation/upload,
rendering at scale, dashboard, publishing, analytics, multi-streamer — the
phases around 09–13. The vendored core is the creative heart those phases
feed into and consume from.

## Verification heritage (why you must not re-derive)

Highlights of what the audits caught and fixed in this core: session-log
truncation at 24k chars (would have silently dropped hours of script), LLM
JSON extraction returning array elements instead of arrays, zero-width
candidate matching, budget thinning starving late candidates, memory crashes
on hostile JSON (Infinity, null-for-list, deep nesting), a Windows START.bat
parser kill, ffmpeg zero-encode reported as success, phantom reactions on
muted-mic audio, English captions forced onto German streams, format profiles
fabricated as 90s cut styles. Every one is regression-tested in
`vendor/clip_lab_core/tests/`.
