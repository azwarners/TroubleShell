"""Tests for configuration management.

Targets config loading/saving edge cases and persistence.
"""

import pytest
from pathlib import Path
from triagetty.config import Config, config_path, load_config, save_config, _toml_value, DEFAULT_SYSTEM_PROMPT


def test_config_default_values() -> None:
    """Config should have sensible defaults."""
    config = Config()
    assert config.endpoint_url == "http://localhost:11434/v1"
    assert config.model == "llama3.2"
    assert config.api_key == ""
    assert config.max_context_tokens == 8000
    assert config.request_timeout is None
    assert config.shell == "/bin/bash"
    assert config.terminal_font == "Monospace 10"
    assert config.terminal_font_size == 10
    assert config.chat_font_size == 10
    assert config.verify_tls is True


def test_default_prompt_describes_captured_context() -> None:
    assert "bounded snapshot" not in DEFAULT_SYSTEM_PROMPT.lower()
    assert "recent terminal" not in DEFAULT_SYSTEM_PROMPT.lower()
    assert "provider context limit" in DEFAULT_SYSTEM_PROMPT.lower()


def test_config_custom_values() -> None:
    """Config should accept custom values."""
    config = Config(
        endpoint_url="http://custom:8080/v1",
        model="custom-model",
        api_key="secret",
        max_context_tokens=120000,
        request_timeout=90,
        shell="/bin/zsh",
        terminal_font="Monospace 12",
        terminal_font_size=14,
        chat_font_size=14,
        verify_tls=False,
    )
    assert config.endpoint_url == "http://custom:8080/v1"
    assert config.model == "custom-model"
    assert config.api_key == "secret"
    assert config.max_context_tokens == 120000
    assert config.request_timeout == 90
    assert config.shell == "/bin/zsh"
    assert config.terminal_font == "Monospace 12"
    assert config.terminal_font_size == 14
    assert config.chat_font_size == 14
    assert config.verify_tls is False


def test_config_is_frozen() -> None:
    """Config should be immutable."""
    config = Config()
    with pytest.raises(AttributeError):
        config.model = "changed"


def test_config_path_uses_xdg_config_home() -> None:
    """Config path should use XDG_CONFIG_HOME when set."""
    path = config_path(environ={"XDG_CONFIG_HOME": "/custom/config"})
    assert path == Path("/custom/config/triagetty/config.toml")


def test_config_path_uses_home_config() -> None:
    """Config path should use ~/.config when XDG_CONFIG_HOME not set."""
    path = config_path(environ={})
    assert "triagetty" in str(path)
    assert path.name == "config.toml"


def test_load_config_from_nonexistent_file() -> None:
    """Loading from non-existent file should return default config."""
    config = load_config(Path("/nonexistent/path/config.toml"))
    assert config == Config()


def test_load_config_from_empty_file(tmp_path: Path) -> None:
    """Loading from empty file should return default config."""
    config_path = tmp_path / "empty.toml"
    config_path.write_text("")
    config = load_config(config_path)
    assert config == Config()


def test_save_and_load_config(tmp_path: Path) -> None:
    """Config should round-trip through save/load."""
    config = Config(
        endpoint_url="http://custom:8080/v1",
        model="custom-model",
        api_key="secret",
        max_context_tokens=120000,
        shell="/bin/zsh",
        terminal_font="Monospace 12",
        terminal_font_size=14,
        chat_font_size=14,
        verify_tls=False,
    )
    config_path = tmp_path / "test_config.toml"
    save_config(config, config_path)
    loaded = load_config(config_path)
    assert loaded.endpoint_url == config.endpoint_url
    assert loaded.model == config.model
    assert loaded.api_key == config.api_key
    assert loaded.max_context_tokens == config.max_context_tokens
    assert loaded.shell == config.shell
    assert loaded.terminal_font == config.terminal_font
    assert loaded.terminal_font_size == config.terminal_font_size
    assert loaded.chat_font_size == config.chat_font_size
    assert loaded.verify_tls == config.verify_tls


def test_load_config_with_partial_values(tmp_path: Path) -> None:
    """Config with partial values should fill in defaults."""
    config_path = tmp_path / "partial_config.toml"
    config_path.write_text('model = "custom-model"\n')
    config = load_config(config_path)
    assert config.model == "custom-model"
    # Other values should be defaults
    assert config.endpoint_url == "http://localhost:11434/v1"
    assert config.api_key == ""


def test_load_config_supports_configurable_request_timeout(tmp_path: Path) -> None:
    config_path = tmp_path / "timeout.toml"
    config_path.write_text('request_timeout = 180\n')
    assert load_config(config_path).request_timeout == 180


def test_load_config_supports_unlimited_request_timeout(tmp_path: Path) -> None:
    config_path = tmp_path / "unlimited.toml"
    config_path.write_text('request_timeout = "none"\n')
    assert load_config(config_path).request_timeout is None


def test_load_config_ignores_unknown_keys(tmp_path: Path) -> None:
    """Config should ignore unknown keys."""
    config_path = tmp_path / "unknown_keys.toml"
    config_path.write_text('model = "custom-model"\nunknown_key = "value"\n')
    config = load_config(config_path)
    assert config.model == "custom-model"
    # Should not crash on unknown key


def test_load_config_with_legacy_system_prompt_override(tmp_path: Path) -> None:
    """Config should handle legacy system_prompt_override key."""
    config_path = tmp_path / "legacy_config.toml"
    config_path.write_text('system_prompt_override = "Custom legacy prompt"\n')
    config = load_config(config_path)
    assert config.system_prompt == "Custom legacy prompt"


def test_load_config_prefers_system_prompt(tmp_path: Path) -> None:
    """Config should prefer system_prompt over legacy key."""
    config_path = tmp_path / "both_keys.toml"
    config_path.write_text('system_prompt = "New prompt"\nsystem_prompt_override = "Old prompt"\n')
    config = load_config(config_path)
    assert config.system_prompt == "New prompt"


def test_toml_value_escapes_strings() -> None:
    """String values should be properly escaped."""
    assert _toml_value("simple") == '"simple"'
    assert _toml_value('with "quotes"') == '"with \\"quotes\\""'
    assert _toml_value("with\\backslash") == '"with\\\\backslash"'


def test_toml_value_escapes_multiline_strings() -> None:
    """Multiline strings should use triple quotes."""
    result = _toml_value("line1\nline2")
    assert '"""' in result
    assert "line1\nline2" in result


def test_toml_value_handles_booleans() -> None:
    """Booleans should be rendered correctly."""
    assert _toml_value(True) == "true"
    assert _toml_value(False) == "false"


def test_toml_value_handles_integers() -> None:
    """Integers should be rendered as strings."""
    assert _toml_value(42) == "42"
    assert _toml_value(0) == "0"


def test_toml_value_handles_unlimited_timeout() -> None:
    assert _toml_value(None) == '"none"'


def test_save_config_creates_directories(tmp_path: Path) -> None:
    """Save should create parent directories."""
    config_path = tmp_path / "nested" / "path" / "config.toml"
    save_config(Config(), config_path)
    assert config_path.exists()


def test_save_config_sets_permissions(tmp_path: Path) -> None:
    """Save should set restrictive permissions."""
    config_path = tmp_path / "restricted_config.toml"
    save_config(Config(), config_path)
    import stat
    mode = config_path.stat().st_mode
    # Should be 600 (owner read/write only)
    assert (mode & stat.S_IRUSR) != 0
    assert (mode & stat.S_IWUSR) != 0
    assert (mode & stat.S_IRGRP) == 0


def test_config_with_unicode_values(tmp_path: Path) -> None:
    """Config should handle unicode values."""
    config = Config(
        model="中文模型",
        shell="/bin/bash",
    )
    config_path = tmp_path / "unicode_config.toml"
    save_config(config, config_path)
    loaded = load_config(config_path)
    assert loaded.model == "中文模型"
