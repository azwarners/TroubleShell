"""Display-only transcript utilities and rough whole-request estimation."""

import re

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize_transcript(text: str) -> str:
    """Normalize text for display; this is not a model-context source."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_RE.sub("", text)
    while text.startswith("\n\n"):
        text = text[1:]
    while text.endswith("\n\n"):
        text = text[:-1]
    return text


def estimate_tokens(text: str) -> int:
    """Provide a transparent rough estimate for whole-request compaction."""
    if not text:
        return 0
    lines = text.splitlines()
    if not lines:
        return 0
    non_empty_lines = sum(1 for line in lines if line.strip())
    code_ratio = non_empty_lines / len(lines)
    adjusted_chars_per_token = 4.0 - (code_ratio * 0.8)
    line_overhead = len(lines) * 2
    char_estimate = len(text) / adjusted_chars_per_token
    return round(char_estimate + line_overhead)
