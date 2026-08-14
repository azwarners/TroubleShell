"""Tests for display normalization and whole-request estimation."""

from triagetty.terminal.transcript import estimate_tokens, normalize_transcript


def test_normalize_removes_control_noise_and_normalizes_newlines() -> None:
    assert normalize_transcript("a\r\nb\x00\x1b[31mred") == "a\nb[31mred"


def test_normalize_handles_crlf_and_cr_only() -> None:
    assert normalize_transcript("line1\r\nline2\rline3") == "line1\nline2\nline3"


def test_normalize_removes_control_chars_except_newline_tab() -> None:
    result = normalize_transcript("a\x00b\x07c\x08d\te\n")
    assert result == "abcd\te\n"


def test_normalize_preserves_ansi_color_codes() -> None:
    result = normalize_transcript("\x1b[31mred\x1b[0m\n\x1b[32mgreen\x1b[0m")
    assert "red" in result and "green" in result


def test_normalize_handles_empty_and_large_text() -> None:
    assert normalize_transcript("") == ""
    assert len(normalize_transcript("line\n" * 10000).splitlines()) == 10000


def test_estimate_tokens_is_rough_and_displayable() -> None:
    assert estimate_tokens("") == 0
    assert 3 <= estimate_tokens("12345678") <= 6


def test_estimate_tokens_for_large_text() -> None:
    assert estimate_tokens("x" * 100000) == 31252


def test_estimate_tokens_for_typical_terminal_context() -> None:
    tokens = estimate_tokens("line of terminal output text\n" * 200)
    assert 1500 < tokens < 2500
