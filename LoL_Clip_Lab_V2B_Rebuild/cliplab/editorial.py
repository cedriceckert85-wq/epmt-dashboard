"""LLM-Editorial (der Kern): Session-Pass + Moment-Pass.

- Session-Pass liest das GESAMTE Timeline-Dokument in zeilen-alignierten
  Chunks; Funde werden fortgeschrieben und dedupliziert gemerged.
  Ein Gag aus Minute 3 mit Payoff in Stunde 3 bleibt verbindbar.
- Moment-Pass bewertet Signal-Kandidaten UND darf eigene Momente entdecken.
  Kontext: volle Details ±window um jeden Kandidaten + gleichmaessige
  Stichprobe des Rests. KEIN Kandidat verliert seinen Kontext.
- JEDES LLM-Feld wird sanitisiert (sanitize.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

from .config import Config
from .events import GameEvent
from .jsonextract import extract_json
from .reactions import Reaction
from .sanitize import (
    clean_captions,
    clean_category,
    clean_list,
    clean_num,
    clean_sfx,
    clean_str,
    clean_str_list,
    clean_tag,
    clean_tags,
    clean_time,
    clean_zooms,
)
from .timeline import TimelineEntry, chunk_text_lines
from .util import fmt_tc

SESSION_MARKER = "### CLIPLAB-TASK: SESSION-ANALYSE ###"
MOMENT_MARKER = "### CLIPLAB-TASK: MOMENT-AUSWAHL ###"

Runner = Callable[[str], "str | None"]


# ---------------------------------------------------------------------------
# Datenmodelle


@dataclass
class Candidate:
    t0: float
    t1: float
    peak_t: float
    signal: float
    sources: list[str] = field(default_factory=list)

    @property
    def is_point(self) -> bool:
        return (self.t1 - self.t0) <= 1e-6


@dataclass
class Moment:
    t0: float
    t1: float
    title: str = "Moment"
    category: str = "moment"
    score: float = 5.0  # semantisch, 0..10
    punchline_t: float = -1.0
    reason: str = ""
    style: str = ""
    channels: list[str] = field(default_factory=list)
    callback_refs: list[dict] = field(default_factory=list)
    lore_refs: list[str] = field(default_factory=list)
    captions: list[dict] = field(default_factory=list)
    zooms: list[dict] = field(default_factory=list)
    sfx: list[dict] = field(default_factory=list)
    source: str = "llm"  # llm | llm2 | signal
    from_llm_window: bool = True
    signal: float = 0.0
    second_score: float | None = None
    final: float = 0.0
    rank: int = 0

    @property
    def is_point(self) -> bool:
        return (self.t1 - self.t0) <= 1e-6


@dataclass
class SessionInsights:
    running_gags: list[dict] = field(default_factory=list)
    callbacks: list[dict] = field(default_factory=list)
    arcs: list[dict] = field(default_factory=list)
    catchphrases: list[str] = field(default_factory=list)
    lore: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "running_gags": self.running_gags,
            "callbacks": self.callbacks,
            "arcs": self.arcs,
            "catchphrases": self.catchphrases,
            "lore": self.lore,
            "notes": self.notes,
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# Kandidaten aus Signalen


def build_candidates(
    reactions: list[Reaction],
    events: list[GameEvent],
    merge_within_s: float = 5.0,
) -> list[Candidate]:
    """Reaktionen + positive Events zu Kandidaten mergen.

    Einzel-Event-Kandidaten sind punktfoermig (t0 == t1).
    """
    items: list[Candidate] = []
    for r in reactions:
        items.append(
            Candidate(
                t0=float(r.t0),
                t1=float(r.t1),
                peak_t=float(r.t),
                signal=float(max(0.0, min(1.0, r.intensity))),
                sources=[f"reaction({r.intensity:.2f})"],
            )
        )
    for ev in events:
        if ev.weight <= 0:
            continue  # negative Events erscheinen nur in der Timeline
        items.append(
            Candidate(
                t0=float(ev.t),
                t1=float(ev.t),
                peak_t=float(ev.t),
                signal=float(min(1.5, ev.weight / 5.0)),
                sources=[f"event:{ev.kind}"],
            )
        )
    items.sort(key=lambda c: (c.peak_t, c.t0))
    merged: list[Candidate] = []
    for c in items:
        if merged and (c.peak_t - merged[-1].peak_t) <= merge_within_s:
            prev = merged[-1]
            stronger = prev if prev.signal >= c.signal else c
            prev.t0 = min(prev.t0, c.t0)
            prev.t1 = max(prev.t1, c.t1)
            prev.signal = min(2.0, prev.signal + c.signal)
            prev.peak_t = stronger.peak_t
            prev.sources = prev.sources + c.sources
            continue
        merged.append(c)
    return merged


# ---------------------------------------------------------------------------
# Match-Geometrie (F5)


def windows_match(m0: float, m1: float, c0: float, c1: float) -> bool:
    """Zeit-Ueberlappung mit Punkt-Sonderfaellen.

    - Punkt-Kandidat in Moment-Fenster (inkl. Kante) -> Match
    - reine Kanten-Beruehrung zweier echter Fenster -> KEIN Match
    - Punkt vs. Punkt -> nur (nahezu) identisch
    """
    eps = 1e-6
    m_point = (m1 - m0) <= eps
    c_point = (c1 - c0) <= eps
    if m_point and c_point:
        return abs(m0 - c0) <= 0.01
    if c_point:
        return m0 <= c0 <= m1
    if m_point:
        return c0 <= m0 <= c1
    return min(m1, c1) - max(m0, c0) > eps


def dedupe_moments(moments: list[Moment]) -> list[Moment]:
    """Identische Fenster sind Duplikate — sie verbrennen keine Ranking-Plaetze.

    Behalten wird das jeweils besser bewertete Exemplar (Primaer vor Zweit).
    """
    order = {"llm": 0, "signal": 1, "llm2": 2}
    kept: list[Moment] = []
    for m in moments:
        dup = None
        for k in kept:
            if abs(m.t0 - k.t0) <= 0.01 and abs(m.t1 - k.t1) <= 0.01:
                dup = k
                break
        if dup is None:
            kept.append(m)
            continue
        better = (m.score, -order.get(m.source, 9)) > (dup.score, -order.get(dup.source, 9))
        if better:
            kept[kept.index(dup)] = m
    return kept


def attach_candidates(moments: list[Moment], candidates: list[Candidate]) -> set[int]:
    """Momente per Zeit-Ueberlappung auf Kandidaten matchen.

    Gematchte Kandidaten gelten als konsumiert; das Moment behaelt SEIN
    (LLM-)Schnittfenster und erbt das staerkste Kandidaten-Signal.
    """
    consumed: set[int] = set()
    for m in moments:
        best = 0.0
        for i, c in enumerate(candidates):
            if windows_match(m.t0, m.t1, c.t0, c.t1):
                consumed.add(i)
                best = max(best, c.signal)
        m.signal = max(m.signal, best)
    return consumed


def moments_from_candidates(candidates: list[Candidate]) -> list[Moment]:
    """Signal-only-Fallback: Kandidaten direkt als Momente (ohne LLM)."""
    out: list[Moment] = []
    for c in candidates:
        is_event = any(s.startswith("event:") for s in c.sources)
        if is_event:
            kinds = [s.split(":", 1)[1] for s in c.sources if s.startswith("event:")]
            title = f"Game-Event: {', '.join(kinds)}"
            category = "clutch" if c.signal >= 0.6 else "moment"
        else:
            title = f"Laute Reaktion (Intensitaet {c.signal:.2f})"
            category = "hype"
        out.append(
            Moment(
                t0=c.t0,
                t1=c.t1,
                title=title,
                category=category,
                score=0.0,
                reason="Signal-only: Audio-/Event-Kandidat ohne LLM-Bewertung",
                source="signal",
                from_llm_window=False,
                signal=c.signal,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Prompt-Bausteine


def language_rule(cfg: Config) -> str:
    if cfg.language and cfg.language != "auto":
        return (
            f"Schreibe Titel, Captions, Begruendungen und Gag-Namen auf "
            f"'{cfg.language}'."
        )
    return (
        "Schreibe Titel, Captions, Begruendungen und Gag-Namen in der "
        "SPRACHE, die die Streamer im Transkript sprechen."
    )


def hosts_rule(cfg: Config) -> str:
    if cfg.hosts:
        return (
            "Die Streamer (Duo) heissen: "
            + ", ".join(clean_str(h, 40) for h in cfg.hosts if clean_str(h, 40))
            + ". Ordne Gags und Zitate der richtigen Person zu."
        )
    return "Es streamt ein Duo; ordne Gags moeglichst der richtigen Person zu."


def channels_block(cfg: Config) -> str:
    lines = ["Verfuegbare Kanaele (channels-Tags):"]
    for ch in cfg.channels:
        extra = []
        if ch.kind == "full":
            extra.append("Ganz-VOD-Kanal, braucht nur Kapitel")
        if ch.max_s:
            extra.append(f"max. {int(ch.max_s)}s pro Clip")
        if ch.vertical:
            extra.append("vertikal 9:16")
        suffix = f" ({'; '.join(extra)})" if extra else ""
        note = f" — {ch.note}" if ch.note else ""
        lines.append(f"- {ch.name}{suffix}{note}")
    return "\n".join(lines)


def styles_block(cut_styles: dict, budget_chars: int = 2000) -> str:
    """Nur CUT-Stile anbieten. JEDER Stilname erreicht den Prompt;
    das Beschreibungs-Budget wird fair aufgeteilt."""
    if not cut_styles:
        return ""
    names = sorted(cut_styles.keys())
    per_style = max(40, budget_chars // max(1, len(names)))
    lines = ["Gelernte Schnitt-Stile (style-Tag, genau einen passenden waehlen):"]
    for name in names:
        st = cut_styles[name]
        desc_parts = [f"ideal ~{int(round(st.get('ideal_len_s', 0)))}s"]
        cpm = st.get("cuts_per_min")
        if cpm is not None:
            desc_parts.append(f"{cpm:.1f} Schnitte/min")
        notes = clean_str(st.get("notes", ""), max_len=per_style)
        if notes:
            desc_parts.append(notes)
        cap = clean_str(st.get("caption_style", ""), max_len=per_style // 2)
        if cap:
            desc_parts.append(f"Captions: {cap}")
        lines.append(f"- {name}: " + ", ".join(desc_parts))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Session-Pass


_SESSION_SCHEMA = (
    '{"running_gags":[{"name":"...","first_t":123,"note":"..."}],'
    '"callbacks":[{"setup_t":123,"payoff_t":4567,"note":"..."}],'
    '"arcs":[{"t0":0,"t1":600,"title":"..."}],'
    '"catchphrases":["..."],"lore":["..."],"notes":["..."],'
    '"summary":"1-3 Saetze"}'
)


def build_session_prompt(
    cfg: Config,
    chunk: str,
    chunk_no: int,
    chunk_total: int,
    prev: SessionInsights,
    memory_block: str,
) -> str:
    parts = [
        SESSION_MARKER,
        "Du bist Editorial-Assistent fuer ein Streamer-Duo (League of Legends).",
        "Lies den Timeline-Abschnitt und erkenne: Running Gags, Callbacks "
        "(Setup frueh, Payoff spaeter — auch Stunden spaeter!), Story-Arcs, "
        "Catchphrases, Lore.",
        hosts_rule(cfg),
        language_rule(cfg),
    ]
    if memory_block:
        parts += ["", "KANAL-GEDAECHTNIS (aus frueheren Sessions — erkenne Wiederkehrendes):", memory_block]
    if chunk_total > 1 or prev.running_gags or prev.callbacks:
        parts += [
            "",
            "BISHERIGE FUNDE aus frueheren Abschnitten dieser Session "
            "(fortschreiben und ergaenzen, NICHTS davon verlieren):",
            json.dumps(prev.to_dict(), ensure_ascii=False),
        ]
    parts += [
        "",
        f"--- TIMELINE-ABSCHNITT {chunk_no}/{chunk_total} ---",
        chunk,
        "--- ENDE ABSCHNITT ---",
        "",
        "Antworte NUR mit einem JSON-Objekt exakt in dieser Form:",
        _SESSION_SCHEMA,
    ]
    return "\n".join(parts)


def sanitize_insights(data, duration: float) -> SessionInsights:
    ins = SessionInsights()
    if not isinstance(data, dict):
        return ins
    for g in clean_list(data.get("running_gags"))[:60]:
        if isinstance(g, str):
            g = {"name": g}
        if not isinstance(g, dict):
            continue
        name = clean_str(g.get("name"), max_len=80)
        if not name:
            continue
        ins.running_gags.append(
            {
                "name": name,
                "first_t": clean_time(g.get("first_t"), duration, default=-1.0),
                "note": clean_str(g.get("note"), max_len=200),
            }
        )
    for c in clean_list(data.get("callbacks"))[:60]:
        if not isinstance(c, dict):
            continue
        setup = clean_time(c.get("setup_t"), duration, default=-1.0)
        payoff = clean_time(c.get("payoff_t"), duration, default=-1.0)
        if setup < 0 or payoff < 0 or payoff <= setup:
            continue
        ins.callbacks.append(
            {
                "setup_t": setup,
                "payoff_t": payoff,
                "note": clean_str(c.get("note"), max_len=200),
            }
        )
    for a in clean_list(data.get("arcs"))[:40]:
        if not isinstance(a, dict):
            continue
        t0 = clean_time(a.get("t0"), duration, default=-1.0)
        t1 = clean_time(a.get("t1"), duration, default=-1.0)
        if t0 < 0 or t1 <= t0:
            continue
        ins.arcs.append({"t0": t0, "t1": t1, "title": clean_str(a.get("title"), max_len=120)})
    ins.catchphrases = clean_str_list(data.get("catchphrases"), max_items=20, max_len=120)
    ins.lore = clean_str_list(data.get("lore"), max_items=20, max_len=160)
    ins.notes = clean_str_list(data.get("notes"), max_items=20, max_len=200)
    ins.summary = clean_str(data.get("summary"), max_len=500)
    return ins


def merge_insights(base: SessionInsights, new: SessionInsights) -> SessionInsights:
    """Dedupliziert mergen — Funde frueherer Chunks bleiben erhalten."""
    from .util import slugify

    out = SessionInsights()
    seen_gags: set[str] = set()
    for g in base.running_gags + new.running_gags:
        key = slugify(g["name"], fallback="")
        if not key or key in seen_gags:
            for existing in out.running_gags:
                if slugify(existing["name"], fallback="?") == key:
                    if existing.get("first_t", -1) < 0 <= g.get("first_t", -1):
                        existing["first_t"] = g["first_t"]
                    if not existing.get("note") and g.get("note"):
                        existing["note"] = g["note"]
            continue
        seen_gags.add(key)
        out.running_gags.append(dict(g))
    seen_cb: set[tuple] = set()
    for c in base.callbacks + new.callbacks:
        key = (int(round(c["setup_t"])), int(round(c["payoff_t"])))
        if key in seen_cb:
            continue
        seen_cb.add(key)
        out.callbacks.append(dict(c))
    seen_arc: set[tuple] = set()
    for a in base.arcs + new.arcs:
        key = (int(round(a["t0"])), int(round(a["t1"])))
        if key in seen_arc:
            continue
        seen_arc.add(key)
        out.arcs.append(dict(a))
    for lst_name in ("catchphrases", "lore", "notes"):
        merged: list[str] = []
        for s in getattr(base, lst_name) + getattr(new, lst_name):
            if s not in merged:
                merged.append(s)
        setattr(out, lst_name, merged[:20])
    out.summary = new.summary or base.summary
    out.running_gags = out.running_gags[:40]
    out.callbacks = out.callbacks[:40]
    out.arcs = out.arcs[:30]
    return out


def session_pass(
    cfg: Config,
    doc: str,
    duration: float,
    runner: Runner | None,
    memory_block: str = "",
) -> SessionInsights:
    """GESAMTES Timeline-Dokument analysieren (chunked, Funde mitgefuehrt)."""
    insights = SessionInsights()
    if runner is None:
        return insights
    chunks = chunk_text_lines(doc, cfg.chunk_chars)
    total = len(chunks)
    for i, chunk in enumerate(chunks, start=1):
        prompt = build_session_prompt(cfg, chunk, i, total, insights, memory_block)
        raw = runner(prompt)
        if raw is None:
            continue
        data = extract_json(raw)
        if data is None:
            continue
        insights = merge_insights(insights, sanitize_insights(data, duration))
    return insights


# ---------------------------------------------------------------------------
# Moment-Pass


_MOMENT_SCHEMA = (
    '{"moments":[{"t0":120,"t1":158,"title":"...","category":"funny|fail|clutch|hype|'
    'rage|tilt|wholesome|skill|wtf|talk","score":8.5,"punchline_t":152,'
    '"reason":"...","style":"<stilname oder leer>","channels":["insta","yt"],'
    '"callback_refs":[{"t":200,"note":"Setup frueher"}],"lore_refs":["Gag-Name"],'
    '"captions":[{"t":125,"text":"..."}],"zooms":[{"t":152,"duration":1.5}],'
    '"sfx":[{"t":153,"kind":"boom"}]}]}'
)


def build_moment_context(
    entries: list[TimelineEntry],
    candidates: list[Candidate],
    budget_chars: int,
    window_s: float,
) -> str:
    """Kontextblock: volle Details ±window um jeden Kandidaten +
    gleichmaessige Stichprobe des Rests. Budget begrenzt, aber KEIN
    Kandidat verliert seinen Kontext."""
    budget_chars = max(2000, int(budget_chars))
    if not entries:
        return "(keine Timeline-Daten)"
    used: set[int] = set()
    blocks: list[str] = []
    if candidates:
        per_cand = max(300, int(budget_chars * 0.75) // len(candidates))
        for ci, cand in enumerate(candidates, start=1):
            lo = cand.peak_t - window_s
            hi = cand.peak_t + window_s
            idxs = [i for i, e in enumerate(entries) if lo <= e.t <= hi]
            if not idxs:
                # naechste Zeile trotzdem mitgeben — Kontext nie ganz verlieren
                nearest = min(
                    range(len(entries)), key=lambda i: abs(entries[i].t - cand.peak_t)
                )
                idxs = [nearest]
            # Budget: naheste Zeilen zuerst behalten, dann chronologisch
            idxs_near = sorted(idxs, key=lambda i: (abs(entries[i].t - cand.peak_t), i))
            picked: list[int] = []
            size = 0
            for i in idxs_near:
                line_len = len(entries[i].line) + 1
                if picked and size + line_len > per_cand:
                    continue
                picked.append(i)
                size += line_len
            picked.sort()
            used.update(picked)
            span = f"{fmt_tc(cand.t0, True)}–{fmt_tc(cand.t1, True)}"
            header = (
                f"=== KANDIDAT {ci}: t={int(round(cand.peak_t))} "
                f"(Fenster {span}, Signal {cand.signal:.2f}, "
                f"Quellen: {', '.join(cand.sources) or '-'}) ==="
            )
            blocks.append("\n".join([header] + [entries[i].line for i in picked]))

    rest = [i for i in range(len(entries)) if i not in used]
    remaining = budget_chars - sum(len(b) + 1 for b in blocks)
    if rest and remaining > 200:
        total_rest_chars = sum(len(entries[i].line) + 1 for i in rest)
        step = max(1, -(-total_rest_chars // remaining))  # ceil
        sampled = rest[::step]
        picked2: list[int] = []
        size = 0
        for i in sampled:
            line_len = len(entries[i].line) + 1
            if size + line_len > remaining:
                break
            picked2.append(i)
            size += line_len
        if picked2:
            blocks.append(
                "\n".join(
                    ["=== GLEICHMAESSIGE STICHPROBE DER RESTLICHEN SESSION ==="]
                    + [entries[i].line for i in picked2]
                )
            )
    return "\n\n".join(blocks)


def build_moment_prompt(
    cfg: Config,
    entries: list[TimelineEntry],
    candidates: list[Candidate],
    insights: SessionInsights,
    cut_styles: dict,
    memory_block: str,
    duration: float,
) -> str:
    parts = [
        MOMENT_MARKER,
        "Du bist Cutter/Editor fuer ein Streamer-Duo (League of Legends).",
        "Finde die CLIP-WUERDIGEN Momente dieser Session und liefere exakte "
        "Schnittfenster. Das Fenster t0..t1 MUSS das Setup enthalten "
        "(nicht erst bei der Pointe anfangen).",
        hosts_rule(cfg),
        language_rule(cfg),
        f"Session-Dauer: {int(round(duration))}s.",
        "Bewerte die aufgefuehrten KANDIDATEN — aber du DARFST zusaetzlich "
        "eigene Momente entdecken, auch ohne Game-Event oder Lautstaerke-Peak "
        "(z.B. trockener Humor, Story-Payoffs).",
        "",
        channels_block(cfg),
    ]
    sb = styles_block(cut_styles)
    if sb:
        parts += ["", sb]
    else:
        parts += ["", "Keine gelernten Stile vorhanden — style leer lassen."]
    if memory_block:
        parts += ["", "KANAL-GEDAECHTNIS (markiere Wiedererkanntes via lore_refs):", memory_block]
    if insights.running_gags or insights.callbacks or insights.summary:
        parts += [
            "",
            "SESSION-ANALYSE (Pass 1 — nutze Callbacks/Gags fuer Fenster und lore_refs):",
            json.dumps(insights.to_dict(), ensure_ascii=False),
        ]
    parts += [
        "",
        "=== KANDIDATEN & KONTEXT ===",
        build_moment_context(entries, candidates, cfg.moment_budget_chars, cfg.context_window_s),
        "",
        "Antworte NUR mit einem JSON-Objekt exakt in dieser Form:",
        _MOMENT_SCHEMA,
        "Regeln: score 0-10; punchline_t = Sekunde der Pointe; channels nur "
        "aus der Kanal-Liste; style nur aus der Stil-Liste (oder leer); "
        "captions/zooms/sfx sparsam und nur wenn sie den Clip besser machen.",
    ]
    return "\n".join(parts)


def sanitize_moment(
    raw,
    duration: float,
    cut_style_names: set[str],
    cfg: Config,
    source: str = "llm",
) -> Moment | None:
    if not isinstance(raw, dict):
        return None
    t0 = clean_time(raw.get("t0"), duration, default=-1.0)
    t1 = clean_time(raw.get("t1"), duration, default=-1.0)
    if t0 < 0 or t1 < 0:
        return None
    if t1 < t0:
        t0, t1 = t1, t0
    channel_names = cfg.channel_names()
    style = clean_tag(raw.get("style"), cut_style_names)
    channels = clean_tags(raw.get("channels"), channel_names)
    # Kohaerenz-Regel: Stil "<kanal>_<x>" (oder exakt "<kanal>") impliziert den Kanal
    if style:
        for ch in channel_names:
            if (style == ch or style.startswith(ch + "_")) and ch not in channels:
                spec = cfg.channel(ch)
                if spec is not None and spec.kind != "full":
                    channels.append(ch)
    callback_refs: list[dict] = []
    for ref in clean_list(raw.get("callback_refs"))[:12]:
        if isinstance(ref, dict):
            t = clean_time(ref.get("t", ref.get("setup_t")), duration, default=-1.0)
            note = clean_str(ref.get("note"), max_len=160)
        else:
            t = clean_time(ref, duration, default=-1.0)
            note = ""
        if t < 0:
            continue
        callback_refs.append({"t": round(t, 2), "note": note})
        if len(callback_refs) >= 6:
            break
    title = clean_str(raw.get("title"), max_len=90)
    if not title:
        title = f"Moment bei {fmt_tc(t0)}"
    m = Moment(
        t0=t0,
        t1=t1,
        title=title,
        category=clean_category(raw.get("category")),
        score=clean_num(raw.get("score"), 0.0, 10.0, default=5.0),
        punchline_t=clean_time(raw.get("punchline_t"), duration, default=-1.0),
        reason=clean_str(raw.get("reason"), max_len=300),
        style=style,
        channels=channels,
        callback_refs=callback_refs,
        lore_refs=clean_str_list(raw.get("lore_refs"), max_items=6, max_len=80),
        captions=clean_captions(raw.get("captions"), duration),
        zooms=clean_zooms(raw.get("zooms"), duration),
        sfx=clean_sfx(raw.get("sfx"), duration),
        source=source,
        from_llm_window=(t1 - t0) >= 1.0,
    )
    return m


def parse_moments_response(
    raw_text: str | None,
    duration: float,
    cut_style_names: set[str],
    cfg: Config,
    source: str = "llm",
    max_moments: int = 80,
) -> list[Moment]:
    if raw_text is None:
        return []
    data = extract_json(raw_text)
    if isinstance(data, dict):
        raw_list = data.get("moments")
    else:
        raw_list = data
    if not isinstance(raw_list, list):
        return []
    out: list[Moment] = []
    for entry in raw_list[: max_moments * 2]:
        m = sanitize_moment(entry, duration, cut_style_names, cfg, source=source)
        if m is not None:
            out.append(m)
        if len(out) >= max_moments:
            break
    return out


def moment_pass(
    cfg: Config,
    entries: list[TimelineEntry],
    candidates: list[Candidate],
    insights: SessionInsights,
    cut_styles: dict,
    memory_block: str,
    duration: float,
    runner: Runner | None,
) -> tuple[list[Moment], str]:
    """Moment-Pass ausfuehren. Rueckgabe (Momente, benutzter Prompt).

    Der Prompt wird zurueckgegeben, damit das Doppel-Gehirn (F9) den
    IDENTISCHEN Prompt erhaelt.
    """
    prompt = build_moment_prompt(
        cfg, entries, candidates, insights, cut_styles, memory_block, duration
    )
    if runner is None:
        return [], prompt
    raw = runner(prompt)
    moments = parse_moments_response(
        raw, duration, set(cut_styles.keys()), cfg, source="llm"
    )
    return moments, prompt
