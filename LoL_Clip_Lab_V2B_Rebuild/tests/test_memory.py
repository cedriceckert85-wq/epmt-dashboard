"""F6: Kanal-Gedaechtnis — Zaehler, Re-Analyse, Korruption, Konsolidierung."""

from __future__ import annotations

import json

import pytest

from cliplab.config import Config
from cliplab.editorial import SessionInsights
from cliplab.memory import CONSOLIDATE_MARKER, BrainStore, fresh_brain, sanitize_brain
from tests.conftest import FakeRunner, make_moment


@pytest.fixture
def store(tmp_path, cfg):
    return BrainStore(tmp_path / "memory.json", cfg, now_fn=lambda: "2026-01-01")


def insights_with_gag(name="Der Busch", summary="Zusammenfassung"):
    ins = SessionInsights()
    ins.running_gags = [{"name": name, "first_t": 10.0, "note": "n"}]
    ins.catchphrases = ["Ich habs gesagt"]
    ins.lore = ["Smurf heisst Buschangst"]
    ins.summary = summary
    return ins


class TestBasics:
    def test_fresh_when_missing(self, store):
        brain = store.load()
        assert brain["gags"] == [] and brain["sessions"] == {}

    def test_new_gag_created(self, store):
        brain, report = store.update_after_session(
            store.load(), "vod1.mkv", insights_with_gag(), []
        )
        assert brain["gags"][0]["times_seen"] == 1
        assert brain["gags"][0]["first_seen"] == "vod1.mkv"
        assert any("neuer Gag" in r for r in report)

    def test_save_load_roundtrip(self, store):
        brain, _ = store.update_after_session(store.load(), "vod1.mkv", insights_with_gag(), [])
        store.save(brain)
        loaded = store.load()
        assert loaded["gags"][0]["name"] == "Der Busch"
        assert "vod1.mkv" in loaded["sessions"]

    def test_second_session_bumps(self, store):
        b, _ = store.update_after_session(store.load(), "vod1.mkv", insights_with_gag(), [])
        b, report = store.update_after_session(b, "vod2.mkv", insights_with_gag(), [])
        assert b["gags"][0]["times_seen"] == 2
        assert b["gags"][0]["last_seen"] == "vod2.mkv"
        assert any("wiedererkannt" in r for r in report)

    def test_reanalysis_same_vod_no_bump(self, store):
        # Pflicht-Invariante: gleiche VOD nochmal -> KEIN Zaehler-Bump
        b, _ = store.update_after_session(store.load(), "vod1.mkv", insights_with_gag(), [])
        b, report = store.update_after_session(
            b, "vod1.mkv", insights_with_gag(summary="neue Summary"), []
        )
        assert b["gags"][0]["times_seen"] == 1
        assert any("Summary-Refresh" in r for r in report)

    def test_reanalysis_refreshes_summary(self, store):
        b, _ = store.update_after_session(store.load(), "vod1.mkv", insights_with_gag(), [])
        b, _ = store.update_after_session(
            b, "vod1.mkv", insights_with_gag(summary="NEU"), []
        )
        entry = [s for s in b["summaries"] if s["vod"] == "vod1.mkv"]
        assert len(entry) == 1 and entry[0]["summary"] == "NEU"

    def test_lore_refs_count_as_sighting(self, store):
        b, _ = store.update_after_session(store.load(), "vod1.mkv", insights_with_gag(), [])
        moment = make_moment(10, 20, lore_refs=["Der Busch"])
        b, _ = store.update_after_session(b, "vod2.mkv", SessionInsights(), [moment])
        assert b["gags"][0]["times_seen"] == 2

    def test_max_one_bump_per_gag_per_session(self, store):
        b, _ = store.update_after_session(store.load(), "vod1.mkv", insights_with_gag(), [])
        moments = [
            make_moment(10, 20, lore_refs=["Der Busch"]),
            make_moment(30, 40, lore_refs=["Der Busch"]),
        ]
        b, _ = store.update_after_session(b, "vod2.mkv", insights_with_gag(), moments)
        assert b["gags"][0]["times_seen"] == 2  # genau EIN Bump

    def test_llm2_lore_refs_ignored(self, store):
        # Gedaechtnis bleibt Primaer-only (F9)
        b, _ = store.update_after_session(store.load(), "vod1.mkv", insights_with_gag(), [])
        moment = make_moment(10, 20, lore_refs=["Der Busch"], source="llm2")
        b, _ = store.update_after_session(b, "vod2.mkv", SessionInsights(), [moment])
        assert b["gags"][0]["times_seen"] == 1

    def test_catchphrases_and_lore_collected(self, store):
        b, _ = store.update_after_session(store.load(), "vod1.mkv", insights_with_gag(), [])
        assert "Ich habs gesagt" in b["catchphrases"]
        assert "Smurf heisst Buschangst" in b["lore"]

    def test_clear(self, store):
        store.save(fresh_brain())
        assert store.path.is_file()
        assert store.clear() is True
        assert not store.path.is_file()
        assert store.clear() is False


class TestCaps:
    def test_gag_cap(self, store, cfg):
        b = store.load()
        for i in range(cfg.memory_max_gags + 20):
            ins = insights_with_gag(name=f"Gag Nummer {i}")
            b, _ = store.update_after_session(b, f"vod{i}.mkv", ins, [])
        assert len(b["gags"]) <= cfg.memory_max_gags

    def test_summary_cap(self, store, cfg):
        b = store.load()
        for i in range(cfg.memory_max_summaries + 5):
            b, _ = store.update_after_session(b, f"vod{i}.mkv", insights_with_gag(), [])
        assert len(b["summaries"]) <= cfg.memory_max_summaries


class TestCorruption:
    def test_invalid_json_fresh(self, store):
        store.path.write_text("{kaputt::::", encoding="utf-8")
        assert store.load() == fresh_brain()

    def test_non_dict_fresh(self, store):
        store.path.write_text('["liste", "statt", "dict"]', encoding="utf-8")
        assert store.load() == fresh_brain()

    def test_infinity_counter_cleaned(self, store):
        store.path.write_text(
            '{"gags":[{"name":"G","times_seen":Infinity}]}', encoding="utf-8"
        )
        b = store.load()
        assert isinstance(b["gags"][0]["times_seen"], int)
        assert b["gags"][0]["times_seen"] >= 1

    def test_strings_instead_of_dicts_cleaned(self, store):
        store.path.write_text('{"gags":["nur ein string"]}', encoding="utf-8")
        b = store.load()
        assert b["gags"][0]["name"] == "nur ein string"
        assert b["gags"][0]["times_seen"] == 1

    def test_deep_nesting_no_crash(self, store):
        deep = '{"gags":' + "[" * 5000 + "]" * 5000 + "}"
        store.path.write_text(deep, encoding="utf-8")
        b = store.load()  # darf nicht crashen
        assert isinstance(b, dict)

    def test_hostile_mixed_garbage(self, store):
        store.path.write_text(
            json.dumps(
                {
                    "version": "boese",
                    "gags": [
                        {"name": 42},
                        {"name": "OK", "times_seen": -99, "note": ["liste"]},
                        None,
                        {"name": "Zwei\nZeilen", "times_seen": 3.7},
                    ],
                    "catchphrases": {"kein": "array"},
                    "lore": [1, 2, "echt"],
                    "sessions": {"vod": "2026-01-01", "auch_ok": {"analyzed_at": "x"}},
                    "summaries": [{"vod": "v", "summary": "s"}, "muell"],
                }
            ),
            encoding="utf-8",
        )
        b = store.load()
        names = [g["name"] for g in b["gags"]]
        assert "OK" in names and "Zwei Zeilen" in names
        assert all(g["times_seen"] >= 1 for g in b["gags"])
        assert b["catchphrases"] == []
        assert "echt" in b["lore"]  # Zahlen werden zu Strings bereinigt, "echt" bleibt
        assert set(b["sessions"]) == {"vod", "auch_ok"}
        assert len(b["summaries"]) == 1

    def test_duplicate_slugs_deduped(self, store):
        store.path.write_text(
            '{"gags":[{"name":"Der Busch"},{"name":"der busch"}]}', encoding="utf-8"
        )
        assert len(store.load()["gags"]) == 1

    def test_sanitize_brain_non_dict(self, cfg):
        assert sanitize_brain(None, cfg) == fresh_brain()
        assert sanitize_brain("x", cfg) == fresh_brain()


class TestConsolidation:
    def test_llm_mapping_by_meaning(self, store):
        b, _ = store.update_after_session(store.load(), "vod1.mkv", insights_with_gag("Der Busch"), [])
        runner = FakeRunner(
            by_marker={
                CONSOLIDATE_MARKER: json.dumps(
                    [{"new": "Jonas' Buschfluch", "matches": "der_busch"}]
                )
            }
        )
        ins = insights_with_gag("Jonas' Buschfluch")
        b, _ = store.update_after_session(b, "vod2.mkv", ins, [], runner=runner)
        # anders formuliert, aber per Bedeutung gemappt -> Bump statt Duplikat
        assert len(b["gags"]) == 1 and b["gags"][0]["times_seen"] == 2

    def test_llm_explicit_new(self, store):
        b, _ = store.update_after_session(store.load(), "vod1.mkv", insights_with_gag("Der Busch"), [])
        runner = FakeRunner(
            by_marker={
                CONSOLIDATE_MARKER: json.dumps([{"new": "Voellig Anders", "matches": None}])
            }
        )
        b, _ = store.update_after_session(
            b, "vod2.mkv", insights_with_gag("Voellig Anders"), [], runner=runner
        )
        assert len(b["gags"]) == 2

    def test_mechanical_fallback_slug_match(self, store):
        b, _ = store.update_after_session(store.load(), "vod1.mkv", insights_with_gag("Der Busch!"), [])
        # LLM antwortet Muell -> mechanischer Fallback (Slug-Gleichheit)
        runner = FakeRunner(by_marker={CONSOLIDATE_MARKER: "kein json"})
        b, _ = store.update_after_session(
            b, "vod2.mkv", insights_with_gag("der busch"), [], runner=runner
        )
        assert len(b["gags"]) == 1 and b["gags"][0]["times_seen"] == 2

    def test_mechanical_containment(self, store):
        b, _ = store.update_after_session(
            store.load(), "vod1.mkv", insights_with_gag("Der verfluchte Busch"), []
        )
        b, _ = store.update_after_session(
            b, "vod2.mkv", insights_with_gag("verfluchte busch"), [], runner=None
        )
        assert len(b["gags"]) == 1 and b["gags"][0]["times_seen"] == 2

    def test_llm_hallucinated_slug_ignored(self, store):
        b, _ = store.update_after_session(store.load(), "vod1.mkv", insights_with_gag("Der Busch"), [])
        runner = FakeRunner(
            by_marker={
                CONSOLIDATE_MARKER: json.dumps(
                    [{"new": "Der Busch", "matches": "gibts_nicht_slug"}]
                )
            }
        )
        b, _ = store.update_after_session(
            b, "vod2.mkv", insights_with_gag("Der Busch"), [], runner=runner
        )
        # Fallback: mechanisch gematcht -> Bump
        assert b["gags"][0]["times_seen"] == 2

    def test_consolidation_runner_exception_safe(self, store):
        def boom(prompt):
            raise RuntimeError("kaputt")

        b, _ = store.update_after_session(store.load(), "vod1.mkv", insights_with_gag(), [])
        b, _ = store.update_after_session(b, "vod2.mkv", insights_with_gag(), [], runner=boom)
        assert b["gags"][0]["times_seen"] == 2  # mechanischer Fallback


class TestRenderBlock:
    def test_empty_brain_empty_block(self, store):
        assert store.render_block(fresh_brain()) == ""

    def test_block_contains_counts(self, store):
        b, _ = store.update_after_session(store.load(), "vod1.mkv", insights_with_gag(), [])
        block = store.render_block(b)
        assert "Der Busch" in block and "1x gesehen" in block
        assert "Ich habs gesagt" in block
        assert "vod1.mkv" in block

    def test_save_failure_silent(self, tmp_path, cfg):
        blocker = tmp_path / "datei"
        blocker.write_text("x", encoding="utf-8")
        store = BrainStore(blocker / "geht_nicht.json", cfg)
        store.save(fresh_brain())  # Elternpfad ist eine Datei — darf nicht werfen
