"""Merge the deterministic signal score and the LLM semantic score into a
final ranking. Pure functions — fully unit-tested and deterministic given the
same inputs (the LLM output is an input here, produced upstream)."""


def _normalize(cands, attr):
    vals = [getattr(c, attr) for c in cands]
    hi = max(vals) if vals else 0.0
    if hi <= 0:
        return {id(c): 0.0 for c in cands}
    return {id(c): getattr(c, attr) / hi for c in cands}


def rank_candidates(cands, cfg, top_k=None):
    """Assign final_score = w_signal*norm(signal) + w_semantic*norm(semantic)
    and return the selected top set (global top_k, with a per-10-minute cap so
    one busy stretch cannot crowd everything else out). Stable, deterministic.
    top_k overrides cfg.top_k (the pipeline scales it with session length)."""
    if not cands:
        return []
    limit = top_k if top_k is not None else cfg.top_k
    nsig = _normalize(cands, "signal_score")
    nsem = _normalize(cands, "semantic_score")
    for c in cands:
        c.final_score = round(cfg.w_signal * nsig[id(c)]
                              + cfg.w_semantic * nsem[id(c)], 4)

    # per-10-min cap
    ordered = sorted(cands, key=lambda c: (-c.final_score, c.t0))
    per_bucket = {}
    kept = []
    for c in ordered:
        bucket = int(c.t0 // 600)
        if per_bucket.get(bucket, 0) >= cfg.top_per_10min:
            continue
        per_bucket[bucket] = per_bucket.get(bucket, 0) + 1
        kept.append(c)
        if len(kept) >= limit:
            break
    return sorted(kept, key=lambda c: (-c.final_score, c.t0))
