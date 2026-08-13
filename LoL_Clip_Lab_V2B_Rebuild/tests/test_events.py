"""F4: Game-Events aus JSON/CSV."""

from __future__ import annotations

import pytest

from cliplab.errors import MissingInputError
from cliplab.events import DEFAULT_WEIGHT, default_weight, load_events


def write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


class TestJson:
    def test_dict_form(self, tmp_path):
        p = write(tmp_path, "e.json", '{"events":[{"t": 10, "kind": "penta"}]}')
        events, warnings = load_events(p)
        assert len(events) == 1
        assert events[0].kind == "penta" and events[0].weight == 5.0
        assert warnings == []

    def test_list_form(self, tmp_path):
        p = write(tmp_path, "e.json", '[{"t": 5, "kind": "kill"}, {"t": 9, "kind": "baron"}]')
        events, _ = load_events(p)
        assert [e.kind for e in events] == ["kill", "baron"]

    def test_weight_override(self, tmp_path):
        p = write(tmp_path, "e.json", '{"events":[{"t":1,"kind":"penta","weight":0.5}]}')
        events, _ = load_events(p)
        assert events[0].weight == 0.5

    def test_death_negative_default(self, tmp_path):
        p = write(tmp_path, "e.json", '{"events":[{"t":1,"kind":"death"}]}')
        events, _ = load_events(p)
        assert events[0].weight < 0

    def test_unknown_kind_default_weight(self, tmp_path):
        p = write(tmp_path, "e.json", '{"events":[{"t":1,"kind":"selfmade"}]}')
        events, _ = load_events(p)
        assert events[0].weight == DEFAULT_WEIGHT

    def test_broken_entries_skipped(self, tmp_path):
        p = write(
            tmp_path,
            "e.json",
            '{"events":[{"t":"kaputt","kind":"penta"},{"kind":"ohne_t"},'
            '{"t":-5,"kind":"neg"},"string",{"t":10,"kind":"baron"}]}',
        )
        events, _ = load_events(p)
        assert len(events) == 1 and events[0].kind == "baron"

    def test_infinity_t_skipped(self, tmp_path):
        p = write(tmp_path, "e.json", '{"events":[{"t":Infinity,"kind":"penta"},{"t":3,"kind":"kill"}]}')
        events, _ = load_events(p)
        assert len(events) == 1

    def test_infinity_weight_falls_back(self, tmp_path):
        p = write(tmp_path, "e.json", '{"events":[{"t":3,"kind":"penta","weight":Infinity}]}')
        events, _ = load_events(p)
        assert events[0].weight == 5.0

    def test_invalid_json_warns_runs_without(self, tmp_path):
        p = write(tmp_path, "e.json", "{kaputt::::")
        events, warnings = load_events(p)
        assert events == [] and any("kein gueltiges JSON" in w or "0 Events" in w for w in warnings)

    def test_zero_events_warning(self, tmp_path):
        p = write(tmp_path, "e.json", '{"events": []}')
        events, warnings = load_events(p)
        assert events == [] and any("0 Events" in w for w in warnings)

    def test_kind_sanitized_to_slug(self, tmp_path):
        p = write(tmp_path, "e.json", '{"events":[{"t":1,"kind":"Baron Nashor!"}]}')
        events, _ = load_events(p)
        assert events[0].kind == "baron_nashor"


class TestCsv:
    def test_with_header(self, tmp_path):
        p = write(tmp_path, "e.csv", "t,kind,weight\n10,penta,\n20,death,\n")
        events, _ = load_events(p)
        assert len(events) == 2
        assert events[0].weight == 5.0 and events[1].weight < 0

    def test_without_header(self, tmp_path):
        p = write(tmp_path, "e.csv", "10,penta\n20,kill\n")
        events, _ = load_events(p)
        assert len(events) == 2

    def test_weight_column(self, tmp_path):
        p = write(tmp_path, "e.csv", "10,penta,9.5\n")
        events, _ = load_events(p)
        assert events[0].weight == 9.5

    def test_broken_lines_skipped(self, tmp_path):
        p = write(tmp_path, "e.csv", "zehn,penta\n,leer\n30,baron\nnur_ein_feld\n")
        events, _ = load_events(p)
        assert len(events) == 1 and events[0].kind == "baron"

    def test_empty_file_warns(self, tmp_path):
        p = write(tmp_path, "e.csv", "")
        events, warnings = load_events(p)
        assert events == [] and warnings

    def test_sorted_by_time(self, tmp_path):
        p = write(tmp_path, "e.csv", "30,kill\n10,baron\n20,dragon\n")
        events, _ = load_events(p)
        assert [e.t for e in events] == [10.0, 20.0, 30.0]


class TestMisc:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(MissingInputError):
            load_events(tmp_path / "gibtsnicht.json")

    def test_unknown_extension_tries_both(self, tmp_path):
        p = write(tmp_path, "e.txt", "10,penta\n")
        events, _ = load_events(p)
        assert len(events) == 1

    def test_unknown_extension_json(self, tmp_path):
        p = write(tmp_path, "e.dat", '{"events":[{"t":2,"kind":"ace"}]}')
        events, _ = load_events(p)
        assert events[0].kind == "ace"

    def test_default_weight_fn(self):
        assert default_weight("penta") == 5.0
        assert default_weight("nie_gesehen") == DEFAULT_WEIGHT
        assert default_weight("death") < 0

    def test_weight_clamped(self, tmp_path):
        p = write(tmp_path, "e.json", '{"events":[{"t":2,"kind":"x","weight":9999}]}')
        events, _ = load_events(p)
        assert events[0].weight == 10.0
