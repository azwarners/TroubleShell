"""Safe, deliberately small Markdown-to-Pango rendering helpers."""

import html
import re


# Some providers imitate the UI's markup instead of returning Markdown. These
# presentation tags are not part of the response format and would otherwise
# be shown literally after escaping. The `<tt>` tags are the distinctive
# leakage pattern; only in that case remove the small, attribute-free
# formatting allowlist. Arbitrary HTML/Pango markup remains escaped below.
_MODEL_FORMATTING_TAG_RE = re.compile(r"</?(?:b|strong|i|em|tt)>", flags=re.IGNORECASE)
_MODEL_TT_TAG_RE = re.compile(r"</?tt>", flags=re.IGNORECASE)


def prose_to_pango(markdown: str) -> str:
    """Render a small Markdown subset without trusting model-provided markup."""
    if _MODEL_TT_TAG_RE.search(markdown):
        markdown = _MODEL_FORMATTING_TAG_RE.sub("", markdown)
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
