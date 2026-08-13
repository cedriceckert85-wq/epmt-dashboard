"""Stil-Lernen aus Referenz-Clips (F7).

Ordnerstruktur ``references/<kanal>/<stil>/`` (zwei Ebenen); Ebene 1 allein
und Root-Videos funktionieren auch. Ordnername -> Stilname als sicherer
Slug (z.B. ``insta_funny``).

Klassifikation (Pflicht):
- Median-Dauer <= cut_threshold (~2 min)  -> CUT-Stil (ideal-Cliplaenge,
  Pace, Humor-Merkmale, Caption-Stil — per LLM destilliert, mechanischer
  Median-Fallback)
- laenger -> FORMAT-Profil (Ziel-LAUFZEIT des Kanals)
Ganze Videos duerfen NIE als Clip-Schnittstil enden. 0 Schnitte/min ist
eine echte Messung (lange ungeschnittene Takes).
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import Config
from .jsonextract import extract_json
from .media import VIDEO_EXTS
from .sanitize import clean_num, clean_str
from .util import finite, slugify

STYLE_MARKER = "### CLIPLAB-TASK: STIL-DESTILLAT ###"
PROFILE_VERSION = 1

Runner = Callable[[str], "str | None"]


@dataclass
class StyleProfile:
    cuts: dict[str, dict] = field(default_factory=dict)
    formats: dict[str, dict] = field(default_factory=dict)

    def cut_style_names(self) -> set[str]:
        return set(self.cuts.keys())

    def format_runtime_for_channel(self, channel: str) -> float | None:
        """Gelernte Ziel-Laufzeit eines Kanals (aus FORMAT-Profilen)."""
        best: float | None = None
        for f in self.formats.values():
            if f.get("channel") == channel:
                rt = f.get("target_runtime_s")
                if isinstance(rt, (int, float)) and rt > 0:
                    best = float(rt) if best is None else max(best, float(rt))
        return best

    def cut_style_target_len(self, style: str) -> float | None:
        st = self.cuts.get(style)
        if not st:
            return None
        v = st.get("ideal_len_s")
        if isinstance(v, (int, float)) and math.isfinite(v) and v > 0:
            return float(v)
        return None

    def is_empty(self) -> bool:
        return not self.cuts and not self.formats


def style_channel(style_name: str, channel_names: list[str]) -> str:
    """Kohaerenz-Regel: Stil ``<kanal>_<x>`` (oder ``<kanal>``) impliziert
    diesen Kanal."""
    for ch in channel_names:
        if style_name == ch or style_name.startswith(ch + "_"):
            return ch
    return ""


# ---------------------------------------------------------------------------
# Laden / Speichern (versioniert, korrupt -> leer, alles sanitisiert)


def _sanitize_cut(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    ideal = finite(raw.get("ideal_len_s"), default=float("nan"))
    if not math.isfinite(ideal) or ideal <= 0:
        return None
    cpm = raw.get("cuts_per_min")
    if cpm is not None:
        v = finite(cpm, default=float("nan"))
        cpm = round(max(0.0, v), 2) if math.isfinite(v) else None
    return {
        "ideal_len_s": round(min(ideal, 600.0), 1),
        "cuts_per_min": cpm,
        "notes": clean_str(raw.get("notes"), max_len=300),
        "caption_style": clean_str(raw.get("caption_style"), max_len=200),
        "channel": clean_str(raw.get("channel"), max_len=40),
        "sample_count": int(clean_num(raw.get("sample_count"), 0, 10000, default=0)),
    }


def _sanitize_format(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    rt = finite(raw.get("target_runtime_s"), default=float("nan"))
    if not math.isfinite(rt) or rt <= 0:
        return None
    return {
        "target_runtime_s": round(min(rt, 12 * 3600.0), 1),
        "channel": clean_str(raw.get("channel"), max_len=40),
        "sample_count": int(clean_num(raw.get("sample_count"), 0, 10000, default=0)),
        "notes": clean_str(raw.get("notes"), max_len=300),
    }


def load_profile(path: Path | str) -> StyleProfile:
    path = Path(path)
    if not path.is_file():
        return StyleProfile()
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (ValueError, RecursionError, OSError):
        return StyleProfile()
    if not isinstance(data, dict):
        return StyleProfile()
    version = data.get("version")
    if not isinstance(version, int) or version < 1 or version > PROFILE_VERSION:
        return StyleProfile()
    prof = StyleProfile()
    cuts = data.get("cuts")
    if isinstance(cuts, dict):
        for name, raw in list(cuts.items())[:100]:
            slug = slugify(name, fallback="")
            cleaned = _sanitize_cut(raw)
            if slug and cleaned:
                prof.cuts[slug] = cleaned
    formats = data.get("formats")
    if isinstance(formats, dict):
        for name, raw in list(formats.items())[:100]:
            slug = slugify(name, fallback="")
            cleaned = _sanitize_format(raw)
            if slug and cleaned:
                prof.formats[slug] = cleaned
    return prof


def save_profile(path: Path | str, profile: StyleProfile) -> None:
    path = Path(path)
    data = {
        "version": PROFILE_VERSION,
        "cuts": profile.cuts,
        "formats": profile.formats,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Referenz-Scan


def ensure_example_structure(ref_dir: Path | str, cfg: Config) -> bool:
    """Beim ersten `learn` die Beispielstruktur anlegen. True = neu angelegt."""
    ref_dir = Path(ref_dir)
    if ref_dir.is_dir():
        return False
    clip_channels = [c.name for c in cfg.channels if c.kind != "full"]
    for ch in clip_channels or ["insta", "yt"]:
        (ref_dir / ch).mkdir(parents=True, exist_ok=True)
    first = clip_channels[0] if clip_channels else "insta"
    (ref_dir / first / "funny").mkdir(parents=True, exist_ok=True)
    (ref_dir / first / "montage").mkdir(parents=True, exist_ok=True)
    readme = ref_dir / "LIES_MICH.txt"
    readme.write_text(
        "Referenz-Clips hier einsortieren:\n"
        "  references/<kanal>/<stil>/clip.mp4   (z.B. insta/funny)\n"
        "  references/<kanal>/video.mp4         (Ebene 1: Stil = Kanalname)\n"
        "Kurze Clips (Median <= ~2 min) werden als SCHNITT-STIL gelernt,\n"
        "ganze Videos als FORMAT-Profil (Ziel-Laufzeit des Kanals).\n"
        "Danach: python -m cliplab learn\n",
        encoding="utf-8",
    )
    return True


def scan_references(ref_dir: Path | str) -> dict[str, list[Path]]:
    """Videos einsammeln: {stil_slug: [dateien]}.

    Zwei Ebenen (kanal/stil), Ebene 1 (kanal) und Root-Videos ("default").
    """
    ref_dir = Path(ref_dir)
    groups: dict[str, list[Path]] = {}
    if not ref_dir.is_dir():
        return groups

    def add(style: str, f: Path) -> None:
        groups.setdefault(style, []).append(f)

    for entry in sorted(ref_dir.iterdir()):
        if entry.is_file() and entry.suffix.lower() in VIDEO_EXTS:
            add("default", entry)
        elif entry.is_dir():
            ch_slug = slugify(entry.name, fallback="kanal")
            for sub in sorted(entry.iterdir()):
                if sub.is_file() and sub.suffix.lower() in VIDEO_EXTS:
                    add(ch_slug, sub)
                elif sub.is_dir():
                    style_slug = f"{ch_slug}_{slugify(sub.name, fallback='stil')}"
                    for f in sorted(sub.iterdir()):
                        if f.is_file() and f.suffix.lower() in VIDEO_EXTS:
                            add(style_slug, f)
    return groups


# ---------------------------------------------------------------------------
# Lernen


def _distill_with_llm(
    style: str, durations: list[float], rates: list[float], texts: list[str], runner: Runner
) -> dict:
    prompt = "\n".join(
        [
            STYLE_MARKER,
            f"Stil: {style}",
            f"Clip-Dauern (s): {[round(d, 1) for d in durations]}",
            f"Schnitte/min: {[round(r, 1) for r in rates] if rates else 'unbekannt'}",
            "Transkript-Proben:",
            "\n---\n".join(t[:800] for t in texts[:5]) if texts else "(keine)",
            "",
            "Destilliere den Schnitt-Stil. Antworte NUR mit JSON:",
            '{"notes":"Humor-/Pacing-Merkmale in 1-2 Saetzen",'
            '"caption_style":"wie Captions aussehen sollen"}',
        ]
    )
    try:
        raw = runner(prompt)
    except Exception:  # noqa: BLE001
        raw = None
    data = extract_json(raw) if raw else None
    if not isinstance(data, dict):
        return {}
    return {
        "notes": clean_str(data.get("notes"), max_len=300),
        "caption_style": clean_str(data.get("caption_style"), max_len=200),
    }


def learn_styles(
    ref_dir: Path | str,
    cfg: Config,
    probe_duration: Callable[[Path], float | None],
    scene_rate: Callable[[Path, float], float | None] | None = None,
    transcribe_sample: Callable[[Path], str | None] | None = None,
    runner: Runner | None = None,
) -> tuple[StyleProfile, list[str]]:
    """Referenzordner lernen. Rueckgabe (Profil, Report-Zeilen).

    Alle IO-Funktionen sind injizierbar; ohne Whisper wird ohne Text
    weitergelernt (nie abgebrochen).
    """
    report: list[str] = []
    profile = StyleProfile()
    groups = scan_references(ref_dir)
    if not groups:
        report.append(f"Keine Referenz-Videos in {ref_dir} gefunden.")
        return profile, report
    channel_names = cfg.channel_names()
    for style, files in sorted(groups.items()):
        durations: list[float] = []
        rates: list[float] = []
        texts: list[str] = []
        for f in files:
            try:
                dur = probe_duration(f)
            except Exception:  # noqa: BLE001 — einzelne kaputte Datei ueberspringen
                dur = None
            d = finite(dur, default=float("nan"))
            if not math.isfinite(d) or d <= 0:
                report.append(f"  ! {f.name}: Dauer nicht messbar — uebersprungen")
                continue
            durations.append(d)
            if scene_rate is not None:
                try:
                    r = scene_rate(f, d)
                except Exception:  # noqa: BLE001
                    r = None
                if r is not None and math.isfinite(r) and r >= 0:
                    rates.append(float(r))
            if transcribe_sample is not None:
                try:
                    txt = transcribe_sample(f)
                except Exception:  # noqa: BLE001
                    txt = None
                if txt:
                    texts.append(clean_str(txt, max_len=2000))
        if not durations:
            report.append(f"Stil {style}: keine messbaren Clips — uebersprungen")
            continue
        med = statistics.median(durations)
        channel = style_channel(style, channel_names)
        if med <= cfg.style_cut_threshold_s:
            entry = {
                "ideal_len_s": round(med, 1),
                "cuts_per_min": round(statistics.median(rates), 2) if rates else None,
                "notes": "",
                "caption_style": "",
                "channel": channel,
                "sample_count": len(durations),
            }
            distilled: dict = {}
            if runner is not None:
                distilled = _distill_with_llm(style, durations, rates, texts, runner)
            if distilled.get("notes"):
                entry["notes"] = distilled["notes"]
            else:
                pace = (
                    f"{entry['cuts_per_min']:.1f} Schnitte/min"
                    if entry["cuts_per_min"]
                    else (
                        "lange ungeschnittene Takes"
                        if entry["cuts_per_min"] == 0.0
                        else "Schnitt-Tempo unbekannt"
                    )
                )
                entry["notes"] = f"Mechanisch gelernt: Median {med:.0f}s, {pace}."
            if distilled.get("caption_style"):
                entry["caption_style"] = distilled["caption_style"]
            profile.cuts[style] = entry
            pace_str = (
                f"{entry['cuts_per_min']:.1f} Schnitte/min"
                if entry["cuts_per_min"] is not None
                else "Pace unbekannt"
            )
            report.append(
                f"Stil {style}: CUT-Stil — ideal ~{med:.0f}s, {pace_str}, "
                f"{len(durations)} Clips. {entry['notes']}"
            )
        else:
            # Ganze Videos werden NIE zum Clip-Schnittstil.
            profile.formats[style] = {
                "target_runtime_s": round(med, 1),
                "channel": channel,
                "sample_count": len(durations),
                "notes": f"FORMAT-Profil aus {len(durations)} Videos (Median {med:.0f}s).",
            }
            report.append(
                f"Stil {style}: FORMAT-Profil — Ziel-Laufzeit ~{med / 60:.1f} min "
                f"({len(durations)} Videos). Kein Clip-Schnittstil (ganze Videos)."
            )
    return profile, report
