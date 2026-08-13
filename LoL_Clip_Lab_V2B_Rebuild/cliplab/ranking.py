"""Ranking (F10): final = w_signal*norm(signal) + w_semantic*norm(semantic).

Deterministisch, stabiler Tiebreak, Divisionen gegen Null-Summen
abgesichert. Per-10-Minuten-Cap gegen Crowding; globales top_k skaliert
mit der Session-Dauer (ein 4h-Stream hat mehr als 12 Clips).
"""

from __future__ import annotations

from .config import Config
from .editorial import Moment, dedupe_moments


def compute_top_k(duration_s: float, cfg: Config) -> int:
    hours = max(0.0, duration_s) / 3600.0
    k = int(round(hours * max(0.1, cfg.clips_per_hour)))
    return max(cfg.min_clips, k)


def rank_moments(moments: list[Moment], duration_s: float, cfg: Config) -> list[Moment]:
    """Momente deduplizieren, scoren, cappen. Rueckgabe: Top-Liste mit Raengen."""
    moments = dedupe_moments(list(moments))
    if not moments:
        return []

    w_sum = cfg.w_signal + cfg.w_semantic
    if w_sum <= 0:
        w_sig, w_sem = 0.5, 0.5
    else:
        w_sig, w_sem = cfg.w_signal / w_sum, cfg.w_semantic / w_sum

    max_signal = max((m.signal for m in moments), default=0.0)
    for m in moments:
        norm_sig = (m.signal / max_signal) if max_signal > 0 else 0.0
        norm_sem = max(0.0, min(10.0, m.score)) / 10.0
        m.final = w_sig * norm_sig + w_sem * norm_sem

    # stabiler, deterministischer Tiebreak: final desc, dann t0, dann Titel
    ordered = sorted(moments, key=lambda m: (-m.final, m.t0, m.title, m.t1))

    top_k = compute_top_k(duration_s, cfg)
    cap = max(1, cfg.per_10min_cap)
    bucket_counts: dict[int, int] = {}
    picked: list[Moment] = []
    for m in ordered:
        if len(picked) >= top_k:
            break
        bucket = int(max(0.0, m.t0) // 600)
        if bucket_counts.get(bucket, 0) >= cap:
            continue
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        picked.append(m)

    for i, m in enumerate(picked, start=1):
        m.rank = i
    return picked
