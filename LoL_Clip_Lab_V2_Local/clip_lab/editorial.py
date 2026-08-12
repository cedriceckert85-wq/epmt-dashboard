"""The editorial brain — the whole point of this tool.

Given the session timeline (transcript + reactions + optional game events),
it asks the LLM to do what statistics can't: find the FUNNY / hype / callback
moments (including pure-talk moments with no game event), locate the
PUNCHLINE, and suggest captions / zooms / SFX with a short reason.

Two passes:
  1. session pass  -> narrative arcs, running gags, callback pairs
  2. moment pass   -> per-candidate editorial refinement + discovered windows

Everything degrades gracefully: no LLM, bad JSON, or a timeout just leaves the
deterministic signal candidates untouched (editorial_source stays 'signal').
"""
import json

from .models import Candidate

SESSION_PROMPT = """You are an expert short-form video editor for League of Legends
streamers. Read this timestamped session log (speech + audio reactions + optional
game events) and identify the EDITORIAL STORY a human editor would use.

Return ONLY JSON:
{{"running_gags": ["..."],
  "callbacks": [{{"setup_t": <seconds>, "payoff_t": <seconds>, "what": "..."}}],
  "arcs": ["short description of an emotional/narrative arc"],
  "notes": "anything an editor should know"}}

SESSION LOG:
{log}
"""

MOMENT_PROMPT = """You are an expert short-form editor. For each candidate window
below, decide if it is worth clipping and how to cut it. You MAY also add up to
{discover} NEW windows that have NO game event but are funny/interesting talk
moments you spot in the log.

Return ONLY JSON: a list of objects, each:
{{"t0": <s>, "t1": <s>, "category": "funny|hype|clutch|fail|callback|wholesome",
  "semantic_score": <0..10>, "punchline_t": <s or null>,
  "title": "catchy 3-7 word title",
  "why": "one sentence: why it lands",
  "callback_refs": [<earlier seconds>],
  "captions": [{{"t": <s>, "text": "..."}}],
  "zooms": [{{"t": <s>, "duration": <s>}}],
  "sfx": [{{"t": <s>, "kind": "airhorn|vine_boom|bruh|ding|silence"}}]}}
Only include a moment if it is actually good. Timestamps must be within the log.

SESSION CONTEXT: {context}

CANDIDATE WINDOWS:
{cands}

RELEVANT LOG:
{log}
"""


def _clip_score(v, lo, hi):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return lo


def run_editorial(cands, timeline_doc, llm, cfg, *, log=lambda *a: None):
    """Refine candidates in place and return (candidates, source, context).
    source is 'llm' if the LLM contributed, else 'signal'."""
    if not (cfg.use_llm and llm and llm.available()):
        return cands, "signal", {}

    # 1) session pass
    context = llm.ask_json(SESSION_PROMPT.format(log=_truncate(timeline_doc, 24000)))
    if not isinstance(context, dict):
        context = {}
        log("editorial: session pass returned no usable JSON — continuing")

    # 2) moment pass (batched)
    cand_json = json.dumps([{"t0": c.t0, "t1": c.t1,
                             "signals": c.reasons[:6]} for c in cands[: cfg.llm_max_moment_calls]],
                           ensure_ascii=False)
    moments = llm.ask_json(MOMENT_PROMPT.format(
        discover=cfg.discover_no_event_windows,
        context=json.dumps(context, ensure_ascii=False)[:4000],
        cands=cand_json,
        log=_truncate(timeline_doc, 24000)))
    if not isinstance(moments, list):
        log("editorial: moment pass returned no usable JSON — signal-only ranking")
        return cands, "signal", context

    refined = _apply_moments(cands, moments, cfg)
    return refined, "llm", context


def _apply_moments(cands, moments, cfg):
    """Match LLM moments back to candidates by time overlap; unmatched LLM
    moments (with no game event) become discovered candidates."""
    used = set()
    out = list(cands)
    for m in moments:
        if not isinstance(m, dict):
            continue
        t0 = _num(m.get("t0"))
        t1 = _num(m.get("t1"))
        if t0 is None or t1 is None or t1 < t0:
            continue
        target = _best_overlap(cands, t0, t1, used)
        sem = _clip_score(m.get("semantic_score", 0), 0, 10)
        fields = dict(
            category=str(m.get("category", "moment")),
            semantic_score=sem,
            punchline_t=_num(m.get("punchline_t")),
            title=(m.get("title") or None),
            why=(m.get("why") or None),
            callback_refs=[x for x in (_num(r) for r in m.get("callback_refs", [])) if x is not None],
            caption_suggestions=_clean_overlays(m.get("captions")),
            zoom_suggestions=_clean_overlays(m.get("zooms")),
            sfx_suggestions=_clean_overlays(m.get("sfx")),
            editorial_source="llm",
        )
        if target is not None:
            used.add(id(target))
            for k, v in fields.items():
                setattr(target, k, v)
        else:
            # discovered no-event window
            c = Candidate(t0=round(t0, 3), t1=round(t1, 3), signal_score=0.0,
                          reasons=["llm-discovered"])
            for k, v in fields.items():
                setattr(c, k, v)
            out.append(c)
    return out


def _best_overlap(cands, t0, t1, used):
    """Pick the unused candidate that best overlaps the LLM window [t0, t1].

    Candidate windows built from a single game event are zero-width (t0==t1),
    so a strict `overlap > 0` test would never match them and every refined
    moment would wrongly become a 'discovered' duplicate. We therefore accept
    a touching/containing match (overlap >= 0) and only fall through to
    'discovered' when the window genuinely misses every candidate."""
    best, best_ov = None, None
    for c in cands:
        if id(c) in used:
            continue
        ov = min(c.t1, t1) - max(c.t0, t0)
        if best_ov is None or ov > best_ov:
            best, best_ov = c, ov
    if best is not None and best_ov is not None and best_ov >= 0:
        return best
    return None


def _clean_overlays(items):
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        t = _num(it.get("t"))
        if t is None:
            continue
        d = {"t": round(t, 3)}
        d.update({k: v for k, v in it.items() if k != "t"})
        out.append(d)
    return out


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _truncate(s, n):
    return s if len(s) <= n else s[:n] + "\n…[truncated]"
