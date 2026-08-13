"""Selftest (F15): Beweis ohne Abhaengigkeiten.

Fuehrt den kompletten Kreativ-Pfad mit mitgelieferten Fixtures und einem
kanned Demo-LLM vor — deterministisch, ohne Netz, ohne ffmpeg/whisper,
ohne echte CLIs (auch wenn claude/codex auf dem PATH liegen):

- ZWEI Sessions gegen ein Scratch-Gedaechtnis (zweiter Lauf erkennt die
  Gags wieder: Zaehler 2x, Lore-Zeilen im Sheet)
- Stil-Demo (``Cut as:``), Kanal-Plaene, chapters.txt
- beruehrt NIE das echte Gedaechtnis/Profil
- unabhaengig von Nutzer-Umbenennungen in config.toml (nutzt Code-Defaults)
- byte-deterministisch (fixe Uhr, sortierte JSON-Keys)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Callable

from .config import Config
from .editorial import MOMENT_MARKER, SESSION_MARKER
from .errors import ClipLabError
from .memory import CONSOLIDATE_MARKER, BrainStore
from .pipeline import Deps, SessionParts, run_creative_pipeline
from .reactions import Reaction
from .styles import STYLE_MARKER, StyleProfile
from .transcribe import parse_transcript_data
from .events import GameEvent, default_weight

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXED_DATE = "2026-01-01"


class DemoLLM:
    """Kanned Demo-LLM: deterministisch, in-process, spawnt NIE eine CLI.

    Antwortet absichtlich "geschwaetzig" (Text um das JSON herum), damit
    der Selftest auch die JSON-Extraktion vorfuehrt.
    """

    def __init__(self, session_key: str, responses: dict):
        self.session_key = session_key
        self.responses = responses
        self.calls: list[str] = []

    def __call__(self, prompt: str) -> str | None:
        block = self.responses.get(self.session_key, {})
        if SESSION_MARKER in prompt:
            self.calls.append("session")
            payload = block.get("session", {})
        elif MOMENT_MARKER in prompt:
            self.calls.append("moments")
            payload = block.get("moments", {})
        elif CONSOLIDATE_MARKER in prompt:
            self.calls.append("consolidate")
            payload = block.get("consolidate", [])
        elif STYLE_MARKER in prompt:
            self.calls.append("style")
            payload = block.get("style", {})
        else:
            return None
        return (
            "Na klar, hier ist meine Analyse!\n```json\n"
            + json.dumps(payload, ensure_ascii=False)
            + "\n```\nViel Erfolg beim Schneiden!"
        )


def demo_style_profile() -> StyleProfile:
    prof = StyleProfile()
    prof.cuts["insta_funny"] = {
        "ideal_len_s": 42.0,
        "cuts_per_min": 14.0,
        "notes": "Schneller Talk-Humor, harte Cuts direkt auf die Pointe",
        "caption_style": "GROSS, 2-4 Woerter, sparsame Emojis",
        "channel": "insta",
        "sample_count": 3,
    }
    prof.formats["yt"] = {
        "target_runtime_s": 612.0,
        "channel": "yt",
        "sample_count": 2,
        "notes": "FORMAT-Profil aus 2 Videos (Median 612s).",
    }
    return prof


def load_demo_parts(vod_name: str) -> SessionParts:
    segments = parse_transcript_data(
        json.loads((FIXTURES / "demo_transcript.json").read_text(encoding="utf-8"))
    )
    raw_reactions = json.loads(
        (FIXTURES / "demo_reactions.json").read_text(encoding="utf-8")
    )["reactions"]
    reactions = [
        Reaction(t=r["t"], t0=r["t0"], t1=r["t1"], intensity=r["intensity"])
        for r in raw_reactions
    ]
    raw_events = json.loads((FIXTURES / "demo_events.json").read_text(encoding="utf-8"))[
        "events"
    ]
    events = [
        GameEvent(
            t=e["t"], kind=e["kind"], weight=e.get("weight", default_weight(e["kind"]))
        )
        for e in raw_events
    ]
    return SessionParts(
        vod_name=vod_name,
        duration=3600.0,
        segments=segments,
        reactions=reactions,
        events=events,
    )


def run_selftest(out_dir: Path | str | None = None, log: Callable[[str], None] = print) -> int:
    """Kompletter Selbsttest. Rueckgabe 0 = alles gut (sonst ClipLabError)."""
    log("Selftest: kompletter Kreativ-Pfad mit Demo-LLM (offline, deterministisch)")
    if out_dir is None:
        root = Path(tempfile.mkdtemp(prefix="cliplab_selftest_"))
    else:
        root = Path(out_dir)
        root.mkdir(parents=True, exist_ok=True)

    # Code-Defaults — bewusst NICHT die Nutzer-config.toml (F15:
    # unabhaengig von Umbenennungen; beruehrt nie echtes Gedaechtnis/Profil).
    cfg = Config()
    responses = json.loads((FIXTURES / "demo_llm.json").read_text(encoding="utf-8"))
    brain = BrainStore(root / "memory.json", cfg, now_fn=lambda: FIXED_DATE)
    profile = demo_style_profile()
    quiet: Callable[[str], None] = lambda s: None  # noqa: E731

    checks: list[tuple[str, bool]] = []

    def check(name: str, ok: bool) -> None:
        checks.append((name, ok))
        log(f"  [{'OK' if ok else '!!'}] {name}")

    # --- Session 1 -----------------------------------------------------------
    log("Session 1: demo_session_1.mp4 ...")
    deps1 = Deps(
        llm_primary=DemoLLM("session1", responses),
        llm_secondary=None,
        brain=brain,
        profile=profile,
        now_fn=lambda: FIXED_DATE,
        log=quiet,
    )
    res1 = run_creative_pipeline(
        cfg, load_demo_parts("demo_session_1.mp4"), deps1, root / "session1"
    )
    sheet1 = res1.paths["sheet"].read_text(encoding="utf-8")
    chapters1 = res1.paths["chapters"].read_text(encoding="utf-8")
    check("Edit-Sheet Session 1 erzeugt", res1.paths["sheet"].is_file() and len(res1.clips) >= 4)
    check("Stil-Demo: 'Cut as: insta_funny' im Sheet", "Cut as: insta_funny" in sheet1)
    check("Kanal-Plaene vorhanden (insta/yt/uncut)", "Kanal-Plaene" in sheet1
          and "### insta" in sheet1 and "### yt" in sheet1 and "### uncut" in sheet1)
    check("uncut-Plan zeigt auf chapters.txt", "chapters.txt" in sheet1)
    check("chapters.txt beginnt EXAKT mit 00:00", chapters1.startswith("00:00 "))
    check("Kapitel aufsteigend", _ascending(chapters1))
    check("Callback-Insert im Payoff-Clip", "Callback-Insert" in sheet1)
    check("clips.csv parsebar", _csv_ok(res1.paths["csv"]))
    check("edit_plan.json valide", _plan_ok(res1.paths["plan"]))

    # --- Session 2 (Gedaechtnis-Beweis) --------------------------------------
    log("Session 2: demo_session_2.mp4 (Gedaechtnis erkennt den Gag) ...")
    deps2 = Deps(
        llm_primary=DemoLLM("session2", responses),
        llm_secondary=None,
        brain=brain,
        profile=profile,
        now_fn=lambda: FIXED_DATE,
        log=quiet,
    )
    res2 = run_creative_pipeline(
        cfg, load_demo_parts("demo_session_2.mp4"), deps2, root / "session2"
    )
    sheet2 = res2.paths["sheet"].read_text(encoding="utf-8")
    brain_data = brain.load()
    gag = next((g for g in brain_data["gags"] if g["slug"] == "der_verfluchte_busch"), None)
    check("Running Gag im Gedaechtnis", gag is not None)
    check("Gag-Zaehler nach 2. Session == 2", bool(gag) and gag["times_seen"] == 2)
    check("Lore-Zeile (Gedaechtnis) im 2. Sheet", "Lore:" in sheet2 and "🧠" in sheet2)
    check("Zaehler-Anzeige '(2x gesehen)' im 2. Sheet", "(2x gesehen)" in sheet2)
    check("Gedaechtnis meldet Wiedererkennung", any("wiedererkannt" in r for r in res2.memory_report))

    failed = [name for name, ok in checks if not ok]
    log("")
    log(f"Selftest-Ausgaben: {root}")
    log(f"  Arbeitsprobe: {res1.paths['sheet']}")
    if failed:
        raise ClipLabError(
            f"Selftest fehlgeschlagen ({len(failed)}/{len(checks)} Checks): "
            + ", ".join(failed)
        )
    log(f"Selftest OK — alle {len(checks)} Checks bestanden.")
    return 0


def _ascending(chapters_text: str) -> bool:
    from .util import finite

    times: list[float] = []
    for line in chapters_text.strip().splitlines():
        tc = line.split(" ", 1)[0]
        parts = [finite(p, default=-1) for p in tc.split(":")]
        if any(p < 0 for p in parts):
            return False
        t = 0.0
        for p in parts:
            t = t * 60 + p
        times.append(t)
    return all(b > a for a, b in zip(times, times[1:])) and bool(times)


def _csv_ok(path: Path) -> bool:
    import csv

    try:
        rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    except (OSError, csv.Error):
        return False
    return len(rows) >= 2 and rows[0][0] == "rank" and all(
        len(r) == len(rows[0]) for r in rows
    )


def _plan_ok(path: Path) -> bool:
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (
        isinstance(plan, dict)
        and isinstance(plan.get("clips"), list)
        and len(plan["clips"]) >= 4
        and all("t0" in c and "t1" in c and "title" in c for c in plan["clips"])
    )
