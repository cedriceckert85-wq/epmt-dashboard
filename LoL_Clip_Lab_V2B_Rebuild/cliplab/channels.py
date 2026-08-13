"""Kanal-Routing, Kanal-Plaene und YouTube-Kapitel (F8).

- Clip-Kanaele: CHRONOLOGISCH mit Timecodes (Story-Reihenfolge), Rang pro
  Zeile, Laengenwarnung ueber max_s, gelernte Format-Laufzeit.
- kind="full" zeigt auf chapters.txt statt einer Clip-Liste.
- chapters.txt: erstes Kapitel EXAKT 00:00 (frueher erster Clip wird selbst
  der Opener), aufsteigend, >=10s Abstand (naehere falten ins vorherige).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import ChannelSpec, Config
from .styles import StyleProfile
from .util import fmt_dur, fmt_tc

CHAPTER_MIN_GAP_S = 10.0
OPENER_TITLE = "Start"


@dataclass
class PlanEntry:
    t0: float
    t1: float
    rank: int
    title: str
    style: str
    warning: str = ""


@dataclass
class ChannelPlan:
    spec: ChannelSpec
    entries: list[PlanEntry] = field(default_factory=list)
    format_runtime_s: float | None = None

    @property
    def is_full(self) -> bool:
        return self.spec.kind == "full"


def build_channel_plans(clips, cfg: Config, profile: StyleProfile | None) -> list[ChannelPlan]:
    """Pro Kanal einen Plan bauen. ``clips`` = geplante Clips (planning.Clip)."""
    plans: list[ChannelPlan] = []
    for spec in cfg.channels:
        plan = ChannelPlan(spec=spec)
        if profile is not None:
            plan.format_runtime_s = profile.format_runtime_for_channel(spec.name)
        if spec.kind != "full":
            selected = [c for c in clips if spec.name in c.channels]
            selected.sort(key=lambda c: (c.t0, c.rank))  # CHRONOLOGISCH!
            for c in selected:
                warning = ""
                if spec.max_s and (c.t1 - c.t0) > spec.max_s:
                    warning = (
                        f"LAENGE: {fmt_dur(c.t1 - c.t0)} > max. {int(spec.max_s)}s "
                        f"fuer {spec.name} — kuerzen!"
                    )
                plan.entries.append(
                    PlanEntry(
                        t0=c.t0,
                        t1=c.t1,
                        rank=c.rank,
                        title=c.title,
                        style=c.style,
                        warning=warning,
                    )
                )
        plans.append(plan)
    return plans


def build_chapters(clips, duration: float) -> list[tuple[float, str]]:
    """YouTube-taugliche Kapitelmarker aus den Clips (chronologisch).

    - erstes Kapitel EXAKT bei 0 (ein frueher erster Clip WIRD der Opener)
    - streng aufsteigend, >=10s Abstand — naehere falten ins vorherige
    """
    chrono = sorted(clips, key=lambda c: (c.t0, c.rank))
    chapters: list[tuple[float, str]] = []
    if chrono and chrono[0].t0 < CHAPTER_MIN_GAP_S:
        chapters.append((0.0, chrono[0].title))
        rest = chrono[1:]
    else:
        chapters.append((0.0, OPENER_TITLE))
        rest = chrono
    for c in rest:
        if c.t0 - chapters[-1][0] < CHAPTER_MIN_GAP_S:
            continue  # ins vorherige Kapitel falten
        if duration > 0 and c.t0 >= duration:
            continue
        chapters.append((float(c.t0), c.title))
    return chapters


def render_chapters(chapters: list[tuple[float, str]]) -> str:
    lines = [f"{fmt_tc(t)} {title}".rstrip() for t, title in chapters]
    return "\n".join(lines) + "\n"
