"""Tests for display normalization and whole-request estimation."""

from troubleshell.terminal.transcript import (
    estimate_tokens,
    estimate_request_tokens,
    normalize_transcript,
    request_compaction_limit,
    render_terminal_stream,
)


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


def test_render_terminal_stream_removes_shell_metadata_and_applies_line_editing() -> None:
    raw = (
        "\x1b]666;vte.shell.precmd!\x1b\\"
        "\x1b[?2004h\x1b]0;nick@host: ~\a"
        "\x1b[01;32mnick@host\x1b[00m:\x1b[01;34m~\x1b[00m$ \r\x1b[K\r"
        "\x1b[01;32mnick@host\x1b[00m:\x1b[01;34m~\x1b[00m$ "
        "echo \"testing \b\x1b[K\b\x1b[K\b\x1b[K\b\x1b[K\b\x1b[K\b\x1b[K\b\x1b[K\b\x1b[K"
        "Hel;lo\b\x1b[K\b\x1b[K\b\x1b[K\b\x1b[Kllo, world!\"\b\b\a\x1b[C\x1b[C\a\r\n"
        "\x1b[?2004l\r\x1b]133;C\x1b\\\r\x1b]666;vte.shell.preexec!\x1b\\"
        "Hello, world!\r\n"
        "\x1b]666;vte.shell.precmd!\x1b\\\x1b[?2004h"
        "\x1b[01;32mnick@host\x1b[00m:\x1b[01;34m~\x1b[00m$ "
    )

    assert render_terminal_stream(raw) == (
        "nick@host:~$ echo \"Hello, world!\"\n"
        "Hello, world!\n"
        "nick@host:~$ "
    )
    assert "\x1b" not in render_terminal_stream(raw)
    assert "vte.shell" not in render_terminal_stream(raw)


def test_estimate_tokens_is_rough_and_displayable() -> None:
    assert estimate_tokens("") == 0
    assert 3 <= estimate_tokens("12345678") <= 6


def test_estimate_tokens_for_large_text() -> None:
    assert estimate_tokens("x" * 100000) == 31252


def test_estimate_tokens_for_typical_terminal_context() -> None:
    tokens = estimate_tokens("line of terminal output text\n" * 200)
    assert 1500 < tokens < 2500


def test_request_preflight_estimate_is_conservative_and_leaves_headroom() -> None:
    contents = ("line of terminal output\n" * 100, "question")
    assert estimate_request_tokens(contents) == 2 * sum(estimate_tokens(text) for text in contents)
    assert request_compaction_limit(128_000) == 115_200
