"""Tests for chat response markdown parsing.

Targets robustness against various markdown formats and edge cases.
"""

import pytest
from troubleshell.chat.parser import parse_response
from troubleshell.chat.models import CodeSegment, TextSegment


# --- Basic parsing tests ---

def test_parse_response_returns_text_segment_for_plain_text() -> None:
    segments = parse_response("This is plain text.")
    assert len(segments) == 1
    assert isinstance(segments[0], TextSegment)
    assert segments[0].text == "This is plain text."


def test_parse_response_returns_code_segment_for_bash_block() -> None:
    markdown = "```bash\necho hello\n```"
    segments = parse_response(markdown)
    assert len(segments) == 1
    assert isinstance(segments[0], CodeSegment)
    assert segments[0].language == "bash"
    assert segments[0].code == "echo hello"
    assert segments[0].insertable is True


def test_parse_response_returns_code_segment_for_shell_block() -> None:
    markdown = "```shell\nls -la\n```"
    segments = parse_response(markdown)
    assert len(segments) == 1
    assert isinstance(segments[0], CodeSegment)
    assert segments[0].language == "shell"
    assert segments[0].insertable is True


def test_parse_response_returns_code_segment_for_sh_block() -> None:
    markdown = "```sh\npwd\n```"
    segments = parse_response(markdown)
    assert len(segments) == 1
    assert isinstance(segments[0], CodeSegment)
    assert segments[0].language == "sh"
    assert segments[0].insertable is True


def test_parse_response_returns_non_insertable_code_for_python() -> None:
    markdown = "```python\nprint('hello')\n```"
    segments = parse_response(markdown)
    assert len(segments) == 1
    assert isinstance(segments[0], CodeSegment)
    assert segments[0].language == "python"
    assert segments[0].insertable is False


def test_parse_response_returns_non_insertable_code_for_yaml() -> None:
    markdown = "```yaml\nkey: value\n```"
    segments = parse_response(markdown)
    assert len(segments) == 1
    assert isinstance(segments[0], CodeSegment)
    assert segments[0].language == "yaml"
    assert segments[0].insertable is False


# --- Mixed content tests ---

def test_parse_response_handles_text_and_code_mixed() -> None:
    markdown = """Some intro text.

```bash
command here
```

Some outro text."""
    segments = parse_response(markdown)
    assert len(segments) == 3
    assert isinstance(segments[0], TextSegment)
    assert isinstance(segments[1], CodeSegment)
    assert isinstance(segments[2], TextSegment)


def test_parse_response_handles_multiple_code_blocks() -> None:
    markdown = """First block:
```bash
echo one
```

Middle text.

Second block:
```bash
echo two
```
"""
    segments = parse_response(markdown)
    assert len(segments) == 4
    assert isinstance(segments[0], TextSegment)
    assert isinstance(segments[1], CodeSegment)
    assert isinstance(segments[2], TextSegment)
    assert isinstance(segments[3], CodeSegment)


def test_parse_response_handles_different_languages() -> None:
    markdown = """```bash
shell command
```

```python
python code
```

```yaml
yaml config
```
"""
    segments = parse_response(markdown)
    assert len(segments) == 3
    assert segments[0].language == "bash"
    assert segments[0].insertable is True
    assert segments[1].language == "python"
    assert segments[1].insertable is False
    assert segments[2].language == "yaml"
    assert segments[2].insertable is False


# --- Edge case tests ---

def test_parse_response_handles_empty_string() -> None:
    segments = parse_response("")
    assert len(segments) == 1
    assert isinstance(segments[0], TextSegment)
    assert segments[0].text == ""


def test_parse_response_handles_only_whitespace() -> None:
    segments = parse_response("   \n  \n  ")
    assert len(segments) == 1
    assert isinstance(segments[0], TextSegment)


def test_parse_response_handles_unclosed_code_block() -> None:
    """Unclosed code blocks should be handled gracefully."""
    markdown = """```bash
echo hello
This code block is never closed"""
    segments = parse_response(markdown)
    # Should still produce a code segment with the content
    assert len(segments) == 1
    assert isinstance(segments[0], CodeSegment)
    assert "echo hello" in segments[0].code


def test_parse_response_handles_empty_code_block() -> None:
    """Empty code blocks should be handled."""
    markdown = """```bash
```"""
    segments = parse_response(markdown)
    assert len(segments) == 1
    assert isinstance(segments[0], CodeSegment)
    assert segments[0].code == ""


def test_parse_response_handles_code_block_with_no_language() -> None:
    """Code blocks without language should not be insertable."""
    markdown = """```
some code
```"""
    segments = parse_response(markdown)
    assert len(segments) == 1
    assert isinstance(segments[0], CodeSegment)
    assert segments[0].language is None
    assert segments[0].insertable is False


def test_parse_response_handles_nested_backticks_in_code() -> None:
    """Backticks inside code blocks should be preserved."""
    markdown = """```bash
echo "use `command` here"
```"""
    segments = parse_response(markdown)
    assert len(segments) == 1
    assert isinstance(segments[0], CodeSegment)
    assert "`command`" in segments[0].code


def test_parse_response_handles_backticks_in_text() -> None:
    """Inline code in text should not be parsed as code blocks."""
    markdown = "Use the `ls` command to list files."
    segments = parse_response(markdown)
    assert len(segments) == 1
    assert isinstance(segments[0], TextSegment)
    assert "`ls`" in segments[0].text


def test_parse_response_handles_four_backticks() -> None:
    """Four backticks should not be recognized as a fence."""
    markdown = """````
not a fence
````"""
    segments = parse_response(markdown)
    assert len(segments) == 1
    assert isinstance(segments[0], TextSegment)


def test_parse_response_handles_indented_fences() -> None:
    """Fences with up to 3 spaces of indentation should be recognized."""
    markdown = """   ```bash
    echo hello
    ```"""
    segments = parse_response(markdown)
    assert len(segments) == 1
    assert isinstance(segments[0], CodeSegment)


def test_parse_response_handles_fences_with_too_much_indentation() -> None:
    """Fences with more than 3 spaces should not be recognized."""
    markdown = """    ```bash
    echo hello
    ```"""
    segments = parse_response(markdown)
    assert len(segments) == 1
    assert isinstance(segments[0], TextSegment)


def test_parse_response_handles_language_case_insensitivity() -> None:
    """Language names should be case-insensitive."""
    for lang in ["bash", "Bash", "BASH", "BaSh"]:
        markdown = f"```{lang}\necho test\n```"
        segments = parse_response(markdown)
        assert len(segments) == 1
        assert segments[0].language == "bash"
        assert segments[0].insertable is True


def test_parse_response_handles_language_with_spaces() -> None:
    """Language names with spaces should be handled."""
    markdown = """```bash extra stuff
echo test
```"""
    segments = parse_response(markdown)
    assert len(segments) == 1
    assert segments[0].language == "bash"


def test_parse_response_handles_multiline_code() -> None:
    """Multiline code blocks should preserve all lines."""
    markdown = """```bash
line 1
line 2
line 3
```"""
    segments = parse_response(markdown)
    assert len(segments) == 1
    assert segments[0].code == "line 1\nline 2\nline 3"


def test_parse_response_handles_code_with_special_chars() -> None:
    """Code with special characters should be preserved."""
    markdown = """```bash
echo "Hello $USER @ $(hostname)"
grep -E '\\d+' file.txt
```"""
    segments = parse_response(markdown)
    assert len(segments) == 1
    assert "$USER" in segments[0].code
    assert "@ " in segments[0].code


# --- Production-like scenarios ---

def test_parse_response_handles_typical_troubleshooting_response() -> None:
    """Parse a realistic troubleshooting response."""
    markdown = """The disk is nearly full. Let me check the sizes of directories:

```bash
du -sh /data/* 2>/dev/null | sort -rh | head -20
```

This will show the top 20 directories by size.

Also check what's using the most space in the root partition:

```bash
df -h /
```
"""
    segments = parse_response(markdown)
    # text, code, text, code
    assert len(segments) == 4
    assert isinstance(segments[0], TextSegment)
    assert isinstance(segments[1], CodeSegment)
    assert isinstance(segments[2], TextSegment)
    assert isinstance(segments[3], CodeSegment)


def test_parse_response_handles_response_with_no_code() -> None:
    """Response with no code blocks should return only text."""
    markdown = """The issue is that your disk is 98% full. You need to clean up some space.
I recommend looking at old model files that you don't use anymore."""
    segments = parse_response(markdown)
    assert len(segments) == 1
    assert isinstance(segments[0], TextSegment)


def test_parse_response_handles_response_with_only_code() -> None:
    """Response with only a code block."""
    markdown = """```bash
ls -la /data
```"""
    segments = parse_response(markdown)
    assert len(segments) == 1
    assert isinstance(segments[0], CodeSegment)


def test_parse_response_handles_malformed_markdown() -> None:
    """Malformed markdown should not crash the parser."""
    # Various malformed scenarios
    test_cases = [
        "```",  # opening only
        "```bash",  # opening with lang, no content
        "```bash\n",  # opening with newline only
        "```bash\n```",  # empty block
        "```bash\n```python\n```",  # nested closing
        "```bash\n```bash\n```",  # same lang nested
    ]
    for markdown in test_cases:
        segments = parse_response(markdown)
        assert len(segments) >= 1  # Should always return at least one segment
