"""Erstes balanciertes Top-Level-JSON (Objekt ODER Array) aus
geschwaetzigem LLM-Output extrahieren.

- Klammern in Strings und Escapes werden korrekt behandelt.
- Begrenzte Versuche: kein O(n^2) bei Klammer-Fluten.
- RecursionError (tiefes Nesting in json.loads) wird abgefangen.
"""

from __future__ import annotations

import json
from typing import Any

MAX_ATTEMPTS = 32
MAX_SCAN_CHARS = 4_000_000


def _scan_balanced(text: str, start: int) -> int | None:
    """Iterativer Scanner ab ``start`` (dort steht '{' oder '[').

    Rueckgabe: Endindex (exklusiv) des balancierten Spans oder None.
    """
    depth = 0
    in_str = False
    esc = False
    n = len(text)
    for i in range(start, n):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{" or c == "[":
            depth += 1
        elif c == "}" or c == "]":
            depth -= 1
            if depth == 0:
                return i + 1
            if depth < 0:
                return None
    return None


def extract_json(text: Any, max_attempts: int = MAX_ATTEMPTS) -> Any | None:
    """Erstes parsebares Top-Level-JSON aus Text ziehen; None wenn keins."""
    if not isinstance(text, str) or not text:
        return None
    text = text[:MAX_SCAN_CHARS]
    pos = 0
    attempts = 0
    while attempts < max_attempts:
        i_obj = text.find("{", pos)
        i_arr = text.find("[", pos)
        candidates = [i for i in (i_obj, i_arr) if i != -1]
        if not candidates:
            return None
        start = min(candidates)
        attempts += 1
        end = _scan_balanced(text, start)
        if end is not None:
            try:
                return json.loads(text[start:end])
            except RecursionError:
                pass
            except (ValueError, TypeError):
                pass
        pos = start + 1
    return None
