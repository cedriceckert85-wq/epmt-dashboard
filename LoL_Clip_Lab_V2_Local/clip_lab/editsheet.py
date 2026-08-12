"""Render the edit plan as human-facing artifacts: a Markdown 'edit sheet' you
read top-to-bottom, plus machine JSON and a CSV you can import into an editor.
"""
from .util import hhmmss, write_json, write_text


CAT_EMOJI = {"funny": "😂", "hype": "🔥", "clutch": "🎯", "fail": "💀",
             "callback": "🔁", "wholesome": "🥹", "moment": "⭐"}


def write_edit_sheet(plan, out_dir, *, vod_name, meta):
    write_json(f"{out_dir}/edit_plan.json",
               {"vod": vod_name, "meta": meta, "clips": [p.as_dict() for p in plan]})
    write_text(f"{out_dir}/edit_sheet.md", _markdown(plan, vod_name, meta))
    write_text(f"{out_dir}/clips.csv", _csv(plan))
    if plan:
        # ready-to-paste YouTube chapter markers for the uncut upload
        write_text(f"{out_dir}/chapters.txt", _chapters(plan))
    return out_dir


def _markdown(plan, vod_name, meta):
    L = [f"# Edit Sheet — {vod_name}", ""]
    L.append(f"- Source duration: {hhmmss(meta.get('duration', 0))}")
    L.append(f"- Editorial brain: **{meta.get('editorial', 'signal-only')}**")
    if meta.get("memory"):
        L.append(f"- 🧠 Channel memory: {meta['memory'].get('gags', 0)} running gags "
                 f"across {meta['memory'].get('sessions_analyzed', 0)} analyzed sessions")
    L.append(f"- Reactions found: {meta.get('reactions', 0)} · "
             f"game events: {meta.get('events', 0)} · candidates: {meta.get('candidates', 0)}")
    L.append(f"- Suggested clips: **{len(plan)}**")
    L.append("")
    L.append("Each clip below is a suggestion — open your editor at the timecodes, "
             "review, and keep what lands. Cut points are punchline-aware.")
    L.append("")
    for p in plan:
        emoji = CAT_EMOJI.get(p.category, "⭐")
        L.append(f"## {p.rank}. {emoji} {p.title}   ·   score {p.final_score:.2f}")
        L.append("")
        L.append(f"- **Cut:** `{hhmmss(p.clip_t0)}` → `{hhmmss(p.clip_t1)}`  "
                 f"({p.duration:.1f}s, {p.category})")
        if p.style_target:
            L.append(f"- **Cut as:** {p.style_target}-style (your reference style)")
        if p.channels:
            L.append(f"- **Channels:** {', '.join(p.channels)}")
        if p.punchline_t is not None:
            tail = p.clip_t1 - p.punchline_t
            note = ("clip ends just after" if tail <= 4.0
                    else "clip runs on through the follow-up")
            L.append(f"- **Punchline at:** `{hhmmss(p.punchline_t)}`  ({note})")
        L.append(f"- **Why it works:** {p.why}")
        if p.transcript_excerpt:
            L.append(f"- **Said:** _{p.transcript_excerpt}_")
        for cap in p.captions:
            L.append(f"  - caption @ `{hhmmss(cap['t'])}`: “{cap.get('text','')}”")
        for z in p.zooms:
            L.append(f"  - zoom @ `{hhmmss(z['t'])}` for {z.get('duration', 1.0):.1f}s")
        for s in p.sfx:
            L.append(f"  - SFX @ `{hhmmss(s['t'])}`: {s.get('kind','')}")
        for ins in p.callback_inserts:
            L.append(f"  - callback insert from `{hhmmss(ins['ref_t0'])}`–"
                     f"`{hhmmss(ins['ref_t1'])}` — {ins.get('note','')}")
        for ref in p.lore_refs:
            L.append(f"  - 🧠 running gag (channel lore): {ref}")
        L.append("")
    L.extend(_channel_plans(plan))
    return "\n".join(L)


def _channel_plans(plan):
    """Per-channel sections: which clips go where, with a Shorts length check
    and the pointer to chapters.txt for the uncut upload."""
    tagged = [p for p in plan if p.channels]
    if not tagged:
        return []
    names = []
    for p in tagged:
        for c in p.channels:
            if c not in names:
                names.append(c)
    L = ["---", "", "## 📺 Channel plans", ""]
    for name in names:
        clips = [p for p in plan if name in p.channels]
        total = sum(p.duration for p in clips)
        unit = "clip" if len(clips) == 1 else "clips"
        L.append(f"### {name}  ·  {len(clips)} {unit}  ·  {total:.0f}s total")
        for p in clips:
            # over-60s note on any short-form-named channel, incl. common
            # renames (the user's channels are config-driven)
            shortish = any(k in name for k in ("short", "kurz", "tiktok", "reel"))
            warn = "  ⚠️ over 60s" if shortish and p.duration > 60 else ""
            L.append(f"- {p.rank}. {p.title}  ({p.duration:.1f}s{warn})")
        L.append("")
    L.append("Uncut upload: paste `chapters.txt` into the video description — "
             "instant chapter markers for the best moments.")
    L.append("")
    return L


def _chapters(plan):
    """YouTube chapter list: ascending, starting at 00:00, MM:SS granularity.
    A clip starting in the first second becomes the 00:00 chapter itself
    (no 'Intro' placeholder stealing its title); colliding start seconds are
    bumped forward instead of silently dropping a title."""
    ordered = sorted(plan, key=lambda p: p.clip_t0)
    rows = []
    seen = set()
    if not ordered or int(max(0, ordered[0].clip_t0)) > 0:
        rows.append("00:00 Intro")
        seen.add(0)
    for p in ordered:
        t = max(0, int(p.clip_t0))
        while t in seen:
            t += 1
        seen.add(t)
        h, rest = divmod(t, 3600)
        m, s = divmod(rest, 60)
        ts = f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        rows.append(f"{ts} {p.title}")
    return "\n".join(rows) + "\n"


def _csv(plan):
    rows = ["rank,category,title,start_s,end_s,duration_s,punchline_s,score,style,channels"]
    for p in plan:
        title = '"' + (p.title or "").replace('"', "'") + '"'
        rows.append(f"{p.rank},{p.category},{title},{p.clip_t0},{p.clip_t1},"
                    f"{p.duration},{p.punchline_t if p.punchline_t is not None else ''},"
                    f"{p.final_score},{p.style_target or ''},"
                    f"{'+'.join(p.channels)}")
    return "\n".join(rows) + "\n"
