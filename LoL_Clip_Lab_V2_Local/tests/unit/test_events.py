"""Optional game events load from JSON or CSV a user supplies for a downloaded
VOD. Both formats and their error tolerance are pinned."""
from clip_lab.events import load_events


def test_none_path_gives_empty():
    assert load_events(None) == []


def test_json_list(tmp_path):
    p = tmp_path / "e.json"
    p.write_text('[{"t": 10, "kind": "penta", "weight": 9}]', encoding="utf-8")
    evs = load_events(str(p))
    assert len(evs) == 1
    assert evs[0].kind == "penta" and evs[0].weight == 9.0


def test_json_events_key(tmp_path):
    p = tmp_path / "e.json"
    p.write_text('{"events": [{"t": 5, "kind": "kill"}, {"t": 1, "kind": "ace"}]}',
                 encoding="utf-8")
    evs = load_events(str(p))
    assert [e.t for e in evs] == [1.0, 5.0]      # sorted by time


def test_json_skips_malformed_rows(tmp_path):
    p = tmp_path / "e.json"
    p.write_text('[{"kind": "no_time"}, {"t": 3, "kind": "kill"}]', encoding="utf-8")
    evs = load_events(str(p))
    assert len(evs) == 1 and evs[0].t == 3.0


def test_csv_with_header(tmp_path):
    p = tmp_path / "e.csv"
    p.write_text("t,kind,weight\n10,penta,9\n20,kill\n", encoding="utf-8")
    evs = load_events(str(p))
    assert len(evs) == 2
    assert evs[0].kind == "penta" and evs[0].weight == 9.0
    assert evs[1].kind == "kill" and evs[1].weight == 0.0


def test_csv_without_header(tmp_path):
    p = tmp_path / "e.csv"
    p.write_text("30,dragon\n5,baron\n", encoding="utf-8")
    evs = load_events(str(p))
    assert [e.t for e in evs] == [5.0, 30.0]


def test_csv_ignores_bad_timestamps(tmp_path):
    p = tmp_path / "e.csv"
    p.write_text("notanumber,kill\n7,ace\n", encoding="utf-8")
    evs = load_events(str(p))
    assert len(evs) == 1 and evs[0].kind == "ace"
