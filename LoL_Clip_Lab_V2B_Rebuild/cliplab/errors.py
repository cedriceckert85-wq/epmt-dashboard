"""Freundliche Fehlerklassen.

Erwartbare Fehler werden als ClipLabError (oder Unterklassen) geworfen und
zentral im CLI-Einstieg abgefangen: verstaendliche Meldung mit Loesungsweg,
NIE ein Stacktrace fuer den Nutzer.
"""

from __future__ import annotations


class ClipLabError(Exception):
    """Operativer Fehler mit verstaendlicher Meldung (Exit-Code 1)."""

    exit_code = 1

    def __init__(self, message: str, hint: str = ""):
        self.message = message
        self.hint = hint
        super().__init__(message)

    def friendly(self) -> str:
        out = f"FEHLER: {self.message}"
        if self.hint:
            out += f"\n  -> {self.hint}"
        return out


class MissingInputError(ClipLabError):
    """Fehlende Eingabedatei/-ordner (Exit-Code 2)."""

    exit_code = 2
