"""Conservative Markdown fence parsing without a Markdown execution surface."""

from dataclasses import dataclass
import re

from .models import CodeSegment, TextSegment

_FENCE_RE = re.compile(r"^\s{0,3}```\s*(\w*)[^`]*$")
_SHELL_LANGUAGES = {"bash", "sh", "shell"}


def parse_response(markdown: str) -> tuple[TextSegment | CodeSegment, ...]:
    segments: list[TextSegment | CodeSegment] = []
    prose: list[str] = []
    lines = markdown.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        match = _FENCE_RE.match(lines[index].rstrip("\n"))
        if not match:
            prose.append(lines[index])
            index += 1
            continue
        # Only add non-empty prose segments
        if prose:
            prose_text = "".join(prose)
            if prose_text.strip():
                segments.append(TextSegment(prose_text))
            prose = []
        language = match.group(1).lower().strip() or None
        index += 1
        code: list[str] = []
        while index < len(lines) and not re.match(r"^\s{0,3}```\s*$", lines[index].rstrip("\n")):
            code.append(lines[index])
            index += 1
        if index < len(lines):
            index += 1
        # Models sometimes omit the language after the opening fence even
        # when the block is clearly intended as a command. Treat an
        # unlabeled block as shell code so the UI still offers Insert,
        # Execute, and Copy. Explicitly labeled non-shell blocks remain
        # display-only.
        segments.append(CodeSegment(
            language,
            "".join(code).rstrip("\n"),
            language is None or language in _SHELL_LANGUAGES,
        ))
    # Only add non-empty prose segments at the end
    if prose:
        prose_text = "".join(prose)
        if prose_text.strip():
            segments.append(TextSegment(prose_text))
    # Handle empty input
    if not segments:
        segments.append(TextSegment(""))
    return tuple(segments)
