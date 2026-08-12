"""Tests for command insertion text processing.

Targets text sanitization and safety for terminal insertion.
"""

import pytest
from triagetty.terminal.insertion import insertable_text


def test_insertable_text_preserves_command() -> None:
    """Normal commands should be preserved."""
    result = insertable_text("ls -la /path")
    assert result == "ls -la /path"


def test_insertable_text_normalizes_crlf() -> None:
    """Windows line endings should be normalized."""
    result = insertable_text("line1\r\nline2")
    assert result == "line1\nline2"


def test_insertable_text_normalizes_cr() -> None:
    """Old Mac line endings should be normalized."""
    result = insertable_text("line1\rline2")
    assert result == "line1\nline2"


def test_insertable_text_handles_mixed_line_endings() -> None:
    """Mixed line endings should all be normalized."""
    result = insertable_text("line1\r\nline2\rline3\nline4")
    assert result == "line1\nline2\nline3\nline4"


def test_insertable_text_preserves_unicode() -> None:
    """Unicode characters should be preserved."""
    result = insertable_text("echo 你好")
    assert result == "echo 你好"


def test_insertable_text_preserves_special_chars() -> None:
    """Special characters should be preserved."""
    result = insertable_text("grep -E '\\d+' file.txt")
    assert result == "grep -E '\\d+' file.txt"


def test_insertable_text_handles_empty_string() -> None:
    result = insertable_text("")
    assert result == ""


def test_insertable_text_preserves_shell_variables() -> None:
    """Shell variables should be preserved."""
    result = insertable_text("echo $HOME")
    assert result == "echo $HOME"


def test_insertable_text_preserves_quotes() -> None:
    """Quotes should be preserved."""
    result = insertable_text('echo "hello world"')
    assert result == 'echo "hello world"'


def test_insertable_text_preserves_pipes() -> None:
    """Pipes should be preserved."""
    result = insertable_text("cat file | grep pattern")
    assert result == "cat file | grep pattern"


def test_insertable_text_preserves_redirection() -> None:
    """Redirection should be preserved."""
    result = insertable_text("command > output.txt")
    assert result == "command > output.txt"


def test_insertable_text_preserves_backticks() -> None:
    """Backticks should be preserved."""
    result = insertable_text("echo `hostname`")
    assert result == "echo `hostname`"


def test_insertable_text_preserves_semicolons() -> None:
    """Semicolons should be preserved."""
    result = insertable_text("cmd1; cmd2; cmd3")
    assert result == "cmd1; cmd2; cmd3"


def test_insertable_text_handles_multiline_command() -> None:
    """Multiline commands should be preserved."""
    result = insertable_text("command1\ncommand2\ncommand3")
    assert result == "command1\ncommand2\ncommand3"


def test_insertable_text_handles_command_with_spaces() -> None:
    """Commands with spaces should be preserved."""
    result = insertable_text("echo 'hello world'")
    assert result == "echo 'hello world'"
