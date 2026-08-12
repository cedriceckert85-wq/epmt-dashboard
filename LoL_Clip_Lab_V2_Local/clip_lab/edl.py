"""Turn ranked candidates into concrete, punchline-aware clip cut points +
an overlay plan (captions / zooms / SFX / callback inserts). Pure functions.

The point of this stage is the 'edit intelligence' the user asked for:
- a funny beat gets enough SETUP lead-in and ends just after its PUNCHLINE,
  not on a stopwatch;
- a clutch/hype beat starts from the action;
- everything is clamped to sane clip lengths and to the VOD bounds;
- caption/zoom/SFX suggestions are clamped into the clip.
"""
from .models import EditPlanItem
from .timeline import transcript_excerpt


def _clip_bounds(c, cfg, duration):
    cat = (c.category or "").lower()
    # base pre/post-roll by category
    if cat == "funny":
        pre = cfg.funny_setup_preroll_s
        post = cfg.default_postroll_s
    elif cat in ("clutch", "hype", "fail"):
        pre = cfg.default_preroll_s
        post = cfg.default_postroll_s
    else:
        pre = cfg.reaction_preroll_s
        post = cfg.reaction_postroll_s

    start = c.t0 - pre
    # punchline-aware end: end shortly AFTER the punchline, not by stopwatch
    if c.punchline_t is not None:
        end = max(c.t1, c.punchline_t + cfg.punchline_decay_s)
    else:
        end = c.t1 + post

    # Desired length, clamped to the sane clip range. We then place a window of
    # exactly this length rather than clamping the raw edges — clamping edges to
    # the media bounds could push one edge in without re-extending the other and
    # silently break the clip_min_s guarantee near t=0 or t=duration (e.g. a
    # pentakill in the last seconds of the VOD would yield a 3s clip).
    target_len = min(cfg.clip_max_s, max(cfg.clip_min_s, end - start))
    has_media = bool(duration and duration > 0)
    if has_media:
        target_len = min(target_len, float(duration))  # can't exceed the whole VOD

    # keep the end anchor (punchline / natural end), then slide the fixed-length
    # window to fit inside [0, duration] without shrinking it
    start = end - target_len
    if has_media and end > duration:
        end = float(duration)
        start = end - target_len
    if start < 0:
        start = 0.0
        end = start + target_len

    return round(start, 3), round(end, 3)


def _clamp_overlays(items, t0, t1):
    out = []
    for it in items or []:
        t = it.get("t")
        if t is None:
            continue
        if t < t0 or t > t1:
            continue
        out.append(it)
    return out


def build_edit_plan(ranked, segments, cfg, duration):
    """Return list[EditPlanItem], ordered by rank. Overlapping clips are
    merged so two adjacent candidates don't produce a double clip."""
    plan = []
    for i, c in enumerate(ranked, 1):
        t0, t1 = _clip_bounds(c, cfg, duration)
        # callback inserts: reference an earlier moment, clamped to available media
        inserts = []
        for ref in (c.callback_refs or []):
            if 0 <= ref < t0:  # only earlier, retained-elsewhere material
                inserts.append({"ref_t0": round(max(0.0, ref - 2.0), 3),
                                "ref_t1": round(ref + 2.0, 3),
                                "note": "callback to earlier moment"})
        plan.append(EditPlanItem(
            rank=i, clip_t0=t0, clip_t1=t1,
            category=c.category or "moment",
            title=c.title or f"Moment @ {int(c.t0//60)}:{int(c.t0%60):02d}",
            why=c.why or "; ".join(c.reasons[:3]),
            punchline_t=c.punchline_t,
            final_score=c.final_score,
            captions=_clamp_overlays(c.caption_suggestions, t0, t1),
            zooms=_clamp_overlays(c.zoom_suggestions, t0, t1),
            sfx=_clamp_overlays(c.sfx_suggestions, t0, t1),
            callback_inserts=inserts,
            lore_refs=list(c.lore_refs or []),
            transcript_excerpt=transcript_excerpt(segments, t0, t1)))

    return _merge_overlaps(plan)


def _merge_overlaps(plan):
    """If two clips overlap in time, drop the lower-ranked one (its content is
    already covered). Ranks are re-numbered afterwards."""
    plan_sorted = sorted(plan, key=lambda p: p.final_score, reverse=True)
    kept = []
    for p in plan_sorted:
        if any(not (p.clip_t1 <= k.clip_t0 or p.clip_t0 >= k.clip_t1) for k in kept):
            continue
        kept.append(p)
    kept.sort(key=lambda p: p.final_score, reverse=True)
    for i, p in enumerate(kept, 1):
        p.rank = i
    return kept
