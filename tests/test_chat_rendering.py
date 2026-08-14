"""Tests for chat response Pango rendering.

Targets HTML escaping and sanitization to prevent markup injection.
"""

import pytest
from triagetty.chat.rendering import prose_to_pango, code_to_pango


# --- Prose to Pango tests ---

def test_prose_to_pango_escapes_html() -> None:
    """HTML should be escaped to prevent injection."""
    result = prose_to_pango("<script>alert('xss')</script>")
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_prose_to_pango_escapes_ampers() -> None:
    """Ampersands should be escaped."""
    result = prose_to_pango("file1 & file2")
    assert "file1 &amp; file2" in result


def test_prose_to_pango_escapes_less_than() -> None:
    """Less than signs should be escaped."""
    result = prose_to_pango("value < 10")
    assert "value &lt; 10" in result


def test_prose_to_pango_escapes_greater_than() -> None:
    """Greater than signs should be escaped."""
    result = prose_to_pango("value > 10")
    assert "value &gt; 10" in result


def test_prose_to_pango_preserves_quotes() -> None:
    """Quotes should not be escaped (quote=False)."""
    result = prose_to_pango('He said "hello"')
    assert '"hello"' in result


def test_prose_to_pango_escapes_pango_markup() -> None:
    """Pango markup should be escaped."""
    result = prose_to_pango("<b>bold</b>")
    assert "<b>" not in result
    assert "&lt;b&gt;bold&lt;/b&gt;" in result


def test_prose_to_pango_handles_h1_headings() -> None:
    """H1 headings should be rendered as bold."""
    result = prose_to_pango("# Heading")
    assert "<b>Heading</b>" in result


def test_prose_to_pango_handles_h2_headings() -> None:
    """H2 headings should be rendered as bold."""
    result = prose_to_pango("## Heading")
    assert "<b>Heading</b>" in result


def test_prose_to_pango_handles_h3_headings() -> None:
    """H3 headings should be rendered as bold."""
    result = prose_to_pango("### Heading")
    assert "<b>Heading</b>" in result


def test_prose_to_pango_handles_bold_text() -> None:
    """Bold text (**text**) should be rendered."""
    result = prose_to_pango("This is **bold** text.")
    assert "<b>bold</b>" in result


def test_prose_to_pango_handles_italic_text() -> None:
    """Italic text (*text*) should be rendered."""
    result = prose_to_pango("This is *italic* text.")
    assert "<i>italic</i>" in result


def test_prose_to_pango_handles_inline_code() -> None:
    """Inline code (`code`) should be rendered."""
    result = prose_to_pango("Use the `ls` command.")
    assert "<tt>ls</tt>" in result


def test_prose_to_pango_removes_provider_formatting_tags() -> None:
    """Provider-generated UI tags should not leak into rendered prose."""
    result = prose_to_pango("Check <tt>top</tt> and <b>memory</b>. </b></i></tt>")
    assert "<tt>top</tt>" not in result
    assert "<b>memory</b>" not in result
    assert "Check top and memory." in result


def test_prose_to_pango_handles_empty_string() -> None:
    assert prose_to_pango("") == ""


def test_prose_to_pango_handles_multiline_text() -> None:
    """Multiline text should be handled."""
    result = prose_to_pango("Line 1\nLine 2\nLine 3")
    assert "Line 1" in result
    assert "Line 2" in result
    assert "Line 3" in result


def test_prose_to_pango_handles_unicode() -> None:
    """Unicode characters should be preserved."""
    result = prose_to_pango("Hello 世界 🌍")
    assert "Hello" in result
    assert "世界" in result


def test_prose_to_pango_handles_multiple_headings() -> None:
    """Multiple headings should all be rendered."""
    result = prose_to_pango("# H1\n## H2\n### H3")
    assert result.count("<b>") == 3


def test_prose_to_pango_handles_nested_bold() -> None:
    """Nested bold should be handled."""
    result = prose_to_pango("**outer **inner** outer**")
    assert "<b>" in result


# --- Code to Pango tests ---

def test_code_to_pango_escapes_html() -> None:
    """HTML in code should be escaped."""
    result = code_to_pango("<div>content</div>")
    assert "&lt;div&gt;content&lt;/div&gt;" in result


def test_code_to_pango_escapes_ampersands() -> None:
    """Ampersands in code should be escaped."""
    result = code_to_pango("file1 & file2")
    assert "file1 &amp; file2" in result


def test_code_to_pango_wraps_in_tt() -> None:
    """Code should be wrapped in <tt> tags."""
    result = code_to_pango("echo hello")
    assert result.startswith("<tt>")
    assert result.endswith("</tt>")


def test_code_to_pango_handles_empty_string() -> None:
    result = code_to_pango("")
    assert result == "<tt></tt>"


def test_code_to_pango_preserves_whitespace() -> None:
    """Whitespace in code should be preserved."""
    result = code_to_pango("    indented\n\talso indented")
    assert "    indented" in result
    assert "\talso indented" in result


def test_code_to_pango_handles_multiline_code() -> None:
    """Multiline code should be handled."""
    result = code_to_pango("line1\nline2\nline3")
    assert "line1" in result
    assert "line2" in result
    assert "line3" in result


def test_code_to_pango_handles_special_characters() -> None:
    """Special characters in code should be escaped."""
    result = code_to_pango('echo "value < $VAR > output"')
    assert "&lt;" in result
    assert "&gt;" in result


# --- Security tests ---

def test_prose_to_pango_prevents_script_injection() -> None:
    """Script injection attempts should be neutralized."""
    malicious = '<script src="http://evil.com/malware.js"></script>'
    result = prose_to_pango(malicious)
    assert "<script" not in result
    assert "&lt;script" in result


def test_prose_to_pango_prevents_pango_injection() -> None:
    """Pango injection attempts should be neutralized."""
    malicious = "<link href='file:///etc/passwd'/>"
    result = prose_to_pango(malicious)
    assert "<link" not in result
    assert "&lt;link" in result


def test_code_to_pango_prevents_pango_injection() -> None:
    """Pango injection in code should be neutralized."""
    malicious = "<link href='file:///etc/passwd'/>"
    result = code_to_pango(malicious)
    assert "<link" not in result
    assert "&lt;link" in result


def test_prose_to_pango_handles_xss_in_heading() -> None:
    """XSS attempts in headings should be neutralized."""
    malicious = "# <script>alert('xss')</script>"
    result = prose_to_pango(malicious)
    assert "<b>" in result  # heading is rendered
    assert "&lt;script&gt;" in result  # but script is escaped


def test_prose_to_pango_handles_xss_in_bold() -> None:
    """XSS attempts in bold text should be neutralized."""
    malicious = "**<script>alert('xss')</script>**"
    result = prose_to_pango(malicious)
    assert "<b>" in result
    assert "&lt;script&gt;" in result
