"""Command line: analyze / cut / doctor / selftest."""
import argparse
import sys
from pathlib import Path

from . import __version__
from .config import Config
from .doctor import format_doctor, run_doctor
from .pipeline import analyze

ROOT = Path(__file__).resolve().parents[1]


def _cfg(args):
    cfg = Config.load(ROOT)
    for k in ("whisper_model", "encoder"):
        v = getattr(args, k, None)
        if v:
            setattr(cfg, k, v)
    if getattr(args, "no_llm", False):
        cfg.use_llm = False
    return cfg


def cmd_analyze(args):
    cfg = _cfg(args)
    out = Path(args.out or (Path(args.vod).stem + "_clips"))
    if not args.transcript and not Path(args.vod).exists():
        print(f"VOD not found: {args.vod}", file=sys.stderr)
        return 2
    plan, meta = analyze(args.vod, cfg, out, transcript_path=args.transcript,
                         events_path=args.events, audio_stream=args.audio_stream)
    print(f"\nEdit sheet: {out/'edit_sheet.md'}")
    print(f"Machine plan: {out/'edit_plan.json'}   ·   CSV: {out/'clips.csv'}")
    print(f"Editorial brain used: {meta['editorial']}  ·  {len(plan)} clips suggested")
    if args.cut:
        _cut_all(args.vod, plan, cfg, out)
    return 0


def _cut_all(vod, plan, cfg, out):
    from .render import cut_clip, pick_encoder
    _, enc = pick_encoder(cfg)
    print(f"\nCutting {len(plan)} clips with {enc} …")
    cdir = Path(out) / "cuts"
    cdir.mkdir(parents=True, exist_ok=True)
    for p in plan:
        name = f"{p.rank:02d}_{p.category}.mp4"
        try:
            cut_clip(vod, cdir / name, p.clip_t0, p.clip_t1, cfg,
                     vertical=cfg.render_vertical)
            print(f"  ok  {name}")
        except Exception as e:
            print(f"  FAIL {name}: {e}")


def cmd_cut(args):
    cfg = _cfg(args)
    from .util import read_json
    from .render import cut_clip, pick_encoder
    plan = read_json(args.plan)["clips"]
    _, enc = pick_encoder(cfg)
    out = Path(args.out or "cuts")
    out.mkdir(parents=True, exist_ok=True)
    print(f"Cutting {len(plan)} clips with {enc} …")
    for p in plan:
        name = f"{p['rank']:02d}_{p.get('category','moment')}.mp4"
        try:
            cut_clip(args.vod, out / name, p["clip_t0"], p["clip_t1"], cfg,
                     vertical=cfg.render_vertical)
            print(f"  ok  {name}")
        except Exception as e:
            print(f"  FAIL {name}: {e}")
    return 0


def cmd_doctor(args):
    ok, rows = run_doctor(_cfg(args))
    print(format_doctor(ok, rows))
    return 0 if ok else 3


def cmd_selftest(args):
    """Run the whole editorial→rank→edl→edit-sheet path on the bundled sample
    transcript+events — no VOD, no whisper, no ffmpeg, no network needed.

    By default it uses a CANNED editorial brain (clip_lab._demo) so the edit
    sheet shows the full creative output: funny titles, punchline-aware cuts,
    captions, SFX and callbacks. Pass --signal-only to see the deterministic
    fallback the tool uses when no LLM is available."""
    cfg = _cfg(args)
    out = Path(args.out or "selftest_out")
    sample_t = ROOT / "samples" / "fixture_transcript.json"
    sample_e = ROOT / "samples" / "fixture_events.json"
    if args.signal_only:
        cfg.use_llm = False
        llm = None
    else:
        from ._demo import demo_llm
        cfg.use_llm = True
        llm = demo_llm()
    plan, meta = analyze(str(ROOT / "samples" / "sample_vod.mkv"), cfg, out,
                         transcript_path=sample_t, events_path=sample_e, llm=llm)
    print(f"\nSelf-test OK — editorial brain: {meta['editorial']} — "
          f"{len(plan)} clips → {out/'edit_sheet.md'}")
    print("Open that file to see the suggested cuts, captions and SFX.")
    return 0 if plan else 1


def build_parser():
    p = argparse.ArgumentParser(prog="clip_lab", description="LoL Clip Lab — local edit studio")
    p.add_argument("--version", action="version", version=f"clip_lab {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", help="analyze a VOD -> edit sheet")
    a.add_argument("vod")
    a.add_argument("--out", help="output folder (default: <vod>_clips)")
    a.add_argument("--transcript", help="use a pre-made transcript JSON (skip whisper)")
    a.add_argument("--events", help="optional game events JSON/CSV")
    a.add_argument("--audio-stream", help="ffmpeg audio stream to use, e.g. a:1 for the mic")
    a.add_argument("--whisper-model", help="tiny|base|small|medium")
    a.add_argument("--no-llm", action="store_true", help="signal-only, no editorial LLM")
    a.add_argument("--cut", action="store_true", help="also cut the clips with ffmpeg")
    a.add_argument("--encoder", help="auto|amf|x264")
    a.set_defaults(func=cmd_analyze)

    c = sub.add_parser("cut", help="cut clips from an existing edit_plan.json")
    c.add_argument("vod")
    c.add_argument("plan")
    c.add_argument("--out", help="output folder (default: cuts)")
    c.add_argument("--encoder")
    c.set_defaults(func=cmd_cut)

    d = sub.add_parser("doctor", help="check local tooling")
    d.set_defaults(func=cmd_doctor)

    s = sub.add_parser("selftest", help="run the editorial core on the bundled sample")
    s.add_argument("--out")
    s.add_argument("--signal-only", action="store_true",
                   help="use the deterministic fallback instead of the demo editorial brain")
    s.set_defaults(func=cmd_selftest)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)
