"""Schnittplanung / EDL (F11).

- Punchline-bewusst: Ende kurz nach punchline_t (konfigurierbarer Decay).
- Kategorie-abhaengiger Setup-Vorlauf — aber NICHT zusaetzlich, wenn das
  Fenster schon vom LLM kommt (das enthaelt sein Setup bereits).
- Laengen: min/max aus Config; die Ziel-Laenge eines gelernten CUT-Stils
  darf das generische Maximum uebersteuern (Obergrenze ~90s).
- Media-Grenzen: Fenster fester Laenge in [0, Dauer] SCHIEBEN statt Kanten
  zu klemmen; VOD kuerzer als Minimum -> ganze VOD.
- Ueberlappende Clips mergen (besserer gewinnt), Raenge neu nummerieren;
  Overlays in den Clip geklemmt; callback_refs nur auf frueheres Material.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Config
from .editorial import Moment
from .styles import StyleProfile

# Setup-Vorlauf pro Kategorie (nur fuer Signal-/Punkt-Fenster ohne LLM-Setup)
SETUP_LEAD_S: dict[str, float] = {
    "clutch": 15.0,
    "skill": 12.0,
    "hype": 10.0,
    "funny": 8.0,
    "wtf": 8.0,
    "rage": 8.0,
    "tilt": 8.0,
    "fail": 6.0,
    "talk": 10.0,
}
DEFAULT_SETUP_LEAD_S = 8.0
POST_ROLL_S = 6.0

PUNCHLINE_OK = "ends_just_after"
PUNCHLINE_RUNS_ON = "runs_on"
PUNCHLINE_CUT = "punchline_cut"
PUNCHLINE_UNKNOWN = "unknown"


@dataclass
class Clip:
    rank: int
    t0: float
    t1: float
    title: str
    category: str
    final: float
    score: float  # semantisch 0..10
    signal: float
    style: str
    channels: list[str]
    punchline_t: float
    punchline_state: str
    reason: str
    captions: list[dict] = field(default_factory=list)
    zooms: list[dict] = field(default_factory=list)
    sfx: list[dict] = field(default_factory=list)
    callback_refs: list[dict] = field(default_factory=list)
    lore_refs: list[str] = field(default_factory=list)
    source: str = "llm"
    second_score: float | None = None

    @property
    def duration(self) -> float:
        return self.t1 - self.t0

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "t0": round(self.t0, 2),
            "t1": round(self.t1, 2),
            "duration_s": round(self.duration, 2),
            "title": self.title,
            "category": self.category,
            "final_score": round(self.final, 4),
            "semantic_score": round(self.score, 2),
            "signal_score": round(self.signal, 3),
            "style": self.style,
            "channels": list(self.channels),
            "punchline_t": round(self.punchline_t, 2) if self.punchline_t >= 0 else None,
            "punchline_state": self.punchline_state,
            "reason": self.reason,
            "captions": self.captions,
            "zooms": self.zooms,
            "sfx": self.sfx,
            "callback_refs": self.callback_refs,
            "lore_refs": self.lore_refs,
            "source": self.source,
            "second_score": self.second_score,
        }


def _shift_into_media(t0: float, t1: float, duration: float) -> tuple[float, float]:
    """Fenster fester Laenge in [0, duration] SCHIEBEN statt Kanten klemmen."""
    length = t1 - t0
    if duration > 0 and length >= duration:
        return 0.0, duration  # VOD kuerzer als das Fenster -> ganze VOD
    if t0 < 0:
        t0, t1 = 0.0, length
    if duration > 0 and t1 > duration:
        t0, t1 = duration - length, duration
    return max(0.0, t0), (min(t1, duration) if duration > 0 else t1)


def _clamp_overlays(items: list[dict], t0: float, t1: float) -> list[dict]:
    out = []
    for item in items:
        d = dict(item)
        t = d.get("t", t0)
        d["t"] = round(min(max(float(t), t0), t1), 2)
        out.append(d)
    return out


def plan_window(m: Moment, duration: float, cfg: Config, profile: StyleProfile | None) -> tuple[float, float, str]:
    """Schnittfenster + Punchline-Status fuer EIN Moment berechnen."""
    if m.from_llm_window:
        t0, t1 = m.t0, m.t1  # LLM-Fenster enthaelt sein Setup bereits
    else:
        anchor = m.t0 if m.is_point else (m.t0 + m.t1) / 2.0
        lead = SETUP_LEAD_S.get(m.category, DEFAULT_SETUP_LEAD_S)
        t0 = anchor - lead
        t1 = (m.t1 if not m.is_point else anchor) + POST_ROLL_S

    decay = max(0.5, cfg.punchline_decay_s)
    punch = m.punchline_t
    if punch >= 0 and punch > t0 and punch <= t1 + 30.0:
        t1 = punch + decay  # Ende kurz nach der Pointe

    # Laengen-Grenzen; gelernter CUT-Stil darf das generische Maximum
    # uebersteuern — aber nur bis zur Obergrenze (~90s)
    max_len = cfg.max_clip_s
    if profile is not None and m.style:
        target = profile.cut_style_target_len(m.style)
        if target is not None and target > max_len:
            max_len = min(target, max(cfg.style_max_cap_s, cfg.max_clip_s))
    min_len = min(cfg.min_clip_s, max_len)

    if t1 - t0 > max_len:
        t0 = t1 - max_len  # Anfang kuerzen, Pointe behalten
    if t1 - t0 < min_len:
        t0 = t1 - min_len  # Setup verlaengern

    t0, t1 = _shift_into_media(t0, t1, duration)

    if punch < 0:
        state = PUNCHLINE_UNKNOWN
    elif punch > t1 + 0.01:
        state = PUNCHLINE_CUT
    elif t1 - punch <= decay + 1.0:
        state = PUNCHLINE_OK
    else:
        state = PUNCHLINE_RUNS_ON
    return t0, t1, state


def plan_clips(
    ranked: list[Moment],
    duration: float,
    cfg: Config,
    profile: StyleProfile | None = None,
) -> list[Clip]:
    """Aus gerankten Momenten die finale Clip-Liste (EDL) bauen."""
    clips: list[Clip] = []
    for m in ranked:
        t0, t1, state = plan_window(m, duration, cfg, profile)
        # Ueberlappung mit bereits akzeptierten (= besseren) Clips: besserer gewinnt
        overlaps = any(min(t1, c.t1) - max(t0, c.t0) > 0 for c in clips)
        if overlaps:
            continue
        clips.append(
            Clip(
                rank=0,
                t0=t0,
                t1=t1,
                title=m.title,
                category=m.category,
                final=m.final,
                score=m.score,
                signal=m.signal,
                style=m.style,
                channels=list(m.channels),
                punchline_t=m.punchline_t,
                punchline_state=state,
                reason=m.reason,
                captions=_clamp_overlays(m.captions, t0, t1),
                zooms=_clamp_overlays(m.zooms, t0, t1),
                sfx=_clamp_overlays(m.sfx, t0, t1),
                callback_refs=[r for r in m.callback_refs if r.get("t", 0) < t0],
                lore_refs=list(m.lore_refs),
                source=m.source,
                second_score=m.second_score,
            )
        )
    for i, c in enumerate(clips, start=1):  # Raenge neu nummerieren
        c.rank = i
    return clips
