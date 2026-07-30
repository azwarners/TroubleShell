"""Safe, deliberately small Markdown-to-Pango rendering helpers."""

import html
import re


def prose_to_pango(markdown: str) -> str:
    """Render a small Markdown subset without trusting model-provided markup."""
    escaped = html.escape(markdown, quote=False)
    escaped = re.sub(r"^### (.+)$", r"<b>\1</b>", escaped, flags=re.MULTILINE)
    escaped = re.sub(r"^## (.+)$", r"<b>\1</b>", escaped, flags=re.MULTILINE)
    escaped = re.sub(r"^# (.+)$", r"<b>\1</b>", escaped, flags=re.MULTILINE)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped, flags=re.DOTALL)
    escaped = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", escaped)
    escaped = re.sub(r"`([^`\n]+)`", r"<tt>\1</tt>", escaped)
    return escaped


def code_to_pango(code: str) -> str:
    """Escape code for display in a Pango-markup label."""
    return f"<tt>{html.escape(code, quote=False)}</tt>"
