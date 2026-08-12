"""Configuration with sane AMD-friendly defaults. Loaded from config.toml
if present (Python 3.11 tomllib), else these defaults; CLI flags override."""
from dataclasses import dataclass, field, replace
from pathlib import Path


@dataclass
class Config:
    # --- transcription (AMD: CPU by default, no CUDA) ---
    whisper_model: str = "small"          # tiny|base|small|medium ; small = good speed/quality
    whisper_device: str = "cpu"           # cpu (safe on AMD) | cuda (NVIDIA only)
    whisper_compute_type: str = "int8"    # int8 = fast on CPU
    whisper_language: str = "auto"        # auto | de | en
    whisper_vad: bool = True              # skip silence -> much faster

    # --- reaction detection ---
    reaction_frame_ms: int = 50
    reaction_min_gap_s: float = 2.0       # merge peaks closer than this
    reaction_prominence: float = 0.55     # 0..1 threshold over local baseline
    reaction_baseline_window_s: float = 20.0

    # --- ranking ---
    w_signal: float = 0.45
    w_semantic: float = 0.55
    reaction_cooccurrence_window_s: float = 8.0
    reaction_cooccurrence_boost: float = 1.5
    cluster_merge_gap_s: float = 10.0
    top_k: int = 12
    top_per_10min: int = 4

    # --- cut rules (punchline-aware) ---
    clip_min_s: float = 8.0
    clip_max_s: float = 45.0
    default_preroll_s: float = 4.0
    default_postroll_s: float = 3.0
    funny_setup_preroll_s: float = 6.0    # comedy needs its setup
    punchline_decay_s: float = 2.5        # end a beat after its punchline
    reaction_preroll_s: float = 2.0
    reaction_postroll_s: float = 4.0

    # --- editorial LLM (the creative brain) ---
    use_llm: bool = True
    llm_cmd: list = field(default_factory=lambda: ["claude", "-p"])
    llm_timeout_s: int = 240
    llm_max_moment_calls: int = 40
    discover_no_event_windows: int = 8    # pure comedy/talk moments with no game event

    # --- rendering (AMD: AMF or CPU x264, no NVENC) ---
    encoder: str = "auto"                 # auto|amf|x264 ; auto=amf if available else x264
    render_crf: int = 20                  # x264 quality
    render_vertical: bool = False         # also emit a 9:16 crop

    @classmethod
    def load(cls, root):
        cfg = cls()
        p = Path(root) / "config.toml"
        if not p.exists():
            return cfg
        try:
            import tomllib
            data = tomllib.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return cfg
        flat = {}
        for section in data.values():
            if isinstance(section, dict):
                flat.update(section)
        flat.update({k: v for k, v in data.items() if not isinstance(v, dict)})
        known = {f for f in cls().__dataclass_fields__}
        return replace(cfg, **{k: v for k, v in flat.items() if k in known})
