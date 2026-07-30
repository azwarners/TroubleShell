"""Bounded, display-oriented terminal transcript handling."""

import re

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize_transcript(text: str) -> str:
    """Remove control noise while retaining newlines, tabs, and visible formatting."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _CONTROL_RE.sub("", text)


def estimate_tokens(text: str) -> int:
    """Provide a transparent rough estimate for display, not billing or limits."""
    return round(len(text) / 4) if text else 0


def bound_transcript(text: str, *, max_lines: int, max_characters: int) -> str:
    """Return the newest content within both configured bounds."""
    if max_lines < 1 or max_characters < 1:
        return ""
    cleaned = normalize_transcript(text)
    lines = cleaned.splitlines()
    bounded = "\n".join(lines[-max_lines:])
    if len(bounded) > max_characters:
        bounded = bounded[-max_characters:]
        if "\n" in bounded:
            bounded = bounded.split("\n", 1)[1]
    return bounded
