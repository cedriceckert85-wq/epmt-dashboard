"""Pipeline-Orchestrierung: Kreativ-Pfad, Degradation, analyze_vod."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cliplab.config import Config
from cliplab.editorial import MOMENT_MARKER, SESSION_MARKER
from cliplab.errors import ClipLabError, MissingInputError
from cliplab.events import GameEvent
from cliplab.memory import BrainStore
from cliplab.pipeline import (
    AnalyzeRequest,
    Deps,
    SessionParts,
    analyze_vod,
    run_creative_pipeline,
)
from cliplab.reactions import Reaction
from cliplab.styles import StyleProfile
from tests.conftest import FakeRunner, make_segment


def demo_parts(vod="vod.mkv"):
    return SessionParts(
        vod_name=vod,
        duration=1200.0,
        segments=[
            make_segment(10, 20, "hallo welt wir spielen"),
            make_segment(300, 310, "grosser moment kommt"),
            make_segment(600, 610, "und die pointe sitzt"),
        ],
        reactions=[Reaction(t=305, t0=303, t1=308, intensity=0.9)],
        events=[GameEvent(t=600, kind="penta", weight=5.0)],
    )


def moment_response():
    return json.dumps(
        {
            "moments": [
                {
                    "t0": 295, "t1": 330, "title": "Grosser Moment", "category": "hype",
                    "score": 8.0, "punchline_t": 320, "channels": ["insta"],
                },
                {
                    "t0": 590, "t1": 625, "title": "Penta", "category": "clutch",
                    "score": 9.0, "channels": ["yt"], "lore_refs": ["Der Busch"],
                },
            ]
        }
    )


def session_response():
    return json.dumps(
        {"running_gags": [{"name": "Der Busch"}], "summary": "Testsession."}
    )


def llm_runner():
    return FakeRunner(
        by_marker={SESSION_MARKER: session_response(), MOMENT_MARKER: moment_response()}
    )


quiet = lambda s: None  # noqa: E731


class TestCreativePipeline:
    def test_llm_mode_produces_outputs(self, tmp_path, cfg):
        deps = Deps(llm_primary=llm_runner(), log=quiet)
        res = run_creative_pipeline(cfg, demo_parts(), deps, tmp_path / "out")
        assert res.mode == "llm"
        assert len(res.clips) == 2
        for key in ("sheet", "plan", "csv", "chapters"):
            assert res.paths[key].is_file()

    def test_signal_only_when_no_llm(self, tmp_path, cfg):
        deps = Deps(llm_primary=None, log=quiet)
        res = run_creative_pipeline(cfg, demo_parts(), deps, tmp_path / "out")
        assert res.mode == "signal-only"
        assert res.clips  # brauchbares Sheet trotzdem
        sheet = res.paths["sheet"].read_text(encoding="utf-8")
        assert "Signal-only" in sheet  # klar gekennzeichnet

    def test_garbage_llm_falls_back_to_signal(self, tmp_path, cfg):
        deps = Deps(llm_primary=FakeRunner(responses=["m", "u", "e", "l", "l"]), log=quiet)
        res = run_creative_pipeline(cfg, demo_parts(), deps, tmp_path / "out")
        assert res.mode == "signal-only"
        assert any("Fallback" in w for w in res.warnings)

    def test_memory_updated_in_llm_mode(self, tmp_path, cfg):
        brain = BrainStore(tmp_path / "mem.json", cfg, now_fn=lambda: "2026-01-01")
        deps = Deps(llm_primary=llm_runner(), brain=brain, log=quiet)
        run_creative_pipeline(cfg, demo_parts(), deps, tmp_path / "out")
        data = brain.load()
        assert any(g["name"] == "Der Busch" for g in data["gags"])
        assert "vod.mkv" in data["sessions"]

    def test_signal_only_does_not_pollute_memory(self, tmp_path, cfg):
        brain = BrainStore(tmp_path / "mem.json", cfg, now_fn=lambda: "2026-01-01")
        deps = Deps(llm_primary=None, brain=brain, log=quiet)
        run_creative_pipeline(cfg, demo_parts(), deps, tmp_path / "out")
        data = brain.load()
        assert data["gags"] == [] and data["sessions"] == {}

    def test_memory_block_injected_into_prompts(self, tmp_path, cfg):
        brain = BrainStore(tmp_path / "mem.json", cfg, now_fn=lambda: "2026-01-01")
        seeded = brain.load()
        seeded["gags"].append(
            {"name": "Alter Gag", "slug": "alter_gag", "times_seen": 3,
             "first_seen": "a", "last_seen": "b", "note": ""}
        )
        brain.save(seeded)
        runner = llm_runner()
        deps = Deps(llm_primary=runner, brain=brain, log=quiet)
        run_creative_pipeline(cfg, demo_parts(), deps, tmp_path / "out")
        session_prompts = [p for p in runner.prompts if SESSION_MARKER in p]
        moment_prompts = [p for p in runner.prompts if MOMENT_MARKER in p]
        assert any("Alter Gag" in p for p in session_prompts)  # beide Paesse
        assert any("Alter Gag" in p for p in moment_prompts)

    def test_dualbrain_wired(self, tmp_path, cfg):
        secondary = FakeRunner(
            by_marker={
                MOMENT_MARKER: json.dumps(
                    {"moments": [{"t0": 295, "t1": 330, "score": 4.0, "title": "x"}]}
                )
            }
        )
        deps = Deps(llm_primary=llm_runner(), llm_secondary=secondary, log=quiet)
        res = run_creative_pipeline(cfg, demo_parts(), deps, tmp_path / "out")
        blended = [m for m in res.moments if m.second_score is not None]
        assert len(blended) == 1 and blended[0].score == 6.0
        # Zweitmeinung bekam den IDENTISCHEN Moment-Prompt
        assert secondary.prompts and MOMENT_MARKER in secondary.prompts[0]

    def test_styles_offered_and_tagged(self, tmp_path, cfg):
        prof = StyleProfile()
        prof.cuts["insta_funny"] = {"ideal_len_s": 40.0, "cuts_per_min": 10.0,
                                    "notes": "", "caption_style": "", "channel": "insta",
                                    "sample_count": 1}
        runner = FakeRunner(
            by_marker={
                SESSION_MARKER: session_response(),
                MOMENT_MARKER: json.dumps(
                    {"moments": [{"t0": 295, "t1": 330, "score": 8, "style": "insta_funny"}]}
                ),
            }
        )
        deps = Deps(llm_primary=runner, profile=prof, log=quiet)
        res = run_creative_pipeline(cfg, demo_parts(), deps, tmp_path / "out")
        moment_prompt = next(p for p in runner.prompts if MOMENT_MARKER in p)
        assert "insta_funny" in moment_prompt
        sheet = res.paths["sheet"].read_text(encoding="utf-8")
        assert "Cut as: insta_funny" in sheet

    def test_stats_in_plan(self, tmp_path, cfg):
        deps = Deps(llm_primary=llm_runner(), log=quiet)
        res = run_creative_pipeline(cfg, demo_parts(), deps, tmp_path / "out")
        assert res.plan["stats"]["segments"] == 3
        assert res.plan["stats"]["reactions"] == 1
        assert res.plan["duration_s"] == 1200.0

    def test_empty_session_no_crash(self, tmp_path, cfg):
        parts = SessionParts(vod_name="leer.mkv", duration=60.0)
        deps = Deps(llm_primary=None, log=quiet)
        res = run_creative_pipeline(cfg, parts, deps, tmp_path / "out")
        assert res.paths["sheet"].is_file()
        assert res.clips == []


class TestAnalyzeVod:
    def _deps(self, tmp_path, duration=1200.0):
        wav = tmp_path / "audio.wav"

        def fake_extract(vod, wav_out, audio_stream=""):
            Path(wav_out).write_bytes(b"RIFFfake")
            return Path(wav_out)

        import numpy as np

        return Deps(
            llm_primary=None,
            log=quiet,
            ffprobe_duration=lambda p: duration,
            extract_audio=fake_extract,
            read_wav=lambda p: (np.zeros(16000), 16000),
            transcribe_wav=lambda *a, **k: ([make_segment(1, 5, "text")], {"language": "de"}),
            have_ffmpeg=lambda: "/usr/bin/ffmpeg",
        )

    def test_missing_vod_exit2_error(self, tmp_path, cfg):
        with pytest.raises(MissingInputError):
            analyze_vod(cfg, AnalyzeRequest(vod=tmp_path / "nix.mkv"), Deps(log=quiet))

    def test_full_flow_with_fakes(self, tmp_path, cfg):
        vod = tmp_path / "session.mkv"
        vod.write_bytes(b"fake")
        res = analyze_vod(cfg, AnalyzeRequest(vod=vod), self._deps(tmp_path))
        assert res.out_dir == tmp_path / ("session" + cfg.out_suffix)
        assert res.paths["sheet"].is_file()

    def test_wav_deleted_by_default(self, tmp_path, cfg):
        vod = tmp_path / "session.mkv"
        vod.write_bytes(b"fake")
        res = analyze_vod(cfg, AnalyzeRequest(vod=vod), self._deps(tmp_path))
        assert not (res.out_dir / "audio_16k.wav").exists()

    def test_wav_kept_with_config(self, tmp_path, cfg):
        cfg.keep_wav = True
        vod = tmp_path / "session.mkv"
        vod.write_bytes(b"fake")
        res = analyze_vod(cfg, AnalyzeRequest(vod=vod), self._deps(tmp_path))
        assert (res.out_dir / "audio_16k.wav").exists()

    def test_transcript_skips_whisper(self, tmp_path, cfg):
        vod = tmp_path / "session.mkv"
        vod.write_bytes(b"fake")
        tr = tmp_path / "t.json"
        tr.write_text(
            json.dumps({"segments": [{"t0": 1, "t1": 5, "text": "aus datei"}]}),
            encoding="utf-8",
        )
        deps = self._deps(tmp_path)

        def no_whisper(*a, **k):
            raise AssertionError("Whisper darf nicht aufgerufen werden")

        deps.transcribe_wav = no_whisper
        res = analyze_vod(cfg, AnalyzeRequest(vod=vod, transcript=tr), deps)
        assert res.paths["sheet"].is_file()

    def test_transcript_without_ffmpeg_degrades(self, tmp_path, cfg):
        vod = tmp_path / "session.mkv"
        vod.write_bytes(b"fake")
        tr = tmp_path / "t.json"
        tr.write_text(
            json.dumps({"segments": [{"t0": 1, "t1": 500, "text": "lang"}]}),
            encoding="utf-8",
        )

        def no_probe(p):
            raise ClipLabError("kein ffprobe")

        deps = Deps(
            llm_primary=None, log=quiet,
            ffprobe_duration=no_probe, have_ffmpeg=lambda: None,
        )
        res = analyze_vod(cfg, AnalyzeRequest(vod=vod, transcript=tr), deps)
        # Dauer aus Transkript geschaetzt, Hinweise gesammelt
        assert res.plan["duration_s"] >= 500
        assert res.warnings

    def test_no_ffmpeg_no_transcript_fatal(self, tmp_path, cfg):
        vod = tmp_path / "session.mkv"
        vod.write_bytes(b"fake")

        def no_probe(p):
            raise ClipLabError("kein ffprobe")

        deps = Deps(log=quiet, ffprobe_duration=no_probe, have_ffmpeg=lambda: None)
        with pytest.raises(ClipLabError):
            analyze_vod(cfg, AnalyzeRequest(vod=vod), deps)

    def test_audio_stream_flag_passed(self, tmp_path, cfg):
        vod = tmp_path / "session.mkv"
        vod.write_bytes(b"fake")
        seen = {}
        deps = self._deps(tmp_path)
        orig = deps.extract_audio

        def spy(v, w, audio_stream=""):
            seen["stream"] = audio_stream
            return orig(v, w, audio_stream)

        deps.extract_audio = spy
        analyze_vod(cfg, AnalyzeRequest(vod=vod, audio_stream="a:1"), deps)
        assert seen["stream"] == "a:1"

    def test_audio_stream_from_config(self, tmp_path, cfg):
        cfg.audio_stream = "a:1"
        vod = tmp_path / "session.mkv"
        vod.write_bytes(b"fake")
        seen = {}
        deps = self._deps(tmp_path)
        orig = deps.extract_audio

        def spy(v, w, audio_stream=""):
            seen["stream"] = audio_stream
            return orig(v, w, audio_stream)

        deps.extract_audio = spy
        analyze_vod(cfg, AnalyzeRequest(vod=vod), deps)
        assert seen["stream"] == "a:1"

    def test_events_loaded(self, tmp_path, cfg):
        vod = tmp_path / "session.mkv"
        vod.write_bytes(b"fake")
        ev = tmp_path / "e.csv"
        ev.write_text("100,penta\n", encoding="utf-8")
        res = analyze_vod(cfg, AnalyzeRequest(vod=vod, events=ev), self._deps(tmp_path))
        assert res.plan["stats"]["events"] == 1

    def test_out_dir_override(self, tmp_path, cfg):
        vod = tmp_path / "session.mkv"
        vod.write_bytes(b"fake")
        res = analyze_vod(
            cfg, AnalyzeRequest(vod=vod, out_dir=tmp_path / "custom"), self._deps(tmp_path)
        )
        assert res.out_dir == tmp_path / "custom"
