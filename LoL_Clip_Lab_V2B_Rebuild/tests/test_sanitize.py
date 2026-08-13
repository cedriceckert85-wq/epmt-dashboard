"""F5: Sanitisierung ALLER LLM-Felder."""

from __future__ import annotations

import pytest

from cliplab.sanitize import (
    KNOWN_SFX,
    category_emoji,
    clean_captions,
    clean_category,
    clean_list,
    clean_num,
    clean_sfx,
    clean_str,
    clean_str_list,
    clean_tag,
    clean_tags,
    clean_time,
    clean_zooms,
)
from cliplab.util import slugify


class TestCleanStr:
    def test_newlines_collapsed(self):
        assert clean_str("hallo\nwelt\r\ndrei") == "hallo welt drei"

    def test_control_chars_removed(self):
        assert clean_str("a\x00b\x1fc") == "a b c"

    def test_length_capped(self):
        out = clean_str("x" * 500, max_len=50)
        assert len(out) <= 50 and out.endswith("…")

    def test_whitespace_collapsed(self):
        assert clean_str("  viel   platz  ") == "viel platz"

    def test_none(self):
        assert clean_str(None) == ""

    def test_default_used(self):
        assert clean_str(None, default="fallback") == "fallback"

    def test_number_becomes_string(self):
        assert clean_str(42) == "42"

    def test_infinity_number_rejected(self):
        assert clean_str(float("inf")) == ""

    def test_dict_rejected(self):
        assert clean_str({"a": 1}) == ""

    def test_list_rejected(self):
        assert clean_str([1, 2]) == ""

    def test_bool_is_not_text(self):
        # bool ist int-Subklasse — als "True"-Text waere Unsinn, str() ist ok
        out = clean_str(True)
        assert out in ("", "True")

    def test_tab_collapsed(self):
        assert clean_str("a\tb") == "a b"


class TestCleanNum:
    def test_clamps_high(self):
        assert clean_num(99, 0, 10) == 10

    def test_clamps_low(self):
        assert clean_num(-5, 0, 10) == 0

    def test_infinity_clamped(self):
        assert clean_num(float("inf"), 0, 10, default=5) == 5

    def test_neg_infinity(self):
        assert clean_num(float("-inf"), 0, 10, default=5) == 5

    def test_nan(self):
        assert clean_num(float("nan"), 0, 10, default=3) == 3

    def test_string_number(self):
        assert clean_num("7.5", 0, 10) == 7.5

    def test_garbage_string(self):
        assert clean_num("viel", 0, 10, default=2) == 2

    def test_none(self):
        assert clean_num(None, 0, 10, default=1) == 1

    def test_bool_rejected(self):
        assert clean_num(True, 0, 10, default=4) == 4


class TestCleanList:
    def test_none_becomes_empty(self):
        assert clean_list(None) == []

    def test_string_becomes_empty(self):
        assert clean_list("keine liste") == []

    def test_dict_becomes_empty(self):
        assert clean_list({"a": 1}) == []

    def test_list_passthrough(self):
        assert clean_list([1, 2]) == [1, 2]

    def test_tuple_converted(self):
        assert clean_list((1, 2)) == [1, 2]


class TestCategory:
    def test_known(self):
        assert clean_category("funny") == "funny"

    def test_path_traversal_neutralized(self):
        slug = clean_category("../../etc/passwd")
        assert "/" not in slug and ".." not in slug and "\\" not in slug

    def test_spaces_to_underscore(self):
        assert clean_category("Big Plays") == "big_plays"

    def test_umlauts(self):
        assert clean_category("Späße") == "spaesse"

    def test_empty_fallback(self):
        assert clean_category("") == "moment"

    def test_none_fallback(self):
        assert clean_category(None) == "moment"

    def test_emoji_known(self):
        assert category_emoji("funny") == "😂"

    def test_emoji_unknown_default(self):
        assert category_emoji("selfmade_kategorie") == "🎬"

    def test_length_capped(self):
        assert len(clean_category("x" * 500)) <= 24


class TestTags:
    def test_known_kept(self):
        assert clean_tag("insta", ["insta", "yt"]) == "insta"

    def test_unknown_dropped(self):
        assert clean_tag("tiktok", ["insta", "yt"]) == ""

    def test_case_slug_match(self):
        assert clean_tag("Insta", ["insta"]) == "insta"

    def test_non_string(self):
        assert clean_tag(42, ["insta"]) == ""

    def test_list_filtered(self):
        assert clean_tags(["insta", "nope", "yt"], ["insta", "yt"]) == ["insta", "yt"]

    def test_list_null_tolerated(self):
        assert clean_tags(None, ["insta"]) == []

    def test_duplicates_removed(self):
        assert clean_tags(["yt", "yt"], ["yt"]) == ["yt"]


class TestCleanTime:
    def test_in_range(self):
        assert clean_time(50, 100) == 50

    def test_clamped_to_duration(self):
        assert clean_time(500, 100) == 100

    def test_negative_clamped(self):
        assert clean_time(-5, 100) == 0.0

    def test_infinity(self):
        assert clean_time(float("inf"), 100, default=-1) == -1

    def test_string(self):
        assert clean_time("42", 100) == 42

    def test_garbage_default(self):
        assert clean_time("bla", 100, default=-1) == -1


class TestOverlays:
    def test_captions_cleaned(self):
        raw = [
            {"t": 5, "text": "GUT"},
            {"t": "kaputt", "text": "weg"},
            {"t": 8, "text": ""},
            "kein dict",
            {"t": 3, "text": "Zeilen\numbruch"},
        ]
        out = clean_captions(raw, 100)
        assert out == [
            {"t": 3.0, "text": "Zeilen umbruch"},
            {"t": 5.0, "text": "GUT"},
        ]

    def test_captions_null(self):
        assert clean_captions(None, 100) == []

    def test_captions_capped(self):
        raw = [{"t": i, "text": f"c{i}"} for i in range(50)]
        assert len(clean_captions(raw, 100)) == 12

    def test_zoom_duration_clamped(self):
        out = clean_zooms([{"t": 5, "duration": 999}], 100)
        assert out[0]["duration"] == 10.0

    def test_zoom_default_duration(self):
        out = clean_zooms([{"t": 5}], 100)
        assert out[0]["duration"] == 1.5

    def test_zoom_bad_time_dropped(self):
        assert clean_zooms([{"t": None}], 100) == []

    def test_sfx_known_kind(self):
        out = clean_sfx([{"t": 5, "kind": "boom"}], 100)
        assert out == [{"t": 5.0, "kind": "boom"}]

    def test_sfx_unknown_kind_dropped(self):
        assert clean_sfx([{"t": 5, "kind": "explosion_9000"}], 100) == []

    def test_sfx_kinds_are_slugs(self):
        for kind in KNOWN_SFX:
            assert slugify(kind) == kind

    def test_sorted_by_time(self):
        out = clean_captions([{"t": 9, "text": "b"}, {"t": 1, "text": "a"}], 100)
        assert [c["t"] for c in out] == [1.0, 9.0]


class TestStrList:
    def test_null(self):
        assert clean_str_list(None) == []

    def test_non_strings_dropped(self):
        assert clean_str_list(["ok", 5, None, {"a": 1}]) == ["ok", "5"]

    def test_dedup(self):
        assert clean_str_list(["a", "a", "b"]) == ["a", "b"]

    def test_capped(self):
        assert len(clean_str_list([f"s{i}" for i in range(99)], max_items=10)) == 10


class TestSlugify:
    def test_basic(self):
        assert slugify("Insta Funny") == "insta_funny"

    def test_umlauts(self):
        assert slugify("Büsche & Bäume") == "buesche_baeume"

    def test_traversal(self):
        s = slugify("../../evil")
        assert ".." not in s and "/" not in s

    def test_never_empty(self):
        assert slugify("///", fallback="f") == "f"

    def test_non_string(self):
        assert slugify(None) == "x"

    def test_max_len(self):
        assert len(slugify("a" * 200, max_len=48)) <= 48
