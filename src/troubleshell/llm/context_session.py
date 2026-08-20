"""Context session state machine for terminal event tracking.

Per the Terminal Context Blueprint, this module provides:
- ContextSession: state machine tracking acknowledged/unacknowledged range
- Compaction when approaching provider limits
"""

from dataclasses import dataclass, field
import re

from troubleshell.chat.models import ChatMessage
from troubleshell.terminal.transcript import estimate_tokens, render_terminal_stream
from troubleshell.terminal.transcript_store import TranscriptSlice, TranscriptStore


_TERMINAL_CONTEXT_RE = re.compile(
    r"<terminal_context>\n.*?\n</terminal_context>", re.DOTALL
)
_COMPACTION_MARKER = "(older terminal context compacted)\n"


@dataclass
class ContextSession:
    """State machine tracking terminal context for model requests.

    Per blueprint contract:
    - Acknowledgement cursor advances only after successful response
    - Failed/cancelled requests discard only the transient request object
    - Unacknowledged terminal events are resent on next send attempt
    - History contains only complete (user, assistant) pairs as ChatMessage objects
    - Compaction retains newest third when approaching provider limits
    """
    transcript: TranscriptStore
    acknowledged_sequence: int = 0
    transcript_start_sequence: int = 0  # First sequence in current transcript baseline
    pending_slice: TranscriptSlice | None = None  # Atomic snapshot for current request
    pending_user_message: ChatMessage | None = None  # The exact user message sent
    history: list[ChatMessage] = field(default_factory=list)
    _compaction_passes: int = field(default=0, init=False, repr=False)

    def request_slice(self) -> TranscriptSlice:
        """Atomically snapshot and store the terminal context for a request.

        Calls TranscriptStore.snapshot_slice() once. Its end sequence is the
        immutable boundary for this request, even if output arrives while the
        request is later compacted and rebuilt.

        Returns:
            The TranscriptSlice covering [acknowledged_sequence, current_end)
        """
        slice_ = self.transcript.snapshot_slice(self.acknowledged_sequence)
        self.pending_slice = slice_
        self._compaction_passes = 0
        return slice_

    def rebase_pending_slice_after_compaction(self) -> TranscriptSlice:
        """Rebuild the pending slice from the compacted start at its fixed end.

        Compaction may advance ``acknowledged_sequence``.  It must not extend
        an already-snapshotted request to include output that arrived after the
        request boundary, so this deliberately uses the existing pending end
        rather than taking another store snapshot.
        """
        if self.pending_slice is None:
            raise RuntimeError("cannot rebase a request before taking its snapshot")
        self.pending_slice = self.transcript.get_slice(
            self.acknowledged_sequence, self.pending_slice.end_sequence
        )
        return self.pending_slice

    def snapshot_for_send(self, user_message: ChatMessage) -> None:
        """Store the user message being sent; request slice should already exist.

        Args:
            user_message: The exact user message in the outbound request.
        """
        self.pending_user_message = user_message

    def build_request_payload(self) -> str:
        """Return rendered terminal context text from the stored pending slice.

        Returns:
            The terminal transcript text to include in the model request
        """
        if self.pending_slice is None:
            return ""
        return render_terminal_stream(self.pending_slice.text)

    def commit_on_success(self, response: str) -> None:
        """Advance acknowledgement after successful response.

        Per blueprint contract:
        - Add the (user, assistant) pair to history
        - Advance acknowledged_sequence to the pending end
        - Clear the pending request state

        Args:
            response: The model's response
        """
        # Append the EXACT user message that was sent (with terminal context)
        if self.pending_user_message is not None:
            self.history.append(self.pending_user_message)
        self.history.append(ChatMessage("assistant", response))
        if self.pending_slice is not None:
            self.acknowledged_sequence = self.pending_slice.end_sequence
        self.pending_slice = None
        self.pending_user_message = None
        self._compaction_passes = 0

    def rollback_on_failure(self) -> None:
        """Discard the transient request object on cancellation or failure.

        Per blueprint contract:
        - Leave acknowledged_sequence unchanged
        - Clear the pending request state
        - Next send will include the same unacknowledged range
        """
        self.pending_slice = None
        self.pending_user_message = None
        self._compaction_passes = 0

    def compact(self, provider_limit: int) -> int:
        """Compact history and terminal context when approaching provider limits.

        Per blueprint contract:
        - Retain newest third of terminal events
        - Retain newest third of history
        - Update acknowledged_sequence to the first retained terminal event

        Args:
            provider_limit: Provider's token limit

        Returns:
            The new start sequence after compaction
        """
        total_events = self.transcript.next_sequence - self.transcript_start_sequence
        # Compaction is called only after the complete request estimate says it
        # is needed. Never compare event counts with a token limit here.
        new_start = self.transcript_start_sequence + (total_events * 2) // 3
        advanced = new_start > self.transcript_start_sequence
        if advanced:
            self.transcript_start_sequence = new_start
            self.acknowledged_sequence = new_start
        # Old terminal output is embedded in committed user messages.  Dropping
        # it from the cursor alone would not reduce the next provider request.
        # Preserve the question/assistant conversation while replacing only
        # discarded terminal bytes with an explicit marker.
        if advanced:
            self.history = [
                ChatMessage(
                    message.role,
                    _TERMINAL_CONTEXT_RE.sub(
                        "<terminal_context>\n(older terminal context compacted)\n</terminal_context>",
                        message.content,
                    ) if message.role == "user" else message.content,
                )
                for message in self.history
            ]

        self._compaction_passes += 1
        if self.pending_slice is not None:
            self.rebase_pending_slice_after_compaction()
            # A single event may contain most of the request. Sequence-based
            # rebasing cannot reduce that event, so retain its newest bytes as
            # the blueprint permits. Repeated calls progressively reduce it.
            text = self.pending_slice.text
            if self._compaction_passes == 1 and not advanced:
                retained = text[-max(1, len(text) // 3):]
            elif self._compaction_passes > 1:
                retained = text[-max(1, len(text) // 2):]
            else:
                retained = ""
            if retained:
                self.pending_slice = TranscriptSlice(
                    self.pending_slice.start_sequence,
                    self.pending_slice.end_sequence,
                    _COMPACTION_MARKER + retained,
                )
        return self.transcript_start_sequence

    def get_unacknowledged_count(self) -> int:
        """Return the number of unacknowledged terminal events."""
        return self.transcript.next_sequence - self.acknowledged_sequence
