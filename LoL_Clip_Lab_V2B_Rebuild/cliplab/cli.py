"""CLI (F13): python -m cliplab <kommando>.

Alle Fehlerpfade freundlich: fehlende Dateien -> Exit 2 + Meldung;
operative Fehler zentral abgefangen -> Exit 1 + Meldung. Nie ein
Stacktrace fuer erwartbare Probleme.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, media
from .config import Config, load_config
from .cutting import cut_from_plan
from .doctor import run_doctor
from .errors import ClipLabError, MissingInputError
from .fetchcmd import fetch
from .llm import CliLLM
from .memory import BrainStore
from .pipeline import AnalyzeRequest, Deps, analyze_vod
from .selftest import run_selftest
from .styles import ensure_example_structure, learn_styles, load_profile, save_profile
from .transcribe import WhisperUnavailable, load_whisper_model, transcribe_wav


def say(msg: str = "") -> None:
    try:
        print(msg)
    except UnicodeEncodeError:  # Windows-Konsole mit Legacy-Codepage
        print(str(msg).encode("ascii", "replace").decode("ascii"))


# ---------------------------------------------------------------------------
# Parser


def _add_analyze_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--out", type=Path, default=None, help="Ausgabeordner")
    p.add_argument("--transcript", type=Path, default=None,
                   help="fertiges Transkript-JSON (ueberspringt Whisper)")
    p.add_argument("--events", type=Path, default=None,
                   help="Game-Events (JSON oder CSV)")
    p.add_argument("--audio-stream", default=None,
                   help="Tonspur, z.B. a:1 (Spur 2 = nur Mikro)")
    p.add_argument("--whisper-model", default=None,
                   choices=["tiny", "base", "small", "medium"],
                   help="Whisper-Modellgroesse")
    p.add_argument("--no-llm", action="store_true", help="Signal-only (ohne LLM)")
    p.add_argument("--no-memory", action="store_true", help="Kanal-Gedaechtnis aus")
    p.add_argument("--no-style", action="store_true", help="Stil-Profil ignorieren")
    p.add_argument("--cut", action="store_true", help="Clips nach der Analyse schneiden")
    p.add_argument("--encoder", default=None, choices=["auto", "amf", "x264"],
                   help="Video-Encoder fuers Schneiden (AMD AMF oder CPU x264)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cliplab",
        description="LoL Clip Lab — lokales Edit-Sheet-Tool fuer Stream-VODs",
    )
    parser.add_argument("--config", type=Path, default=None, help="Pfad zur config.toml")
    parser.add_argument("--version", action="version", version=f"cliplab {__version__}")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("analyze", help="eine VOD analysieren -> Edit-Sheet")
    p.add_argument("vod", type=Path)
    _add_analyze_flags(p)

    p = sub.add_parser("batch", help="alle VODs eines Ordners analysieren")
    p.add_argument("folder", type=Path)
    _add_analyze_flags(p)

    p = sub.add_parser("cut", help="Clips laut edit_plan.json schneiden")
    p.add_argument("vod", type=Path)
    p.add_argument("plan", type=Path)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--encoder", default=None, choices=["auto", "amf", "x264"])

    p = sub.add_parser("learn", help="Stile aus Referenz-Clips lernen")
    p.add_argument("folder", type=Path, nargs="?", default=None)
    p.add_argument("--no-llm", action="store_true", help="nur mechanisch lernen")

    p = sub.add_parser("fetch", help="Referenz-Clips per yt-dlp laden")
    p.add_argument("urls", nargs="+")
    p.add_argument("--style", default=None, help="Ziel: kanal/stil (z.B. insta/funny)")

    p = sub.add_parser("memory", help="Kanal-Gedaechtnis anzeigen/loeschen")
    p.add_argument("--clear", action="store_true")

    sub.add_parser("doctor", help="Umgebung pruefen (ffmpeg, whisper, LLM-CLI, ...)")

    p = sub.add_parser("selftest", help="kompletter Offline-Selbsttest mit Demo-Daten")
    p.add_argument("--out", type=Path, default=None, help="Ausgabeordner behalten")

    return parser


# ---------------------------------------------------------------------------
# Deps-Verdrahtung


def build_deps(cfg: Config, no_llm: bool, no_memory: bool, no_style: bool) -> Deps:
    llm_primary = None
    if not no_llm:
        runner = CliLLM(cfg.llm_cmd, timeout_s=cfg.llm_timeout_s)
        if runner.available():
            llm_primary = runner
        else:
            say(
                "Hinweis: LLM-CLI "
                f"({' '.join(cfg.llm_cmd) or 'leer'}) nicht gefunden — "
                "Signal-only-Modus (Sheet wird klar gekennzeichnet)."
            )
    llm_secondary = None
    if llm_primary is not None and cfg.llm2_cmd:
        runner2 = CliLLM(cfg.llm2_cmd, timeout_s=cfg.llm_timeout_s)
        if runner2.available():
            llm_secondary = runner2
        # nicht installiert -> STILL ueberspringen (F9)
    brain = None
    if cfg.memory_enabled and not no_memory:
        brain = BrainStore(cfg.resolve(cfg.memory_path), cfg)
    profile = None
    if not no_style:
        profile = load_profile(cfg.resolve(cfg.style_profile_path))
    return Deps(
        llm_primary=llm_primary,
        llm_secondary=llm_secondary,
        brain=brain,
        profile=profile,
        log=say,
    )


def _request_from_args(vod: Path, args) -> AnalyzeRequest:
    return AnalyzeRequest(
        vod=vod,
        out_dir=args.out,
        transcript=args.transcript,
        events=args.events,
        audio_stream=getattr(args, "audio_stream", None),
        whisper_model=args.whisper_model,
        no_llm=args.no_llm,
        no_memory=args.no_memory,
        no_style=args.no_style,
    )


# ---------------------------------------------------------------------------
# Kommandos


def cmd_analyze(args, cfg: Config) -> int:
    deps = build_deps(cfg, args.no_llm, args.no_memory, args.no_style)
    result = analyze_vod(cfg, _request_from_args(args.vod, args), deps)
    say("")
    say(f"Fertig: {result.paths['sheet']}")
    say(f"  Clips: {len(result.clips)} · Modus: {result.mode}")
    for w in result.warnings:
        say(f"  Hinweis: {w}")
    if args.cut:
        say("Schneide Clips ...")
        ok, notes = cut_from_plan(
            args.vod, result.paths["plan"], cfg,
            out_dir=result.out_dir / "clips",
            encoder_choice=args.encoder,
            log=say,
        )
        say(f"  {ok} Clip-Dateien geschnitten.")
        for n in notes:
            say(f"  Hinweis: {n}")
    return 0


def cmd_batch(args, cfg: Config) -> int:
    folder = Path(args.folder)
    if not folder.is_dir():
        raise MissingInputError(
            f"Ordner nicht gefunden: {folder}",
            hint="batch erwartet einen Ordner voller VOD-Dateien.",
        )
    vods = sorted(
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in media.VIDEO_EXTS
    )
    if not vods:
        raise ClipLabError(
            f"Keine Videodateien in {folder} gefunden.",
            hint=f"Unterstuetzt: {', '.join(sorted(media.VIDEO_EXTS))}",
        )
    failures = 0
    for i, vod in enumerate(vods, start=1):
        say(f"[{i}/{len(vods)}] {vod.name}")
        try:
            deps = build_deps(cfg, args.no_llm, args.no_memory, args.no_style)
            sub_args_out = args.out / vod.stem if args.out else None
            req = _request_from_args(vod, args)
            req.out_dir = sub_args_out
            result = analyze_vod(cfg, req, deps)
            say(f"  -> {result.paths['sheet']}")
            if args.cut:
                ok, notes = cut_from_plan(
                    vod, result.paths["plan"], cfg,
                    out_dir=result.out_dir / "clips",
                    encoder_choice=args.encoder, log=say,
                )
                say(f"  -> {ok} Clips geschnitten")
        except ClipLabError as exc:
            failures += 1
            say(exc.friendly())
            say("  ... weiter mit der naechsten Datei.")
    say(f"Batch fertig: {len(vods) - failures}/{len(vods)} erfolgreich.")
    return 1 if failures else 0


def cmd_cut(args, cfg: Config) -> int:
    ok, notes = cut_from_plan(
        args.vod, args.plan, cfg, out_dir=args.out,
        encoder_choice=args.encoder, log=say,
    )
    say(f"{ok} Clip-Dateien geschnitten.")
    for n in notes:
        say(f"Hinweis: {n}")
    return 0


class _SharedWhisperSampler:
    """Geteiltes Whisper-Modell fuer Transkript-Proben beim Stil-Lernen.

    Ohne Whisper: liefert None und das Lernen laeuft ohne Text weiter.
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.model = None
        self.dead = False

    def __call__(self, path: Path) -> str | None:
        if self.dead:
            return None
        if self.model is None:
            try:
                self.model = load_whisper_model(self.cfg.whisper_model)
            except WhisperUnavailable as exc:
                say(f"Hinweis: {exc.message} — lerne ohne Transkript-Proben weiter.")
                self.dead = True
                return None
        import tempfile

        try:
            with tempfile.TemporaryDirectory(prefix="cliplab_learn_") as td:
                wav = Path(td) / "sample.wav"
                exe = media.have_ffmpeg()
                if exe is None:
                    return None
                media.default_run(
                    [exe, "-y", "-v", "error", "-t", "120", "-i", str(path),
                     "-vn", "-ac", "1", "-ar", "16000", str(wav)],
                    timeout=600,
                )
                if not wav.is_file() or wav.stat().st_size == 0:
                    return None
                segments, _info = transcribe_wav(wav, self.cfg.whisper_model, self.cfg.language, model=self.model)
                return " ".join(s.text for s in segments)
        except ClipLabError:
            return None


def cmd_learn(args, cfg: Config) -> int:
    ref_dir = Path(args.folder) if args.folder else cfg.resolve(cfg.references_dir)
    if ensure_example_structure(ref_dir, cfg):
        say(f"Beispielstruktur angelegt: {ref_dir}")
        say("Referenz-Clips in die Unterordner legen (z.B. insta/funny) und")
        say("`python -m cliplab learn` erneut ausfuehren.")
        return 0
    if media.have_ffmpeg() is None:
        raise ClipLabError(
            "ffmpeg fehlt — ohne ffprobe/ffmpeg kann `learn` keine Clips vermessen.",
            hint="ffmpeg installieren; `doctor` prueft die Umgebung.",
        )
    runner = None
    if not args.no_llm:
        cli = CliLLM(cfg.llm_cmd, timeout_s=cfg.llm_timeout_s)
        if cli.available():
            runner = cli
        else:
            say("Hinweis: LLM-CLI nicht gefunden — lerne rein mechanisch (Mediane).")
    sampler = _SharedWhisperSampler(cfg)
    profile, report = learn_styles(
        ref_dir,
        cfg,
        probe_duration=lambda p: media.ffprobe_duration(p),
        scene_rate=lambda p, d: media.scene_cut_rate(p, d),
        transcribe_sample=sampler,
        runner=runner,
    )
    for line in report:
        say(line)
    if profile.is_empty():
        say("Nichts gelernt — keine brauchbaren Referenzen gefunden.")
        return 0
    out_path = cfg.resolve(cfg.style_profile_path)
    save_profile(out_path, profile)
    say(f"Stil-Profil gespeichert: {out_path}")
    say(f"  CUT-Stile: {', '.join(sorted(profile.cuts)) or '-'}")
    say(f"  FORMAT-Profile: {', '.join(sorted(profile.formats)) or '-'}")
    return 0


def cmd_memory(args, cfg: Config) -> int:
    store = BrainStore(cfg.resolve(cfg.memory_path), cfg)
    if args.clear:
        if store.clear():
            say(f"Gedaechtnis geloescht: {store.path}")
        else:
            say(f"Kein Gedaechtnis vorhanden ({store.path}).")
        return 0
    brain = store.load()
    say(f"Gedaechtnis: {store.path}")
    say(
        f"  {len(brain['gags'])} Running Gags · {len(brain['catchphrases'])} "
        f"Catchphrases · {len(brain['lore'])} Lore · "
        f"{len(brain['sessions'])} Sessions"
    )
    block = store.render_block(brain)
    if block:
        say("")
        say(block)
    else:
        say("  (noch leer — entsteht bei der ersten LLM-Analyse)")
    return 0


def dispatch(args, cfg: Config, config_warnings: list[str]) -> int:
    if args.command == "analyze":
        return cmd_analyze(args, cfg)
    if args.command == "batch":
        return cmd_batch(args, cfg)
    if args.command == "cut":
        return cmd_cut(args, cfg)
    if args.command == "learn":
        return cmd_learn(args, cfg)
    if args.command == "fetch":
        return fetch(args.urls, args.style, cfg, log=say)
    if args.command == "memory":
        return cmd_memory(args, cfg)
    if args.command == "doctor":
        return run_doctor(cfg, config_warnings, log=say)
    if args.command == "selftest":
        return run_selftest(args.out, log=say)
    build_parser().print_help()
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        cfg, warnings = load_config(args.config)
        for w in warnings:
            say(f"WARNUNG: {w}")
        return dispatch(args, cfg, warnings)
    except MissingInputError as exc:
        say(exc.friendly())
        return 2
    except ClipLabError as exc:
        say(exc.friendly())
        return 1
    except KeyboardInterrupt:
        say("Abgebrochen.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
