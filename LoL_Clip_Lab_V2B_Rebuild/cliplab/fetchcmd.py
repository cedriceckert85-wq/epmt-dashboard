"""``fetch``-Kommando: Referenz-Clips per yt-dlp holen (F13).

Sicherheit: ``--``-Trenner gegen Options-Injection, %-Escaping im
Output-Template, Slugs gegen Pfad-Traversal, Rechte-Hinweis.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable

from .config import Config
from .errors import ClipLabError
from .media import default_run
from .util import slugify

RIGHTS_HINT = (
    "Hinweis: Nur Clips herunterladen, deren Nutzung euch erlaubt ist "
    "(eigene Videos / Erlaubnis des Urhebers)."
)


def style_target_dir(references_dir: Path, style: str | None) -> Path:
    """Zielordner aus '--style kanal/stil' — Slugs verhindern Traversal."""
    if not style:
        return references_dir
    parts = [p for p in str(style).replace("\\", "/").split("/") if p.strip()]
    if not parts or len(parts) > 2:
        raise ClipLabError(
            f"Ungueltige Stil-Angabe: {style!r}",
            hint="Erwartet: --style kanal oder --style kanal/stil (z.B. insta/funny).",
        )
    safe = [slugify(p, fallback="") for p in parts]
    if not all(safe):
        raise ClipLabError(
            f"Stil-Angabe {style!r} ergibt keinen brauchbaren Ordnernamen.",
            hint="Nur Buchstaben/Zahlen verwenden, z.B. insta/funny.",
        )
    target = references_dir
    for s in safe:
        target = target / s
    return target


def fetch(
    urls: list[str],
    style: str | None,
    cfg: Config,
    run_fn=default_run,
    which=shutil.which,
    log: Callable[[str], None] = print,
) -> int:
    if not urls:
        raise ClipLabError("Keine URL angegeben.", hint="fetch URL [URL ...]")
    exe = which("yt-dlp")
    if exe is None:
        raise ClipLabError(
            "yt-dlp wurde nicht gefunden.",
            hint="python -m pip install yt-dlp — dann erneut versuchen.",
        )
    target = style_target_dir(cfg.resolve(cfg.references_dir), style)
    target.mkdir(parents=True, exist_ok=True)
    log(RIGHTS_HINT)
    log(f"Ziel: {target}")
    # %-Zeichen im Pfad escapen — yt-dlp interpretiert % im Output-Template
    outtmpl = str(target).replace("%", "%%") + "/%(title).120B.%(ext)s"
    argv = [exe, "--no-playlist", "-o", outtmpl, "--", *[str(u) for u in urls]]
    try:
        proc = run_fn(argv, timeout=3600)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ClipLabError(f"yt-dlp liess sich nicht ausfuehren ({exc}).")
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()
        detail = tail[-1] if tail else "unbekannter Fehler"
        raise ClipLabError(
            f"yt-dlp meldete einen Fehler: {detail}",
            hint="URL pruefen; manche Plattformen blocken Downloads.",
        )
    log("Download fertig. Danach: python -m cliplab learn")
    return 0
