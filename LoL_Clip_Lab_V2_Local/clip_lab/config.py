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
    # optional SECOND brain (e.g. Codex): reviews every clip too — scores are
    # blended, extra finds added. Empty list = disabled. "{prompt}" in an entry
    # passes the prompt as an argument instead of stdin.
    llm_cmd_b: list = field(default_factory=list)
    llm_timeout_s: int = 240
    llm_max_moment_calls: int = 40
    discover_no_event_windows: int = 8    # pure comedy/talk moments with no game event
    # the session pass reads the WHOLE stream script; longer sessions are sent
    # in chunks of this many characters with the findings carried forward
    llm_session_chunk_chars: int = 150_000
    # moment pass: timeline seconds of log context around each candidate, and
    # the total log budget (rest is an even sample across the session)
    llm_moment_context_s: float = 90.0
    llm_moment_log_chars: int = 60_000

    # --- channel memory (the long-term brain across sessions) ---
    memory_enabled: bool = True
    memory_file: str = "channel_memory.json"  # relative -> next to the tool
    memory_max_gags: int = 40
    memory_max_sessions: int = 20

    # --- target channels (each moment gets tagged with the channels it serves) ---
    channels: list = field(default_factory=lambda: [
        {"name": "insta",
         "note": "vertical 9:16 reel/short, hook in the first 2 seconds, ideally under 60s"},
        {"name": "yt",
         "note": "edited highlight video for the main YouTube channel"},
        {"name": "uncut",
         "note": "full-session upload; the best moments become chapter markers"},
    ])

    # --- style learning from reference videos ---
    style_enabled: bool = True
    style_file: str = "style_profile.json"    # relative -> next to the tool
    references_dir: str = "references"        # drop example clips you LIKE here
    style_probe_s: int = 120                  # seconds sampled per clip for cut-pace
    style_scene_threshold: float = 0.35       # ffmpeg scene-change sensitivity

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
        except Exception as e:
            # a one-character TOML typo must not SILENTLY discard the user's
            # whole configuration
            import sys
            print(f"WARNING: {p} could not be parsed ({type(e).__name__}: {e}) "
                  "— using built-in defaults", file=sys.stderr)
            return cfg
        flat = {}
        for section in data.values():
            if isinstance(section, dict):
                flat.update(section)
        flat.update({k: v for k, v in data.items() if not isinstance(v, dict)})
        known = {f for f in cls().__dataclass_fields__}
        return replace(cfg, **{k: v for k, v in flat.items() if k in known})
