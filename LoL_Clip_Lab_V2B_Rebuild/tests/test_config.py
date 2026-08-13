"""Config: tomllib-Laden, Defaults, kaputte Configs, Kanal-Parsing."""

from __future__ import annotations

import pytest

from cliplab.config import Config, load_config


def write_cfg(tmp_path, content):
    p = tmp_path / "config.toml"
    p.write_text(content, encoding="utf-8")
    return p


class TestDefaults:
    def test_defaults_without_file(self, tmp_path):
        cfg, warnings = load_config(cwd=tmp_path)
        assert cfg.llm_cmd == ["claude", "-p"]
        assert warnings == []

    def test_llm2_default_empty(self):
        # Nutzer-Vorgabe: Zweit-Gehirn ist im Code-Default DEAKTIVIERT
        assert Config().llm2_cmd == []

    def test_default_channels(self):
        cfg = Config()
        names = cfg.channel_names()
        assert names == ["insta", "yt", "uncut"]
        insta = cfg.channel("insta")
        assert insta.vertical and insta.max_s == 60.0
        assert cfg.channel("uncut").kind == "full"

    def test_missing_explicit_path_warns(self, tmp_path):
        cfg, warnings = load_config(tmp_path / "nope.toml")
        assert warnings and cfg.llm_cmd == ["claude", "-p"]


class TestLoading:
    def test_values_loaded(self, tmp_path):
        p = write_cfg(
            tmp_path,
            '[general]\nlanguage = "de"\nhosts = ["A", "B"]\nkeep_wav = true\n'
            '[whisper]\nmodel = "tiny"\n'
            "[llm]\ntimeout_s = 60.0\n"
            "[ranking]\nw_signal = 0.3\nw_semantic = 0.7\n",
        )
        cfg, warnings = load_config(p)
        assert cfg.language == "de"
        assert cfg.hosts == ["A", "B"]
        assert cfg.keep_wav is True
        assert cfg.whisper_model == "tiny"
        assert cfg.llm_timeout_s == 60.0
        assert cfg.w_signal == 0.3
        assert warnings == []

    def test_broken_toml_warns_and_defaults(self, tmp_path):
        p = write_cfg(tmp_path, "[general\nkaputt===")
        cfg, warnings = load_config(p)
        assert any("kaputt" in w for w in warnings)
        assert cfg.language == "auto"

    def test_wrong_type_warns_keeps_default(self, tmp_path):
        p = write_cfg(tmp_path, '[general]\nkeep_wav = "ja"\n')
        cfg, warnings = load_config(p)
        assert cfg.keep_wav is False
        assert any("keep_wav" in w for w in warnings)

    def test_int_for_float_ok(self, tmp_path):
        p = write_cfg(tmp_path, "[llm]\ntimeout_s = 120\n")
        cfg, warnings = load_config(p)
        assert cfg.llm_timeout_s == 120.0 and not warnings

    def test_unknown_keys_ignored(self, tmp_path):
        p = write_cfg(tmp_path, "[general]\nvoellig_neu = 1\n[neue_sektion]\nx = 2\n")
        cfg, warnings = load_config(p)
        assert warnings == []

    def test_unknown_whisper_model_warns(self, tmp_path):
        p = write_cfg(tmp_path, '[whisper]\nmodel = "large-v3"\n')
        cfg, warnings = load_config(p)
        assert cfg.whisper_model == "small" and warnings

    def test_unknown_encoder_warns(self, tmp_path):
        p = write_cfg(tmp_path, '[cutting]\nencoder = "wunder_encoder"\n')
        cfg, warnings = load_config(p)
        assert cfg.encoder == "auto" and warnings

    def test_llm_cmd_loaded(self, tmp_path):
        p = write_cfg(tmp_path, '[llm]\nllm_cmd = ["mycli", "--json"]\nllm2_cmd = ["other", "-"]\n')
        cfg, _ = load_config(p)
        assert cfg.llm_cmd == ["mycli", "--json"]
        assert cfg.llm2_cmd == ["other", "-"]

    def test_llm_cmd_wrong_type(self, tmp_path):
        p = write_cfg(tmp_path, '[llm]\nllm_cmd = "claude -p"\n')
        cfg, warnings = load_config(p)
        assert cfg.llm_cmd == ["claude", "-p"] and warnings

    def test_tiny_chunk_clamped(self, tmp_path):
        p = write_cfg(tmp_path, "[llm]\nchunk_chars = 10\n")
        cfg, warnings = load_config(p)
        assert cfg.chunk_chars == 5000 and warnings

    def test_negative_weights_reset(self, tmp_path):
        p = write_cfg(tmp_path, "[ranking]\nw_signal = -1.0\n")
        cfg, warnings = load_config(p)
        assert cfg.w_signal == 0.45 and warnings

    def test_base_dir_set(self, tmp_path):
        p = write_cfg(tmp_path, "[general]\n")
        cfg, _ = load_config(p)
        assert cfg.resolve("memory.json") == tmp_path / "memory.json"

    def test_found_in_cwd(self, tmp_path):
        write_cfg(tmp_path, '[general]\nlanguage = "de"\n')
        cfg, _ = load_config(cwd=tmp_path)
        assert cfg.language == "de"


class TestChannels:
    def test_custom_channels_followed(self, tmp_path):
        p = write_cfg(
            tmp_path,
            '[[channels]]\nname = "shorts"\nmax_s = 45\nvertical = true\n'
            '[[channels]]\nname = "haupt"\n'
            '[[channels]]\nname = "archiv"\nkind = "full"\n',
        )
        cfg, warnings = load_config(p)
        assert cfg.channel_names() == ["shorts", "haupt", "archiv"]
        assert cfg.channel("shorts").max_s == 45
        assert cfg.channel("archiv").kind == "full"
        assert warnings == []

    def test_broken_entry_tolerated_with_warning(self, tmp_path):
        p = write_cfg(
            tmp_path,
            "[[channels]]\nname = 42\n"
            '[[channels]]\nname = "ok"\n',
        )
        cfg, warnings = load_config(p)
        assert cfg.channel_names() == ["ok"]
        assert any("uebersprungen" in w for w in warnings)

    def test_all_broken_falls_back_to_defaults(self, tmp_path):
        p = write_cfg(tmp_path, "[[channels]]\nnote = \"ohne name\"\n")
        cfg, warnings = load_config(p)
        assert cfg.channel_names() == ["insta", "yt", "uncut"]
        assert warnings

    def test_duplicate_channel_skipped(self, tmp_path):
        p = write_cfg(tmp_path, '[[channels]]\nname = "a"\n[[channels]]\nname = "a"\n')
        cfg, warnings = load_config(p)
        assert cfg.channel_names() == ["a"] and warnings

    def test_unknown_kind_warns(self, tmp_path):
        p = write_cfg(tmp_path, '[[channels]]\nname = "a"\nkind = "quer"\n')
        cfg, warnings = load_config(p)
        assert cfg.channel("a").kind == "clips" and warnings

    def test_channel_name_slugged(self, tmp_path):
        p = write_cfg(tmp_path, '[[channels]]\nname = "Mein Kanal!"\n')
        cfg, _ = load_config(p)
        assert cfg.channel_names() == ["mein_kanal"]

    def test_negative_max_s_zeroed(self, tmp_path):
        p = write_cfg(tmp_path, '[[channels]]\nname = "a"\nmax_s = -10\n')
        cfg, _ = load_config(p)
        assert cfg.channel("a").max_s == 0.0
