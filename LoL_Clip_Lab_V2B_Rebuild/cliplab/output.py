"""Ausgaben (F12): edit_sheet.md, edit_plan.json, clips.csv, chapters.txt.

- Sheet: Mensch. Header mit Stats (+Gedaechtnis-Stand), pro Clip alle
  Schnitt-Infos inkl. ehrlicher Punchline-Zeile und Transkript-Auszug
  (Kopf UND Ende — die Pointe faellt nicht dem Truncating zum Opfer).
- edit_plan.json: Maschine, komplette Felder.
- clips.csv: parsebar (Titel gequotet, Stil/Kanaele kommasicher via '|').
- chapters.txt: YouTube-Kapitel.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from .channels import ChannelPlan, render_chapters
from .planning import (
    PUNCHLINE_CUT,
    PUNCHLINE_OK,
    PUNCHLINE_RUNS_ON,
    Clip,
)
from .sanitize import category_emoji
from .transcribe import TranscriptSegment
from .util import fmt_dur, fmt_span, fmt_tc

PLAN_VERSION = 1


def excerpt_for_clip(
    segments: list[TranscriptSegment],
    t0: float,
    t1: float,
    head_chars: int = 280,
    tail_chars: int = 160,
) -> str:
    """Transkript-Auszug: Kopf UND Ende des Clip-Fensters."""
    texts = [s.text for s in segments if s.t1 > t0 and s.t0 < t1]
    full = " ".join(texts).strip()
    if not full:
        return ""
    if len(full) <= head_chars + tail_chars + 5:
        return full
    return full[:head_chars].rstrip() + " […] " + full[-tail_chars:].lstrip()


def punchline_line(clip: Clip) -> str:
    if clip.punchline_t < 0:
        return "- Punchline: unbekannt (kein punchline_t vom LLM)"
    tc = fmt_tc(clip.punchline_t)
    if clip.punchline_state == PUNCHLINE_OK:
        return f"- Punchline: {tc} — Clip endet kurz nach der Pointe ✅"
    if clip.punchline_state == PUNCHLINE_RUNS_ON:
        return f"- Punchline: {tc} — ⚠️ Clip laeuft nach der Pointe weiter (hinten straffen)"
    if clip.punchline_state == PUNCHLINE_CUT:
        return f"- Punchline: {tc} — ⚠️ Pointe liegt HINTER dem Clip-Ende (Fenster pruefen!)"
    return f"- Punchline: {tc}"


def render_clip_section(
    clip: Clip, segments: list[TranscriptSegment], memory_gags: dict[str, dict] | None
) -> str:
    lines: list[str] = []
    emoji = category_emoji(clip.category)
    lines.append(
        f"### #{clip.rank} {emoji} {clip.title} — Score {clip.final * 10:.1f}"
    )
    lines.append(
        f"- Cut: {fmt_span(clip.t0, clip.t1)} ({fmt_dur(clip.duration)})"
        f" · Kategorie: {clip.category}"
    )
    if clip.style:
        lines.append(f"- Cut as: {clip.style}")
    if clip.channels:
        lines.append(f"- Channels: {', '.join(clip.channels)}")
    else:
        lines.append("- Channels: (keine Kanal-Zuordnung)")
    lines.append(punchline_line(clip))
    if clip.reason:
        lines.append(f"- Warum: {clip.reason}")
    if clip.second_score is not None:
        lines.append(f"- Zweitmeinung: {clip.second_score:.1f}/10 (Score gemittelt)")
    elif clip.source == "llm2":
        lines.append("- Quelle: Zweitmeinung (vom Primaer-Gehirn uebersprungen)")
    elif clip.source == "signal":
        lines.append("- Quelle: Signal-only (ohne LLM-Bewertung)")
    excerpt = excerpt_for_clip(segments, clip.t0, clip.t1)
    if excerpt:
        lines.append(f"- Transkript: »{excerpt}«")
    if clip.captions:
        caps = " · ".join(f"[{fmt_tc(c['t'])}] \"{c['text']}\"" for c in clip.captions)
        lines.append(f"- Captions: {caps}")
    if clip.zooms:
        zooms = " · ".join(f"{fmt_tc(z['t'])} ({z['duration']:.1f}s)" for z in clip.zooms)
        lines.append(f"- Zooms: {zooms}")
    if clip.sfx:
        sfx = " · ".join(f"{fmt_tc(s['t'])} {s['kind']}" for s in clip.sfx)
        lines.append(f"- SFX: {sfx}")
    for ref in clip.callback_refs:
        note = f" — {ref['note']}" if ref.get("note") else ""
        lines.append(
            f"- Callback-Insert: Setup bei {fmt_tc(ref['t'])}{note} "
            "(frueheres Material einblenden)"
        )
    for ref in clip.lore_refs:
        extra = ""
        if memory_gags:
            from .util import slugify

            gag = memory_gags.get(slugify(ref, fallback=""))
            if gag:
                extra = f" ({gag['times_seen']}x gesehen)"
        lines.append(f"- 🧠 Lore: \"{ref}\"{extra}")
    return "\n".join(lines)


def render_channel_plans(plans: list[ChannelPlan]) -> str:
    lines = ["## 📺 Kanal-Plaene", ""]
    for plan in plans:
        spec = plan.spec
        meta = []
        if spec.vertical:
            meta.append("vertikal 9:16")
        if spec.max_s:
            meta.append(f"max {int(spec.max_s)}s")
        if plan.format_runtime_s:
            meta.append(f"gelernte Ziel-Laufzeit ~{plan.format_runtime_s / 60:.1f} min")
        suffix = f" ({' · '.join(meta)})" if meta else ""
        lines.append(f"### {spec.name}{suffix}")
        if spec.note:
            lines.append(f"_{spec.note}_")
        if plan.is_full:
            lines.append("→ chapters.txt (Kapitelmarker fuer die ganze Session)")
            lines.append("")
            continue
        if not plan.entries:
            lines.append("(keine Clips fuer diesen Kanal)")
            lines.append("")
            continue
        lines.append("Chronologisch (Story-Reihenfolge fuers Video):")
        for e in plan.entries:
            style = f" · Stil {e.style}" if e.style else ""
            lines.append(
                f"- {fmt_span(e.t0, e.t1)} ({fmt_dur(e.t1 - e.t0)}) · #{e.rank} {e.title}{style}"
            )
            if e.warning:
                lines.append(f"  - ⚠️ {e.warning}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_edit_sheet(
    vod_name: str,
    duration: float,
    mode_line: str,
    stats: dict,
    clips: list[Clip],
    plans: list[ChannelPlan],
    segments: list[TranscriptSegment],
    memory_state: dict | None,
    generated_on: str,
    warnings: list[str] | None = None,
) -> str:
    lines = [
        f"# 🎬 Edit Sheet — {vod_name}",
        "",
        f"- Dauer: {fmt_tc(duration, force_hours=True)}",
        f"- Modus: {mode_line}",
        (
            f"- Analyse: {stats.get('segments', 0)} Transkript-Segmente · "
            f"{stats.get('reactions', 0)} Reaktionen · "
            f"{stats.get('events', 0)} Game-Events · "
            f"{stats.get('candidates', 0)} Kandidaten"
        ),
        f"- Momente: {stats.get('moments', 0)} bewertet → {len(clips)} Clips geplant",
    ]
    if memory_state is None:
        lines.append("- 🧠 Gedaechtnis: aus (--no-memory oder Signal-only)")
    else:
        lines.append(
            f"- 🧠 Gedaechtnis: {memory_state.get('gags_known', 0)} Running Gags bekannt · "
            f"{memory_state.get('sessions_known', 0)} Sessions erinnert"
        )
    lines.append(f"- Erstellt: {generated_on}")
    if warnings:
        lines.append("")
        lines.append("## ⚠️ Hinweise")
        for w in warnings:
            lines.append(f"- {w}")
    lines += ["", "## Clips", ""]
    if not clips:
        lines.append("(keine Clips gefunden — Session zu ruhig oder Eingaben pruefen)")
    memory_gags = None
    if memory_state and memory_state.get("gags_by_slug"):
        memory_gags = memory_state["gags_by_slug"]
    for clip in clips:
        lines.append(render_clip_section(clip, segments, memory_gags))
        lines.append("")
    lines.append(render_channel_plans(plans))
    return "\n".join(lines).rstrip() + "\n"


def render_clips_csv(clips: list[Clip]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(
        [
            "rank",
            "title",
            "category",
            "t0_s",
            "t1_s",
            "duration_s",
            "timecode",
            "score",
            "style",
            "channels",
            "punchline_t",
            "source",
        ]
    )
    for c in clips:
        writer.writerow(
            [
                c.rank,
                c.title,
                c.category,
                f"{c.t0:.2f}",
                f"{c.t1:.2f}",
                f"{c.duration:.2f}",
                fmt_span(c.t0, c.t1),
                f"{c.final * 10:.1f}",
                c.style,
                "|".join(c.channels),  # kommasicher
                f"{c.punchline_t:.2f}" if c.punchline_t >= 0 else "",
                c.source,
            ]
        )
    return buf.getvalue()


def build_plan_dict(
    vod_name: str,
    duration: float,
    mode: str,
    stats: dict,
    clips: list[Clip],
    plans: list[ChannelPlan],
    chapters: list[tuple[float, str]],
    generated_on: str,
) -> dict:
    return {
        "version": PLAN_VERSION,
        "tool": "cliplab",
        "vod": vod_name,
        "duration_s": round(duration, 2),
        "mode": mode,
        "generated": generated_on,
        "stats": stats,
        "channels": [
            {
                "name": p.spec.name,
                "kind": p.spec.kind,
                "max_s": p.spec.max_s,
                "vertical": p.spec.vertical,
                "format_runtime_s": p.format_runtime_s,
            }
            for p in plans
        ],
        "clips": [c.to_dict() for c in clips],
        "chapters": [{"t": round(t, 2), "title": title} for t, title in chapters],
    }


def write_outputs(
    out_dir: Path | str,
    sheet_text: str,
    plan: dict,
    clips: list[Clip],
    chapters: list[tuple[float, str]],
) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "sheet": out_dir / "edit_sheet.md",
        "plan": out_dir / "edit_plan.json",
        "csv": out_dir / "clips.csv",
        "chapters": out_dir / "chapters.txt",
    }
    paths["sheet"].write_text(sheet_text, encoding="utf-8")
    paths["plan"].write_text(
        json.dumps(plan, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    paths["csv"].write_text(render_clips_csv(clips), encoding="utf-8")
    paths["chapters"].write_text(render_chapters(chapters), encoding="utf-8")
    return paths
