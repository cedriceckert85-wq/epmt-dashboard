"""media.py: Einheiten ohne Binaries + echte ffmpeg-Integrationstests
(synthetisches Testvideo, 2-Spuren-Fall inkl. a:1, echter Schnitt)."""

from __future__ import annotations

import shutil
import wave
from pathlib import Path

import numpy as np
import pytest

from cliplab.errors import ClipLabError, MissingInputError
from cliplab.media import (
    VIDEO_EXTS,
    cut_clip,
    default_run,
    extract_audio,
    ffprobe_duration,
    normalize_audio_stream,
    read_wav_mono,
    scene_cut_rate,
)

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg nicht installiert")


class TestUnits:
    def test_normalize_audio_stream_variants(self):
        assert normalize_audio_stream("") == ""
        assert normalize_audio_stream("a:1") == "a:1"
        assert normalize_audio_stream("1") == "a:1"
        assert normalize_audio_stream(" a:0 ") == "a:0"

    @pytest.mark.parametrize("bad", ["x:1", "a:", "audio", "a:1;rm -rf /", "-map"])
    def test_normalize_audio_stream_invalid(self, bad):
        with pytest.raises(ClipLabError):
            normalize_audio_stream(bad)

    def test_video_exts_cover_spec(self):
        for ext in (".mp4", ".mkv", ".webm", ".mov", ".avi", ".ts", ".m4v"):
            assert ext in VIDEO_EXTS

    def test_ffprobe_missing_file(self, tmp_path):
        if not HAVE_FFMPEG:
            pytest.skip("braucht ffprobe")
        with pytest.raises(MissingInputError):
            ffprobe_duration(tmp_path / "nix.mkv")

    def test_read_wav_missing(self, tmp_path):
        with pytest.raises(ClipLabError):
            read_wav_mono(tmp_path / "nix.wav")

    def test_read_wav_roundtrip(self, tmp_path):
        p = tmp_path / "t.wav"
        data = (np.sin(np.linspace(0, 100, 16000)) * 20000).astype(np.int16)
        with wave.open(str(p), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(data.tobytes())
        samples, sr = read_wav_mono(p)
        assert sr == 16000 and len(samples) == 16000
        assert np.abs(samples).max() <= 1.0

    def test_cut_invalid_range(self, tmp_path):
        with pytest.raises(ClipLabError):
            cut_clip(tmp_path / "v.mkv", tmp_path / "o.mp4", 10, 5, 100,
                     which=lambda n: "/usr/bin/" + n)


@pytest.fixture(scope="module")
def synth_video(tmp_path_factory):
    """Synthetisches Testvideo: 8s, Video + ZWEI Tonspuren
    (a:0 = 440 Hz, a:1 = 880 Hz)."""
    if not HAVE_FFMPEG:
        pytest.skip("ffmpeg nicht installiert")
    d = tmp_path_factory.mktemp("media")
    out = d / "testvideo.mp4"
    proc = default_run(
        [
            shutil.which("ffmpeg"), "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=duration=8:size=320x240:rate=10",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
            "-f", "lavfi", "-i", "sine=frequency=880:duration=8",
            "-map", "0:v", "-map", "1:a", "-map", "2:a",
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
            str(out),
        ],
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return out


def dominant_freq(wav_path: Path) -> float:
    samples, sr = read_wav_mono(wav_path)
    spectrum = np.abs(np.fft.rfft(samples))
    freqs = np.fft.rfftfreq(len(samples), 1.0 / sr)
    return float(freqs[int(np.argmax(spectrum))])


@needs_ffmpeg
class TestRealIngest:
    def test_duration_probed(self, synth_video):
        dur = ffprobe_duration(synth_video)
        assert 7.0 <= dur <= 9.5

    def test_extract_default_track(self, synth_video, tmp_path):
        wav = tmp_path / "a.wav"
        extract_audio(synth_video, wav)
        f = dominant_freq(wav)
        assert abs(f - 440) < 30  # Standardspur = Spur 1

    def test_extract_second_track_a1(self, synth_video, tmp_path):
        # DER 2-Spuren-Fall: a:1 = nur-Mikro-Spur (hier 880 Hz)
        wav = tmp_path / "b.wav"
        extract_audio(synth_video, wav, audio_stream="a:1")
        f = dominant_freq(wav)
        assert abs(f - 880) < 40

    def test_extract_missing_track_friendly(self, synth_video, tmp_path):
        with pytest.raises(ClipLabError) as e:
            extract_audio(synth_video, tmp_path / "c.wav", audio_stream="a:7")
        assert "Tonspur" in (e.value.hint or "") or "a:7" in str(e.value)

    def test_wav_is_16k_mono(self, synth_video, tmp_path):
        wav = tmp_path / "d.wav"
        extract_audio(synth_video, wav)
        samples, sr = read_wav_mono(wav)
        assert sr == 16000
        assert 7.0 * 16000 <= len(samples) <= 9.5 * 16000


@needs_ffmpeg
class TestRealCut:
    def test_cut_produces_file(self, synth_video, tmp_path):
        out = tmp_path / "clip.mp4"
        notes = cut_clip(synth_video, out, 1.0, 3.0, 8.0)
        assert out.is_file() and out.stat().st_size > 0
        assert notes == []
        assert abs(ffprobe_duration(out) - 2.0) < 0.5

    def test_cut_range_outside_errors_not_empty_file(self, synth_video, tmp_path):
        out = tmp_path / "leer.mp4"
        with pytest.raises(ClipLabError):
            cut_clip(synth_video, out, 100.0, 110.0, 8.0)
        assert not out.exists()  # keine leere Datei zuruecklassen

    def test_cut_truncated_range_note(self, synth_video, tmp_path):
        out = tmp_path / "kurz.mp4"
        notes = cut_clip(synth_video, out, 6.0, 20.0, 8.0)
        assert out.is_file()
        assert any("gekuerzt" in n for n in notes)

    def test_vertical_crop_dimensions(self, synth_video, tmp_path):
        out = tmp_path / "vert.mp4"
        cut_clip(synth_video, out, 1.0, 2.0, 8.0, vertical=True)
        proc = default_run(
            [
                shutil.which("ffprobe"), "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0", str(out),
            ],
            timeout=60,
        )
        w, h = proc.stdout.strip().split(",")
        assert (int(w), int(h)) == (1080, 1920)  # 9:16


@needs_ffmpeg
class TestRealSceneRate:
    def test_static_video_zero_cuts(self, synth_video):
        rate = scene_cut_rate(synth_video, 8.0)
        assert rate is not None and rate == 0.0  # echte Messung: 0 Schnitte/min

    def test_no_ffmpeg_returns_none(self, synth_video):
        assert scene_cut_rate(synth_video, 8.0, which=lambda n: None) is None


@needs_ffmpeg
class TestRealReactionsEndToEnd:
    def test_burst_in_real_pipeline(self, tmp_path):
        """Ingest -> WAV -> Reaktionserkennung mit echtem ffmpeg beweisen."""
        from cliplab.reactions import detect_reactions

        # 60s Audio: leises Rauschen + lauter Burst bei t=30
        sr = 16000
        rng = np.random.default_rng(42)
        sig = rng.normal(0, 0.02, 60 * sr)
        t = np.arange(2 * sr) / sr
        sig[30 * sr : 32 * sr] += 0.7 * np.sin(2 * np.pi * 250 * t)
        raw = (np.clip(sig, -1, 1) * 32767).astype(np.int16)
        src_wav = tmp_path / "src.wav"
        with wave.open(str(src_wav), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(raw.tobytes())
        # WAV -> Video mit Tonspur
        video = tmp_path / "vod.mkv"
        proc = default_run(
            [
                shutil.which("ffmpeg"), "-y", "-v", "error",
                "-f", "lavfi", "-i", "color=c=black:s=160x120:d=60:r=5",
                "-i", str(src_wav),
                "-map", "0:v", "-map", "1:a",
                "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                "-shortest", str(video),
            ],
            timeout=180,
        )
        assert proc.returncode == 0, proc.stderr
        # Ingest wie in der echten Pipeline
        wav = tmp_path / "audio_16k.wav"
        extract_audio(video, wav)
        samples, got_sr = read_wav_mono(wav)
        found = detect_reactions(samples, got_sr)
        assert found, "Burst im echten Pfad nicht gefunden"
        assert any(abs(r.t - 31.0) <= 2.0 for r in found)
