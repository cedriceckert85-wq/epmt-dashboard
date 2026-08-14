"""Pipeline-Orchestrierung.

Zwei Ebenen:
- ``run_creative_pipeline``: von fertigen Bausteinen (Transkript,
  Reaktionen, Events, Dauer) bis zu den Ausgabedateien. Komplett ohne
  Binaries lauffaehig — Selftest und Tests nutzen genau diesen Pfad.
- ``analyze_vod``: echte VOD -> ffprobe/ffmpeg/whisper -> Bausteine ->
  ``run_creative_pipeline``.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Callable

from . import media, transcribe
from .channels import build_channel_plans, build_chapters
from .config import Config
from .dualbrain import blend_second_opinion
from .editorial import (
    Moment,
    SessionInsights,
    attach_candidates,
    build_candidates,
    dedupe_moments,
    moment_pass,
    moments_from_candidates,
    session_pass,
)
from .errors import ClipLabError, MissingInputError
from .events import GameEvent, load_events
from .memory import BrainStore
from .output import build_plan_dict, render_edit_sheet, write_outputs
from .planning import Clip, plan_clips
from .ranking import rank_moments
from .reactions import Reaction, detect_reactions
from .styles import StyleProfile
from .timeline import build_entries, render_doc
from .transcribe import TranscriptSegment


def _today() -> str:
    return datetime.date.today().isoformat()


@dataclass
class SessionParts:
    vod_name: str
    duration: float
    segments: list[TranscriptSegment] = dc_field(default_factory=list)
    reactions: list[Reaction] = dc_field(default_factory=list)
    events: list[GameEvent] = dc_field(default_factory=list)


@dataclass
class Deps:
    """Injizierbare Abhaengigkeiten (Tests/Selftest ersetzen alles Echte)."""

    llm_primary: Callable | None = None
    llm_secondary: Callable | None = None
    brain: BrainStore | None = None
    profile: StyleProfile | None = None
    now_fn: Callable[[], str] = _today
    log: Callable[[str], None] = print
    ffprobe_duration: Callable = media.ffprobe_duration
    extract_audio: Callable = media.extract_audio
    read_wav: Callable = media.read_wav_mono
    transcribe_wav: Callable = transcribe.transcribe_wav
    have_ffmpeg: Callable = media.have_ffmpeg


@dataclass
class AnalyzeResult:
    out_dir: Path
    paths: dict
    clips: list[Clip]
    moments: list[Moment]
    insights: SessionInsights
    mode: str
    warnings: list[str]
    memory_report: list[str]
    plan: dict


def run_creative_pipeline(
    cfg: Config,
    parts: SessionParts,
    deps: Deps,
    out_dir: Path | str,
    extra_warnings: list[str] | None = None,
) -> AnalyzeResult:
    warnings: list[str] = list(extra_warnings or [])
    log = deps.log

    entries = build_entries(parts.segments, parts.reactions, parts.events)
    doc = render_doc(entries, parts.duration, parts.vod_name)
    candidates = build_candidates(parts.reactions, parts.events)

    # Gedaechtnis VOR der Analyse injizieren
    brain_data = None
    memory_block = ""
    if deps.brain is not None:
        brain_data = deps.brain.load()
        memory_block = deps.brain.render_block(brain_data)

    cut_styles = deps.profile.cuts if deps.profile is not None else {}

    insights = SessionInsights()
    moments: list[Moment] = []
    mode = "signal-only"
    mode_line = (
        "Signal-only — keine LLM-CLI verfuegbar; Ranking rein nach "
        "Audio-Reaktionen/Game-Events (klar gekennzeichnet)"
    )
    if deps.llm_primary is not None:
        log("LLM-Editorial: Session-Pass ...")
        insights = session_pass(cfg, doc, parts.duration, deps.llm_primary, memory_block)
        log("LLM-Editorial: Moment-Pass ...")
        moments, moment_prompt = moment_pass(
            cfg,
            entries,
            candidates,
            insights,
            cut_styles,
            memory_block,
            parts.duration,
            deps.llm_primary,
        )
        if moments:
            mode = "llm"
            mode_line = "LLM-Editorial (zwei Paesse ueber die konfigurierte CLI)"
            # Doppel-Gehirn (F9): identischer Moment-Prompt, Blend-Semantik
            moments, notes = blend_second_opinion(
                moments,
                moment_prompt,
                deps.llm_secondary,
                parts.duration,
                set(cut_styles.keys()),
                cfg,
            )
            for n in notes:
                log(n)
            if deps.llm_secondary is not None and any("uebernommen" in n or "bewertet" in n for n in notes):
                mode_line += " + Zweitmeinung"
        else:
            # Ehrliche Modus-Zeile: die CLI war DA, die Antwort war unbrauchbar
            mode_line = (
                "Signal-only — LLM lieferte keine verwertbaren Momente; "
                "Ranking rein nach Audio-Reaktionen/Game-Events"
            )
            warnings.append(
                "LLM lieferte keine verwertbaren Momente — Fallback auf Signal-only."
            )
    if mode == "signal-only":
        moments = moments_from_candidates(candidates)

    moments = dedupe_moments(moments)
    attach_candidates(moments, candidates)

    ranked = rank_moments(moments, parts.duration, cfg)
    clips = plan_clips(ranked, parts.duration, cfg, deps.profile)

    # Gedaechtnis NACH der Analyse fortschreiben — nur bei echter
    # LLM-Analyse (Signal-only verschmutzt das Gedaechtnis nicht).
    memory_report: list[str] = []
    memory_state: dict | None = None
    if deps.brain is not None and brain_data is not None and mode == "llm":
        brain_data, memory_report = deps.brain.update_after_session(
            brain_data,
            parts.vod_name,
            insights,
            moments,
            runner=deps.llm_primary,
        )
        deps.brain.save(brain_data)
        memory_state = {
            "gags_known": len(brain_data["gags"]),
            "sessions_known": len(brain_data["sessions"]),
            "gags_by_slug": {g["slug"]: g for g in brain_data["gags"]},
        }
    for line in memory_report:
        log(line)

    plans = build_channel_plans(clips, cfg, deps.profile)
    chapters = build_chapters(clips, parts.duration)

    stats = {
        "segments": len(parts.segments),
        "reactions": len(parts.reactions),
        "events": len(parts.events),
        "candidates": len(candidates),
        "moments": len(moments),
        "clips": len(clips),
    }
    generated_on = deps.now_fn()
    sheet = render_edit_sheet(
        parts.vod_name,
        parts.duration,
        mode_line,
        stats,
        clips,
        plans,
        parts.segments,
        memory_state,
        generated_on,
        warnings=warnings,
    )
    plan = build_plan_dict(
        parts.vod_name, parts.duration, mode, stats, clips, plans, chapters, generated_on
    )
    paths = write_outputs(out_dir, sheet, plan, clips, chapters)
    return AnalyzeResult(
        out_dir=Path(out_dir),
        paths=paths,
        clips=clips,
        moments=moments,
        insights=insights,
        mode=mode,
        warnings=warnings,
        memory_report=memory_report,
        plan=plan,
    )


@dataclass
class AnalyzeRequest:
    vod: Path
    out_dir: Path | None = None
    transcript: Path | None = None
    events: Path | None = None
    audio_stream: str | None = None  # None = Config; sonst CLI-Override
    whisper_model: str | None = None
    no_llm: bool = False
    no_memory: bool = False
    no_style: bool = False


def analyze_vod(cfg: Config, req: AnalyzeRequest, deps: Deps) -> AnalyzeResult:
    """Echte VOD analysieren (F1/F2/F3 + kreative Pipeline)."""
    vod = Path(req.vod)
    if not vod.is_file():
        raise MissingInputError(
            f"VOD nicht gefunden: {vod}",
            hint="Pfad pruefen. Unterstuetzt: mp4/mkv/webm/mov/avi/ts/m4v.",
        )
    out_dir = Path(req.out_dir) if req.out_dir else vod.parent / (vod.stem + cfg.out_suffix)
    out_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    log = deps.log

    # Dauer (ffprobe); mit --transcript geht es notfalls auch ohne
    duration = 0.0
    try:
        duration = deps.ffprobe_duration(vod)
    except ClipLabError as exc:
        if req.transcript is None:
            raise
        warnings.append(
            f"ffprobe nicht nutzbar ({exc.message}) — Dauer aus dem Transkript geschaetzt."
        )

    # Transkript
    if req.transcript is not None:
        segments = transcribe.load_transcript_json(req.transcript)
        log(f"Transkript geladen: {len(segments)} Segmente (Whisper uebersprungen)")
    else:
        segments = None  # spaeter, braucht erst das WAV

    # Audio -> WAV (fuer Reaktionen und ggf. Whisper)
    audio_stream = cfg.audio_stream if req.audio_stream is None else req.audio_stream
    wav_path = out_dir / "audio_16k.wav"
    samples = None
    sr = 16000
    if deps.have_ffmpeg() is not None:
        try:
            deps.extract_audio(vod, wav_path, audio_stream=audio_stream)
            samples, sr = deps.read_wav(wav_path)
        except ClipLabError as exc:
            if segments is None:
                raise
            warnings.append(f"Audio-Analyse uebersprungen: {exc.message}")
    elif segments is None:
        raise ClipLabError(
            "ffmpeg fehlt — ohne ffmpeg kann keine echte VOD analysiert werden.",
            hint="ffmpeg installieren (`doctor` prueft die Umgebung) — oder "
            "--transcript datei.json nutzen.",
        )
    else:
        warnings.append("ffmpeg fehlt — keine Audio-Reaktionserkennung moeglich.")

    if segments is None:
        model_size = req.whisper_model or cfg.whisper_model
        log(f"Transkription (faster-whisper {model_size}, CPU int8, VAD) ...")
        segments, info = deps.transcribe_wav(wav_path, model_size, cfg.language)
        log(f"Transkript: {len(segments)} Segmente, Sprache: {info.get('language', '?')}")

    if duration <= 0:
        duration = max((s.t1 for s in segments), default=0.0) + 5.0

    reactions: list[Reaction] = []
    if samples is not None:
        reactions = detect_reactions(
            samples,
            sr,
            threshold_db=cfg.reaction_threshold_db,
            floor_dbfs=cfg.reaction_floor_dbfs,
            merge_gap_s=cfg.reaction_merge_gap_s,
            baseline_window_s=cfg.reaction_baseline_window_s,
        )
        log(f"Reaktionserkennung: {len(reactions)} laute Stellen")

    events: list[GameEvent] = []
    if req.events is not None:
        events, ev_warnings = load_events(req.events)
        warnings.extend(ev_warnings)
        log(f"Game-Events: {len(events)} geladen")

    # WAV-Zwischendatei nach der Analyse loeschen (Config-Schalter)
    if wav_path.is_file() and not cfg.keep_wav:
        try:
            wav_path.unlink()
        except OSError:
            pass

    parts = SessionParts(
        vod_name=vod.name,
        duration=duration,
        segments=segments,
        reactions=reactions,
        events=events,
    )
    return run_creative_pipeline(cfg, parts, deps, out_dir, extra_warnings=warnings)
