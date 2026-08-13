"""Preflight: what is available locally, tuned for the AMD test box. Nothing
here is fatal for `analyze` except ffmpeg (needed to read the VOD's audio) —
the tool degrades: no whisper -> supply a transcript; no LLM -> signal-only."""
import platform

from . import transcribe
from .llm_client import LLMClient
from .render import _amf_available
from .util import which


def run_doctor(cfg):
    rows = []
    ok = True

    def add(name, present, detail, fatal=False):
        nonlocal ok
        rows.append((name, present, detail, fatal))
        if fatal and not present:
            ok = False

    add("python", True, platform.python_version())
    add("ffmpeg", which("ffmpeg") is not None,
        "reads the VOD audio + cuts clips", fatal=True)
    add("ffprobe", which("ffprobe") is not None, "reads VOD duration")
    add("faster-whisper", transcribe.available(),
        "transcription — model downloads on first analyze (needs internet once)")

    llm = LLMClient(cfg.llm_cmd, cfg.llm_timeout_s)
    add("LLM CLI (" + cfg.llm_cmd[0] + ")", llm.available(),
        "editorial brain: humor/callbacks/punchlines (else signal-only)")

    if cfg.llm_cmd_b:
        llm_b = LLMClient(cfg.llm_cmd_b, cfg.llm_timeout_s)
        add("2nd LLM (" + cfg.llm_cmd_b[0] + ")", llm_b.available(),
            "second opinion: reviews every clip too (optional)")

    add("yt-dlp", which("yt-dlp") is not None,
        "`fetch` downloads reference videos by URL (optional)")

    add("AMD AMF encoder", _amf_available(),
        "hardware clip encoding on the Radeon (else CPU x264 is used)")

    return ok, rows


def format_doctor(ok, rows):
    lines = ["== LoL Clip Lab — Local Doctor =="]
    for name, present, detail, fatal in rows:
        mark = "[ok]  " if present else ("[FAIL]" if fatal else "[warn]")
        lines.append(f"  {mark} {name:22s} {detail}")
    lines.append("")
    if ok:
        lines.append("Ready. `analyze <your_vod.mp4>` to get an edit sheet.")
    else:
        lines.append("ffmpeg is required (reads the VOD). Install it, then retry. See README.")
    lines.append("Note: AMD box — Whisper runs on CPU, encoding uses AMF/CPU (no CUDA/NVENC needed).")
    return "\n".join(lines)
