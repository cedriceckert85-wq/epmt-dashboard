"""Merge transcript + reactions + optional game events into a single, LLM- and
human-readable session timeline, and into candidate windows for ranking."""
from .models import Candidate


def transcript_excerpt(segments, t0, t1, max_chars=600):
    parts = []
    for s in segments:
        if s.t1 < t0 or s.t0 > t1:
            continue
        parts.append(s.text.strip())
    text = " ".join(p for p in parts if p)
    if len(text) <= max_chars:
        return text
    # keep head AND tail: the punchline lives at the END of a clip, and a
    # head-only cut would drop exactly the line the clip exists for
    half = max_chars // 2
    return text[:half] + " … " + text[-half:]


def build_timeline_doc(segments, reactions, events, *, chunk_s=None):
    """A compact, timestamped text document of the whole session for the LLM
    session pass. Lines are sorted by time and tagged by source."""
    rows = []
    for s in segments:
        if s.text.strip():
            rows.append((s.t0, f"[{_ts(s.t0)}] SPEECH: {s.text.strip()}"))
    for r in reactions:
        rows.append((r.t, f"[{_ts(r.t)}] REACTION (intensity {r.intensity:.2f})"))
    for e in events:
        rows.append((e.t, f"[{_ts(e.t)}] GAME: {e.kind}"
                          + (f" {e.detail}" if e.detail else "")))
    rows.sort(key=lambda x: x[0])
    return "\n".join(r[1] for r in rows)


def _ts(t):
    m = int(t // 60)
    s = t % 60
    return f"{m}:{s:05.2f}"


def signal_candidates(reactions, events, cfg):
    """Deterministic candidate windows from reactions + game events, merged
    into clusters. This is the safety net that always produces something even
    without the LLM."""
    points = []
    for r in reactions:
        points.append((r.t, 1.0 + 2.0 * r.intensity, f"reaction@{_ts(r.t)}"))
    for e in events:
        w = e.weight if e.weight else _default_event_weight(e.kind)
        points.append((e.t, w, f"{e.kind}@{_ts(e.t)}"))
        # reaction co-occurrence boost
        for r in reactions:
            if abs(r.t - e.t) <= cfg.reaction_cooccurrence_window_s:
                points[-1] = (e.t, w * cfg.reaction_cooccurrence_boost,
                              points[-1][2] + "+reaction")
                break
    if not points:
        return []
    points.sort(key=lambda x: x[0])

    # cluster points within cluster_merge_gap_s
    clusters = [[points[0]]]
    for p in points[1:]:
        if p[0] - clusters[-1][-1][0] <= cfg.cluster_merge_gap_s:
            clusters[-1].append(p)
        else:
            clusters.append([p])

    cands = []
    for cl in clusters:
        t0 = min(p[0] for p in cl)
        t1 = max(p[0] for p in cl)
        score = sum(p[1] for p in cl)
        reasons = [p[2] for p in cl]
        cands.append(Candidate(t0=round(t0, 3), t1=round(t1, 3),
                               signal_score=round(score, 3), reasons=reasons))
    return cands


def _default_event_weight(kind):
    table = {
        "penta": 10, "quadra": 7, "triple": 4, "double": 2, "multikill": 4,
        "ace": 8, "shutdown": 3, "first_blood": 3, "firstblood": 3,
        "baron": 4, "elder": 4, "dragon": 3, "objective_steal": 6, "steal": 6,
        "kill": 1.5, "death": -1, "tower": 1.5,
    }
    return float(table.get(str(kind).lower(), 1.0))
