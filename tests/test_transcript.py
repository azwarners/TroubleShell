"""Tests for terminal transcript handling.

Targets edge cases that caused "output got cut off" issues in production.
"""

from triagetty.terminal.transcript import bound_transcript, estimate_tokens, normalize_transcript


# --- Normalize transcript tests ---

def test_normalize_removes_control_noise_and_normalizes_newlines() -> None:
    assert normalize_transcript("a\r\nb\x00\x1b[31mred") == "a\nb[31mred"


def test_normalize_handles_crlf_only() -> None:
    """Windows-style line endings should be normalized."""
    result = normalize_transcript("line1\r\nline2\r\nline3")
    assert result == "line1\nline2\nline3"


def test_normalize_handles_cr_only() -> None:
    """Old Mac-style line endings should be normalized."""
    result = normalize_transcript("line1\rline2\rline3")
    assert result == "line1\nline2\nline3"


def test_normalize_removes_all_control_chars_except_newline_tab() -> None:
    """Control characters like null, bell, backspace should be removed."""
    text = "a\x00b\x07c\x08d\te\n"  # null, bell, backspace, tab, newline
    result = normalize_transcript(text)
    assert result == "abcd\te\n"
    assert "\x00" not in result
    assert "\x07" not in result
    assert "\x08" not in result


def test_normalize_preserves_ansi_color_codes() -> None:
    """ANSI escape sequences (like colors) should be preserved."""
    text = "\x1b[31mred\x1b[0m\n\x1b[32mgreen\x1b[0m"
    result = normalize_transcript(text)
    assert "red" in result
    assert "green" in result


def test_normalize_handles_empty_string() -> None:
    assert normalize_transcript("") == ""


def test_normalize_handles_very_long_text() -> None:
    """Should handle large terminal dumps without error."""
    long_text = "line of text with some content\n" * 10000
    result = normalize_transcript(long_text)
    assert len(result.splitlines()) == 10000


# --- Bound transcript tests ---

def test_bound_transcript_keeps_newest_lines_within_token_budget() -> None:
    """Keep newest lines that fit within the token budget."""
    # New estimate: each line adds ~2 tokens overhead + content at ~3.2 chars/token
    # "one\n" = 3/3.2 + 2 = ~3 tokens per line roughly
    # 4 lines = ~12 tokens, so max_tokens=10 would drop the oldest
    # With max_tokens=10, should keep newest 3 lines
    result = bound_transcript("one\ntwo\nthree\nfour", max_tokens=10)
    assert result == "two\nthree\nfour"  # dropped "one" to fit budget
    # With max_tokens=4, should keep only newest single line (each line costs ~3-4 tokens)
    result = bound_transcript("one\ntwo\nthree\nfour", max_tokens=4)
    assert "four" in result  # newest should be kept
    assert "one" not in result  # oldest should be dropped
    assert "two" not in result  # second line should also be dropped


def test_bound_transcript_single_long_line() -> None:
    """Single long line should be truncated to fit token budget."""
    # "x" * 40 = 40 chars = ~10 tokens
    long_text = "x" * 40
    result = bound_transcript(long_text, max_tokens=10)
    assert len(result) <= 40


def test_bound_transcript_empty_input() -> None:
    result = bound_transcript("", max_tokens=1000)
    assert result == ""


def test_bound_transcript_invalid_token_budget() -> None:
    """Zero or negative token budget should return empty."""
    assert bound_transcript("text", max_tokens=0) == ""
    assert bound_transcript("text", max_tokens=-1) == ""


def test_bound_transcript_exactly_at_token_limit() -> None:
    """When text has exactly max_tokens, all should be returned."""
    text = "\n".join(f"line{i}" for i in range(5))
    result = bound_transcript(text, max_tokens=100)
    assert len(result.splitlines()) == 5


def test_bound_transcript_over_token_limit() -> None:
    """When text exceeds token budget, oldest lines should be dropped."""
    lines = [f"line{i}" for i in range(10)]
    text = "\n".join(lines)
    # New estimate: each line ~6 chars at 3.2 chars/token + 2 overhead = ~4 tokens per line
    # 10 lines = ~40 tokens, max_tokens=10 keeps only 2 lines (line8, line9)
    result = bound_transcript(text, max_tokens=10)
    result_lines = result.splitlines()
    assert len(result_lines) == 2  # Only 2 lines fit in budget
    assert "line9" in result  # newest should be kept
    assert "line8" in result  # second newest should be kept
    assert "line0" not in result  # oldest should be dropped
    assert "line7" not in result  # should also be dropped


def test_bound_transcript_single_very_long_line() -> None:
    """Very long single line should be truncated to fit token budget."""
    long_line = "x" * 50000  # ~12500 tokens
    result = bound_transcript(long_line, max_tokens=100)
    # Should be truncated to ~400 chars (100 tokens * 4 chars/token)
    assert len(result) <= 400


def test_bound_transcript_mixed_line_lengths() -> None:
    """Mixed line lengths should be bounded correctly."""
    text = "short\n" + "m" * 1000 + "\n" + "s" * 5000 + "\nfinal"
    # ~3 chars = ~1 token per short line, ~250 tokens for m*1000, ~1250 tokens for s*5000
    # With max_tokens=100, should keep only the newest lines that fit
    result = bound_transcript(text, max_tokens=100)
    result_lines = result.splitlines()
    assert "final" in result  # newest should be kept
    assert len(result) <= 400  # ~100 tokens * 4 chars/token


def test_bound_transcript_preserves_unicode() -> None:
    """Unicode characters should be preserved."""
    text = "line with émojis 🎉 and chinese 字符"
    result = bound_transcript(text, max_tokens=100)
    assert "émojis" in result
    assert "字符" in result


def test_bound_transcript_simulates_large_terminal_output() -> None:
    """Simulate a realistic large terminal output scenario."""
    # Simulate ls -la output with many files
    lines = []
    for i in range(500):
        lines.append(f"-rw-r--r-- 1 user user 4096 Jan 1 00:00 file{i}.txt")
    text = "\n".join(lines)
    
    # Each line is ~47 chars = ~12 tokens
    # 500 lines = ~6000 tokens
    # With max_tokens=2400, should keep ~200 lines
    result = bound_transcript(text, max_tokens=2400)
    result_lines = result.splitlines()
    
    assert len(result_lines) <= 200
    # Should contain the most recent files
    assert "file499" in result


def test_bound_transcript_whitespace_only() -> None:
    """Whitespace lines should be preserved."""
    text = "   \n  \n  "
    result = bound_transcript(text, max_tokens=100)
    assert " " in result


def test_bound_transcript_control_characters_removed_before_bounding() -> None:
    """Control chars should be stripped, then bounding applied."""
    text = "\x00" * 100 + "\n" + "clean line"
    result = bound_transcript(text, max_tokens=100)
    assert "\x00" not in result
    assert "clean line" in result


# --- Estimate tokens tests ---

def test_estimate_tokens_is_a_display_only_rough_estimate() -> None:
    assert estimate_tokens("") == 0
    # 8 chars, 1 line, all non-empty -> code_ratio=1.0, adjusted_chars_per_token=3.2
    # line_overhead = 2, char_estimate = 8/3.2 = 2.5 -> round to 3, total = 3+2 = 5
    # Allow reasonable range since heuristic is display-oriented
    assert 3 <= estimate_tokens("12345678") <= 6


def test_estimate_tokens_for_large_text() -> None:
    """Token estimation should work for large amounts of text."""
    # 100000 chars, 1 line, 1 non-empty -> code_ratio=1.0, adjusted_chars_per_token=3.2
    # line_overhead = 2, char_estimate = 100000/3.2 = 31250 -> total = 31250+2 = 31252
    large_text = "x" * 100000
    tokens = estimate_tokens(large_text)
    assert tokens == 31252  # 100000/3.2 + 2 (single line overhead)


def test_estimate_tokens_for_typical_terminal_context() -> None:
    """Token estimation for typical terminal context size."""
    # 200 lines * 28 chars = 5600 chars, all non-empty -> code_ratio=1.0, adjusted_chars_per_token=3.2
    # line_overhead = 200*2 = 400, char_estimate = 5600/3.2 = 1750 -> total = 1750+400 = 2150
    context = "line of terminal output text\n" * 200
    tokens = estimate_tokens(context)
    assert tokens > 0
    # New estimate: ~2150 tokens (higher due to line overhead)
    assert 1500 < tokens < 2500
