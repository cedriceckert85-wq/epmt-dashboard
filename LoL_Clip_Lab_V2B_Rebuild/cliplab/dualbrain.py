"""Doppel-Gehirn (F9): optionale Zweitmeinung ueber eine zweite LLM-CLI.

- Erhaelt den IDENTISCHEN Moment-Prompt wie das Primaer-Gehirn.
- Blend-Semantik:
  * von beiden bewertete Clips -> Score-Mittelwert + Notiz
  * vom Primaer uebersprungene -> Zweitmeinung uebernehmen
  * neue Fenster -> aufnehmen (aber NICHT mit eigenen Funden matchen,
    keine Duplikate erzeugen)
  * die Arbeit des Primaer-Gehirns (Titel, Captions, ...) wird NIE
    ueberschrieben, auch bei Score 0
- Nicht installiert -> still ueberspringen; Muell-Antwort -> Primaer-Ergebnis
  unangetastet. Session-Pass + Gedaechtnis bleiben Primaer-only
  (durchgesetzt in pipeline.py/memory.py via moment.source).

Auslieferungszustand: AUS — ``llm2_cmd = []`` in Code-Default und
config.toml-Vorlage. Opt-in siehe README.
"""

from __future__ import annotations

from typing import Callable

from .config import Config
from .editorial import Moment, parse_moments_response, windows_match

Runner = Callable[[str], "str | None"]


def blend_second_opinion(
    primary: list[Moment],
    moment_prompt: str,
    runner2: Runner | None,
    duration: float,
    cut_style_names: set[str],
    cfg: Config,
) -> tuple[list[Moment], list[str]]:
    """Zweitmeinung einholen und einblenden.

    Rueckgabe: (Momente, Notizen fuers Log). Ohne Runner oder bei
    Muell-Antworten bleibt ``primary`` unveraendert.
    """
    if runner2 is None:
        return primary, []
    try:
        raw = runner2(moment_prompt)
    except Exception:  # noqa: BLE001 — Zweitmeinung darf NIE den Lauf kippen
        return primary, ["Zweitmeinung: CLI-Fehler — uebersprungen"]
    if raw is None:
        return primary, ["Zweitmeinung: keine Antwort — uebersprungen"]
    secondary = parse_moments_response(
        raw, duration, cut_style_names, cfg, source="llm2"
    )
    if not secondary:
        return primary, ["Zweitmeinung: keine verwertbaren Momente — Primaer unangetastet"]

    notes: list[str] = []
    blended = 0
    adopted: list[Moment] = []
    matched_primary: set[int] = set()
    for sm in secondary:
        hit_idx = None
        for i, pm in enumerate(primary):
            if windows_match(pm.t0, pm.t1, sm.t0, sm.t1):
                hit_idx = i
                break
        if hit_idx is not None:
            pm = primary[hit_idx]
            if hit_idx not in matched_primary:
                # Score-Mittelwert + Notiz; Titel/Captions/etc. NIE anfassen.
                pm.second_score = sm.score
                pm.score = (pm.score + sm.score) / 2.0
                matched_primary.add(hit_idx)
                blended += 1
            continue
        # Neues Fenster: nicht mit eigenen Funden matchen — nur exakte
        # Duplikate unter den bereits uebernommenen vermeiden.
        dup = any(
            abs(sm.t0 - a.t0) <= 0.01 and abs(sm.t1 - a.t1) <= 0.01 for a in adopted
        )
        if dup:
            continue
        sm.reason = (sm.reason + " " if sm.reason else "") + "[Zweitmeinung]"
        adopted.append(sm)

    if blended:
        notes.append(f"Zweitmeinung: {blended} Momente doppelt bewertet (Score-Mittel)")
    if adopted:
        notes.append(f"Zweitmeinung: {len(adopted)} zusaetzliche Momente uebernommen")
    return primary + adopted, notes
