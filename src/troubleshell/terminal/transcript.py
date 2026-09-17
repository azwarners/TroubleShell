"""Terminal-stream rendering and conservative whole-request estimation."""

import math
import re

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# A generic OpenAI-compatible endpoint does not expose a standard tokenizer
# API.  The displayable estimate below is deliberately rough; the submission
# gate must be materially more cautious so it never treats a near-limit prompt
# as safe merely because a provider tokenizes terminal-heavy text differently.
REQUEST_ESTIMATE_SAFETY_FACTOR = 2.0
REQUEST_HEADROOM_FRACTION = 0.10


def normalize_transcript(text: str) -> str:
    """Normalize text for display; this is not a model-context source."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_RE.sub("", text)
    while text.startswith("\n\n"):
        text = text[1:]
    while text.endswith("\n\n"):
        text = text[:-1]
    return text


def render_terminal_stream(text: str) -> str:
    """Render captured terminal bytes into useful model-facing text.

    The PTY capture remains raw and append-only.  This deterministic renderer
    is deliberately independent of VTE: it drops terminal metadata (OSC and
    ANSI sequences) and applies the small set of line-editing controls a shell
    prompt commonly emits.  That produces the text an operator saw without
    spending model context on colors, titles, bracketed-paste toggles, or a
    command's intermediate keystrokes.
    """
    completed: list[str] = []
    line: list[str] = []
    cursor = 0

    def write(character: str) -> None:
        nonlocal cursor
        if cursor > len(line):
            line.extend(" " for _ in range(cursor - len(line)))
        if cursor == len(line):
            line.append(character)
        else:
            line[cursor] = character
        cursor += 1

    def erase_line(mode: int) -> None:
        nonlocal cursor
        if mode == 1:
            del line[:min(cursor + 1, len(line))]
            cursor = 0
        elif mode == 2:
            line.clear()
            cursor = 0
        else:  # CSI K and CSI 0 K: cursor through the end of the line.
            del line[cursor:]

    def parameter(value: str, default: int = 1) -> int:
        try:
            return int(value or default)
        except ValueError:
            return default

    index = 0
    while index < len(text):
        character = text[index]
        if character == "\x1b" and index + 1 < len(text):
            introducer = text[index + 1]
            if introducer == "]":  # OSC: title, cwd, VTE shell integration.
                index += 2
                while index < len(text):
                    if text[index] == "\a":
                        index += 1
                        break
                    if text[index:index + 2] == "\x1b\\":
                        index += 2
                        break
                    index += 1
                continue
            if introducer in {"P", "^", "_"}:  # DCS/PM/APC, terminated by ST.
                end = text.find("\x1b\\", index + 2)
                index = len(text) if end < 0 else end + 2
                continue
            if introducer == "[":  # CSI, ending in an ASCII final byte.
                end = index + 2
                while end < len(text) and not ("@" <= text[end] <= "~"):
                    end += 1
                if end >= len(text):
                    break
                params, final = text[index + 2:end], text[end]
                fields = params.lstrip("?>!").split(";")
                if final == "K":
                    erase_line(parameter(fields[0], default=0))
                elif final == "C":
                    cursor += parameter(fields[0])
                elif final == "D":
                    cursor = max(0, cursor - parameter(fields[0]))
                elif final == "G":
                    cursor = max(0, parameter(fields[0]) - 1)
                elif final in {"H", "f"}:
                    # Shell prompts use horizontal movement; treating an
                    # absolute row as a fresh line would incorrectly erase
                    # previously captured evidence, so only honor its column.
                    cursor = max(0, parameter(fields[-1]) - 1)
                index = end + 1
                continue
            # Other two-byte escape sequences carry terminal state only here.
            index += 2
            continue
        if character == "\r":
            cursor = 0
        elif character == "\n":
            completed.append("".join(line))
            line = []
            cursor = 0
        elif character == "\b":
            cursor = max(0, cursor - 1)
        elif character == "\t":
            write("\t")
        elif character >= " ":
            write(character)
        # Bell and remaining C0 controls are terminal state, not evidence.
        index += 1

    rendered = "\n".join(completed)
    if line:
        rendered = f"{rendered}\n" if rendered else ""
        rendered += "".join(line)
    elif completed:
        rendered += "\n"
    return rendered


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


def estimate_request_tokens(contents: list[str] | tuple[str, ...]) -> int:
    """Return a conservative preflight estimate for an entire request.

    This is used only to decide whether to compact before submission.  It is
    intentionally distinct from ``estimate_tokens()``, which remains useful
    as a human-readable rough count in diagnostics.
    """
    rough_total = sum(estimate_tokens(content) for content in contents)
    return math.ceil(rough_total * REQUEST_ESTIMATE_SAFETY_FACTOR)


def request_compaction_limit(provider_limit: int) -> int:
    """Leave fixed fractional headroom inside the provider context window."""
    return max(1, math.floor(provider_limit * (1 - REQUEST_HEADROOM_FRACTION)))
