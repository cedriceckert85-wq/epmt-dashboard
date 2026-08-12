"""Optional clip cutting with ffmpeg. AMD box: uses AMF (h264_amf) if the
ffmpeg build supports it, else CPU libx264. NEVER NVENC (that is NVIDIA-only).

Cutting is the secondary output — the edit sheet is the primary deliverable —
so this is best-effort and never required for `analyze`.
"""
import subprocess

from .util import which


def pick_encoder(cfg):
    """Return (video_args, name). auto -> amf if available else x264."""
    want = cfg.encoder
    if want == "auto":
        want = "amf" if _amf_available() else "x264"
    if want == "amf":
        # AMD hardware encoder (Radeon RX 9070 XT). quality-ish VBR.
        return (["-c:v", "h264_amf", "-quality", "quality", "-rc", "cqp",
                 "-qp_i", "20", "-qp_p", "22"], "h264_amf (AMD)")
    return (["-c:v", "libx264", "-preset", "medium", "-crf", str(cfg.render_crf)],
            "libx264 (CPU)")


def _amf_available():
    if not which("ffmpeg"):
        return False
    try:
        p = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "h264_amf" in (p.stdout or "")


def cut_clip(vod_path, out_path, t0, t1, cfg, *, vertical=False):
    if not which("ffmpeg"):
        raise RuntimeError("ffmpeg not found — install it to cut clips (see README)")
    vargs, _ = pick_encoder(cfg)
    dur = max(0.1, float(t1) - float(t0))
    filt = []
    if vertical:
        # simple centered 9:16 crop (subject-follow is out of scope for the test tool)
        filt = ["-vf", "crop=ih*9/16:ih,scale=1080:1920"]
    cmd = (["ffmpeg", "-y", "-ss", f"{float(t0):.3f}", "-i", str(vod_path),
            "-t", f"{dur:.3f}"] + filt + vargs
           + ["-c:a", "aac", "-b:a", "160k", str(out_path)])
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg cut failed: {p.stderr.strip()[-400:]}")
    return out_path
