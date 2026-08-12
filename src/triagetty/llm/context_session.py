"""Context session state machine for terminal event tracking.

Per the Terminal Context Blueprint, this module provides:
- ContextSession: state machine tracking acknowledged/unacknowledged ranges
- Compaction when approaching provider limits
"""

from dataclasses import dataclass, field
import re

from triagetty.chat.models import ChatMessage
from triagetty.terminal.transcript_store import TranscriptStore


_TERMINAL_CONTEXT_RE = re.compile(
    r"<terminal_context>\n.*?\n</terminal_context>", re.DOTALL
)


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
    pending_request_end_sequence: int | None = None
    pending_user_message: ChatMessage | None = None  # The exact user message sent
    history: list[ChatMessage] = field(default_factory=list)

    def snapshot_for_send(self, user_message: ChatMessage) -> int:
        """Capture the current transcript end sequence before building a request.

        Args:
            user_message: The exact user message in the outbound request.

        Returns:
            The end sequence (exclusive) of the transcript at snapshot time
        """
        self.pending_request_end_sequence = self.transcript.next_sequence
        # Keep the actual serialized message, rather than reconstructing it.
        # This matters when request construction or compaction changes its content.
        self.pending_user_message = user_message
        return self.pending_request_end_sequence

    def build_request_payload(self) -> str:
        """Build the terminal context payload for the request.

        Per blueprint contract:
        - Sends all unacknowledged terminal events through the snapshot
        - Returns the raw text from events in [acknowledged_sequence, pending_end)

        Returns:
            The terminal transcript text to include in the model request
        """
        end_seq = self.pending_request_end_sequence if self.pending_request_end_sequence is not None else self.transcript.next_sequence
        return self.transcript.get_slice(self.acknowledged_sequence, end_seq).text

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
        self.acknowledged_sequence = self.pending_request_end_sequence if self.pending_request_end_sequence is not None else self.acknowledged_sequence
        self.pending_request_end_sequence = None
        self.pending_user_message = None

    def rollback_on_failure(self) -> None:
        """Discard the transient request object on cancellation or failure.

        Per blueprint contract:
        - Leave acknowledged_sequence unchanged
        - Clear the pending request state
        - Next send will include the same unacknowledged range
        """
        self.pending_request_end_sequence = None
        self.pending_user_message = None

    def compact(self, provider_limit: int) -> int:
        """Perform compaction when approaching provider context limit.

        Per blueprint contract: "When the complete request approaches the provider
        limit, TriageTTY performs one explicit compaction: drop the oldest two thirds
        of terminal transcript events and retain the newest third."

        Args:
            provider_limit: The provider's context token limit

        Returns:
            The new acknowledged_sequence (start of retained baseline)
        """
        total_events = self.transcript.next_sequence
        if total_events <= 3:
            return self.acknowledged_sequence

        # Retain newest third: keep events from index 2/3 onwards
        new_start = (total_events * 2) // 3
        if new_start <= self.transcript_start_sequence:
            return self.transcript_start_sequence

        self.transcript_start_sequence = new_start
        self.acknowledged_sequence = new_start
        # Old terminal output is embedded in committed user messages.  Dropping
        # it from the cursor alone would not reduce the next provider request.
        # Preserve the question/assistant conversation while replacing only
        # discarded terminal bytes with an explicit marker.
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
        return new_start

    def get_unacknowledged_count(self) -> int:
        """Return the number of unacknowledged terminal events."""
        return self.transcript.next_sequence - self.acknowledged_sequence
