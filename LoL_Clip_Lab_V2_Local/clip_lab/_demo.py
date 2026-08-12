"""A canned, deterministic 'LLM' for the offline self-test and unit tests.

The real editorial brain calls `claude -p` (or any CLI in config). That needs
the network / a local model and is non-deterministic, so it is unsuitable for a
self-test that must run anywhere and always give the same result.

This module fakes exactly that CLI's contract: it takes the same prompts the
editorial stage builds and returns the same JSON shape a good editor-LLM would.
The timestamps line up with `samples/fixture_transcript.json` +
`samples/fixture_events.json`, so `clip_lab selftest` shows the full creative
output — funny titles, punchline-aware cuts, captions, SFX, callbacks — without
any network, whisper, or ffmpeg. It is a DEMO of the format, not a substitute
for the real model's judgement.
"""
import json

from .llm_client import LLMClient


def _session_reply():
    return {
        "running_gags": [
            "\"I'll hit a Q eventually\" — keeps whiffing skillshots early",
            "Blaming the wall for every failed flash",
        ],
        "callbacks": [
            {"setup_t": 80.0, "payoff_t": 1332.0,
             "what": "early 'I'll hit one eventually' pays off on the pentakill"},
        ],
        "arcs": [
            "From griefing his own skillshots to a hard-carry pentakill",
        ],
        "notes": "The penta at the end lands hardest because of the early running gag.",
    }


def _moment_reply():
    # Tuple layout mirrors what a strong editor-LLM would return. Timestamps
    # match the bundled fixtures; some windows have a game event (matched to a
    # signal candidate), two are pure-talk windows the model 'discovered'.
    return [
        {"t0": 140.0, "t1": 165.0, "category": "hype", "semantic_score": 7.5,
         "punchline_t": 152.0, "title": "First Blood, Finally",
         "why": "The payoff after two minutes of whiffing every skillshot.",
         "callback_refs": [80.0],
         "captions": [{"t": 151.0, "text": "he actually hit one"}],
         "zooms": [{"t": 152.0, "duration": 1.5}],
         "sfx": [{"t": 152.5, "kind": "airhorn"}]},

        {"t0": 182.0, "t1": 205.0, "category": "fail", "semantic_score": 8.0,
         "punchline_t": 194.0, "title": "Flashed Into The Wall",
         "why": "Confidently flashes into terrain, immediately regrets it.",
         "callback_refs": [],
         "captions": [{"t": 195.0, "text": "why is there a wall THERE"}],
         "zooms": [{"t": 194.0, "duration": 1.2}],
         "sfx": [{"t": 194.5, "kind": "vine_boom"}]},

        {"t0": 486.0, "t1": 520.0, "category": "clutch", "semantic_score": 9.2,
         "punchline_t": 505.0, "title": "1v3 Outplay, Are You Kidding",
         "why": "Written off as dead, turns and triples the whole gank.",
         "callback_refs": [],
         "captions": [{"t": 500.0, "text": "im dead im dead — WAIT"}],
         "zooms": [{"t": 505.0, "duration": 2.0}],
         "sfx": [{"t": 505.0, "kind": "bruh"}]},

        {"t0": 700.0, "t1": 730.0, "category": "funny", "semantic_score": 7.0,
         "punchline_t": 718.0, "title": "Told You I'd Hit The Q",
         "why": "Smug callback to the early running gag after one good Q.",
         "callback_refs": [80.0],
         "captions": [{"t": 718.0, "text": "see? SEE?"}],
         "zooms": [],
         "sfx": [{"t": 718.0, "kind": "ding"}]},

        {"t0": 1320.0, "t1": 1350.0, "category": "hype", "semantic_score": 9.8,
         "punchline_t": 1338.0, "title": "PENTAKILL (I Hit All Of Them)",
         "why": "The whole running gag resolves on a clean pentakill.",
         "callback_refs": [80.0, 718.0],
         "captions": [{"t": 1338.0, "text": "I HIT ALL OF THEM"}],
         "zooms": [{"t": 1338.0, "duration": 2.5}],
         "sfx": [{"t": 1338.0, "kind": "airhorn"}]},
    ]


def _memory_reply(prompt):
    """Canned memory consolidation: if the CURRENT MEMORY in the prompt already
    knows the Q gag, bump times_seen — demonstrating that a returning gag gets
    counted up instead of duplicated."""
    current = prompt.split("CURRENT MEMORY:", 1)[-1].split("TODAY'S SESSION", 1)[0]
    seen = 2 if "hit a Q eventually" in current else 1
    mem = {
        "version": 1,
        "sessions_analyzed": seen,
        "gags": [
            {"name": "I'll hit a Q eventually",
             "description": "whiffs every skillshot early, swears the hit is coming",
             "times_seen": seen, "first_seen": "sample_vod.mkv",
             "last_seen": "sample_vod.mkv"},
            {"name": "Blaming the wall",
             "description": "every failed flash is the wall's fault",
             "times_seen": seen, "first_seen": "sample_vod.mkv",
             "last_seen": "sample_vod.mkv"},
        ],
        "catchphrases": ["clip that, somebody clip that right now"],
        "lore": ["The pentakill where he finally hit all his Qs"],
        "sessions": [{"vod": "sample_vod.mkv", "date": "demo",
                      "summary": "From whiffed Qs to a pentakill."}],
    }
    return "Memory updated:\n" + json.dumps(mem, ensure_ascii=False)


def demo_runner(prompt):
    """Emulate a CLI that prints JSON on stdout (with a little prose around it,
    to exercise the client's JSON extraction)."""
    if "LONG-TERM MEMORY" in prompt:
        return _memory_reply(prompt)
    if "CANDIDATE WINDOWS" in prompt:
        moments = _moment_reply()
        # when the channel brain already knows the gags (2nd+ session), tag the
        # continuations so the edit sheet shows the lore connection
        if "CHANNEL MEMORY (from PREVIOUS streams" in prompt:
            for m in moments:
                if m["title"].startswith(("PENTAKILL", "Told You")):
                    m["lore_refs"] = ["I'll hit a Q eventually"]
        body = json.dumps(moments, ensure_ascii=False)
        return "Sure! Here is the edit plan:\n" + body + "\nHope that helps."
    body = json.dumps(_session_reply(), ensure_ascii=False)
    return "Here's the session read:\n" + body


def demo_llm():
    """An LLMClient wired to the canned runner — behaves like an available CLI."""
    return LLMClient(["demo"], timeout_s=5, runner=demo_runner)
