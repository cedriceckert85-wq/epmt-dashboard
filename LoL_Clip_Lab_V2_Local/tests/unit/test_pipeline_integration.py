"""End-to-end proof on the bundled fixtures: transcript + events + the canned
editorial brain must produce a coherent, punchline-aware edit sheet — the exact
path `clip_lab selftest` runs. This is the closest offline stand-in for a real
VOD run (only whisper + ffmpeg are missing, and both are bypassed by supplying a
transcript)."""
from pathlib import Path

from clip_lab._demo import demo_llm
from clip_lab.config import Config
from clip_lab.pipeline import analyze

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples"


def _run(tmp_path, use_llm):
    cfg = Config()
    cfg.use_llm = use_llm
    llm = demo_llm() if use_llm else None
    return analyze(str(SAMPLES / "sample_vod.mkv"), cfg, tmp_path,
                   transcript_path=SAMPLES / "fixture_transcript.json",
                   events_path=SAMPLES / "fixture_events.json",
                   llm=llm, log=lambda *a: None)


def test_llm_path_produces_editorial_clips(tmp_path):
    plan, meta = _run(tmp_path, use_llm=True)
    assert meta["editorial"] == "llm"
    assert len(plan) >= 6
    cats = {p.category for p in plan}
    # the canned brain assigns real categories, not just 'moment'
    assert {"funny", "hype", "clutch", "fail"} & cats


def test_llm_path_has_punchline_aware_cuts(tmp_path):
    plan, _ = _run(tmp_path, use_llm=True)
    punchy = [p for p in plan if p.punchline_t is not None]
    assert punchy
    for p in punchy:
        # clip ends within a few seconds after its punchline (not on a stopwatch)
        assert p.clip_t1 >= p.punchline_t
        assert p.clip_t1 - p.punchline_t <= 15.0


def test_pentakill_carries_callback_inserts(tmp_path):
    plan, _ = _run(tmp_path, use_llm=True)
    penta = [p for p in plan if "PENTAKILL" in (p.title or "")]
    assert penta, "pentakill clip should be present"
    assert penta[0].callback_inserts, "penta should reference the early running gag"


def test_top_clip_is_the_pentakill(tmp_path):
    plan, _ = _run(tmp_path, use_llm=True)
    assert "PENTAKILL" in (plan[0].title or "")   # highest score


def test_signal_only_path_still_produces_a_sheet(tmp_path):
    plan, meta = _run(tmp_path, use_llm=False)
    assert meta["editorial"] == "signal"
    assert len(plan) >= 1
    # without the LLM everything is a generic 'moment' but still cut cleanly
    assert all(p.clip_t1 > p.clip_t0 for p in plan)


def test_artifacts_written_to_disk(tmp_path):
    _run(tmp_path, use_llm=True)
    assert (Path(tmp_path) / "edit_sheet.md").exists()
    assert (Path(tmp_path) / "edit_plan.json").exists()
    assert (Path(tmp_path) / "clips.csv").exists()


def test_transcript_only_ignores_stale_audio(tmp_path):
    # regression: a leftover audio.wav from a prior full run into the same out
    # dir must NOT be read and paired with a transcript-only run.
    work = tmp_path / "work"
    work.mkdir(parents=True)
    (work / "audio.wav").write_bytes(b"not a real wav, must never be read")
    plan, meta = _run(tmp_path, use_llm=True)
    assert meta["reactions"] == 0          # stale audio ignored, not parsed
    assert len(plan) >= 1                  # run still succeeds


def test_deterministic_across_runs(tmp_path):
    a, _ = _run(tmp_path / "a", use_llm=True)
    b, _ = _run(tmp_path / "b", use_llm=True)
    assert [(p.rank, p.title, p.clip_t0, p.clip_t1) for p in a] == \
           [(p.rank, p.title, p.clip_t0, p.clip_t1) for p in b]
