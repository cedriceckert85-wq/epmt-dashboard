"""Kanal-Gedaechtnis (F6): persistentes JSON-„Gehirn" ueber alle VODs.

- Running Gags MIT Zaehler (times_seen, first/last_seen), Catchphrases,
  Lore, Session-Summaries — alles gecappt.
- Wird VOR der Analyse als kompakter Block in beide LLM-Paesse injiziert.
- NACH der Analyse: LLM-Konsolidierung (bekannte Gags nach BEDEUTUNG
  hochzaehlen statt duplizieren) mit deterministischem mechanischem Fallback.
- Invarianten: Re-Analyse derselben VOD erhoeht KEINE Zaehler (nur
  Summary-Refresh); lore_refs zaehlen als Wiederauftreten; max. 1 Bump pro
  Gag pro Session; korrupte/feindliche Dateien -> frisches/bereinigtes
  Gehirn, NIE Crash.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .config import Config
from .jsonextract import extract_json
from .sanitize import clean_str
from .util import slugify

CONSOLIDATE_MARKER = "### CLIPLAB-TASK: GEDAECHTNIS-KONSOLIDIERUNG ###"

MEMORY_VERSION = 1

Runner = Callable[[str], "str | None"]


def fresh_brain() -> dict:
    return {
        "version": MEMORY_VERSION,
        "sessions": {},
        "gags": [],
        "catchphrases": [],
        "lore": [],
        "summaries": [],
    }


def _clean_int(value, lo: int = 0, hi: int = 1_000_000, default: int = 0) -> int:
    from .util import finite

    v = finite(value, default=float(default))
    try:
        v = int(round(v))
    except (ValueError, OverflowError):
        return default
    return max(lo, min(hi, v))


def sanitize_brain(data, cfg: Config) -> dict:
    """Beliebige (auch feindliche) Daten in ein sauberes Gehirn ueberfuehren.

    Strings statt Dicts, Infinity-Zaehler, tiefes Nesting — alles wird
    bereinigt oder verworfen, nie ein Crash.
    """
    out = fresh_brain()
    if not isinstance(data, dict):
        return out
    sessions = data.get("sessions")
    if isinstance(sessions, dict):
        for k, v in list(sessions.items())[:500]:
            name = clean_str(k, max_len=200)
            if not name:
                continue
            at = ""
            if isinstance(v, dict):
                at = clean_str(v.get("analyzed_at"), max_len=40)
            elif isinstance(v, str):
                at = clean_str(v, max_len=40)
            out["sessions"][name] = {"analyzed_at": at}
    gags = data.get("gags")
    if isinstance(gags, list):
        seen: set[str] = set()
        for g in gags[: cfg.memory_max_gags * 4]:
            if isinstance(g, str):
                g = {"name": g}
            if not isinstance(g, dict):
                continue
            name = clean_str(g.get("name"), max_len=80)
            if not name:
                continue
            slug = slugify(name, fallback="")
            if not slug or slug in seen:
                continue
            seen.add(slug)
            out["gags"].append(
                {
                    "name": name,
                    "slug": slug,
                    "times_seen": _clean_int(g.get("times_seen"), lo=1, default=1),
                    "first_seen": clean_str(g.get("first_seen"), max_len=200),
                    "last_seen": clean_str(g.get("last_seen"), max_len=200),
                    "note": clean_str(g.get("note"), max_len=200),
                }
            )
            if len(out["gags"]) >= cfg.memory_max_gags:
                break
    for key, cap in (
        ("catchphrases", cfg.memory_max_phrases),
        ("lore", cfg.memory_max_lore),
    ):
        raw = data.get(key)
        if isinstance(raw, list):
            cleaned: list[str] = []
            for s in raw[: cap * 4]:
                cs = clean_str(s, max_len=160)
                if cs and cs not in cleaned:
                    cleaned.append(cs)
                if len(cleaned) >= cap:
                    break
            out[key] = cleaned
    summaries = data.get("summaries")
    if isinstance(summaries, list):
        for s in summaries[: cfg.memory_max_summaries * 4]:
            if not isinstance(s, dict):
                continue
            vod = clean_str(s.get("vod"), max_len=200)
            summ = clean_str(s.get("summary"), max_len=500)
            if not vod or not summ:
                continue
            out["summaries"].append({"vod": vod, "summary": summ})
            if len(out["summaries"]) >= cfg.memory_max_summaries:
                break
    return out


class BrainStore:
    """Laden/Speichern/Aktualisieren des Kanal-Gedaechtnisses."""

    def __init__(self, path: Path | str, cfg: Config, now_fn: Callable[[], str] | None = None):
        self.path = Path(path)
        self.cfg = cfg
        self.now_fn = now_fn or _today

    def load(self) -> dict:
        if not self.path.is_file():
            return fresh_brain()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8", errors="replace"))
        except (ValueError, RecursionError, OSError):
            return fresh_brain()
        try:
            return sanitize_brain(raw, self.cfg)
        except RecursionError:
            return fresh_brain()

    def save(self, brain: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(brain, ensure_ascii=False, indent=1, sort_keys=True),
                encoding="utf-8",
            )
        except OSError:
            pass  # Gedaechtnis ist nice-to-have; die Analyse selbst laeuft weiter

    def clear(self) -> bool:
        try:
            if self.path.is_file():
                self.path.unlink()
                return True
        except OSError:
            pass
        return False

    # -- Injektion -----------------------------------------------------------

    def render_block(self, brain: dict) -> str:
        """Kompakter Block fuer die Prompt-Injektion (beide Paesse)."""
        lines: list[str] = []
        if brain["gags"]:
            lines.append("Bekannte Running Gags:")
            for g in brain["gags"][: self.cfg.memory_max_gags]:
                note = f" — {g['note']}" if g.get("note") else ""
                lines.append(
                    f"- \"{g['name']}\" ({g['times_seen']}x gesehen, "
                    f"zuletzt: {g.get('last_seen') or '?'}){note}"
                )
        if brain["catchphrases"]:
            lines.append("Catchphrases: " + " | ".join(brain["catchphrases"][:15]))
        if brain["lore"]:
            lines.append("Lore: " + " | ".join(brain["lore"][:15]))
        if brain["summaries"]:
            lines.append("Letzte Sessions:")
            for s in brain["summaries"][-4:]:
                lines.append(f"- {s['vod']}: {s['summary']}")
        return "\n".join(lines)

    # -- Update nach der Analyse --------------------------------------------

    def update_after_session(
        self,
        brain: dict,
        vod_name: str,
        insights,
        moments,
        runner: Runner | None = None,
    ) -> tuple[dict, list[str]]:
        """Gedaechtnis nach einer LLM-Analyse fortschreiben.

        Rueckgabe: (neues Gehirn, Report-Zeilen). Wird bei Signal-only-
        Laeufen NICHT aufgerufen (kein Verschmutzen).
        """
        report: list[str] = []
        vod_name = clean_str(vod_name, max_len=200) or "unbenannte_vod"
        reanalysis = vod_name in brain["sessions"]

        # Neue Gag-Sichtungen dieser Session einsammeln:
        # Session-Pass-Gags + via lore_refs erkannte (nur Primaer-Momente!)
        seen_names: list[str] = []
        for g in getattr(insights, "running_gags", []) or []:
            name = clean_str(g.get("name") if isinstance(g, dict) else g, max_len=80)
            if name and name not in seen_names:
                seen_names.append(name)
        for m in moments or []:
            if getattr(m, "source", "llm") != "llm":
                continue  # Gedaechtnis bleibt Primaer-only (F9)
            for ref in getattr(m, "lore_refs", []) or []:
                name = clean_str(ref, max_len=80)
                if name and name not in seen_names:
                    seen_names.append(name)

        if reanalysis:
            report.append(
                f"Gedaechtnis: {vod_name} bereits analysiert — nur Summary-Refresh, "
                "keine Zaehler-Erhoehung"
            )
        else:
            mapping = self._consolidate(brain, seen_names, runner)
            bumped: set[str] = set()  # max. 1 Bump pro Gag pro Session
            for name in seen_names:
                target_slug = mapping.get(name)
                if target_slug:
                    gag = self._find_gag(brain, target_slug)
                    if gag is not None:
                        if target_slug not in bumped:
                            gag["times_seen"] = _clean_int(
                                gag["times_seen"], lo=1, default=1
                            ) + 1
                            gag["last_seen"] = vod_name
                            bumped.add(target_slug)
                            report.append(
                                f"Gedaechtnis: Gag \"{gag['name']}\" wiedererkannt "
                                f"(jetzt {gag['times_seen']}x)"
                            )
                        continue
                slug = slugify(name, fallback="")
                if not slug or self._find_gag(brain, slug) is not None:
                    continue
                brain["gags"].append(
                    {
                        "name": name,
                        "slug": slug,
                        "times_seen": 1,
                        "first_seen": vod_name,
                        "last_seen": vod_name,
                        "note": "",
                    }
                )
                bumped.add(slug)
                report.append(f"Gedaechtnis: neuer Gag \"{name}\"")

            for phrase in getattr(insights, "catchphrases", []) or []:
                if phrase not in brain["catchphrases"]:
                    brain["catchphrases"].append(phrase)
            for lore in getattr(insights, "lore", []) or []:
                if lore not in brain["lore"]:
                    brain["lore"].append(lore)

        # Summary refresh (auch bei Re-Analyse)
        summary = clean_str(getattr(insights, "summary", ""), max_len=500)
        if not summary:
            n = len(moments or [])
            summary = f"{n} Momente gefunden."
        brain["summaries"] = [s for s in brain["summaries"] if s.get("vod") != vod_name]
        brain["summaries"].append({"vod": vod_name, "summary": summary})
        brain["sessions"][vod_name] = {"analyzed_at": clean_str(self.now_fn(), max_len=40)}

        # Caps durchsetzen
        brain["gags"] = brain["gags"][-self.cfg.memory_max_gags :]
        brain["catchphrases"] = brain["catchphrases"][-self.cfg.memory_max_phrases :]
        brain["lore"] = brain["lore"][-self.cfg.memory_max_lore :]
        brain["summaries"] = brain["summaries"][-self.cfg.memory_max_summaries :]
        return brain, report

    # -- intern --------------------------------------------------------------

    @staticmethod
    def _find_gag(brain: dict, slug: str) -> dict | None:
        for g in brain["gags"]:
            if g.get("slug") == slug:
                return g
        return None

    def _consolidate(
        self, brain: dict, new_names: list[str], runner: Runner | None
    ) -> dict[str, str]:
        """Neue Gag-Namen auf bekannte Gags mappen (Name -> existierender Slug).

        Erst LLM (nach BEDEUTUNG), dann deterministischer mechanischer
        Fallback fuer alles, was das LLM nicht beantwortet hat.
        """
        mapping: dict[str, str] = {}
        if not new_names or not brain["gags"]:
            return mapping
        known = {g["slug"]: g["name"] for g in brain["gags"]}
        if runner is not None:
            prompt = "\n".join(
                [
                    CONSOLIDATE_MARKER,
                    "Bekannte Running Gags (slug: Name):",
                    "\n".join(f"- {s}: {n}" for s, n in known.items()),
                    "",
                    "Neue Gag-Sichtungen dieser Session:",
                    "\n".join(f"- {n}" for n in new_names),
                    "",
                    "Ordne jede neue Sichtung nach BEDEUTUNG einem bekannten Gag zu "
                    "(gleicher Gag, evtl. anders formuliert) oder null wenn wirklich neu.",
                    'Antworte NUR mit JSON: [{"new":"...","matches":"<slug oder null>"}]',
                ]
            )
            try:
                raw = runner(prompt)
            except Exception:  # noqa: BLE001
                raw = None
            data = extract_json(raw) if raw else None
            if isinstance(data, dict):
                data = data.get("mappings")
            if isinstance(data, list):
                for entry in data[:200]:
                    if not isinstance(entry, dict):
                        continue
                    new = clean_str(entry.get("new"), max_len=80)
                    match = entry.get("matches")
                    if not new or new not in new_names:
                        continue
                    if isinstance(match, str) and match in known:
                        mapping[new] = match
                    elif match is None:
                        mapping[new] = ""  # explizit: wirklich neu
                    # halluzinierter Slug -> unbeantwortet lassen
                    # (mechanischer Fallback entscheidet)
        # Mechanischer Fallback fuer unbeantwortete Namen
        for name in new_names:
            if name in mapping:
                if mapping[name] == "":
                    del mapping[name]
                continue
            slug = slugify(name, fallback="")
            if not slug:
                continue
            for k in known:
                if k == slug or (len(slug) >= 4 and (slug in k or k in slug)):
                    mapping[name] = k
                    break
        return mapping


def _today() -> str:
    import datetime

    return datetime.date.today().isoformat()
