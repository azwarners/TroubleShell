"""Tests for terminal pane VTE adapter.

Targets edge cases in terminal text extraction and insertion safety.
"""

import pytest
from triagetty.terminal.pane import TerminalPane


class FakeTerminal:
    def __init__(self, text: str) -> None:
        self.text = text
        self.inserted: list[bytes] = []
        self.focused = False

    def get_text_format(self, format):
        """VTE 3.91+ API - returns text directly."""
        return self.text

    def get_text(self, selection=None, user_data=None):
        """Old VTE API for backward compatibility."""
        return self.text, []

    def feed_child(self, text: bytes) -> None:
        self.inserted.append(text)

    def grab_focus(self) -> None:
        """Mock GTK grab_focus for testing."""
        self.focused = True


class FakeVte:
    class Format:
        TEXT = "text"


class ModernFakeTerminal(FakeTerminal):
    def get_scrollback_lines(self):
        return 100

    def get_row_count(self):
        return 24

    def get_column_count(self):
        return 80

    def get_text_range_format(self, format, start_row, start_col, end_row, end_col):
        """Mock VTE 3.91+ range API for full scrollback."""
        # Return the full text for testing purposes
        return (self.text, [])

    @property
    def __firstlineno__(self):
        """Mock first visible line number."""
        return 100


class EmptyTerminal:
    """Terminal that returns empty text."""
    def get_text_format(self, format):
        return ""

    def get_text(self, selection=None, user_data=None):
        return "", []

    def feed_child(self, text: bytes) -> None:
        pass


class NullTextTerminal:
    """Terminal that returns None for text."""
    def get_text_format(self, format):
        return None

    def get_text(self, selection=None, user_data=None):
        return None, []

    def feed_child(self, text: bytes) -> None:
        pass


# --- Basic transcript tests ---

def test_terminal_pane_bounds_vte_text_at_read_time() -> None:
    pane = TerminalPane(FakeTerminal("one\ntwo\nthree"), shell="/bin/bash")
    # 3 lines estimate to 10 tokens total
    # max_tokens=10 keeps all 3 lines (exactly at budget)
    result = pane.recent_transcript(max_tokens=10)
    assert "one" in result
    assert "two" in result
    assert "three" in result
    # max_tokens=9 drops oldest (9 tokens keeps only 2 lines)
    result = pane.recent_transcript(max_tokens=9)
    assert "two" in result
    assert "three" in result
    assert "one" not in result


def test_terminal_pane_insertion_does_not_execute() -> None:
    terminal = FakeTerminal("")
    TerminalPane(terminal, shell="/bin/bash").insert("echo safe")
    assert terminal.inserted == [b"echo safe"]


def test_terminal_pane_uses_modern_vte_full_scrollback_api() -> None:
    terminal = ModernFakeTerminal("one\ntwo\nthree")
    pane = TerminalPane(terminal, shell="/bin/bash", vte=FakeVte)
    # 3 lines estimate to 10 tokens total
    # max_tokens=10 keeps all 3 lines (exactly at budget)
    result = pane.recent_transcript(max_tokens=10)
    assert "one" in result
    assert "two" in result
    assert "three" in result
    # max_tokens=9 drops oldest
    result2 = pane.recent_transcript(max_tokens=9)
    assert "two" in result2
    assert "three" in result2
    assert "one" not in result2


# --- Edge case tests ---

def test_terminal_pane_handles_empty_terminal() -> None:
    """Empty terminal should return empty transcript."""
    pane = TerminalPane(EmptyTerminal(), shell="/bin/bash")
    result = pane.recent_transcript(max_tokens=1000)
    assert result == ""


def test_terminal_pane_handles_null_terminal_text() -> None:
    """Terminal returning None should not crash."""
    pane = TerminalPane(NullTextTerminal(), shell="/bin/bash")
    result = pane.recent_transcript(max_tokens=1000)
    assert result == ""


def test_terminal_pane_handles_very_long_terminal_text() -> None:
    """Very long terminal text should be bounded."""
    long_text = "line of terminal output\n" * 10000
    pane = TerminalPane(FakeTerminal(long_text), shell="/bin/bash")
    # Each line ~24 chars = ~6 tokens, 10000 lines = ~60000 tokens
    # With max_tokens=600, should keep ~100 lines
    result = pane.recent_transcript(max_tokens=600)
    result_lines = result.splitlines()
    assert len(result_lines) <= 100


def test_terminal_pane_handles_terminal_text_with_control_chars() -> None:
    """Terminal text with control characters should be normalized."""
    text = "line1\x00\x1b[31mred\x1b[0m\nline2\r\nline3"
    pane = TerminalPane(FakeTerminal(text), shell="/bin/bash")
    result = pane.recent_transcript(max_tokens=100)
    assert "\x00" not in result  # null removed
    assert "red" in result


def test_terminal_pane_respects_token_limit() -> None:
    """Token limit should be enforced."""
    text = "x" * 50000  # ~12500 tokens
    pane = TerminalPane(FakeTerminal(text), shell="/bin/bash")
    result = pane.recent_transcript(max_tokens=100)
    # Should be truncated to ~400 chars (100 tokens * 4)
    assert len(result) <= 400


def test_terminal_pane_handles_unicode_terminal_text() -> None:
    """Unicode in terminal text should be preserved."""
    text = "中文终端输出\n日本語\n🎉 emoji"
    pane = TerminalPane(FakeTerminal(text), shell="/bin/bash")
    result = pane.recent_transcript(max_tokens=100)
    assert "中文" in result
    assert "🎉" in result


# --- Insertion safety tests ---

def test_terminal_pane_insertion_preserves_command() -> None:
    """Insertion should preserve the exact command text."""
    terminal = FakeTerminal("")
    command = "ls -la /path/to/file"
    TerminalPane(terminal, shell="/bin/bash").insert(command)
    assert terminal.inserted[0] == command.encode("utf-8")


def test_terminal_pane_insertion_handles_unicode() -> None:
    """Unicode commands should be inserted correctly."""
    terminal = FakeTerminal("")
    command = "echo 你好"
    TerminalPane(terminal, shell="/bin/bash").insert(command)
    assert terminal.inserted[0] == command.encode("utf-8")


def test_terminal_pane_insertion_handles_special_chars() -> None:
    """Special characters in commands should be preserved."""
    terminal = FakeTerminal("")
    command = "grep -E '\\d+' file.txt"
    TerminalPane(terminal, shell="/bin/bash").insert(command)
    assert terminal.inserted[0] == command.encode("utf-8")


def test_terminal_pane_insertion_normalizes_line_endings() -> None:
    """Line endings should be normalized on insertion."""
    terminal = FakeTerminal("")
    command = "line1\r\nline2\rline3"
    TerminalPane(terminal, shell="/bin/bash").insert(command)
    result = terminal.inserted[0].decode("utf-8")
    assert "\r" not in result
    assert "line1\nline2\nline3" in result


def test_terminal_pane_insertion_does_not_add_newline() -> None:
    """Insertion should not add a trailing newline."""
    terminal = FakeTerminal("")
    command = "echo hello"
    TerminalPane(terminal, shell="/bin/bash").insert(command)
    result = terminal.inserted[0].decode("utf-8")
    assert not result.endswith("\n")


def test_terminal_pane_insertion_handles_empty_string() -> None:
    """Empty string insertion should work."""
    terminal = FakeTerminal("")
    TerminalPane(terminal, shell="/bin/bash").insert("")
    assert terminal.inserted == [b""]


def test_terminal_pane_execute_inserts_and_sends_enter() -> None:
    """Execute should insert the command and send Enter to run it."""
    terminal = FakeTerminal("")
    command = "ls -la"
    TerminalPane(terminal, shell="/bin/bash").execute(command)
    # Should insert the command and then send Enter
    assert terminal.inserted == [b"ls -la", b"\n"]
    # Focus should be grabbed
    assert terminal.focused is True


def test_terminal_pane_execute_handles_multiline_command() -> None:
    """Execute should handle multiline commands correctly."""
    terminal = FakeTerminal("")
    command = "echo line1\necho line2"
    TerminalPane(terminal, shell="/bin/bash").execute(command)
    # Should insert the normalized command and then send Enter
    assert terminal.inserted == [b"echo line1\necho line2", b"\n"]


def test_terminal_pane_execute_normalizes_line_endings() -> None:
    """Execute should normalize line endings before sending."""
    terminal = FakeTerminal("")
    command = "line1\r\nline2"
    TerminalPane(terminal, shell="/bin/bash").execute(command)
    result = terminal.inserted[0].decode("utf-8")
    assert "\r" not in result
    assert "line1\nline2" in result


# --- Shell spawning tests ---

def test_terminal_pane_spawn_uses_configured_shell() -> None:
    """Spawn should use the configured shell."""
    terminal = FakeTerminal("")
    pane = TerminalPane(terminal, shell="/bin/zsh")
    assert pane.shell == "/bin/zsh"


def test_terminal_pane_spawn_with_default_shell() -> None:
    """Spawn should use default bash."""
    terminal = FakeTerminal("")
    pane = TerminalPane(terminal, shell="/bin/bash")
    assert pane.shell == "/bin/bash"