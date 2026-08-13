"""Game-Events aus Nutzer-Dateien (JSON oder CSV). Optional.

JSON: ``{"events":[{"t":..,"kind":..,"weight":..}]}`` oder direkt eine Liste.
CSV:  ``t,kind[,weight]`` — Header optional.
Kaputte Zeilen werden uebersprungen; 0 geparste Events aus einer
vorhandenen Datei -> Warnung. Gewicht uebersteuert die Defaults.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path

from .errors import MissingInputError
from .sanitize import clean_str
from .util import finite, slugify

# Sinnvolle Default-Gewichte: penta hoch ... death negativ.
DEFAULT_WEIGHTS: dict[str, float] = {
    "penta": 5.0,
    "pentakill": 5.0,
    "quadra": 4.0,
    "steal": 4.0,
    "baron": 3.0,
    "elder": 3.0,
    "ace": 3.0,
    "triple": 3.0,
    "win": 3.0,
    "first_blood": 2.5,
    "dragon": 2.0,
    "herald": 2.0,
    "double": 2.0,
    "clutch": 2.5,
    "outplay": 2.5,
    "tower": 1.5,
    "objective": 1.5,
    "kill": 1.0,
    "throw": -0.5,
    "lose": -1.0,
    "death": -1.5,
}
DEFAULT_WEIGHT = 1.0


@dataclass
class GameEvent:
    t: float
    kind: str
    weight: float

    def to_dict(self) -> dict:
        return {"t": round(self.t, 2), "kind": self.kind, "weight": round(self.weight, 2)}


def default_weight(kind: str) -> float:
    return DEFAULT_WEIGHTS.get(kind, DEFAULT_WEIGHT)


def _make_event(t_raw, kind_raw, weight_raw=None) -> GameEvent | None:
    t = finite(t_raw, default=float("nan"))
    if not math.isfinite(t) or t < 0:
        return None
    kind = slugify(clean_str(kind_raw, max_len=40), max_len=40, fallback="")
    if not kind:
        return None
    if weight_raw is None or (isinstance(weight_raw, str) and not weight_raw.strip()):
        weight = default_weight(kind)
    else:
        w = finite(weight_raw, default=float("nan"))
        weight = w if math.isfinite(w) else default_weight(kind)
    weight = max(-10.0, min(10.0, weight))
    return GameEvent(t=float(t), kind=kind, weight=weight)


def _parse_json_events(text: str, warnings: list[str]) -> list[GameEvent] | None:
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return None
    if isinstance(data, dict):
        raw = data.get("events")
    else:
        raw = data
    if not isinstance(raw, list):
        warnings.append("events: JSON ohne 'events'-Liste — keine Events geladen")
        return []
    out: list[GameEvent] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        ev = _make_event(entry.get("t"), entry.get("kind"), entry.get("weight"))
        if ev is not None:
            out.append(ev)
    return out


def _parse_csv_events(text: str, warnings: list[str]) -> list[GameEvent]:
    out: list[GameEvent] = []
    reader = csv.reader(text.splitlines())
    for row in reader:
        if not row:
            continue
        cells = [c.strip() for c in row]
        if not cells or not cells[0]:
            continue
        t = finite(cells[0], default=float("nan"))
        if not math.isfinite(t):
            # Header-Zeile oder kaputte Zeile -> ueberspringen
            continue
        kind = cells[1] if len(cells) > 1 else ""
        weight = cells[2] if len(cells) > 2 else None
        ev = _make_event(t, kind, weight)
        if ev is not None:
            out.append(ev)
    return out


def load_events(path: Path | str) -> tuple[list[GameEvent], list[str]]:
    """Events-Datei laden. Rueckgabe (events, warnungen).

    Fehlende Datei -> MissingInputError (der Nutzer hat sie explizit
    angegeben). Kaputte Inhalte degradieren mit Warnung.
    """
    path = Path(path)
    warnings: list[str] = []
    if not path.is_file():
        raise MissingInputError(
            f"Events-Datei nicht gefunden: {path}",
            hint="Pfad pruefen — oder das Flag --events weglassen (Events sind optional).",
        )
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        warnings.append(f"events: {path.name} nicht lesbar ({exc}) — laufe ohne Events")
        return [], warnings

    events: list[GameEvent] | None = None
    suffix = path.suffix.lower()
    if suffix == ".json":
        events = _parse_json_events(text, warnings)
        if events is None:
            warnings.append(f"events: {path.name} ist kein gueltiges JSON — laufe ohne Events")
            events = []
    elif suffix == ".csv":
        events = _parse_csv_events(text, warnings)
    else:
        events = _parse_json_events(text, warnings)
        if events is None:
            events = _parse_csv_events(text, warnings)

    events.sort(key=lambda e: (e.t, e.kind))
    if not events:
        warnings.append(
            f"events: 0 Events aus {path.name} geparst — Format pruefen "
            "(JSON: {\"events\":[{\"t\":..,\"kind\":..}]} oder CSV: t,kind[,weight])"
        )
    return events, warnings
