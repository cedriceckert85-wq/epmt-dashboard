"""Detect reaction moments from mono audio: laughter / shouting / excitement
show up as short-time energy spikes that stand out from the local baseline.

Pure numpy — the audio is passed in as a float32 array in [-1, 1]. The only
non-stdlib dep is numpy; the peak logic is unit-tested with synthetic signals.
"""
from .models import ReactionEvent


def _rms_frames(samples, sr, frame_ms):
    import numpy as np
    frame = max(1, int(sr * frame_ms / 1000))
    n = len(samples) // frame
    if n == 0:
        return np.zeros(0, dtype="float32"), frame
    trimmed = samples[: n * frame].reshape(n, frame).astype("float64")
    rms = np.sqrt(np.mean(trimmed * trimmed, axis=1) + 1e-12)
    return rms.astype("float32"), frame


def detect_reactions(samples, sr, *, frame_ms=50, min_gap_s=2.0,
                     prominence=0.55, baseline_window_s=20.0):
    """Return a list[ReactionEvent]. prominence in 0..1 is how far above the
    rolling median (scaled by rolling spread) a frame must rise to count."""
    import numpy as np
    rms, frame = _rms_frames(np.asarray(samples, dtype="float32"), sr, frame_ms)
    if rms.size == 0:
        return []
    hop_s = frame / sr

    # log energy is more perceptual and stabilizes the threshold
    loge = np.log(rms + 1e-6)
    win = max(3, int(baseline_window_s / hop_s))
    # rolling median + MAD via uniform filters (cheap, dependency-free)
    def _moving(a, w, fn):
        pad = w // 2
        ap = np.pad(a, pad, mode="edge")
        return np.array([fn(ap[i:i + w]) for i in range(len(a))])

    # downsample the baseline computation for speed on long VODs
    med = _moving(loge, win, np.median)
    mad = _moving(np.abs(loge - med), win, np.median) + 1e-6
    z = (loge - med) / (1.4826 * mad)          # robust z-score
    # map prominence 0..1 -> z threshold ~ [1.0 .. 4.0]
    z_thresh = 1.0 + 3.0 * float(prominence)

    above = z >= z_thresh
    events = []
    i = 0
    min_gap_frames = int(min_gap_s / hop_s)
    while i < len(above):
        if not above[i]:
            i += 1
            continue
        j = i
        while j < len(above) and above[j]:
            j += 1
        # onset..offset frame span [i, j)
        seg_z = z[i:j]
        peak = i + int(np.argmax(seg_z))
        intensity = float(np.clip((z[peak] - z_thresh) / 4.0 + 0.3, 0.0, 1.0))
        events.append(ReactionEvent(
            t=round(peak * hop_s, 3),
            t0=round(i * hop_s, 3),
            t1=round(j * hop_s, 3),
            intensity=round(intensity, 3)))
        i = j + min_gap_frames

    # merge events closer than min_gap_s (keep the stronger)
    merged = []
    for ev in events:
        if merged and ev.t - merged[-1].t < min_gap_s:
            if ev.intensity > merged[-1].intensity:
                merged[-1] = ev
        else:
            merged.append(ev)
    return merged
