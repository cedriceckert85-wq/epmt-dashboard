"""The session pass must read the WHOLE stream script, no matter how long —
long sessions are chunked with findings carried forward and merged. The moment
pass gets focused log windows around each candidate plus an even sample of the
rest. These tests pin that scaling behavior (the old code truncated the script
at 24k chars, silently dropping most of a long VOD)."""
from clip_lab.config import Config
from clip_lab.models import Candidate
from clip_lab.editorial import (_chunk_lines, _merge_context, _parse_ts,
                                _relevant_log, _session_pass, run_editorial)
from clip_lab.llm_client import LLMClient


def cfg(**kw):
    c = Config()
    for k, v in kw.items():
        setattr(c, k, v)
    return c


# ---------- chunking ----------

def test_small_doc_is_one_chunk():
    assert _chunk_lines("a\nb\nc", 1000) == ["a\nb\nc"]


def test_chunks_split_on_line_boundaries_and_cover_everything():
    lines = [f"[{i}:00.00] SPEECH: line number {i}" for i in range(200)]
    doc = "\n".join(lines)
    chunks = _chunk_lines(doc, 500)
    assert len(chunks) > 1
    for ch in chunks:
        assert len(ch) <= 500
    # nothing lost, nothing reordered, no line cut in half
    assert "\n".join(chunks).splitlines() == lines


def test_overlong_single_line_gets_own_chunk():
    doc = "short\n" + ("x" * 900) + "\nshort2"
    chunks = _chunk_lines(doc, 100)
    assert any(len(c) > 100 for c in chunks)      # the long line survives whole
    assert "\n".join(chunks).splitlines() == doc.splitlines()


# ---------- context merging ----------

def test_merge_dedupes_lists_and_joins_notes():
    a = {"running_gags": ["gag A"], "callbacks": [{"setup_t": 80, "payoff_t": 900}],
         "notes": "first"}
    b = {"running_gags": ["gag A", "gag B"],
         "callbacks": [{"setup_t": 80, "payoff_t": 900},
                       {"setup_t": 10, "payoff_t": 50}],
         "notes": "second"}
    m = _merge_context(a, b)
    assert m["running_gags"] == ["gag A", "gag B"]
    assert len(m["callbacks"]) == 2
    assert m["notes"] == "first | second"


def test_merge_from_empty_is_identity():
    b = {"running_gags": ["g"], "arcs": ["a"]}
    assert _merge_context({}, b) == b


# ---------- whole-script session pass ----------

def test_long_session_is_sent_in_full_across_chunks():
    # a "long" session: 60 lines, chunk budget forces several chunks
    lines = [f"[{i}:00.00] SPEECH: minute {i} banter" for i in range(60)]
    doc = "\n".join(lines)
    seen_logs = []

    def runner(prompt):
        # capture the log portion of each session call
        seen_logs.append(prompt)
        return '{"running_gags": ["gag %d"]}' % len(seen_logs)

    llm = LLMClient(["x"], runner=runner)
    ctx = _session_pass(llm, doc, cfg(llm_session_chunk_chars=400), log=lambda *a: None)
    assert len(seen_logs) > 1                       # actually chunked
    # every single line of the script reached the LLM in some chunk
    joined = "\n".join(seen_logs)
    for ln in lines:
        assert ln in joined
    # findings from all chunks merged
    assert len(ctx["running_gags"]) == len(seen_logs)


def test_later_chunks_carry_earlier_findings():
    lines = [f"[{i}:00.00] SPEECH: minute {i}" for i in range(40)]
    doc = "\n".join(lines)
    prompts = []

    def runner(prompt):
        prompts.append(prompt)
        return '{"running_gags": ["the Q gag"]}'

    llm = LLMClient(["x"], runner=runner)
    _session_pass(llm, doc, cfg(llm_session_chunk_chars=300), log=lambda *a: None)
    assert len(prompts) >= 2
    assert "FINDINGS FROM EARLIER PARTS" not in prompts[0]
    assert "the Q gag" in prompts[1]                # carried forward


def test_bad_chunk_json_does_not_kill_the_rest():
    lines = [f"[{i}:00.00] SPEECH: minute {i}" for i in range(40)]
    doc = "\n".join(lines)
    calls = []

    def runner(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return "no json at all"                 # first chunk fails
        return '{"running_gags": ["late gag"]}'

    llm = LLMClient(["x"], runner=runner)
    ctx = _session_pass(llm, doc, cfg(llm_session_chunk_chars=300), log=lambda *a: None)
    assert ctx.get("running_gags") == ["late gag"]  # later chunks still counted


# ---------- moment-pass relevant log ----------

def _long_doc(n_lines=400):
    return "\n".join(f"[{i}:00.00] SPEECH: minute {i} of the stream, some banter"
                     for i in range(n_lines))


def test_relevant_log_passthrough_when_small():
    doc = "[1:00.00] SPEECH: hi"
    assert _relevant_log(doc, [], window_s=90, max_chars=1000) == doc


def test_relevant_log_keeps_candidate_context_even_late_in_vod():
    doc = _long_doc(400)                            # ~24k chars
    late = Candidate(t0=380 * 60.0, t1=380 * 60.0, signal_score=5)
    out = _relevant_log(doc, [late], window_s=90, max_chars=3000)
    assert len(out) <= 3000 * 1.2
    # the lines around minute 380 must be present despite the tight budget
    assert "minute 380 " in out
    assert "minute 379 " in out or "minute 381 " in out


def test_relevant_log_samples_rest_for_discovery():
    doc = _long_doc(400)
    c = Candidate(t0=10 * 60.0, t1=10 * 60.0, signal_score=5)
    out = _relevant_log(doc, [c], window_s=60, max_chars=5000)
    # far-away material is sampled too (discovery), not just the candidate zone
    far = [ln for ln in out.splitlines()
           if _parse_ts(ln) is not None and _parse_ts(ln) > 100 * 60]
    assert far


def test_relevant_log_respects_budget():
    doc = _long_doc(1000)
    cands = [Candidate(t0=i * 100 * 60.0, t1=i * 100 * 60.0, signal_score=1)
             for i in range(10)]
    out = _relevant_log(doc, cands, window_s=90, max_chars=4000)
    assert len(out) <= 4000 * 1.2


def test_thinning_does_not_starve_sparse_late_candidate():
    # regression (found by fuzzing): when one dense candidate window blows the
    # budget, the old uniform-stride thinning could drop EVERY line of a sparse
    # late candidate. The fair-share split must keep its closest line.
    lines = [f"[{t//60}:{t%60:05.2f}] SPEECH: blah blah blah blah" for t in range(1800)]
    lines.append("[150:00.00] SPEECH: the only line near the late candidate")
    doc = "\n".join(lines)
    cands = [Candidate(t0=10.0, t1=1700.0, signal_score=1),       # dense, huge
             Candidate(t0=9000.0, t1=9000.0, signal_score=1)]     # sparse, late
    out = _relevant_log(doc, cands, window_s=30, max_chars=2000)
    assert len(out) <= 2000 * 1.2
    late_lines = [ln for ln in out.splitlines()
                  if (_parse_ts(ln) or 0) >= 9000 - 30 and (_parse_ts(ln) or 0) <= 9000 + 30]
    assert late_lines, "late sparse candidate must keep its context line"


def test_chunking_preserves_trailing_blank_line():
    # regression (found by fuzzing): a doc ending in a blank line lost that
    # line in the chunk/rejoin round-trip.
    doc = "a\n\n"
    chunks = _chunk_lines(doc, 2)
    assert "\n".join(chunks) == doc.rstrip("\n") + "\n" or "\n".join(chunks) == doc
    assert "\n".join(chunks).split("\n") == doc.split("\n")


def test_relevant_log_never_empty_for_nonempty_doc():
    # regression (found by fuzzing): all lines longer than the budget used to
    # return an empty string instead of any context at all.
    doc = "\n".join(f"[{i}:00.00] " + "Q" * 900 for i in range(200))
    out = _relevant_log(doc, [], window_s=30, max_chars=500)
    assert out
    assert len(out) <= 500 * 1.2


def test_parse_ts():
    assert _parse_ts("[22:12.00] GAME: penta") == 22 * 60 + 12.0
    assert _parse_ts("[130:05.50] SPEECH: late") == 130 * 60 + 5.5
    assert _parse_ts("no timestamp here") is None


# ---------- end to end: run_editorial still works with the new plumbing ----------

def test_run_editorial_long_doc_uses_llm():
    doc = _long_doc(300)
    cands = [Candidate(t0=150 * 60.0, t1=150 * 60.0, signal_score=3)]

    def runner(prompt):
        if "CANDIDATE WINDOWS" in prompt:
            return '[{"t0": %f, "t1": %f, "category": "funny", "title": "x"}]' % (
                150 * 60.0 - 10, 150 * 60.0 + 10)
        return '{"running_gags": ["gag"]}'

    llm = LLMClient(["x"], runner=runner)
    out, source, ctx = run_editorial(
        cands, doc, llm=llm,
        cfg=cfg(use_llm=True, llm_session_chunk_chars=2000, llm_moment_log_chars=3000))
    assert source == "llm"
    assert out[0].category == "funny"
