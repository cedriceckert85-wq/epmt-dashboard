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
from . import ingest, rank, reactions, timeline, transcribe
from .edl import build_edit_plan
from .editsheet import write_edit_sheet
from .llm_client import LLMClient


def analyze(vod_path, cfg, out_dir, *, transcript_path=None, events_path=None,
            audio_stream=None, llm=None, log=print):
    vod_path = Path(vod_path)
    out = Path(out_dir)
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)

    # 1) transcript (from file, or transcribe the VOD)
    if transcript_path:
        log(f"[1/6] transcript: loading {transcript_path}")
        segments = transcribe.load_transcript(transcript_path)
        duration = _duration_from(segments)
    else:
        log("[1/6] audio: extracting mono track with ffmpeg …")
        wav = ingest.extract_audio(vod_path, work / "audio.wav", audio_stream=audio_stream)
        duration = ingest.probe_duration(vod_path)
        log("[2/6] transcribe: running whisper (CPU) …")
        segments = transcribe.transcribe(wav, cfg, log=log)
        transcribe.save_transcript(segments, work / "transcript.json")

    # 2) reactions (need the audio; if transcript-only, skip)
    reacts = []
    wav_file = work / "audio.wav"
    if wav_file.exists():
        log("[3/6] reactions: scanning audio energy …")
        samples, sr = ingest.read_wav_mono(wav_file)
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
    log("[5/6] editorial: asking the LLM for humor/callbacks/punchlines …"
        if (cfg.use_llm and llm.available())
        else "[5/6] editorial: LLM unavailable — signal-only ranking")
    cands, source, context = editorial_mod.run_editorial(cands, doc, llm, cfg, log=log)

    ranked = rank.rank_candidates(cands, cfg)
    plan = build_edit_plan(ranked, segments, cfg, duration)

    # 5) write the edit sheet
    meta = {"duration": duration, "editorial": source, "reactions": len(reacts),
            "events": len(evs), "candidates": len(cands),
            "session_context": context}
    write_edit_sheet(plan, out, vod_name=vod_path.name, meta=meta)
    log(f"[6/6] done: {len(plan)} clips → {out/'edit_sheet.md'}")
    return plan, meta


def _duration_from(segments):
    return max((s.t1 for s in segments), default=0.0)
