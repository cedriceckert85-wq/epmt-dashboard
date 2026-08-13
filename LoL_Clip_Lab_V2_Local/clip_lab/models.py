"""Plain data models shared across the pipeline. All times are SECONDS
(float) relative to the start of the VOD, unless the field name says _ms."""
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Word:
    t0: float
    t1: float
    text: str


@dataclass
class TranscriptSegment:
    t0: float
    t1: float
    text: str
    words: list = field(default_factory=list)  # list[Word]

    def as_dict(self):
        d = asdict(self)
        return d


@dataclass
class ReactionEvent:
    """A moment where the streamer's audio spikes (laughter / shouting /
    excitement) — the most honest signal of 'something happened here'."""
    t: float               # peak time
    t0: float              # onset
    t1: float              # offset
    intensity: float       # 0..1, prominence over local baseline
    kind: str = "reaction"  # reaction | laugh | shout (best-effort)


@dataclass
class GameEvent:
    """Optional, user-provided match events (kills, objectives, ...). For a
    downloaded VOD there is no live API, so these are optional and come from
    a JSON/CSV the user supplies or leaves empty."""
    t: float
    kind: str              # kill, multikill, ace, dragon, baron, first_blood, ...
    weight: float = 0.0
    detail: dict = field(default_factory=dict)


@dataclass
class Candidate:
    """A candidate highlight window before editorial refinement."""
    t0: float
    t1: float
    signal_score: float
    reasons: list = field(default_factory=list)   # list[str]
    # editorial (LLM) fields, filled later if available
    category: Optional[str] = None                # funny|hype|fail|clutch|callback|wholesome
    semantic_score: float = 0.0
    punchline_t: Optional[float] = None
    title: Optional[str] = None
    why: Optional[str] = None
    callback_refs: list = field(default_factory=list)   # list[float] earlier timestamps
    lore_refs: list = field(default_factory=list)        # list[str] known channel gags this continues
    style_target: Optional[str] = None                   # learned reference style to cut this in
    channels: list = field(default_factory=list)          # target channels this moment serves
    window_from_llm: bool = False                          # t0/t1 are the brain's cut window (setup included)
    caption_suggestions: list = field(default_factory=list)  # [{t, text}]
    zoom_suggestions: list = field(default_factory=list)     # [{t, duration}]
    sfx_suggestions: list = field(default_factory=list)      # [{t, kind}]
    final_score: float = 0.0
    editorial_source: str = "signal"              # signal | llm

    def as_dict(self):
        return asdict(self)


@dataclass
class EditPlanItem:
    """One clip in the final edit sheet: exact cut points + overlay plan."""
    rank: int
    clip_t0: float
    clip_t1: float
    category: str
    title: str
    why: str
    punchline_t: Optional[float]
    final_score: float
    captions: list = field(default_factory=list)   # [{t, text}]
    zooms: list = field(default_factory=list)       # [{t, duration}]
    sfx: list = field(default_factory=list)         # [{t, kind}]
    callback_inserts: list = field(default_factory=list)  # [{ref_t0, ref_t1, note}]
    lore_refs: list = field(default_factory=list)          # known channel gags this continues
    style_target: Optional[str] = None                     # reference style to cut this in
    channels: list = field(default_factory=list)            # target channels (shorts/main/uncut)
    transcript_excerpt: str = ""

    @property
    def duration(self):
        return round(self.clip_t1 - self.clip_t0, 3)

    def as_dict(self):
        d = asdict(self)
        d["duration"] = self.duration
        return d
