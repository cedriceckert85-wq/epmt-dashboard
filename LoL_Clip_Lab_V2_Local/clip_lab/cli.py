"""Command line: analyze / batch / cut / learn / memory / doctor / selftest."""
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


def _anchor_to_root(value):
    p = Path(value)
    if p.is_absolute():
        return p
    if p.drive:
        # Windows drive-relative oddity like "C:mem.json": joining it onto ROOT
        # would silently DISCARD ROOT (drive-reset join semantics) and the file
        # would move around with the current directory — anchor to ROOT instead
        p = Path(p.name)
    return ROOT / p


def _memory_path(cfg):
    return _anchor_to_root(cfg.memory_file)


def _style_path(cfg):
    return _anchor_to_root(cfg.style_file)


def cmd_analyze(args):
    cfg = _cfg(args)
    out = Path(args.out or (Path(args.vod).stem + "_clips"))
    if not args.transcript and not Path(args.vod).exists():
        print(f"VOD not found: {args.vod}", file=sys.stderr)
        return 2
    mem_path = None if args.no_memory else _memory_path(cfg)
    sty_path = None if getattr(args, "no_style", False) else _style_path(cfg)
    plan, meta = analyze(args.vod, cfg, out, transcript_path=args.transcript,
                         events_path=args.events, audio_stream=args.audio_stream,
                         memory_path=mem_path, style_path=sty_path)
    print(f"\nEdit sheet: {out/'edit_sheet.md'}")
    print(f"Machine plan: {out/'edit_plan.json'}   ·   CSV: {out/'clips.csv'}")
    print(f"Editorial brain used: {meta['editorial']}  ·  {len(plan)} clips suggested")
    if meta.get("style"):
        print(f"Style guide: learned from {meta['style']['learned_from']} reference clips")
    if meta.get("memory"):
        print(f"Channel memory: {meta['memory']['gags']} running gags across "
              f"{meta['memory']['sessions_analyzed']} sessions ({mem_path})")
    if args.cut:
        _cut_all(args.vod, plan, cfg, out)
    return 0


def cmd_batch(args):
    """Analyze every video in a folder, one after the other. The channel
    memory grows across all of them — exactly how the brain is meant to be
    fed. Failures on single files don't stop the rest."""
    from .style import list_videos
    cfg = _cfg(args)
    folder = Path(args.folder)
    vids = list_videos(folder)
    if not vids:
        print(f"No videos found in {folder} (looked for "
              "mp4/mkv/webm/mov/avi/ts/m4v).", file=sys.stderr)
        return 2
    mem_path = None if args.no_memory else _memory_path(cfg)
    sty_path = None if args.no_style else _style_path(cfg)
    print(f"Batch: {len(vids)} videos in {folder}\n")
    ok, failed = 0, []
    for i, v in enumerate(vids, 1):
        out = v.parent / (v.stem + "_clips")
        print(f"=== [{i}/{len(vids)}] {v.name} ===")
        try:
            plan, meta = analyze(str(v), cfg, out, memory_path=mem_path,
                                 style_path=sty_path)
            print(f"  -> {len(plan)} clips, {out/'edit_sheet.md'}\n")
            ok += 1
        except Exception as e:
            print(f"  FAIL {v.name}: {e}\n", file=sys.stderr)
            failed.append(v.name)
    print(f"Batch done: {ok}/{len(vids)} analyzed"
          + (f", failed: {', '.join(failed)}" if failed else ""))
    return 0 if ok else 1


def cmd_learn(args):
    """Learn the target style from the reference-videos folder."""
    from .llm_client import LLMClient
    from .style import learn_styles, save_profile, style_brief
    cfg = _cfg(args)
    folder = Path(args.folder) if args.folder else _anchor_to_root(cfg.references_dir)
    if folder.exists() and not folder.is_dir():
        print(f"{folder} is a file, not a folder — pass the folder that "
              "contains your example clips.", file=sys.stderr)
        return 2
    if not folder.is_dir():
        folder.mkdir(parents=True, exist_ok=True)
        print(f"Created {folder}.\nDrop example clips you LIKE in there "
              "(your best uploads or other creators' edits), then run "
              "`learn` again.")
        return 2
    llm = LLMClient(cfg.llm_cmd, cfg.llm_timeout_s)
    profile, fps = learn_styles(folder, cfg, llm, log=print)
    if profile is None:
        print(f"No videos found in {folder} (looked for "
              "mp4/mkv/webm/mov/avi/ts/m4v).", file=sys.stderr)
        return 2
    path = _style_path(cfg)
    save_profile(path, profile)
    print(f"\nStyle profile saved: {path}")
    print(style_brief(profile))
    print("\nEvery `analyze` from now on aims at this style. "
          "Re-run `learn` after changing the reference clips; "
          "delete the file to forget the style.")
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


def cmd_fetch(args):
    """Download videos by URL (e.g. YouTube) into the references folder,
    via yt-dlp. Only download material you have the rights/permission to use."""
    import subprocess
    from .util import which
    cfg = _cfg(args)
    if which("yt-dlp") is None:
        print("yt-dlp is not installed. Install it first:\n"
              "  pip install yt-dlp        (any OS)\n"
              "  winget install yt-dlp     (Windows)", file=sys.stderr)
        return 2
    dest = Path(args.to) if args.to else _anchor_to_root(cfg.references_dir)
    if dest.exists() and not dest.is_dir():
        print(f"{dest} is a file, not a folder.", file=sys.stderr)
        return 2
    dest.mkdir(parents=True, exist_ok=True)
    ok = 0
    for url in args.urls:
        print(f"fetching {url} …")
        p = subprocess.run(["yt-dlp", "-o", str(dest / "%(title)s.%(ext)s"), url])
        if p.returncode == 0:
            ok += 1
        else:
            print(f"  FAIL: {url}", file=sys.stderr)
    print(f"\n{ok}/{len(args.urls)} downloaded to {dest}")
    if ok and not args.to:
        print("Run `learn` next so the style profile picks them up.")
    print("Note: only download videos you have the rights/permission to use.")
    return 0 if ok else 1


def cmd_memory(args):
    """Show (default) or clear the channel brain."""
    from .memory import load_memory, memory_brief
    cfg = _cfg(args)
    path = _memory_path(cfg)
    if args.clear:
        if path.exists():
            path.unlink()
            print(f"Channel memory cleared ({path}).")
        else:
            print("Channel memory is already empty.")
        return 0
    mem = load_memory(path)
    brief = memory_brief(mem, max_chars=8000)
    if not brief:
        print(f"Channel memory is empty ({path}).\n"
              "It fills up automatically with every `analyze` run.")
        return 0
    print(f"== Channel memory ({path}) ==")
    print(f"Sessions analyzed: {mem['sessions_analyzed']}\n")
    print(brief)
    return 0


def cmd_selftest(args):
    """Run the whole editorial→rank→edl→edit-sheet path on the bundled sample
    transcript+events — no VOD, no whisper, no ffmpeg, no network needed.

    By default it uses a CANNED editorial brain (clip_lab._demo) so the edit
    sheet shows the full creative output: funny titles, punchline-aware cuts,
    captions, SFX and callbacks — and runs the ANALYSIS TWICE against a scratch
    channel memory, proving the brain remembers running gags across sessions.
    Pass --signal-only to see the deterministic no-LLM fallback."""
    cfg = _cfg(args)
    out = Path(args.out or "selftest_out")
    sample_t = ROOT / "samples" / "fixture_transcript.json"
    sample_e = ROOT / "samples" / "fixture_events.json"
    sample_vod = str(ROOT / "samples" / "sample_vod.mkv")
    if args.signal_only:
        cfg.use_llm = False
        plan, meta = analyze(sample_vod, cfg, out,
                             transcript_path=sample_t, events_path=sample_e, llm=None)
    else:
        from ._demo import demo_llm
        cfg.use_llm = True
        # scratch brain with its OWN name, so even `--out .` inside the tool
        # dir can never collide with (and delete) the real channel_memory.json
        mem_path = out / "selftest_memory.json"
        if mem_path.resolve() == _memory_path(cfg).resolve():
            mem_path = out / "selftest_memory_scratch.json"
        if mem_path.exists():
            mem_path.unlink()
        # session 1: brain is empty, gags get learned
        plan, meta = analyze(sample_vod, cfg, out, transcript_path=sample_t,
                             events_path=sample_e, llm=demo_llm(),
                             memory_path=mem_path)
        # session 2: the brain now knows the gags -> lore refs in the sheet
        plan, meta = analyze(sample_vod, cfg, out, transcript_path=sample_t,
                             events_path=sample_e, llm=demo_llm(),
                             memory_path=mem_path)
    print(f"\nSelf-test OK — editorial brain: {meta['editorial']} — "
          f"{len(plan)} clips → {out/'edit_sheet.md'}")
    if meta.get("memory"):
        print(f"Channel memory demo: {meta['memory']['gags']} running gags remembered "
              f"across {meta['memory']['sessions_analyzed']} sessions "
              f"(see the 🧠 lines in the edit sheet)")
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
    a.add_argument("--no-memory", action="store_true",
                   help="skip the channel memory (don't read or update the brain)")
    a.add_argument("--no-style", action="store_true",
                   help="ignore the learned style profile for this run")
    a.add_argument("--cut", action="store_true", help="also cut the clips with ffmpeg")
    a.add_argument("--encoder", help="auto|amf|x264")
    a.set_defaults(func=cmd_analyze)

    b = sub.add_parser("batch", help="analyze every video in a folder (brain grows across all)")
    b.add_argument("folder")
    b.add_argument("--no-llm", action="store_true")
    b.add_argument("--no-memory", action="store_true")
    b.add_argument("--no-style", action="store_true")
    b.add_argument("--whisper-model")
    b.set_defaults(func=cmd_batch)

    l = sub.add_parser("learn", help="learn your target style from the references folder")
    l.add_argument("folder", nargs="?",
                   help="folder with example clips (default: references/ next to the tool)")
    l.set_defaults(func=cmd_learn)

    fe = sub.add_parser("fetch", help="download videos by URL into references/ (needs yt-dlp)")
    fe.add_argument("urls", nargs="+")
    fe.add_argument("--to", help="target folder (default: references/)")
    fe.set_defaults(func=cmd_fetch)

    c = sub.add_parser("cut", help="cut clips from an existing edit_plan.json")
    c.add_argument("vod")
    c.add_argument("plan")
    c.add_argument("--out", help="output folder (default: cuts)")
    c.add_argument("--encoder")
    c.set_defaults(func=cmd_cut)

    d = sub.add_parser("doctor", help="check local tooling")
    d.set_defaults(func=cmd_doctor)

    m = sub.add_parser("memory", help="show or clear the channel brain (running gags etc.)")
    m.add_argument("--clear", action="store_true", help="forget everything")
    m.set_defaults(func=cmd_memory)

    s = sub.add_parser("selftest", help="run the editorial core on the bundled sample")
    s.add_argument("--out")
    s.add_argument("--signal-only", action="store_true",
                   help="use the deterministic fallback instead of the demo editorial brain")
    s.set_defaults(func=cmd_selftest)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)
