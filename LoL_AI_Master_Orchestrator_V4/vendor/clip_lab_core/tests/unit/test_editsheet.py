"""The edit sheet is the primary deliverable a human reads, plus machine JSON and
a CSV. We check the three artifacts are written and internally consistent."""
import json

from clip_lab.editsheet import write_edit_sheet
from clip_lab.models import EditPlanItem


def _plan():
    return [
        EditPlanItem(rank=1, clip_t0=100.0, clip_t1=112.0, category="funny",
                     title="A Funny Bit", why="it lands", punchline_t=108.0,
                     final_score=0.91,
                     captions=[{"t": 107.0, "text": "lol"}],
                     sfx=[{"t": 108.0, "kind": "airhorn"}],
                     transcript_excerpt="he said the thing"),
        EditPlanItem(rank=2, clip_t0=500.0, clip_t1=515.0, category="clutch",
                     title="Big Play", why="clutch", punchline_t=None,
                     final_score=0.6),
    ]


def test_writes_three_artifacts(tmp_path):
    write_edit_sheet(_plan(), tmp_path, vod_name="vod.mkv",
                     meta={"duration": 1000, "editorial": "llm",
                           "reactions": 3, "events": 2, "candidates": 5})
    assert (tmp_path / "edit_plan.json").exists()
    assert (tmp_path / "edit_sheet.md").exists()
    assert (tmp_path / "clips.csv").exists()


def test_json_roundtrips_and_has_duration(tmp_path):
    write_edit_sheet(_plan(), tmp_path, vod_name="vod.mkv",
                     meta={"duration": 1000, "editorial": "llm"})
    data = json.loads((tmp_path / "edit_plan.json").read_text(encoding="utf-8"))
    assert data["vod"] == "vod.mkv"
    assert len(data["clips"]) == 2
    assert data["clips"][0]["duration"] == 12.0     # derived property serialized


def test_markdown_shows_titles_and_punchline(tmp_path):
    write_edit_sheet(_plan(), tmp_path, vod_name="vod.mkv",
                     meta={"duration": 1000, "editorial": "llm"})
    md = (tmp_path / "edit_sheet.md").read_text(encoding="utf-8")
    assert "A Funny Bit" in md
    assert "Punchline at" in md          # clip 1 has one
    assert "airhorn" in md               # sfx rendered


def test_csv_has_header_and_rows(tmp_path):
    write_edit_sheet(_plan(), tmp_path, vod_name="vod.mkv",
                     meta={"duration": 1000, "editorial": "llm"})
    lines = (tmp_path / "clips.csv").read_text(encoding="utf-8").strip().splitlines()
    assert lines[0].startswith("rank,category,title")
    assert len(lines) == 3               # header + 2 clips


def test_csv_quotes_titles_with_commas(tmp_path):
    plan = [EditPlanItem(rank=1, clip_t0=0.0, clip_t1=10.0, category="funny",
                         title="Wait, what?!", why="x", punchline_t=None,
                         final_score=0.5)]
    write_edit_sheet(plan, tmp_path, vod_name="v", meta={"duration": 10})
    csv = (tmp_path / "clips.csv").read_text(encoding="utf-8")
    assert '"Wait, what?!"' in csv
