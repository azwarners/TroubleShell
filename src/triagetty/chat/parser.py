"""Conservative Markdown fence parsing without a Markdown execution surface."""

from dataclasses import dataclass
import re

from .models import CodeSegment, TextSegment

_FENCE_RE = re.compile(r"^\s{0,3}```\s*([^\s`]*)\s*$")
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
        if prose:
            segments.append(TextSegment("".join(prose)))
            prose = []
        language = match.group(1).lower() or None
        index += 1
        code: list[str] = []
        while index < len(lines) and not re.match(r"^\s{0,3}```\s*$", lines[index].rstrip("\n")):
            code.append(lines[index])
            index += 1
        if index < len(lines):
            index += 1
        segments.append(CodeSegment(language, "".join(code).rstrip("\n"), language in _SHELL_LANGUAGES))
    if prose:
        segments.append(TextSegment("".join(prose)))
    return tuple(segments)
