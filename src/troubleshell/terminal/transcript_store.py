"""Terminal event storage for context management.

Per the Terminal Context Blueprint:
- Pure Python, append-only in-memory log except explicit user redaction
- Only owner of captured terminal data
- Events are immutable and assigned monotonically increasing sequence numbers
- Distinguishes output vs input streams
"""

from dataclasses import dataclass, field
from threading import RLock
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
    """Append-only in-memory log of terminal events with explicit redaction.

    Per blueprint contract:
    - Pure Python, append-only in-memory log
    - Only owner of captured terminal data
    - Events are immutable and assigned monotonically increasing sequence numbers
    - Distinguishes output vs input streams
    """
    _events: list[TerminalEvent] = field(default_factory=list, init=False, repr=False)
    _next_sequence: int = 0
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    @property
    def events(self) -> tuple[TerminalEvent, ...]:
        """Return an immutable snapshot of all events, ordered by sequence."""
        with self._lock:
            return tuple(self._events)

    def append(self, stream: Literal["output", "input"], raw: bytes) -> TerminalEvent:
        """Append a terminal event and return the created event.

        Args:
            stream: Either "output" (shell-to-terminal) or "input" (terminal-to-shell)
            raw: The captured bytes

        Returns:
            The newly created TerminalEvent with assigned sequence number
        """
        with self._lock:
            event = TerminalEvent(self._next_sequence, stream, raw)
            self._events.append(event)
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
        with self._lock:
            matching = [e for e in self._events if start_seq <= e.sequence < end_seq]
            combined = b"".join(e.raw for e in matching)
            text = combined.decode("utf-8", errors="replace")
            return TranscriptSlice(start_seq, end_seq, text)

    def snapshot_slice(self, start_sequence: int) -> TranscriptSlice:
        """Atomically capture current end and return [start_sequence, end).

        Acquires the lock once, saves _next_sequence as end_sequence, then
        returns a slice up to that boundary. Events appended after the lock
        is released belong to the next request.
        """
        with self._lock:
            end_sequence = self._next_sequence
            matching = [e for e in self._events if start_sequence <= e.sequence < end_sequence]
            combined = b"".join(e.raw for e in matching)
            text = combined.decode("utf-8", errors="replace")
            return TranscriptSlice(start_sequence, end_sequence, text)

    @property
    def next_sequence(self) -> int:
        """Return the next sequence number to be assigned."""
        with self._lock:
            return self._next_sequence

    @property
    def is_empty(self) -> bool:
        """Return True if no events have been captured."""
        with self._lock:
            return len(self._events) == 0

    def redact_text(self, text: str) -> tuple[bool, bytes]:
        """Remove the first exact UTF-8 occurrence and return redacted bytes.

        Redaction is an explicit user action and intentionally rewrites event
        payloads while preserving sequence numbers and event boundaries.
        """
        target = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
        if not target:
            return False, b""
        with self._lock:
            combined = b"".join(event.raw for event in self._events)
            start = combined.find(target)
            if start < 0:
                return False, b""
            end = start + len(target)
            offset = 0
            for index, event in enumerate(self._events):
                event_start = offset
                event_end = offset + len(event.raw)
                local_start = max(0, start - event_start)
                local_end = min(len(event.raw), end - event_start)
                if local_start < local_end:
                    raw = event.raw[:local_start] + event.raw[local_end:]
                    self._events[index] = TerminalEvent(event.sequence, event.stream, raw)
                offset = event_end
            return True, b"".join(event.raw for event in self._events)
