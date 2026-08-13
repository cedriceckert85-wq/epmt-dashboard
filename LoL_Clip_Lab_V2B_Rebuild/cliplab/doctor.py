"""``doctor``-Kommando: zeigt ehrlich, was da ist (F13).

ffmpeg ist das einzig Fatale fuer echte VODs. Alles andere degradiert
(siehe Degradations-Matrix) — doctor sagt jeweils, was dann passiert.
"""

from __future__ import annotations

import shutil
import sys
from typing import Callable

from .config import Config
from .llm import resolve_cmd


def _check(ok: bool, label: str, detail_ok: str, detail_bad: str) -> str:
    mark = "OK " if ok else "-- "
    return f"[{mark}] {label}: {detail_ok if ok else detail_bad}"


def run_doctor(
    cfg: Config,
    config_warnings: list[str] | None = None,
    which=shutil.which,
    log: Callable[[str], None] = print,
) -> int:
    lines: list[str] = ["LoL Clip Lab — Umgebungs-Check", ""]

    lines.append(
        _check(
            sys.version_info >= (3, 11),
            "Python",
            f"{sys.version.split()[0]}",
            f"{sys.version.split()[0]} — 3.11+ empfohlen",
        )
    )

    try:
        import numpy  # noqa: F401

        has_numpy = True
        numpy_detail = f"numpy {numpy.__version__}"
    except ImportError:
        has_numpy = False
        numpy_detail = ""
    lines.append(
        _check(
            has_numpy,
            "numpy",
            numpy_detail,
            "FEHLT — python -m pip install numpy (noetig fuer Reaktionserkennung)",
        )
    )

    ffmpeg = which("ffmpeg")
    ffprobe = which("ffprobe")
    lines.append(
        _check(
            ffmpeg is not None,
            "ffmpeg",
            str(ffmpeg),
            "FEHLT — das ist der EINZIGE Fatal fuer echte VODs. "
            "Installieren: winget install ffmpeg / apt install ffmpeg",
        )
    )
    lines.append(
        _check(
            ffprobe is not None,
            "ffprobe",
            str(ffprobe),
            "FEHLT (gehoert zum ffmpeg-Paket)",
        )
    )

    try:
        import faster_whisper  # noqa: F401

        fw = True
        fw_detail = (
            f"faster-whisper installiert (Modell '{cfg.whisper_model}', CPU int8; "
            "der ERSTE Lauf laedt das Modell einmalig aus dem Netz)"
        )
    except ImportError:
        fw = False
        fw_detail = ""
    lines.append(
        _check(
            fw,
            "faster-whisper",
            fw_detail,
            "FEHLT — Transkription geht dann nur via --transcript datei.json",
        )
    )

    llm = resolve_cmd(cfg.llm_cmd, which=which)
    lines.append(
        _check(
            llm is not None,
            "LLM-CLI (Primaer)",
            f"{' '.join(cfg.llm_cmd)} -> {llm[0] if llm else ''}",
            f"{' '.join(cfg.llm_cmd) or '(leer)'} nicht gefunden — Analyse laeuft "
            "dann Signal-only (brauchbares Sheet, klar gekennzeichnet)",
        )
    )

    if cfg.llm2_cmd:
        llm2 = resolve_cmd(cfg.llm2_cmd, which=which)
        lines.append(
            _check(
                llm2 is not None,
                "LLM-CLI (Zweitmeinung)",
                f"{' '.join(cfg.llm2_cmd)}",
                f"{' '.join(cfg.llm2_cmd)} nicht gefunden — wird still uebersprungen",
            )
        )
    else:
        lines.append("[-- ] LLM-CLI (Zweitmeinung): deaktiviert (llm2_cmd = []) — optionales Opt-in, siehe README")

    ytdlp = which("yt-dlp")
    lines.append(
        _check(
            ytdlp is not None,
            "yt-dlp (optional)",
            str(ytdlp),
            "fehlt — `fetch` steht dann nicht zur Verfuegung",
        )
    )

    mem_path = cfg.resolve(cfg.memory_path)
    lines.append(
        _check(
            mem_path.is_file(),
            "Gedaechtnis",
            str(mem_path),
            f"noch keins ({mem_path}) — entsteht bei der ersten LLM-Analyse",
        )
    )
    prof_path = cfg.resolve(cfg.style_profile_path)
    lines.append(
        _check(
            prof_path.is_file(),
            "Stil-Profil",
            str(prof_path),
            f"noch keins ({prof_path}) — mit `learn` aus Referenz-Clips lernen",
        )
    )

    for w in config_warnings or []:
        lines.append(f"[!! ] {w}")

    lines.append("")
    if ffmpeg is None:
        lines.append("FAZIT: ffmpeg fehlt — bitte installieren, alles andere ist optional.")
    else:
        lines.append("FAZIT: startklar. `python -m cliplab selftest` fuehrt alles einmal vor.")
    for line in lines:
        log(line)
    return 1 if ffmpeg is None else 0
