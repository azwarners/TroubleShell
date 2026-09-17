"""Terminal output capturer — pure raw-byte sink.

Phase 2 removes the unsafe VTE polling adapter. Actual live capture occurs at
the terminal I/O boundary in Phase 3's PTY proxy, which calls record_output(raw)
before forwarding bytes to VTE.

This module provides no polling, threads, VTE access, normalization, line
splitting, or error swallowing.
"""

from dataclasses import dataclass

from troubleshell.terminal.transcript_store import TranscriptStore


@dataclass
class TerminalOutputCapturer:
    """Pure sink for raw terminal output bytes.

    The PTY proxy (Phase 3) is the sole caller of record_output().
    """

    transcript_store: TranscriptStore

    def record_output(self, raw: bytes) -> None:
        """Record raw terminal output bytes exactly as received.

        Zero-length chunks are silently ignored (EOF/closure from PTY proxy).
        """
        if not raw:
            return
        self.transcript_store.append("output", raw)
