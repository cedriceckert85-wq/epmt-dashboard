"""Timeline-Dokument: Transkript + Reaktionen + Events, chronologisch.

Jede Zeile traegt den Zeitpunkt doppelt: menschlich (H:MM:SS) und
maschinell (t=Sekunden), damit das LLM exakte Schnittzeiten liefern kann.
"""

from __future__ import annotations

from dataclasses import dataclass

from .events import GameEvent
from .reactions import Reaction
from .transcribe import TranscriptSegment
from .util import fmt_tc


@dataclass
class TimelineEntry:
    t: float
    kind: str  # "talk" | "reaction" | "event"
    line: str


def _tag(t: float) -> str:
    return f"[{fmt_tc(t, force_hours=True)} | t={int(round(t))}]"


def build_entries(
    segments: list[TranscriptSegment],
    reactions: list[Reaction],
    events: list[GameEvent],
) -> list[TimelineEntry]:
    entries: list[TimelineEntry] = []
    for seg in segments:
        entries.append(
            TimelineEntry(t=seg.t0, kind="talk", line=f"{_tag(seg.t0)} TALK: {seg.text}")
        )
    for r in reactions:
        entries.append(
            TimelineEntry(
                t=r.t,
                kind="reaction",
                line=f"{_tag(r.t)} *** REAKTION (Lautstaerke-Ausbruch, Intensitaet {r.intensity:.2f}) ***",
            )
        )
    for ev in events:
        entries.append(
            TimelineEntry(
                t=ev.t,
                kind="event",
                line=f"{_tag(ev.t)} >>> GAME-EVENT: {ev.kind} (Gewicht {ev.weight:+.1f})",
            )
        )
    entries.sort(key=lambda e: (e.t, {"talk": 1, "reaction": 2, "event": 0}[e.kind]))
    return entries


def render_doc(entries: list[TimelineEntry], duration: float, vod_name: str) -> str:
    head = [
        f"=== SESSION-TIMELINE: {vod_name} ===",
        f"=== Dauer: {fmt_tc(duration, force_hours=True)} ({int(round(duration))}s) ===",
        "",
    ]
    return "\n".join(head + [e.line for e in entries]) + "\n"


def chunk_text_lines(text: str, chunk_chars: int) -> list[str]:
    """Text in zeilen-alignierte Chunks <= chunk_chars teilen.

    Niemals vorne abschneiden — ALLE Zeilen landen in genau einem Chunk.
    Eine einzelne Ueberlaenge-Zeile wird notfalls hart geteilt.
    """
    chunk_chars = max(1000, int(chunk_chars))
    lines = text.splitlines(keepends=True)
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    for line in lines:
        while len(line) > chunk_chars:
            if buf:
                chunks.append("".join(buf))
                buf, size = [], 0
            chunks.append(line[:chunk_chars])
            line = line[chunk_chars:]
        if size + len(line) > chunk_chars and buf:
            chunks.append("".join(buf))
            buf, size = [], 0
        buf.append(line)
        size += len(line)
    if buf:
        chunks.append("".join(buf))
    return chunks or [""]
