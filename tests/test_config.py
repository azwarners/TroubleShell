from pathlib import Path

from triagetty.config import Config, config_path, load_config, save_config


def test_config_round_trip(tmp_path: Path) -> None:
    original = Config(endpoint_url="https://example.test/v1", model="m", api_key="secret",
                      context_line_limit=4, verify_tls=False, system_prompt="line one\nline two")
    path = save_config(original, tmp_path / "config.toml")
    assert load_config(path) == original


def test_config_path_uses_xdg(tmp_path: Path) -> None:
    assert config_path({"XDG_CONFIG_HOME": str(tmp_path)}) == tmp_path / "triagetty" / "config.toml"


def test_legacy_system_prompt_override_is_loaded(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('system_prompt_override = "custom"\n', encoding="utf-8")
    assert load_config(path).system_prompt == "custom"


def test_saved_config_contains_readable_prompt(tmp_path: Path) -> None:
    path = save_config(Config(), tmp_path / "config.toml")
    content = path.read_text(encoding="utf-8")
    assert "system_prompt = \"\"\"" in content
    assert load_config(path).system_prompt == Config().system_prompt
