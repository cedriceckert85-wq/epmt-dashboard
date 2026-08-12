"""The editorial brain — the whole point of this tool.

Given the session timeline (transcript + reactions + optional game events),
it asks the LLM to do what statistics can't: find the FUNNY / hype / callback
moments (including pure-talk moments with no game event), locate the
PUNCHLINE, and suggest captions / zooms / SFX with a short reason.

Two passes:
  1. session pass  -> narrative arcs, running gags, callback pairs.
     It reads the WHOLE stream script: a long session is sent in chunks with
     the findings so far carried into each next chunk, then merged — so a gag
     set up in minute 3 and paid off in hour 3 is still connected.
  2. moment pass   -> per-candidate editorial refinement + discovered windows.
     Its log context is focused: full detail around every candidate window,
     plus an even sample of the rest of the session for discovery.

Everything degrades gracefully: no LLM, bad JSON, or a timeout just leaves the
deterministic signal candidates untouched (editorial_source stays 'signal').
"""
import json
import re

from .models import Candidate

SESSION_PROMPT = """You are an expert short-form video editor for League of Legends
streamers. Read this timestamped session log (speech + audio reactions + optional
game events) and identify the EDITORIAL STORY a human editor would use.

Return ONLY JSON:
{{"running_gags": ["..."],
  "callbacks": [{{"setup_t": <seconds>, "payoff_t": <seconds>, "what": "..."}}],
  "arcs": ["short description of an emotional/narrative arc"],
  "notes": "anything an editor should know"}}

{memory}{prior}SESSION LOG{part}:
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
  "lore_refs": ["name of a KNOWN channel gag this moment continues (only if listed in CHANNEL MEMORY)"],
  "captions": [{{"t": <s>, "text": "..."}}],
  "zooms": [{{"t": <s>, "duration": <s>}}],
  "sfx": [{{"t": <s>, "kind": "airhorn|vine_boom|bruh|ding|silence"}}]}}
Only include a moment if it is actually good. Timestamps must be within the log.

{style}{memory}SESSION CONTEXT: {context}

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


def run_editorial(cands, timeline_doc, llm, cfg, *, memory_brief="",
                  style_brief="", llm_b=None, log=lambda *a: None):
    """Refine candidates in place and return (candidates, source, context).
    source is 'llm' if the LLM contributed, else 'signal'. memory_brief is the
    channel brain's summary of PREVIOUS streams (running gags, lore) so the LLM
    recognizes returning gags; style_brief is the STYLE GUIDE learned from the
    user's reference clips (goes into the moment pass, where cutting decisions
    are made)."""
    if not (cfg.use_llm and llm and llm.available()):
        return cands, "signal", {}

    memory_block = ""
    if memory_brief:
        memory_block = ("CHANNEL MEMORY (from PREVIOUS streams — watch for these "
                        "gags/lore returning; tag continuations via lore_refs):\n"
                        + memory_brief + "\n\n")
    style_block = (style_brief + "\n\n") if style_brief else ""

    # 1) session pass — the WHOLE script, chunked + merged if it is long
    context = _session_pass(llm, timeline_doc, cfg, log, memory_block)

    # 2) moment pass (batched). The SAME prompt is reused for the optional
    # second brain, so both judge identical evidence.
    cand_json = json.dumps([{"t0": c.t0, "t1": c.t1,
                             "signals": c.reasons[:6]} for c in cands[: cfg.llm_max_moment_calls]],
                           ensure_ascii=False)
    mprompt = MOMENT_PROMPT.format(
        discover=cfg.discover_no_event_windows,
        style=style_block,
        memory=memory_block,
        context=json.dumps(context, ensure_ascii=False)[:8000],
        cands=cand_json,
        log=_relevant_log(timeline_doc, cands,
                          window_s=cfg.llm_moment_context_s,
                          max_chars=cfg.llm_moment_log_chars))
    moments = llm.ask_json(mprompt)
    if not isinstance(moments, list):
        log("editorial: moment pass returned no usable JSON — signal-only ranking")
        return cands, "signal", context

    refined = _apply_moments(cands, moments, cfg)
    source = "llm"

    # 3) optional second brain (e.g. Codex): reviews the very same clips;
    # agreement is averaged into the score, extra finds are added
    if llm_b is not None and llm_b.available():
        moments_b = llm_b.ask_json(mprompt)
        if isinstance(moments_b, list):
            _blend_second_opinion(refined, moments_b)
            source = "llm+2nd"
            log("editorial: second brain reviewed the clips too — scores blended")
        else:
            log("editorial: second brain gave no usable JSON — primary only")
    return refined, source, context


def _session_pass(llm, timeline_doc, cfg, log, memory_block=""):
    """Send the WHOLE session log through the session prompt. Long sessions go
    in line-aligned chunks; the merged findings so far ride along into each
    next chunk so cross-chunk gags/callbacks can be connected. memory_block
    (channel brain from previous streams) goes into every chunk. Returns the
    merged context dict ({} if nothing usable came back)."""
    chunks = _chunk_lines(timeline_doc, cfg.llm_session_chunk_chars)
    merged = {}
    for idx, chunk in enumerate(chunks):
        part = f" (part {idx + 1} of {len(chunks)})" if len(chunks) > 1 else ""
        prior = ""
        if merged:
            prior = ("FINDINGS FROM EARLIER PARTS OF THIS SESSION "
                     "(extend/merge them with what you find below):\n"
                     + json.dumps(merged, ensure_ascii=False)[:6000] + "\n\n")
        res = llm.ask_json(SESSION_PROMPT.format(memory=memory_block, prior=prior,
                                                 part=part, log=chunk))
        if isinstance(res, dict):
            merged = _merge_context(merged, res)
        else:
            log(f"editorial: session pass{part} returned no usable JSON — continuing")
    if not merged:
        log("editorial: session pass produced no usable context")
    return merged


def _chunk_lines(doc, max_chars):
    """Split the timeline doc into chunks of whole lines, each <= max_chars
    (a single overlong line gets its own chunk rather than being cut)."""
    if len(doc) <= max_chars:
        return [doc]
    chunks, cur, cur_len = [], [], 0
    # split("\n") (not splitlines) so a trailing blank line survives the
    # chunk/rejoin round-trip instead of being silently dropped
    for line in doc.split("\n"):
        add = len(line) + 1
        if cur and cur_len + add > max_chars:
            chunks.append("\n".join(cur))
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += add
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def _merge_context(a, b):
    """Merge two session-pass results: lists extend with dedupe, notes join,
    scalars from the newer result win."""
    out = dict(a)
    for k, v in b.items():
        prev = out.get(k)
        if isinstance(v, list):
            base = prev if isinstance(prev, list) else []
            seen = {_dedupe_key(x) for x in base}
            merged = list(base)
            for x in v:
                kx = _dedupe_key(x)
                if kx not in seen:
                    merged.append(x)
                    seen.add(kx)
            out[k] = merged
        elif k == "notes" and prev and v and v != prev:
            out[k] = f"{prev} | {v}"
        elif v:
            out[k] = v
    return out


def _dedupe_key(x):
    try:
        return json.dumps(x, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(x)


_TS_RE = re.compile(r"^\[(\d+):(\d+(?:\.\d+)?)\]")


def _parse_ts(line):
    """Read the leading [m:ss.ss] timestamp of a timeline line (seconds)."""
    m = _TS_RE.match(line)
    if not m:
        return None
    return int(m.group(1)) * 60 + float(m.group(2))


def _relevant_log(doc, cands, *, window_s, max_chars):
    """Moment-pass log: full detail within window_s of every candidate window,
    then the remaining budget spent on an even sample across the whole session
    (so the LLM can still DISCOVER funny talk moments far from any signal).
    Bounded by max_chars so an hours-long VOD can't blow up the prompt."""
    if len(doc) <= max_chars:
        return doc
    lines = doc.splitlines()
    times = [_parse_ts(ln) for ln in lines]
    windows = [(c.t0 - window_s, c.t1 + window_s) for c in cands]

    keep = set()
    for i, t in enumerate(times):
        if t is None:
            continue
        if any(lo <= t <= hi for lo, hi in windows):
            keep.add(i)

    used = sum(len(lines[i]) + 1 for i in keep)
    if used > max_chars:
        # Even the candidate context is too big. Split the budget FAIRLY per
        # candidate (closest lines to each candidate first) — a uniform stride
        # over all kept lines would let one dense stretch starve a sparse or
        # late candidate out of its only context line.
        assigned = {}
        for i in sorted(keep):
            t = times[i]
            for ci, (lo, hi) in enumerate(windows):
                if lo <= t <= hi:
                    assigned.setdefault(ci, []).append(i)
                    break
        keep = set()
        used = 0
        share = max_chars // max(1, len(assigned))
        for ci, idxs in assigned.items():
            mid = (cands[ci].t0 + cands[ci].t1) / 2.0
            idxs.sort(key=lambda i: abs((times[i] if times[i] is not None else mid) - mid))
            spent = 0
            for i in idxs:
                if i in keep:
                    continue
                add = len(lines[i]) + 1
                if spent + add > share or used + add > max_chars:
                    continue
                keep.add(i)
                spent += add
                used += add
        # rescue: a candidate whose every line is longer than its share still
        # gets its single closest line if the global budget allows
        for ci, idxs in assigned.items():
            if any(i in keep for i in idxs):
                continue
            for i in idxs:  # already sorted closest-first
                add = len(lines[i]) + 1
                if used + add <= max_chars:
                    keep.add(i)
                    used += add
                    break

    rest = [i for i in range(len(lines)) if i not in keep]
    budget = max_chars - used
    if rest and budget > 0:
        avg = sum(len(lines[i]) + 1 for i in rest) / len(rest)
        n_fit = int(budget / max(avg, 1.0))
        if n_fit > 0:
            stride = max(1, -(-len(rest) // n_fit))  # ceil division
            for i in rest[::stride]:
                add = len(lines[i]) + 1
                if add > budget:
                    continue
                keep.add(i)
                budget -= add

    out = "\n".join(lines[i] for i in sorted(keep))
    if not out and doc:
        # pathological case (every line longer than the budget): a truncated
        # slice is still better context than nothing at all
        out = doc[:max_chars]
    # hard safety net in case of wildly uneven line lengths
    if len(out) > max_chars * 1.2:
        out = out[: int(max_chars * 1.2)]
    return out


def _moment_window(m):
    """Validated (t0, t1) of an LLM moment, or None."""
    if not isinstance(m, dict):
        return None
    t0 = _num(m.get("t0"))
    t1 = _num(m.get("t1"))
    if t0 is None or t1 is None or t1 < t0:
        return None
    return t0, t1


def _moment_fields(m):
    """Sanitized editorial fields from one LLM moment dict."""
    return dict(
        category=str(m.get("category", "moment")),
        semantic_score=_clip_score(m.get("semantic_score", 0), 0, 10),
        punchline_t=_num(m.get("punchline_t")),
        title=(m.get("title") or None),
        why=(m.get("why") or None),
        callback_refs=[x for x in (_num(r) for r in (m.get("callback_refs") or []))
                       if x is not None],
        lore_refs=[str(x).strip()[:120] for x in (m.get("lore_refs") or [])
                   if isinstance(x, str) and x.strip()][:5],
        caption_suggestions=_clean_overlays(m.get("captions")),
        zoom_suggestions=_clean_overlays(m.get("zooms")),
        sfx_suggestions=_clean_overlays(m.get("sfx")),
        editorial_source="llm",
    )


def _discovered(t0, t1, fields):
    c = Candidate(t0=round(t0, 3), t1=round(t1, 3), signal_score=0.0,
                  reasons=["llm-discovered"])
    for k, v in fields.items():
        setattr(c, k, v)
    return c


def _apply_moments(cands, moments, cfg):
    """Match LLM moments back to candidates by time overlap; unmatched LLM
    moments (with no game event) become discovered candidates."""
    used = set()
    out = list(cands)
    for m in moments:
        win = _moment_window(m)
        if win is None:
            continue
        t0, t1 = win
        target = _best_overlap(cands, t0, t1, used)
        fields = _moment_fields(m)
        if target is not None:
            used.add(id(target))
            for k, v in fields.items():
                setattr(target, k, v)
        else:
            out.append(_discovered(t0, t1, fields))
    return out


def _blend_second_opinion(cands, moments_b):
    """Fold the second brain's read into the (already refined) candidates:
    - a clip both brains rated -> semantic scores are averaged and the second
      score is noted in the 'why' line;
    - a clip only the second brain liked (or discovered) -> adopted whole.
    Mutates `cands` in place (appends discovered windows)."""
    used = set()
    for m in moments_b or []:
        win = _moment_window(m)
        if win is None:
            continue
        t0, t1 = win
        target = _best_overlap(cands, t0, t1, used)
        sem_b = _clip_score(m.get("semantic_score", 0), 0, 10)
        if target is None:
            cands.append(_discovered(t0, t1, _moment_fields(m)))
            continue
        used.add(id(target))
        if target.editorial_source == "llm" and target.semantic_score > 0:
            target.semantic_score = round((target.semantic_score + sem_b) / 2, 2)
            if target.why:
                target.why = f"{target.why} [2nd opinion: {sem_b:g}/10]"
        else:
            # the primary brain skipped this candidate — adopt the second read
            for k, v in _moment_fields(m).items():
                setattr(target, k, v)


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
