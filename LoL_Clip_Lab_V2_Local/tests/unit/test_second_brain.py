"""The second editorial brain (e.g. Codex): both brains judge the SAME clips,
agreement is averaged, extra finds are adopted, and every failure mode leaves
the primary result untouched."""
from clip_lab.config import Config
from clip_lab.editorial import run_editorial, _blend_second_opinion
from clip_lab.llm_client import LLMClient
from clip_lab.models import Candidate


def cfg(**kw):
    c = Config()
    c.use_llm = True
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def brain(moment_json, session_json='{"running_gags": []}'):
    def runner(prompt):
        if "CANDIDATE WINDOWS" in prompt:
            return moment_json
        return session_json
    return LLMClient(["x"], runner=runner)


def test_agreement_averages_scores():
    cands = [Candidate(t0=100.0, t1=100.0, signal_score=3)]
    a = brain('[{"t0": 90, "t1": 110, "semantic_score": 6, "title": "T", "why": "w"}]')
    b = brain('[{"t0": 90, "t1": 110, "semantic_score": 10}]')
    out, source, _ = run_editorial(cands, "log", a, cfg(), llm_b=b)
    assert source == "llm+2nd"
    assert out[0].semantic_score == 8.0            # (6+10)/2
    assert "[2nd opinion: 10/10]" in out[0].why


def test_second_brain_discovers_new_window():
    cands = [Candidate(t0=100.0, t1=100.0, signal_score=3)]
    a = brain('[{"t0": 90, "t1": 110, "semantic_score": 6}]')
    b = brain('[{"t0": 90, "t1": 110, "semantic_score": 6}, '
              '{"t0": 500, "t1": 520, "semantic_score": 9, "title": "B find"}]')
    out, _, _ = run_editorial(cands, "log", a, cfg(), llm_b=b)
    found = [c for c in out if c.title == "B find"]
    assert len(found) == 1
    assert found[0].editorial_source == "llm"


def test_second_brain_adopts_candidate_primary_skipped():
    cands = [Candidate(t0=100.0, t1=100.0, signal_score=3),
             Candidate(t0=500.0, t1=500.0, signal_score=2)]
    a = brain('[{"t0": 90, "t1": 110, "semantic_score": 6}]')     # skips 500
    b = brain('[{"t0": 490, "t1": 510, "semantic_score": 7, "title": "late"}]')
    out, _, _ = run_editorial(cands, "log", a, cfg(), llm_b=b)
    late = [c for c in out if c.t0 == 500.0][0]
    assert late.semantic_score == 7
    assert late.title == "late"


def test_bad_second_brain_keeps_primary_result():
    cands = [Candidate(t0=100.0, t1=100.0, signal_score=3)]
    a = brain('[{"t0": 90, "t1": 110, "semantic_score": 6}]')
    b = brain("total garbage, no json")
    out, source, _ = run_editorial(cands, "log", a, cfg(), llm_b=b)
    assert source == "llm"                          # blend skipped
    assert out[0].semantic_score == 6


def test_no_second_brain_unchanged():
    cands = [Candidate(t0=100.0, t1=100.0, signal_score=3)]
    a = brain('[{"t0": 90, "t1": 110, "semantic_score": 6}]')
    out, source, _ = run_editorial(cands, "log", a, cfg(), llm_b=None)
    assert source == "llm"


def test_blend_tolerates_junk_moments():
    c = Candidate(t0=100.0, t1=100.0, signal_score=3, semantic_score=6,
                  editorial_source="llm", why="w")
    _blend_second_opinion([c], ["nope", {"t0": None}, {"t0": 5, "t1": 1},
                               {"t0": 90, "t1": 110, "semantic_score": None,
                                "callback_refs": None}])
    assert c.semantic_score == 3.0                  # (6+0)/2, None -> 0, no crash


def test_null_callback_refs_do_not_crash_apply():
    # regression: "callback_refs": null used to TypeError in _apply_moments
    cands = [Candidate(t0=100.0, t1=100.0, signal_score=3)]
    a = brain('[{"t0": 90, "t1": 110, "semantic_score": 6, "callback_refs": null}]')
    out, _, _ = run_editorial(cands, "log", a, cfg())
    assert out[0].callback_refs == []


def test_llm_client_prompt_as_argument():
    # "{prompt}" placeholder passes the prompt as an argument instead of stdin
    c = LLMClient(["echo", "{prompt}"], timeout_s=10)
    assert c.available()
    assert c.ask_json('{"a": 1}') == {"a": 1}


def test_doctor_shows_second_brain_row():
    from clip_lab.doctor import run_doctor
    c = cfg(llm_cmd_b=["definitely-missing-cli"])
    ok, rows = run_doctor(c)
    names = [r[0] for r in rows]
    assert any("2nd LLM" in n for n in names)


def test_cli_fetch_without_ytdlp(tmp_path, monkeypatch):
    import clip_lab.util as util
    from clip_lab.cli import main
    monkeypatch.setattr(util, "which", lambda n: None)
    assert main(["fetch", "https://example.com/v"]) == 2
