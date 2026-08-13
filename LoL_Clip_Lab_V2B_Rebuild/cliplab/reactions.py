"""Reaktionserkennung: pure numpy, deterministisch.

Findet Stellen, an denen die Streamer LAUT werden (Lachen/Schreien), ueber
Kurzzeit-Energie relativ zur lokalen Baseline (robuste Statistik:
Median + MAD ueber Bloecke, nur "aktive" Frames).

Pflicht-Invarianten:
- leises/konstantes Audio (gemuteter Mic, Netzbrummen) erzeugt KEINE
  Reaktionen: absoluter Energie-Boden (~-50 dBFS) UND Schutz gegen
  kollabierende Streuung (MAD-Floor)
- echte laute Ausbrueche (+20 dB ueber Baseline) werden mit Defaults
  auf +-2s gefunden
- leerer Input crasht nicht; Intensitaet normiert 0..1; nahe Peaks gemerged
"""

from __future__ import annotations

from dataclasses import dataclass

FRAME_S = 0.10  # Fensterlaenge
HOP_S = 0.05  # Schrittweite
SIGMA_FLOOR_DB = 2.0  # Schutz gegen kollabierende Streuung
Z_MIN = 2.5  # robuster z-Score muss zusaetzlich reissen
INTENSITY_FULL_DB = 25.0  # Excess, der Intensitaet 1.0 bedeutet


@dataclass
class Reaction:
    t: float  # Peak-Zeitpunkt
    t0: float  # Regionsanfang
    t1: float  # Regionsende
    intensity: float  # 0..1

    def to_dict(self) -> dict:
        return {
            "t": round(self.t, 2),
            "t0": round(self.t0, 2),
            "t1": round(self.t1, 2),
            "intensity": round(self.intensity, 3),
        }


def _frame_dbfs(samples, sr: int):
    """RMS-Energie pro Frame in dBFS + Frame-Mittenzeiten."""
    import numpy as np

    win = max(1, int(round(FRAME_S * sr)))
    hop = max(1, int(round(HOP_S * sr)))
    n = len(samples)
    if n < win:
        win = n
        hop = max(1, n)
    n_frames = 1 + max(0, (n - win) // hop)
    idx = np.arange(n_frames) * hop
    # Quadratsummen ueber Praefixsummen -> O(n), deterministisch
    sq = np.concatenate(([0.0], np.cumsum(samples.astype(np.float64) ** 2)))
    sums = sq[np.minimum(idx + win, n)] - sq[idx]
    counts = np.minimum(idx + win, n) - idx
    rms = np.sqrt(sums / np.maximum(counts, 1))
    db = 20.0 * np.log10(rms + 1e-10)
    times = (idx + win / 2.0) / sr
    return db, times


def detect_reactions(
    samples,
    sr: int = 16000,
    threshold_db: float = 8.0,
    floor_dbfs: float = -50.0,
    merge_gap_s: float = 2.0,
    baseline_window_s: float = 30.0,
) -> list[Reaction]:
    """Reaktionen im Audio finden. Leerer/kaputter Input -> []."""
    import numpy as np  # lazy — Rest des Tools laeuft auch ohne numpy

    if samples is None:
        return []
    samples = np.asarray(samples)
    if samples.size == 0 or sr <= 0:
        return []
    if samples.ndim > 1:
        samples = samples.mean(axis=-1)
    if np.issubdtype(samples.dtype, np.integer):
        samples = samples.astype(np.float64) / max(1, np.iinfo(samples.dtype).max)
    else:
        samples = samples.astype(np.float64)
    samples = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0)

    db, times = _frame_dbfs(samples, sr)
    if db.size == 0:
        return []

    active = db >= floor_dbfs
    if not np.any(active):
        return []  # komplett leise (gemuteter Mic) -> nichts

    # Baseline/Streuung blockweise ueber AKTIVE Frames (robust: Median/MAD)
    block_frames = max(1, int(round(baseline_window_s / HOP_S)))
    n_frames = db.size
    n_blocks = max(1, (n_frames + block_frames - 1) // block_frames)
    global_active = db[active]
    global_med = float(np.median(global_active))
    centers = np.empty(n_blocks)
    meds = np.empty(n_blocks)
    mads = np.empty(n_blocks)
    for b in range(n_blocks):
        lo = b * block_frames
        hi = min(n_frames, lo + block_frames)
        centers[b] = times[lo : hi].mean() if hi > lo else times[min(lo, n_frames - 1)]
        chunk = db[lo:hi]
        chunk_active = chunk[chunk >= floor_dbfs]
        if chunk_active.size == 0:
            meds[b] = global_med
            mads[b] = SIGMA_FLOOR_DB
            continue
        m = float(np.median(chunk_active))
        meds[b] = m
        mads[b] = float(np.median(np.abs(chunk_active - m)))
    baseline = np.interp(times, centers, meds)
    sigma = np.maximum(np.interp(times, centers, mads) * 1.4826, SIGMA_FLOOR_DB)

    excess = db - baseline
    z = excess / sigma
    peak = (excess >= threshold_db) & (z >= Z_MIN) & (db >= floor_dbfs)
    if not np.any(peak):
        return []

    # Nahe Peak-Frames zu Regionen mergen
    peak_idx = np.flatnonzero(peak)
    gap_frames = max(1, int(round(merge_gap_s / HOP_S)))
    regions: list[tuple[int, int]] = []
    start = prev = int(peak_idx[0])
    for i in peak_idx[1:]:
        i = int(i)
        if i - prev <= gap_frames:
            prev = i
            continue
        regions.append((start, prev))
        start = prev = i
    regions.append((start, prev))

    out: list[Reaction] = []
    for lo, hi in regions:
        seg = excess[lo : hi + 1]
        k = int(np.argmax(seg)) + lo
        intensity = float(np.clip(excess[k] / INTENSITY_FULL_DB, 0.0, 1.0))
        out.append(
            Reaction(
                t=float(times[k]),
                t0=float(times[lo]),
                t1=float(times[hi]),
                intensity=intensity,
            )
        )
    return out
