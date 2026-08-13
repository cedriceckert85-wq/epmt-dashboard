"""F5: Extraktion des ersten balancierten Top-Level-JSON aus Chat-Output."""

from __future__ import annotations

import json

import pytest

from cliplab.jsonextract import extract_json


class TestBasics:
    def test_plain_object(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_plain_array(self):
        assert extract_json("[1, 2, 3]") == [1, 2, 3]

    def test_chatty_prefix_suffix(self):
        text = 'Klar! Hier dein JSON:\n{"a": [1, 2]}\nViel Spass damit!'
        assert extract_json(text) == {"a": [1, 2]}

    def test_markdown_fence(self):
        text = 'Antwort:\n```json\n{"x": true}\n```\nFertig.'
        assert extract_json(text) == {"x": True}

    def test_array_before_object(self):
        assert extract_json('erst [1,2] dann {"a":1}') == [1, 2]

    def test_object_before_array(self):
        assert extract_json('erst {"a":1} dann [1,2]') == {"a": 1}

    def test_nested(self):
        data = {"a": {"b": [{"c": 1}]}}
        assert extract_json("bla " + json.dumps(data) + " blub") == data

    def test_empty_object(self):
        assert extract_json("{}") == {}

    def test_empty_array(self):
        assert extract_json("[]") == []


class TestStringsAndEscapes:
    def test_brackets_inside_strings(self):
        text = '{"t": "ein } in string und ] auch", "n": 1}'
        assert extract_json(text)["n"] == 1

    def test_escaped_quote_in_string(self):
        text = '{"t": "sagt \\"hi}\\" dazu"}'
        assert extract_json(text) == {"t": 'sagt "hi}" dazu'}

    def test_backslash_at_string_end(self):
        text = '{"p": "C:\\\\pfad\\\\"} rest'
        assert extract_json(text) == {"p": "C:\\pfad\\"}

    def test_open_brace_in_string_only(self):
        text = 'vorher { "kaputt \n {"ok": 1}'
        # erste { balanciert nie sauber -> zweiter Versuch findet das Objekt
        assert extract_json(text) == {"ok": 1}

    def test_unicode_content(self):
        text = '{"t": "Bäume 🌳 und Büsche"}'
        assert extract_json(text) == {"t": "Bäume 🌳 und Büsche"}


class TestRobustness:
    def test_none_input(self):
        assert extract_json(None) is None

    def test_empty_string(self):
        assert extract_json("") is None

    def test_no_json(self):
        assert extract_json("nur text ohne alles") is None

    def test_number_only_is_not_extracted(self):
        assert extract_json("42") is None

    def test_unbalanced_only(self):
        assert extract_json("{{{{") is None

    def test_bracket_flood_bounded(self):
        # 100k oeffnende Klammern: begrenzte Versuche, kein O(n^2)-Haenger
        assert extract_json("{" * 100_000) is None

    def test_flood_then_valid_within_attempts(self):
        text = "{bad " * 10 + '{"ok": 1}'
        assert extract_json(text) == {"ok": 1}

    def test_flood_exhausts_attempts(self):
        # mehr kaputte Kandidaten als max_attempts -> None, aber schnell
        text = "{x" * 200
        assert extract_json(text, max_attempts=8) is None

    def test_deep_nesting_recursionerror_caught(self):
        depth = 100_000
        text = "[" * depth + "]" * depth
        # json.loads wirft RecursionError -> als "kein JSON" behandelt
        assert extract_json(text) is None

    def test_mismatched_brackets_skip(self):
        assert extract_json('{"a": 1] {"b": 2}') == {"b": 2}

    def test_invalid_json_single_quotes_skipped(self):
        assert extract_json("{'a': 1} {\"b\": 2}") == {"b": 2}

    def test_infinity_is_parsed(self):
        # json.loads akzeptiert Infinity — Sanitisierung klemmt spaeter
        result = extract_json('{"score": Infinity}')
        assert result is not None and result["score"] == float("inf")

    def test_nan_is_parsed(self):
        result = extract_json('{"x": NaN}')
        assert result is not None

    def test_non_string_input(self):
        assert extract_json(12345) is None

    def test_balanced_inside_invalid(self):
        text = '{invalid {"a": 1}}'
        assert extract_json(text) == {"a": 1}


@pytest.mark.parametrize(
    "payload",
    [
        {"moments": []},
        {"running_gags": [{"name": "x"}]},
        [{"new": "a", "matches": None}],
        {"deep": {"a": {"b": {"c": [1, 2, {"d": "e"}]}}}},
    ],
)
def test_roundtrip_various(payload):
    chatty = "Vorwort!\n" + json.dumps(payload, ensure_ascii=False) + "\nNachwort."
    assert extract_json(chatty) == payload
