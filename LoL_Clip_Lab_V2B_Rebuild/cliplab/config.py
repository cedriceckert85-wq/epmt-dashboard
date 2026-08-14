"""Konfiguration: config.toml (tomllib) + Code-Defaults.

Kaputte Config -> Warnung + Defaults, niemals stilles Verschlucken und
niemals ein Crash. CLI-Flags ueberschreiben die Config (macht cli.py).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .sanitize import clean_str
from .util import finite, slugify

CONFIG_NAME = "config.toml"


@dataclass
class ChannelSpec:
    name: str
    note: str = ""
    kind: str = "clips"  # "clips" oder "full" (Ganz-VOD-Kanal)
    max_s: float = 0.0  # 0 = keine Warnschwelle
    vertical: bool = False


def default_channels() -> list[ChannelSpec]:
    return [
        ChannelSpec(
            name="insta",
            note="Vertikale Reels unter 60s, zwei Stile: funny-talk und montage",
            max_s=60.0,
            vertical=True,
        ),
        ChannelSpec(name="yt", note="Geschnittene Highlight-Videos, ca. 10 Minuten"),
        ChannelSpec(name="uncut", note="Ganze Session, nur Kapitelmarker", kind="full"),
    ]


@dataclass
class Config:
    # [general]
    language: str = "auto"  # "auto" oder erzwungene Sprache, z.B. "de"
    hosts: list[str] = field(default_factory=list)
    keep_wav: bool = False
    out_suffix: str = "_cliplab"

    # [audio]
    audio_stream: str = ""  # z.B. "a:1"; leer = ffmpeg-Standardspur

    # [whisper]
    whisper_model: str = "small"  # tiny | base | small | medium

    # [reactions]
    reaction_threshold_db: float = 8.0
    reaction_floor_dbfs: float = -50.0
    reaction_merge_gap_s: float = 2.0
    reaction_baseline_window_s: float = 30.0

    # [llm]
    llm_cmd: list[str] = field(default_factory=lambda: ["claude", "-p"])
    # Zweitmeinung (F9): Standard AUS (leere Liste). Opt-in z.B.
    # ["codex", "exec", "-"] — siehe README.
    llm2_cmd: list[str] = field(default_factory=list)
    llm_timeout_s: float = 240.0
    chunk_chars: int = 150_000
    moment_budget_chars: int = 150_000
    context_window_s: float = 90.0

    # [memory]
    memory_enabled: bool = True
    memory_path: str = "cliplab_memory.json"
    memory_max_gags: int = 40
    memory_max_phrases: int = 30
    memory_max_lore: int = 30
    memory_max_summaries: int = 12

    # [styles]
    style_profile_path: str = "style_profile.json"
    references_dir: str = "references"
    style_cut_threshold_s: float = 120.0

    # [ranking]
    w_signal: float = 0.45
    w_semantic: float = 0.55
    clips_per_hour: float = 8.0
    min_clips: int = 4
    per_10min_cap: int = 3

    # [planning]
    min_clip_s: float = 8.0
    max_clip_s: float = 60.0
    punchline_decay_s: float = 4.0
    style_max_cap_s: float = 90.0

    # [cutting]
    encoder: str = "auto"  # auto | amf | x264

    # [channels]
    channels: list[ChannelSpec] = field(default_factory=default_channels)

    # Basisverzeichnis fuer relative Pfade (memory/profile); wird beim
    # Laden auf den Ordner der config.toml gesetzt.
    base_dir: str = "."

    def channel_names(self) -> list[str]:
        return [c.name for c in self.channels]

    def channel(self, name: str) -> ChannelSpec | None:
        for c in self.channels:
            if c.name == name:
                return c
        return None

    def resolve(self, path_str: str) -> Path:
        p = Path(path_str)
        if p.is_absolute():
            return p
        return Path(self.base_dir) / p


# ---------------------------------------------------------------------------
# Laden & Mergen


def _want_type(default: Any, value: Any) -> Any | None:
    """Typ-tolerantes Uebernehmen eines Config-Werts; None = ablehnen."""
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        return None
    if isinstance(default, float):
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            import math

            try:
                if math.isfinite(float(value)):
                    return float(value)
            except (OverflowError, ValueError):
                return None  # Riesen-Integer (z.B. 10**400) -> falscher Typ
        return None
    if isinstance(default, int):
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float) and float(value).is_integer():
            return int(value)
        return None
    if isinstance(default, str):
        if isinstance(value, str):
            return value
        return None
    if isinstance(default, list):
        if isinstance(value, list) and all(isinstance(x, str) for x in value):
            return list(value)
        return None
    return None


# Zuordnung TOML-Sektion.key -> Config-Attribut
_KEYMAP: dict[tuple[str, str], str] = {
    ("general", "language"): "language",
    ("general", "hosts"): "hosts",
    ("general", "keep_wav"): "keep_wav",
    ("general", "out_suffix"): "out_suffix",
    ("audio", "audio_stream"): "audio_stream",
    ("whisper", "model"): "whisper_model",
    ("reactions", "threshold_db"): "reaction_threshold_db",
    ("reactions", "floor_dbfs"): "reaction_floor_dbfs",
    ("reactions", "merge_gap_s"): "reaction_merge_gap_s",
    ("reactions", "baseline_window_s"): "reaction_baseline_window_s",
    ("llm", "llm_cmd"): "llm_cmd",
    ("llm", "llm2_cmd"): "llm2_cmd",
    ("llm", "timeout_s"): "llm_timeout_s",
    ("llm", "chunk_chars"): "chunk_chars",
    ("llm", "moment_budget_chars"): "moment_budget_chars",
    ("llm", "context_window_s"): "context_window_s",
    ("memory", "enabled"): "memory_enabled",
    ("memory", "path"): "memory_path",
    ("memory", "max_gags"): "memory_max_gags",
    ("memory", "max_phrases"): "memory_max_phrases",
    ("memory", "max_lore"): "memory_max_lore",
    ("memory", "max_summaries"): "memory_max_summaries",
    ("styles", "profile_path"): "style_profile_path",
    ("styles", "references_dir"): "references_dir",
    ("styles", "cut_threshold_s"): "style_cut_threshold_s",
    ("ranking", "w_signal"): "w_signal",
    ("ranking", "w_semantic"): "w_semantic",
    ("ranking", "clips_per_hour"): "clips_per_hour",
    ("ranking", "min_clips"): "min_clips",
    ("ranking", "per_10min_cap"): "per_10min_cap",
    ("planning", "min_clip_s"): "min_clip_s",
    ("planning", "max_clip_s"): "max_clip_s",
    ("planning", "punchline_decay_s"): "punchline_decay_s",
    ("planning", "style_max_cap_s"): "style_max_cap_s",
    ("cutting", "encoder"): "encoder",
}


def _parse_channels(raw: Any, warnings: list[str]) -> list[ChannelSpec] | None:
    """[[channels]]-Eintraege parsen; kaputte Eintraege tolerieren + warnen."""
    if not isinstance(raw, list):
        warnings.append("config: [channels] ist keine Liste — nutze Defaults")
        return None
    out: list[ChannelSpec] = []
    seen: set[str] = set()
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            warnings.append(f"config: Kanal-Eintrag {i + 1} ist kein Table — uebersprungen")
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            warnings.append(f"config: Kanal-Eintrag {i + 1} ohne gueltigen 'name' — uebersprungen")
            continue
        name = clean_str(name, max_len=40)
        slug = slugify(name, fallback="")
        if not slug:
            warnings.append(f"config: Kanalname {name!r} unbrauchbar — uebersprungen")
            continue
        if slug in seen:
            warnings.append(f"config: doppelter Kanal {name!r} — uebersprungen")
            continue
        seen.add(slug)
        kind = entry.get("kind", "clips")
        if kind not in ("clips", "full"):
            warnings.append(
                f"config: Kanal {name!r}: unbekanntes kind={kind!r} — nutze 'clips'"
            )
            kind = "clips"
        max_s = finite(entry.get("max_s", 0.0), default=0.0)
        if max_s < 0:
            max_s = 0.0
        vertical = entry.get("vertical", False)
        if not isinstance(vertical, bool):
            vertical = False
        note = clean_str(entry.get("note", ""), max_len=300)
        out.append(ChannelSpec(name=slug, note=note, kind=kind, max_s=max_s, vertical=vertical))
    if not out:
        warnings.append("config: keine brauchbaren Kanaele — nutze Defaults (insta/yt/uncut)")
        return None
    return out


def load_config(path: Path | str | None = None, cwd: Path | str | None = None) -> tuple[Config, list[str]]:
    """config.toml laden. Rueckgabe: (Config, Warnungen).

    path=None: sucht config.toml im Arbeitsverzeichnis, dann im App-Ordner
    (Verzeichnis ueber dem Paket). Nicht vorhanden = ok (Defaults, keine
    Warnung). Kaputt = Warnung + Defaults.
    """
    warnings: list[str] = []
    cfg = Config()
    search: list[Path] = []
    if path is not None:
        search = [Path(path)]
    else:
        base = Path(cwd) if cwd is not None else Path.cwd()
        search = [base / CONFIG_NAME, Path(__file__).resolve().parent.parent / CONFIG_NAME]

    found: Path | None = None
    for cand in search:
        try:
            if cand.is_file():
                found = cand
                break
        except OSError:
            continue
    if found is None:
        if path is not None:
            warnings.append(f"config: {path} nicht gefunden — nutze Defaults")
        return cfg, warnings

    import tomllib

    try:
        raw = tomllib.loads(found.read_text(encoding="utf-8", errors="replace"))
    except (tomllib.TOMLDecodeError, OSError, ValueError, RecursionError) as exc:
        # RecursionError: absurd tief verschachtelte TOML-Arrays
        warnings.append(f"config: {found.name} kaputt ({exc}) — nutze Code-Defaults")
        return cfg, warnings
    if not isinstance(raw, dict):
        warnings.append(f"config: {found.name} hat kein Top-Level-Table — nutze Defaults")
        return cfg, warnings

    cfg.base_dir = str(found.resolve().parent)

    for (section, key), attr in _KEYMAP.items():
        sec = raw.get(section)
        if not isinstance(sec, dict) or key not in sec:
            continue
        default = getattr(cfg, attr)
        value = _want_type(default, sec[key])
        if value is None and sec[key] is not None:
            warnings.append(
                f"config: [{section}].{key} hat falschen Typ — nutze Default {default!r}"
            )
            continue
        if value is not None:
            setattr(cfg, attr, value)

    if "channels" in raw:
        channels = _parse_channels(raw.get("channels"), warnings)
        if channels is not None:
            cfg.channels = channels

    _validate(cfg, warnings)
    return cfg, warnings


def _validate(cfg: Config, warnings: list[str]) -> None:
    if cfg.whisper_model not in ("tiny", "base", "small", "medium"):
        warnings.append(
            f"config: whisper model {cfg.whisper_model!r} unbekannt — nutze 'small'"
        )
        cfg.whisper_model = "small"
    if cfg.encoder not in ("auto", "amf", "x264", "h264_amf", "libx264"):
        warnings.append(f"config: encoder {cfg.encoder!r} unbekannt — nutze 'auto'")
        cfg.encoder = "auto"
    if cfg.chunk_chars < 5_000:
        warnings.append("config: chunk_chars zu klein — nutze 5000")
        cfg.chunk_chars = 5_000
    if cfg.moment_budget_chars < 5_000:
        warnings.append("config: moment_budget_chars zu klein — nutze 5000")
        cfg.moment_budget_chars = 5_000
    if cfg.min_clip_s <= 0:
        cfg.min_clip_s = 1.0
    if cfg.max_clip_s < cfg.min_clip_s:
        warnings.append("config: max_clip_s < min_clip_s — angepasst")
        cfg.max_clip_s = cfg.min_clip_s
    if cfg.w_signal < 0 or cfg.w_semantic < 0:
        warnings.append("config: negative Ranking-Gewichte — nutze Defaults")
        cfg.w_signal, cfg.w_semantic = 0.45, 0.55
    if cfg.llm_timeout_s <= 0:
        cfg.llm_timeout_s = 240.0


def config_as_dict(cfg: Config) -> dict:
    d = dataclasses.asdict(cfg)
    return d
