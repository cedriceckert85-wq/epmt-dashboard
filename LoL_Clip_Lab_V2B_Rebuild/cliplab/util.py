"""Kleine Helfer: Timecodes, Slugs, sichere Dateinamen."""

from __future__ import annotations

import math
import re

_UMLAUTS = str.maketrans(
    {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
     "Ä": "ae", "Ö": "oe", "Ü": "ue"}
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: object, max_len: int = 48, fallback: str = "x") -> str:
    """Pfadsicherer Slug: nur [a-z0-9_], keine Traversal-Tricks, nie leer.

    Wird fuer Kategorien, Stilnamen und Dateinamen-Bausteine benutzt.
    """
    if not isinstance(text, str):
        text = str(text) if text is not None else ""
    text = text.translate(_UMLAUTS).lower()
    text = _SLUG_RE.sub("_", text).strip("_")
    text = re.sub(r"_+", "_", text)
    if max_len > 0:
        text = text[:max_len].rstrip("_")
    return text or fallback


def fmt_tc(seconds: float, force_hours: bool = False) -> str:
    """Timecode ``MM:SS`` unter einer Stunde, sonst ``H:MM:SS``.

    Erstes YouTube-Kapitel muss exakt ``00:00`` sein — Minuten werden
    zweistellig gepolstert.
    """
    if not isinstance(seconds, (int, float)) or not math.isfinite(seconds):
        seconds = 0.0
    total = int(max(0.0, float(seconds)))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h > 0 or force_hours:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def fmt_span(t0: float, t1: float) -> str:
    return f"{fmt_tc(t0)} → {fmt_tc(t1)}"


def fmt_dur(seconds: float) -> str:
    """Menschliche Dauer: ``38s`` oder ``4m12s``."""
    if not isinstance(seconds, (int, float)) or not math.isfinite(seconds):
        seconds = 0.0
    total = int(round(max(0.0, float(seconds))))
    if total < 60:
        return f"{total}s"
    m, s = divmod(total, 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m{s:02d}s"


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def finite(value: object, default: float = 0.0) -> float:
    """Zahl -> endlicher float (json akzeptiert Infinity/NaN — und
    Riesen-Integer-Literale wie 10**400 sind gueltiges JSON, deren
    float()-Konvertierung OverflowError wirft!)."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        try:
            v = float(value)
        except (OverflowError, ValueError):
            return default
        if math.isfinite(v):
            return v
        return default
    if isinstance(value, str):
        try:
            v = float(value.strip())
        except (ValueError, TypeError, OverflowError):
            return default
        if math.isfinite(v):
            return v
    return default
