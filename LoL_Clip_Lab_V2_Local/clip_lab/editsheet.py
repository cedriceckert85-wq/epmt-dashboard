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
    return out_dir


def _markdown(plan, vod_name, meta):
    L = [f"# Edit Sheet — {vod_name}", ""]
    L.append(f"- Source duration: {hhmmss(meta.get('duration', 0))}")
    L.append(f"- Editorial brain: **{meta.get('editorial', 'signal-only')}**")
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
        if p.punchline_t is not None:
            L.append(f"- **Punchline at:** `{hhmmss(p.punchline_t)}`  "
                     f"(clip ends shortly after)")
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
        L.append("")
    return "\n".join(L)


def _csv(plan):
    rows = ["rank,category,title,start_s,end_s,duration_s,punchline_s,score"]
    for p in plan:
        title = '"' + (p.title or "").replace('"', "'") + '"'
        rows.append(f"{p.rank},{p.category},{title},{p.clip_t0},{p.clip_t1},"
                    f"{p.duration},{p.punchline_t if p.punchline_t is not None else ''},"
                    f"{p.final_score}")
    return "\n".join(rows) + "\n"
