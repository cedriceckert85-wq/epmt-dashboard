"""Sanitisierung ALLER Felder, die aus LLM-Antworten stammen.

LLM-Text landet in CSV-Zeilen, Dateinamen und YouTube-Kapiteln — deshalb:
- Strings begrenzen, Newlines/Steuerzeichen kollabieren
- Zahlen endlich klemmen (json.loads akzeptiert Infinity/NaN!)
- null statt Liste tolerieren
- Tags nur aus bekannten Mengen
- Kategorien als pfadsichere Slugs
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable

from .util import clamp, finite, slugify

_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]+")
_WS_RE = re.compile(r"\s+")

# Bekannte Kategorien mit Emoji fuer das Edit-Sheet.
CATEGORY_EMOJI = {
    "funny": "😂",
    "fail": "🤦",
    "clutch": "😱",
    "hype": "🔥",
    "rage": "😡",
    "tilt": "🌀",
    "wholesome": "🥰",
    "skill": "🎯",
    "wtf": "🤨",
    "talk": "🎙️",
    "moment": "🎬",
}
DEFAULT_CATEGORY = "moment"
DEFAULT_EMOJI = "🎬"

# Bekannte SFX-Arten (Tag-Menge). Unbekanntes wird verworfen.
KNOWN_SFX = {
    "boom",
    "vine_boom",
    "airhorn",
    "ding",
    "whoosh",
    "record_scratch",
    "sad_trombone",
    "crickets",
    "applause",
    "bruh",
    "drumroll",
}


def clean_str(value: Any, max_len: int = 200, default: str = "") -> str:
    """String begrenzen; Newlines und Steuerzeichen zu Leerzeichen kollabieren."""
    if value is None:
        return default
    if not isinstance(value, str):
        if isinstance(value, (int, float)):
            # bool ist int-Subklasse; float(10**400) wirft OverflowError —
            # ein 400-stelliges Integer-Literal ist aber gueltiges JSON!
            try:
                if isinstance(value, bool) or not math.isfinite(float(value)):
                    return default
            except (OverflowError, ValueError):
                return default
            value = str(value)
        else:
            return default
    value = _CTRL_RE.sub(" ", value)
    value = _WS_RE.sub(" ", value).strip()
    if max_len > 0 and len(value) > max_len:
        value = value[: max_len - 1].rstrip() + "…"
    return value or default


def clean_num(
    value: Any, lo: float, hi: float, default: float = 0.0
) -> float:
    """Zahl -> endlicher float, in [lo, hi] geklemmt."""
    v = finite(value, default=default)
    if not math.isfinite(v):
        v = default
    return clamp(v, lo, hi)


def clean_list(value: Any) -> list:
    """null / Nicht-Liste -> leere Liste (LLMs liefern gern ``null``)."""
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def clean_category(value: Any) -> str:
    """Kategorie als pfadsicherer Slug; unbekannt ist ok, aber sicher."""
    slug = slugify(value if isinstance(value, str) else "", max_len=24,
                   fallback=DEFAULT_CATEGORY)
    return slug


def category_emoji(category: str) -> str:
    return CATEGORY_EMOJI.get(category, DEFAULT_EMOJI)


def clean_tag(value: Any, allowed: Iterable[str]) -> str:
    """Tag nur aus bekannter Menge; sonst leer."""
    allowed_set = set(allowed)
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    if candidate in allowed_set:
        return candidate
    slug = slugify(candidate, max_len=48, fallback="")
    if slug in allowed_set:
        return slug
    return ""


def clean_tags(value: Any, allowed: Iterable[str]) -> list[str]:
    """Liste von Tags gegen bekannte Menge filtern, Reihenfolge stabil."""
    allowed_set = set(allowed)
    out: list[str] = []
    for item in clean_list(value):
        tag = clean_tag(item, allowed_set)
        if tag and tag not in out:
            out.append(tag)
    return out


def clean_time(value: Any, duration: float, default: float = -1.0) -> float:
    """Zeitpunkt in [0, duration]; nicht parsebar -> default (-1 = fehlt)."""
    v = finite(value, default=float("nan"))
    if not math.isfinite(v):
        return default
    if duration > 0:
        return clamp(v, 0.0, duration)
    return max(0.0, v)


def clean_captions(value: Any, duration: float, max_items: int = 12) -> list[dict]:
    out = []
    for item in clean_list(value)[: max_items * 3]:
        if not isinstance(item, dict):
            continue
        t = clean_time(item.get("t"), duration)
        text = clean_str(item.get("text"), max_len=120)
        if t < 0 or not text:
            continue
        out.append({"t": round(t, 2), "text": text})
        if len(out) >= max_items:
            break
    out.sort(key=lambda c: c["t"])
    return out


def clean_zooms(value: Any, duration: float, max_items: int = 8) -> list[dict]:
    out = []
    for item in clean_list(value)[: max_items * 3]:
        if not isinstance(item, dict):
            continue
        t = clean_time(item.get("t"), duration)
        if t < 0:
            continue
        d = clean_num(item.get("duration"), 0.2, 10.0, default=1.5)
        out.append({"t": round(t, 2), "duration": round(d, 2)})
        if len(out) >= max_items:
            break
    out.sort(key=lambda z: z["t"])
    return out


def clean_sfx(value: Any, duration: float, max_items: int = 8) -> list[dict]:
    out = []
    for item in clean_list(value)[: max_items * 3]:
        if not isinstance(item, dict):
            continue
        t = clean_time(item.get("t"), duration)
        kind = clean_tag(item.get("kind"), KNOWN_SFX)
        if t < 0 or not kind:
            continue
        out.append({"t": round(t, 2), "kind": kind})
        if len(out) >= max_items:
            break
    out.sort(key=lambda s: s["t"])
    return out


def clean_str_list(value: Any, max_items: int = 10, max_len: int = 120) -> list[str]:
    out: list[str] = []
    for item in clean_list(value)[: max_items * 3]:
        s = clean_str(item, max_len=max_len)
        if s and s not in out:
            out.append(s)
        if len(out) >= max_items:
            break
    return out
