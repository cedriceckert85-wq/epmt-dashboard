"""The JSON extractor is load-bearing: the editorial brain only works if we can
pull JSON back out of a chatty CLI's stdout, whether it returns an object OR an
array. The array case regressed once (it grabbed the first array element), so it
is pinned here."""
from clip_lab.llm_client import LLMClient, _extract_json


def test_extract_plain_object():
    assert _extract_json('{"a": 1, "b": 2}') == {"a": 1, "b": 2}


def test_extract_object_wrapped_in_prose():
    out = _extract_json('Sure, here you go:\n{"ok": true}\nHope that helps!')
    assert out == {"ok": True}


def test_extract_top_level_array_not_first_element():
    # Regression: must return the whole array, not just its first object.
    text = 'Here is the plan:\n[{"t0": 1}, {"t0": 2}, {"t0": 3}]\ndone'
    out = _extract_json(text)
    assert isinstance(out, list)
    assert [o["t0"] for o in out] == [1, 2, 3]


def test_extract_ignores_braces_inside_strings():
    out = _extract_json('{"text": "a } weird { string", "n": 5}')
    assert out == {"text": "a } weird { string", "n": 5}


def test_extract_handles_escaped_quotes():
    out = _extract_json(r'{"q": "she said \"hi\"", "n": 1}')
    assert out == {"q": 'she said "hi"', "n": 1}


def test_extract_nested_structures():
    out = _extract_json('noise {"a": [1, {"b": 2}], "c": {"d": 3}} noise')
    assert out == {"a": [1, {"b": 2}], "c": {"d": 3}}


def test_extract_returns_none_on_garbage():
    assert _extract_json("no json here at all") is None
    assert _extract_json("") is None


def test_extract_skips_malformed_then_finds_valid():
    # first '{' opens an incomplete block; a later valid object should win
    out = _extract_json('{oops not json ... then {"good": 1}')
    assert out == {"good": 1}


def test_client_runner_object():
    c = LLMClient(["x"], runner=lambda p: '{"hello": "world"}')
    assert c.available() is True
    assert c.ask_json("anything") == {"hello": "world"}


def test_client_runner_returns_none_on_bad():
    c = LLMClient(["x"], runner=lambda p: "totally not json")
    assert c.ask_json("anything") is None


def test_client_missing_binary_unavailable():
    c = LLMClient(["definitely-not-a-real-binary-xyz"])
    assert c.available() is False
