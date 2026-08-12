"""Append-only terminal event storage for context management.

Per the Terminal Context Blueprint:
- Pure Python, append-only in-memory log
- Only owner of captured terminal data
- Events are immutable and assigned monotonically increasing sequence numbers
- Distinguishes output vs input streams
"""

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class TerminalEvent:
    """A single captured terminal event.

    Per blueprint contract:
    - Every terminal event belongs to an ordered, append-only session transcript
    - Events are assigned monotonically increasing sequence numbers
    - Each event is included in model context once, and never deliberately duplicated
    """
    sequence: int
    stream: Literal["output", "input"]
    raw: bytes


@dataclass(frozen=True)
class TranscriptSlice:
    """An immutable view into a range of terminal events.

    Per blueprint contract:
    - Contains text from events in range [start_sequence, end_sequence)
    - The text is the concatenation of raw bytes from matching events
    """
    start_sequence: int
    end_sequence: int
    text: str


@dataclass
class TranscriptStore:
    """Append-only in-memory log of terminal events.

    Per blueprint contract:
    - Pure Python, append-only in-memory log
    - Only owner of captured terminal data
    - Events are immutable and assigned monotonically increasing sequence numbers
    - Distinguishes output vs input streams
    """
    events: list[TerminalEvent] = field(default_factory=list)
    _next_sequence: int = 0

    def append(self, stream: Literal["output", "input"], raw: bytes) -> TerminalEvent:
        """Append a terminal event and return the created event.

        Args:
            stream: Either "output" (shell-to-terminal) or "input" (terminal-to-shell)
            raw: The captured bytes

        Returns:
            The newly created TerminalEvent with assigned sequence number
        """
        event = TerminalEvent(self._next_sequence, stream, raw)
        self.events.append(event)
        self._next_sequence += 1
        return event

    def get_slice(self, start_seq: int, end_seq: int) -> TranscriptSlice:
        """Return a slice of the transcript for the given sequence range.

        Joins all raw bytes before decoding to correctly handle multi-byte
        UTF-8 characters split across events.

        Args:
            start_seq: Inclusive start sequence number
            end_seq: Exclusive end sequence number

        Returns:
            TranscriptSlice containing all events in [start_seq, end_seq)
        """
        matching = [e for e in self.events if start_seq <= e.sequence < end_seq]
        # Join raw bytes first, then decode once
        combined = b"".join(e.raw for e in matching)
        text = combined.decode("utf-8", errors="replace")
        return TranscriptSlice(start_seq, end_seq, text)

    @property
    def next_sequence(self) -> int:
        """Return the next sequence number to be assigned."""
        return self._next_sequence

    @property
    def is_empty(self) -> bool:
        """Return True if no events have been captured."""
        return len(self.events) == 0