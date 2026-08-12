"""The channel brain: running gags must persist across sessions, counters must
bump instead of duplicating, corrupt files must not crash, LLM output must be
sanitized, and everything must degrade to the mechanical merge."""
import json

from clip_lab.config import Config
from clip_lab.llm_client import LLMClient
from clip_lab.memory import (empty_memory, load_memory, memory_brief,
                             save_memory, update_memory, _mechanical_merge)


def cfg(**kw):
    c = Config()
    for k, v in kw.items():
        setattr(c, k, v)
    return c


CTX = {"running_gags": ["I'll hit a Q eventually"],
       "arcs": ["from whiffing to a pentakill"],
       "notes": "penta pays off the gag"}


# ---------- load / save ----------

def test_missing_file_is_fresh_brain(tmp_path):
    mem = load_memory(tmp_path / "nope.json")
    assert mem == empty_memory()


def test_corrupt_file_is_fresh_brain(tmp_path):
    p = tmp_path / "m.json"
    p.write_text("{{{{ definitely not json", encoding="utf-8")
    assert load_memory(p) == empty_memory()


def test_wrong_types_are_dropped(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"gags": "not a list", "lore": ["ok"]}), encoding="utf-8")
    mem = load_memory(p)
    assert mem["gags"] == []          # bad type -> default
    assert mem["lore"] == ["ok"]      # good type -> kept


def test_roundtrip(tmp_path):
    p = tmp_path / "m.json"
    mem = _mechanical_merge(empty_memory(), CTX, "vod1.mkv", cfg(), "2026-08-12")
    save_memory(p, mem)
    assert load_memory(p) == mem


# ---------- mechanical merge ----------

def test_new_gag_is_learned():
    mem = _mechanical_merge(empty_memory(), CTX, "vod1.mkv", cfg(), "d")
    assert len(mem["gags"]) == 1
    g = mem["gags"][0]
    assert g["name"] == "I'll hit a Q eventually"
    assert g["times_seen"] == 1 and g["first_seen"] == "vod1.mkv"
    assert mem["sessions_analyzed"] == 1


def test_returning_gag_bumps_counter_not_duplicate():
    mem = _mechanical_merge(empty_memory(), CTX, "vod1.mkv", cfg(), "d")
    ctx2 = {"running_gags": ["i'll hit a q EVENTUALLY"]}   # different casing
    mem = _mechanical_merge(mem, ctx2, "vod2.mkv", cfg(), "d")
    assert len(mem["gags"]) == 1                            # no duplicate
    assert mem["gags"][0]["times_seen"] == 2
    assert mem["gags"][0]["last_seen"] == "vod2.mkv"
    assert mem["sessions_analyzed"] == 2


def test_gag_cap_keeps_most_seen():
    mem = empty_memory()
    mem = _mechanical_merge(mem, {"running_gags": ["keeper"]}, "v1", cfg(), "d")
    mem = _mechanical_merge(mem, {"running_gags": ["keeper"]}, "v2", cfg(), "d")
    many = {"running_gags": [f"one-off {i}" for i in range(60)]}
    mem = _mechanical_merge(mem, many, "v3", cfg(memory_max_gags=10), "d")
    assert len(mem["gags"]) == 10
    assert mem["gags"][0]["name"] == "keeper"               # most-seen survives first


def test_sessions_capped():
    mem = empty_memory()
    for i in range(30):
        mem = _mechanical_merge(mem, {}, f"v{i}", cfg(memory_max_sessions=5), "d")
    assert len(mem["sessions"]) == 5
    assert mem["sessions"][-1]["vod"] == "v29"
    assert mem["sessions_analyzed"] == 30                   # counter keeps counting


def test_junk_gags_ignored():
    mem = _mechanical_merge(empty_memory(),
                            {"running_gags": ["", "   ", 42, None, "real gag"]},
                            "v", cfg(), "d")
    assert [g["name"] for g in mem["gags"]] == ["real gag"]


# ---------- LLM consolidation ----------

def test_llm_consolidation_used_and_sanitized():
    def runner(prompt):
        return json.dumps({"version": 1, "sessions_analyzed": 3,
                           "gags": [{"name": "the Q gag", "times_seen": "7"},
                                    {"no_name": True},
                                    {"name": "x" * 500, "times_seen": -3}],
                           "catchphrases": ["hey", 123],
                           "lore": ["thing"],
                           "sessions": [{"vod": "v", "summary": "s"}]})
    llm = LLMClient(["x"], runner=runner)
    mem = update_memory(empty_memory(), CTX, "vod.mkv", llm, cfg(), today="d")
    names = [g["name"] for g in mem["gags"]]
    assert "the Q gag" in names
    assert all(len(n) <= 120 for n in names)                # clamped
    assert all(g["times_seen"] >= 1 for g in mem["gags"])   # clamped
    assert mem["catchphrases"] == ["hey"]                   # non-str dropped
    assert mem["sessions_analyzed"] == 3


def test_bad_llm_json_falls_back_to_mechanical():
    llm = LLMClient(["x"], runner=lambda p: "not json, sorry")
    mem = update_memory(empty_memory(), CTX, "vod.mkv", llm, cfg(), today="d")
    assert [g["name"] for g in mem["gags"]] == ["I'll hit a Q eventually"]
    assert mem["sessions_analyzed"] == 1


def test_no_llm_uses_mechanical():
    mem = update_memory(empty_memory(), CTX, "vod.mkv", None, cfg(), today="d")
    assert len(mem["gags"]) == 1


def test_memory_prompt_receives_current_memory():
    prompts = []
    def runner(prompt):
        prompts.append(prompt)
        return json.dumps({"version": 1, "sessions_analyzed": 2, "gags": []})
    start = _mechanical_merge(empty_memory(), CTX, "vod1", cfg(), "d")
    llm = LLMClient(["x"], runner=runner)
    update_memory(start, {"running_gags": ["new gag"]}, "vod2", llm, cfg(), today="d")
    assert len(prompts) == 1
    assert "I'll hit a Q eventually" in prompts[0]          # old brain visible
    assert "new gag" in prompts[0]                          # today's findings visible


# ---------- brief ----------

def test_brief_empty_for_fresh_brain():
    assert memory_brief(empty_memory()) == ""


def test_brief_lists_gags_and_respects_budget():
    mem = empty_memory()
    for i in range(30):
        mem = _mechanical_merge(mem, {"running_gags": [f"gag number {i}"]},
                                f"v{i}", cfg(), "d")
    brief = memory_brief(mem, max_chars=500)
    assert "gag number 0" in brief
    assert len(brief) <= 500
