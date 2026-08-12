"""Channel memory — the tool's long-term brain ACROSS sessions.

The editorial pass understands running gags WITHIN one VOD. This module makes
them persist: a small JSON file (default: channel_memory.json next to the tool)
accumulates running gags (with times_seen counters), catchphrases, lore and
per-session summaries over every VOD you analyze.

Before a run the memory is injected into the editorial prompts, so the LLM
recognizes when a gag from a previous stream reappears (and can tag the clip
with a lore reference). After a run the memory is updated: an LLM consolidation
call merges today's findings in (bumping counters instead of duplicating);
without an LLM a deterministic mechanical merge does the same on exact matches.

Everything degrades gracefully: a missing or corrupt file is a fresh brain,
a bad LLM reply falls back to the mechanical merge, and nothing here ever
raises into the pipeline. Delete the file to make the tool forget.
"""
import json
from datetime import date
from pathlib import Path

from .util import read_json, write_json

MEMORY_VERSION = 1


def empty_memory():
    return {"version": MEMORY_VERSION, "sessions_analyzed": 0,
            "gags": [], "catchphrases": [], "lore": [], "sessions": []}


def load_memory(path):
    """Load the brain; missing/corrupt/odd-typed files yield a fresh one."""
    p = Path(path)
    if not p.exists():
        return empty_memory()
    try:
        raw = read_json(p)
    except (OSError, ValueError):
        return empty_memory()
    if not isinstance(raw, dict):
        return empty_memory()
    mem = empty_memory()
    for k in mem:
        if k in raw and isinstance(raw[k], type(mem[k])):
            mem[k] = raw[k]
    return mem


def save_memory(path, mem):
    write_json(path, mem)


def memory_brief(mem, max_chars=4000):
    """Compact, prompt-ready text of what the channel brain knows. Empty
    string when there is nothing worth injecting."""
    if not (mem.get("gags") or mem.get("catchphrases")
            or mem.get("lore") or mem.get("sessions")):
        return ""
    L = []
    if mem.get("gags"):
        L.append("Known running gags (times seen, most established first):")
        for g in mem["gags"]:
            line = f'- "{g.get("name", "?")}" ({g.get("times_seen", 1)}x'
            if g.get("last_seen"):
                line += f', last: {g["last_seen"]}'
            line += ")"
            if g.get("description"):
                line += f' — {g["description"]}'
            L.append(line)
    if mem.get("catchphrases"):
        L.append("Catchphrases: " + "; ".join(str(c) for c in mem["catchphrases"]))
    if mem.get("lore"):
        L.append("Channel lore: " + "; ".join(str(x) for x in mem["lore"]))
    for s in mem.get("sessions", [])[-3:]:
        L.append(f'Previous session ({s.get("vod", "?")}): {s.get("summary", "")}')
    text = "\n".join(L)
    return text[:max_chars]


MEMORY_PROMPT = """You are the LONG-TERM MEMORY of a League of Legends streamer's
clip channel. Merge TODAY'S session findings into the channel memory so a future
editor recognizes running gags, catchphrases and lore when they reappear.

Rules:
- If a known gag reappeared today, bump its times_seen and update last_seen —
  do NOT duplicate it (match by meaning, not exact wording).
- Keep entries short. Keep at most {max_gags} gags and {max_sessions} session
  summaries; when trimming, drop the least-seen / oldest first, but never drop
  a gag with times_seen >= 2 while a times_seen == 1 gag remains.
- Add one compact summary line for today's session.

Return ONLY JSON, exactly this shape:
{{"version": 1, "sessions_analyzed": <int>,
  "gags": [{{"name": "...", "description": "...", "times_seen": <int>,
             "first_seen": "...", "last_seen": "..."}}],
  "catchphrases": ["..."],
  "lore": ["..."],
  "sessions": [{{"vod": "...", "date": "...", "summary": "..."}}]}}

CURRENT MEMORY:
{memory}

TODAY'S SESSION (vod: {vod}, date: {date}):
{session}
"""


def update_memory(mem, session_context, vod_name, llm, cfg, *,
                  log=lambda *a: None, today=None):
    """Return the updated brain. LLM consolidation when available (it can merge
    'the Q gag' with 'he never hits his Qs' — meaning, not wording); otherwise
    a deterministic mechanical merge on exact names. Never raises."""
    today = today or date.today().isoformat()
    mechanical = _mechanical_merge(mem, session_context, vod_name, cfg, today)
    if not (llm and getattr(cfg, "use_llm", True) and llm.available()):
        return mechanical

    payload = {k: session_context.get(k) for k in
               ("running_gags", "callbacks", "arcs", "notes")
               if session_context.get(k)}
    res = llm.ask_json(MEMORY_PROMPT.format(
        max_gags=cfg.memory_max_gags, max_sessions=cfg.memory_max_sessions,
        memory=json.dumps(mem, ensure_ascii=False)[:12000],
        vod=str(vod_name), date=today,
        session=json.dumps(payload, ensure_ascii=False)[:8000]))
    if not (isinstance(res, dict) and isinstance(res.get("gags"), list)):
        log("memory: LLM consolidation returned no usable JSON — mechanical merge")
        return mechanical
    return _sanitize(res, mechanical, cfg)


def _sanitize(res, fallback, cfg):
    """Never trust LLM output shape: clamp types, lengths and counts."""
    out = empty_memory()
    try:
        out["sessions_analyzed"] = max(int(res.get("sessions_analyzed", 0)),
                                       fallback["sessions_analyzed"])
    except (TypeError, ValueError):
        out["sessions_analyzed"] = fallback["sessions_analyzed"]
    gags = []
    for g in res["gags"][: cfg.memory_max_gags]:
        if not isinstance(g, dict):
            continue
        name = str(g.get("name", "")).strip()[:120]
        if not name:
            continue
        try:
            seen = max(1, int(g.get("times_seen", 1)))
        except (TypeError, ValueError):
            seen = 1
        gags.append({"name": name,
                     "description": str(g.get("description", ""))[:200],
                     "times_seen": seen,
                     "first_seen": str(g.get("first_seen", ""))[:120],
                     "last_seen": str(g.get("last_seen", ""))[:120]})
    out["gags"] = gags
    out["catchphrases"] = [str(x)[:120] for x in res.get("catchphrases", [])
                           if isinstance(x, str) and x.strip()][:30]
    out["lore"] = [str(x)[:200] for x in res.get("lore", [])
                   if isinstance(x, str) and x.strip()][:30]
    sessions = []
    for s in res.get("sessions", []):
        if isinstance(s, dict):
            sessions.append({"vod": str(s.get("vod", ""))[:120],
                             "date": str(s.get("date", ""))[:40],
                             "summary": str(s.get("summary", ""))[:300]})
    out["sessions"] = sessions[-cfg.memory_max_sessions:]
    return out


def _mechanical_merge(mem, ctx, vod, cfg, today):
    """Deterministic fallback: exact-name (casefold) gag matching, counter
    bumps, session summary from the first arc / the notes."""
    out = json.loads(json.dumps(mem))  # deep copy
    out["sessions_analyzed"] = int(out.get("sessions_analyzed", 0)) + 1
    known = {str(g.get("name", "")).casefold(): g for g in out["gags"]}
    for gag in (ctx or {}).get("running_gags") or []:
        if not isinstance(gag, str) or not gag.strip():
            continue
        name = gag.strip()[:120]
        key = name.casefold()
        if key in known:
            known[key]["times_seen"] = int(known[key].get("times_seen", 1)) + 1
            known[key]["last_seen"] = str(vod)
        else:
            g = {"name": name, "description": "", "times_seen": 1,
                 "first_seen": str(vod), "last_seen": str(vod)}
            out["gags"].append(g)
            known[key] = g
    out["gags"].sort(key=lambda g: -int(g.get("times_seen", 1)))
    out["gags"] = out["gags"][: cfg.memory_max_gags]

    arcs = (ctx or {}).get("arcs") or []
    notes = (ctx or {}).get("notes") or ""
    summary = str(arcs[0])[:300] if arcs else str(notes)[:300]
    out["sessions"].append({"vod": str(vod), "date": today, "summary": summary})
    out["sessions"] = out["sessions"][-cfg.memory_max_sessions:]
    return out
