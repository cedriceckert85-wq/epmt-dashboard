"""Optional game-event loading. A downloaded VOD has no live Riot API, so
events are OPTIONAL and come from a file the user supplies (or none at all).

Accepted:
  - JSON: [{"t": 123.4, "kind": "double_kill", "weight": 2, "detail": {...}}, ...]
  - CSV : t,kind[,weight]   (header optional)
Timestamps are seconds from the start of the VOD.
"""
import csv

from .models import GameEvent
from .util import read_json


def load_events(path):
    if path is None:
        return []
    p = str(path)
    if p.lower().endswith(".json"):
        return _from_json(read_json(p))
    return _from_csv(p)


def _from_json(data):
    rows = data.get("events", data) if isinstance(data, dict) else data
    out = []
    for r in rows or []:
        try:
            out.append(GameEvent(t=float(r["t"]), kind=str(r.get("kind", "event")),
                                 weight=float(r.get("weight", 0) or 0),
                                 detail=r.get("detail", {}) or {}))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(out, key=lambda e: e.t)


def _from_csv(path):
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row or row[0].strip().lower() in ("t", "time", "timestamp"):
                continue
            try:
                t = float(row[0])
            except ValueError:
                continue
            kind = row[1].strip() if len(row) > 1 else "event"
            weight = 0.0
            if len(row) > 2:
                try:
                    weight = float(row[2])
                except ValueError:
                    weight = 0.0
            out.append(GameEvent(t=t, kind=kind, weight=weight))
    return sorted(out, key=lambda e: e.t)
