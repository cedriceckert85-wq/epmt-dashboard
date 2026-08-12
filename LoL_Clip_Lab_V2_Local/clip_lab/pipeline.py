"""Orchestrate the analyze pipeline end to end:

  VOD ─(ffmpeg)→ audio ─(whisper)→ transcript ┐
                       └─(numpy)→ reactions ───┼→ timeline ─(LLM)→ editorial
  events.json (optional) ──────────────────────┘                      │
                                                             rank → EDL → edit sheet

Every stage degrades gracefully; the deterministic signal path always yields
a usable edit sheet even with no LLM and no game events.
"""
from pathlib import Path

from . import editorial as editorial_mod
from . import events as events_mod
from . import memory as memory_mod
from . import ingest, rank, reactions, timeline, transcribe
from .edl import build_edit_plan
from .editsheet import write_edit_sheet
from .llm_client import LLMClient


def analyze(vod_path, cfg, out_dir, *, transcript_path=None, events_path=None,
            audio_stream=None, llm=None, memory_path=None, log=print):
    vod_path = Path(vod_path)
    out = Path(out_dir)
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)

    # 1) transcript (from file, or transcribe the VOD)
    audio_wav = None  # set only when WE extract audio this run
    if transcript_path:
        log(f"[1/6] transcript: loading {transcript_path}")
        segments = transcribe.load_transcript(transcript_path)
        duration = _duration_from(segments)
    else:
        log("[1/6] audio: extracting mono track with ffmpeg …")
        audio_wav = Path(ingest.extract_audio(vod_path, work / "audio.wav",
                                              audio_stream=audio_stream))
        duration = ingest.probe_duration(vod_path)
        log("[2/6] transcribe: running whisper (CPU) …")
        segments = transcribe.transcribe(audio_wav, cfg, log=log)
        transcribe.save_transcript(segments, work / "transcript.json")

    # 2) reactions. Gate on audio WE extracted this run, not on a file existing
    # on disk — a stale audio.wav from a prior full run into the same --out dir
    # must not be paired with a different session's transcript.
    reacts = []
    if audio_wav is not None and audio_wav.exists():
        log("[3/6] reactions: scanning audio energy …")
        samples, sr = ingest.read_wav_mono(audio_wav)
        reacts = reactions.detect_reactions(
            samples, sr, frame_ms=cfg.reaction_frame_ms,
            min_gap_s=cfg.reaction_min_gap_s, prominence=cfg.reaction_prominence,
            baseline_window_s=cfg.reaction_baseline_window_s)
    else:
        log("[3/6] reactions: no audio (transcript-only mode) — skipping")

    # 3) optional game events
    evs = events_mod.load_events(events_path) if events_path else []
    log(f"[4/6] context: {len(segments)} speech segments, {len(reacts)} reactions, "
        f"{len(evs)} game events")

    # 4) candidates + editorial brain
    cands = timeline.signal_candidates(reacts, evs, cfg)
    doc = timeline.build_timeline_doc(segments, reacts, evs)
    if llm is None:
        llm = LLMClient(cfg.llm_cmd, cfg.llm_timeout_s)

    # channel memory (the brain across sessions): inject what earlier streams
    # taught us, so returning running gags are recognized
    memory = None
    brief = ""
    if memory_path and cfg.memory_enabled:
        memory = memory_mod.load_memory(memory_path)
        brief = memory_mod.memory_brief(memory)
        if brief:
            log(f"[brain] channel memory: {len(memory['gags'])} running gags from "
                f"{memory['sessions_analyzed']} earlier sessions")

    log("[5/6] editorial: asking the LLM for humor/callbacks/punchlines …"
        if (cfg.use_llm and llm.available())
        else "[5/6] editorial: LLM unavailable — signal-only ranking")
    cands, source, context = editorial_mod.run_editorial(
        cands, doc, llm, cfg, memory_brief=brief, log=log)

    ranked = rank.rank_candidates(cands, cfg)
    plan = build_edit_plan(ranked, segments, cfg, duration)

    # 5) write the edit sheet (+ update the brain with today's findings)
    meta = {"duration": duration, "editorial": source, "reactions": len(reacts),
            "events": len(evs), "candidates": len(cands),
            "session_context": context}
    if memory is not None:
        memory = memory_mod.update_memory(memory, context, vod_path.name,
                                          llm if cfg.use_llm else None, cfg, log=log)
        memory_mod.save_memory(memory_path, memory)
        meta["memory"] = {"gags": len(memory["gags"]),
                          "sessions_analyzed": memory["sessions_analyzed"]}
        log(f"[brain] memory updated: {len(memory['gags'])} running gags remembered")
    write_edit_sheet(plan, out, vod_name=vod_path.name, meta=meta)
    log(f"[6/6] done: {len(plan)} clips → {out/'edit_sheet.md'}")
    return plan, meta


def _duration_from(segments):
    return max((s.t1 for s in segments), default=0.0)
