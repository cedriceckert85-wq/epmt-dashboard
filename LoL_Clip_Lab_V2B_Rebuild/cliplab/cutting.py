"""``cut``-Kommando: Clips laut edit_plan.json wirklich schneiden (F13).

- validiert Plan-Datei und -Form
- erkennt ffmpegs Stumm-Fehlschlag (Range ausserhalb -> Fehler statt leerer
  Datei; abgeschnittene Ranges -> ehrliche Notiz)
- Kanal-Namen im Dateinamen; vertical-Kanaele bekommen den 9:16-Crop
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Callable

from .config import Config
from .errors import ClipLabError, MissingInputError
from .media import cut_clip, default_run, ffprobe_duration, make_clip_filename, pick_encoder_args
from .util import finite


def load_plan(path: Path | str) -> dict:
    """edit_plan.json laden und die Form validieren."""
    path = Path(path)
    if not path.is_file():
        raise MissingInputError(
            f"Plan-Datei nicht gefunden: {path}",
            hint="Zuerst `analyze` laufen lassen — das erzeugt edit_plan.json.",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (ValueError, RecursionError, OSError) as exc:
        raise ClipLabError(f"Plan-Datei {path.name} ist kein gueltiges JSON ({exc}).")
    if not isinstance(data, dict) or not isinstance(data.get("clips"), list):
        raise ClipLabError(
            f"Plan-Datei {path.name} hat nicht die erwartete Form.",
            hint='Erwartet: {"clips":[{"t0":..,"t1":..,"title":..}, ...]} aus `analyze`.',
        )
    return data


def _plan_clip_ok(c) -> bool:
    if not isinstance(c, dict):
        return False
    t0 = finite(c.get("t0"), default=float("nan"))
    t1 = finite(c.get("t1"), default=float("nan"))
    return math.isfinite(t0) and math.isfinite(t1) and 0 <= t0 < t1


def cut_from_plan(
    vod: Path | str,
    plan_path: Path | str,
    cfg: Config,
    out_dir: Path | str | None = None,
    encoder_choice: str | None = None,
    run_fn=default_run,
    which=shutil.which,
    log: Callable[[str], None] = print,
) -> tuple[int, list[str]]:
    """Alle Clips aus dem Plan schneiden. Rueckgabe (anzahl_ok, notizen)."""
    vod = Path(vod)
    if not vod.is_file():
        raise MissingInputError(f"VOD nicht gefunden: {vod}")
    plan = load_plan(plan_path)
    raw_clips = plan["clips"]
    valid = [c for c in raw_clips if _plan_clip_ok(c)]
    if not valid:
        raise ClipLabError(
            "Der Plan enthaelt keine gueltigen Clips (t0/t1 fehlen oder kaputt).",
            hint="edit_plan.json neu erzeugen (`analyze`).",
        )
    skipped = len(raw_clips) - len(valid)
    notes: list[str] = []
    if skipped:
        notes.append(f"{skipped} kaputte Clip-Eintraege im Plan uebersprungen.")

    out_dir = Path(out_dir) if out_dir else vod.parent / (vod.stem + cfg.out_suffix) / "clips"
    out_dir.mkdir(parents=True, exist_ok=True)

    duration = ffprobe_duration(vod, run_fn=run_fn, which=which)
    enc_name, enc_args = pick_encoder_args(encoder_choice or cfg.encoder, run_fn, which)
    log(f"Encoder: {enc_name} (AMD-sicher: AMF oder CPU x264)")

    # Kanal-Metadaten: aus dem Plan, sonst aus der Config
    chan_meta: dict[str, dict] = {}
    for ch in plan.get("channels", []) or []:
        if isinstance(ch, dict) and isinstance(ch.get("name"), str):
            chan_meta[ch["name"]] = ch
    for spec in cfg.channels:
        chan_meta.setdefault(
            spec.name, {"name": spec.name, "kind": spec.kind, "vertical": spec.vertical}
        )

    ok = 0
    for c in valid:
        rank = int(finite(c.get("rank"), default=0)) or (ok + 1)
        title = str(c.get("title") or "clip")
        category = str(c.get("category") or "moment")
        channels = [
            ch for ch in (c.get("channels") or [])
            if isinstance(ch, str) and chan_meta.get(ch, {}).get("kind") != "full"
        ]
        targets: list[tuple[str, bool]] = [
            (ch, bool(chan_meta.get(ch, {}).get("vertical"))) for ch in channels
        ] or [("", False)]
        for channel, vertical in targets:
            fname = make_clip_filename(rank, category, title, channel)
            try:
                clip_notes = cut_clip(
                    vod,
                    out_dir / fname,
                    float(c["t0"]),
                    float(c["t1"]),
                    duration,
                    encoder_args=enc_args,
                    vertical=vertical,
                    run_fn=run_fn,
                    which=which,
                )
            except ClipLabError as exc:
                notes.append(f"#{rank} {fname}: {exc.message}")
                continue
            ok += 1
            for n in clip_notes:
                notes.append(f"#{rank} {fname}: {n}")
            log(f"  geschnitten: {fname}" + (" (9:16)" if vertical else ""))
    return ok, notes
