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


def test_memory_remembers_gags_across_sessions(tmp_path):
    # THE brain behavior: a gag learned in session 1 must be visible to the
    # editorial LLM in session 2, and the counter must grow.
    from clip_lab.memory import load_memory
    mem_path = tmp_path / "brain.json"

    cfg = Config()
    cfg.use_llm = True
    prompts_session2 = []

    plan1, meta1 = analyze(str(SAMPLES / "sample_vod.mkv"), cfg, tmp_path / "run1",
                           transcript_path=SAMPLES / "fixture_transcript.json",
                           events_path=SAMPLES / "fixture_events.json",
                           llm=demo_llm(), memory_path=mem_path,
                           log=lambda *a: None)
    assert meta1["memory"]["gags"] >= 1                       # learned something
    mem_after_1 = load_memory(mem_path)
    seen_1 = mem_after_1["gags"][0]["times_seen"]

    # second session: wrap the demo runner to capture what the LLM gets told
    from clip_lab._demo import demo_runner
    from clip_lab.llm_client import LLMClient

    def spy_runner(prompt):
        prompts_session2.append(prompt)
        return demo_runner(prompt)

    # session 2 is a DIFFERENT vod — a same-name rerun deliberately does not
    # bump counters (re-analysis must not inflate the brain)
    plan2, meta2 = analyze(str(SAMPLES / "sample_vod2.mkv"), cfg, tmp_path / "run2",
                           transcript_path=SAMPLES / "fixture_transcript.json",
                           events_path=SAMPLES / "fixture_events.json",
                           llm=LLMClient(["spy"], runner=spy_runner),
                           memory_path=mem_path, log=lambda *a: None)

    session_prompts = [p for p in prompts_session2
                       if "CANDIDATE WINDOWS" not in p and "LONG-TERM MEMORY" not in p]
    assert session_prompts, "session pass must have run"
    assert any("CHANNEL MEMORY" in p and "hit a Q eventually" in p
               for p in session_prompts), \
        "session 2's LLM must be told about the gag learned in session 1"

    mem_after_2 = load_memory(mem_path)
    assert mem_after_2["sessions_analyzed"] > mem_after_1["sessions_analyzed"]
    assert mem_after_2["gags"][0]["times_seen"] > seen_1      # counter bumped


def test_lore_refs_reach_the_edit_sheet(tmp_path):
    # second session with a knowing brain -> 🧠 lines in the sheet
    mem_path = tmp_path / "brain.json"
    cfg = Config()
    cfg.use_llm = True
    for run in ("run1", "run2"):
        plan, meta = analyze(str(SAMPLES / "sample_vod.mkv"), cfg, tmp_path / run,
                             transcript_path=SAMPLES / "fixture_transcript.json",
                             events_path=SAMPLES / "fixture_events.json",
                             llm=demo_llm(), memory_path=mem_path,
                             log=lambda *a: None)
    sheet = (tmp_path / "run2" / "edit_sheet.md").read_text(encoding="utf-8")
    assert "🧠 running gag (channel lore): I'll hit a Q eventually" in sheet
    assert "Channel memory:" in sheet                          # header stats
    penta = [p for p in plan if "PENTAKILL" in (p.title or "")]
    assert penta and penta[0].lore_refs == ["I'll hit a Q eventually"]


def test_rerun_same_vod_does_not_inflate_memory(tmp_path):
    # tweak-config-and-rerun is THE normal loop: analyzing the SAME vod again
    # must not bump gag counters or sessions_analyzed
    from clip_lab.memory import load_memory
    mem_path = tmp_path / "brain.json"
    cfg = Config()
    cfg.use_llm = True
    for run in ("a", "b"):
        analyze(str(SAMPLES / "sample_vod.mkv"), cfg, tmp_path / run,
                transcript_path=SAMPLES / "fixture_transcript.json",
                events_path=SAMPLES / "fixture_events.json",
                llm=demo_llm(), memory_path=mem_path, log=lambda *a: None)
    mem = load_memory(mem_path)
    assert mem["sessions_analyzed"] == 1                   # not inflated
    assert all(g["times_seen"] == 1 for g in mem["gags"])


def test_no_memory_path_means_no_brain(tmp_path):
    plan, meta = _run(tmp_path, use_llm=True)                  # helper passes no memory_path
    assert "memory" not in meta
    assert not (tmp_path / "channel_memory.json").exists()


def test_signal_only_runs_do_not_pollute_the_brain(tmp_path):
    # regression: without editorial context there is nothing to remember —
    # empty session rows must not be appended (they would slowly evict the
    # real summaries from the capped list)
    from clip_lab.memory import load_memory
    mem_path = tmp_path / "brain.json"
    cfg = Config()
    cfg.use_llm = False
    for run in ("r1", "r2", "r3"):
        analyze(str(SAMPLES / "sample_vod.mkv"), cfg, tmp_path / run,
                transcript_path=SAMPLES / "fixture_transcript.json",
                events_path=SAMPLES / "fixture_events.json",
                llm=None, memory_path=mem_path, log=lambda *a: None)
    assert not mem_path.exists() or load_memory(mem_path)["sessions"] == []


def test_deterministic_across_runs(tmp_path):
    a, _ = _run(tmp_path / "a", use_llm=True)
    b, _ = _run(tmp_path / "b", use_llm=True)
    assert [(p.rank, p.title, p.clip_t0, p.clip_t1) for p in a] == \
           [(p.rank, p.title, p.clip_t0, p.clip_t1) for p in b]
