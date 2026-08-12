"""Bounded, display-oriented terminal transcript handling."""

import re

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize_transcript(text: str) -> str:
    """Remove control noise and visual padding while retaining newlines and formatting."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_RE.sub("", text)
    # Strip VTE visual padding: 2+ consecutive newlines at boundaries
    # Preserve single trailing newline (normal terminal behavior)
    while text.startswith("\n\n"):
        text = text[1:]
    while text.endswith("\n\n"):
        text = text[:-1]
    return text


def estimate_tokens(text: str) -> int:
    """Provide a transparent rough estimate for display, not billing or limits.
    
    Uses a line-aware heuristic that accounts for:
    - Average token density per character (~4 chars/token for prose)
    - Additional tokens for line breaks and formatting overhead
    - Higher density for code/terminal output (~3 chars/token)
    """
    if not text:
        return 0
    
    lines = text.splitlines()
    if not lines:
        return 0
    
    # Count non-empty lines vs total lines to detect code-heavy output
    non_empty_lines = sum(1 for line in lines if line.strip())
    code_ratio = non_empty_lines / len(lines) if lines else 0
    
    # Base estimate: 4 chars per token for prose, adjusting toward 3 for code
    # Terminal output typically has higher token density
    adjusted_chars_per_token = 4.0 - (code_ratio * 0.8)  # Range: 4.0 (prose) to 3.2 (code-heavy)
    
    # Add overhead for line breaks (each line typically costs extra tokens)
    line_overhead = len(lines) * 2  # ~2 tokens per line for formatting
    
    char_estimate = len(text) / adjusted_chars_per_token
    return round(char_estimate + line_overhead)


def bound_transcript(text: str, *, max_tokens: int) -> str:
    """Return the newest content within the token budget.
    
    Works backwards from the end to find a natural line boundary that
    stays within the token limit. Uses the estimate_tokens heuristic.
    """
    if max_tokens < 1:
        return ""
    cleaned = normalize_transcript(text)
    lines = cleaned.splitlines()
    
    # Start with all lines and trim from the beginning until we're within budget
    result_lines = lines[:]
    while result_lines:
        candidate = "\n".join(result_lines)
        if estimate_tokens(candidate) <= max_tokens:
            break
        # Remove the oldest line
        result_lines.pop(0)
    
    # If even a single line exceeds the budget, truncate at character level
    if result_lines and estimate_tokens("\n".join(result_lines)) > max_tokens:
        # Binary search for the largest character count within token budget
        full_text = "\n".join(result_lines)
        low, high = 1, len(full_text)
        while low < high:
            mid = (low + high) // 2
            if estimate_tokens(full_text[-mid:]) <= max_tokens:
                low = mid + 1
            else:
                high = mid
        return full_text[-low:].split("\n", 1)[1] if "\n" in full_text[-low:] else full_text[-low:]
    
    return "\n".join(result_lines)
