"""Config defaults must stay AMD-safe (CPU whisper, no CUDA/NVENC) and config.toml
overrides must apply."""
from clip_lab.config import Config


def test_amd_safe_defaults():
    c = Config()
    assert c.whisper_device == "cpu"        # never cuda by default (AMD box)
    assert c.whisper_compute_type == "int8"
    assert c.encoder == "auto"              # resolves to amf or x264, never nvenc


def test_load_without_toml_returns_defaults(tmp_path):
    c = Config.load(tmp_path)
    assert c.whisper_model == Config().whisper_model


def test_load_applies_toml_overrides(tmp_path):
    (tmp_path / "config.toml").write_text(
        "[whisper]\nwhisper_model = \"medium\"\n\n[ranking]\ntop_k = 20\n",
        encoding="utf-8")
    c = Config.load(tmp_path)
    assert c.whisper_model == "medium"
    assert c.top_k == 20


def test_load_ignores_unknown_keys(tmp_path):
    (tmp_path / "config.toml").write_text(
        "[misc]\nnot_a_real_field = 5\nwhisper_model = \"tiny\"\n", encoding="utf-8")
    c = Config.load(tmp_path)
    assert c.whisper_model == "tiny"
    assert not hasattr(c, "not_a_real_field")


def test_load_survives_broken_toml(tmp_path):
    (tmp_path / "config.toml").write_text("this is not valid toml === [[[",
                                          encoding="utf-8")
    c = Config.load(tmp_path)
    assert c.whisper_model == Config().whisper_model   # falls back to defaults
