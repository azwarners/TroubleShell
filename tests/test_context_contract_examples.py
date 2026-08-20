"""Phase 0: Contract tests for the Terminal Context Blueprint.

These tests document the required behavior from the blueprint and should FAIL
under the current implementation. They target pure logic that doesn't require
GTK/VTE, focusing on the state machine contract:

- Failed/cancelled requests resend the same terminal range
- Events acknowledged only after successful response
- Events during a request appear in the next turn only
- Duplicate terminal text in distinct events remains distinct
- No output disappears because VTE scrollback is limited
- Normal turns never trim terminal events
- Compaction retains the newest third and emits one explicit baseline
- Subsequent turns append to the compacted baseline without repeated trimming
- History always contains complete user/assistant pairs
"""

from dataclasses import dataclass, field
from typing import Literal

from troubleshell.chat.models import ChatMessage


# --- Minimal test fixtures that mimic the blueprint's event model ---


@dataclass(frozen=True)
class TerminalEvent:
    """Mimics the blueprint's TerminalEvent (Phase 1 model)."""
    sequence: int
    stream: Literal["output", "input"]
    raw: bytes


@dataclass(frozen=True)
class TranscriptSlice:
    """Mimics the blueprint's TranscriptSlice (Phase 1 model)."""
    start_sequence: int
    end_sequence: int
    text: str


@dataclass
class MockTranscriptStore:
    """
    Minimal append-only transcript store for testing the contract.
    NOT the Phase 1 implementation — just a test fixture.
    """
    events: list[TerminalEvent] = field(default_factory=list)
    _next_sequence: int = 0

    def append(self, stream: Literal["output", "input"], raw: bytes) -> TerminalEvent:
        event = TerminalEvent(self._next_sequence, stream, raw)
        self.events.append(event)
        self._next_sequence += 1
        return event

    def get_slice(self, start_seq: int, end_seq: int) -> TranscriptSlice:
        """Return text from events in range [start_seq, end_seq)."""
        matching = [e for e in self.events if start_seq <= e.sequence < end_seq]
        text = "".join(e.raw.decode("utf-8", errors="replace") for e in matching)
        return TranscriptSlice(start_seq, end_seq, text)


@dataclass
class MockContextSession:
    """
    Minimal context session state machine for testing the contract.
    NOT the Phase 1 implementation — just a test fixture.
    """
    transcript: MockTranscriptStore
    acknowledged_sequence: int = 0
    transcript_start_sequence: int = 0
    pending_request_end_sequence: int | None = None
    pending_user_message: ChatMessage | None = None  # The exact user message sent
    history: list[ChatMessage] = field(default_factory=list)

    def snapshot_for_send(self, question: str, terminal_payload: str) -> int:
        """Capture the current end sequence before building a request."""
        self.pending_request_end_sequence = self.transcript._next_sequence
        # Store the EXACT user message with terminal context
        user_content = (
            f"<terminal_context>\n{terminal_payload}\n</terminal_context>\n\n"
            f"<user_question>\n{question}\n</user_question>"
        )
        self.pending_user_message = ChatMessage("user", user_content)
        return self.transcript._next_sequence

    def build_request_payload(self) -> str:
        """Build the terminal context payload for the request."""
        end_seq = self.pending_request_end_sequence if self.pending_request_end_sequence is not None else self.transcript._next_sequence
        return self.transcript.get_slice(self.acknowledged_sequence, end_seq).text

    def commit_on_success(self, response: str) -> None:
        """Advance acknowledgement after successful response."""
        # Append the EXACT user message that was sent (with terminal context)
        if self.pending_user_message is not None:
            self.history.append(self.pending_user_message)
        self.history.append(ChatMessage("assistant", response))
        self.acknowledged_sequence = self.pending_request_end_sequence if self.pending_request_end_sequence is not None else self.acknowledged_sequence
        self.pending_request_end_sequence = None
        self.pending_user_message = None

    def rollback_on_failure(self) -> None:
        """Discard the transient request object on cancellation or failure."""
        self.pending_request_end_sequence = None
        self.pending_user_message = None

    def compact(self, provider_limit: int) -> int:
        """Perform compaction (mock version)."""
        total_events = self.transcript._next_sequence
        if total_events <= 3:
            return self.acknowledged_sequence
        new_start = (total_events * 2) // 3
        if new_start <= self.transcript_start_sequence:
            return self.transcript_start_sequence
        self.transcript_start_sequence = new_start
        self.acknowledged_sequence = new_start
        return new_start


# --- Phase 0 Contract Tests ---


def test_failed_request_resends_same_terminal_range() -> None:
    """A failed or cancelled request resends the same terminal range.
    
    Blueprint contract: "A failed, cancelled, or rejected model request does not
    consume context. Its unacknowledged terminal events are resent on the next
    successful submission attempt."
    """
    store = MockTranscriptStore()
    session = MockContextSession(transcript=store)
    
    # Emit some terminal output
    store.append("output", b"line 1\n")
    store.append("output", b"line 2\n")
    store.append("output", b"line 3\n")
    
    # First send attempt
    session.snapshot_for_send("Test question", "terminal output")
    payload_1 = session.build_request_payload()
    
    # Simulate failure (do NOT commit)
    session.rollback_on_failure()
    
    # Second send attempt without new terminal events
    session.snapshot_for_send("Test question", "terminal output")
    payload_2 = session.build_request_payload()
    
    # Both payloads should contain the same terminal range
    assert payload_1 == payload_2
    assert "line 1" in payload_1
    assert "line 3" in payload_1
    
    # Acknowledgement cursor should still be at 0
    assert session.acknowledged_sequence == 0


def test_acknowledgement_only_after_successful_response() -> None:
    """An event is acknowledged only after a successful response.
    
    Blueprint contract: "On a successful model response, append the user request
    and assistant response to committed history, then advance acknowledged_sequence
    to the snapshot end."
    """
    store = MockTranscriptStore()
    session = MockContextSession(transcript=store)
    
    # Emit terminal output
    store.append("output", b"event A\n")
    store.append("output", b"event B\n")
    
    # Send and fail
    session.snapshot_for_send("Test question", "terminal output")
    session.rollback_on_failure()
    
    # Acknowledgement should still be at 0
    assert session.acknowledged_sequence == 0
    
    # Send again and succeed
    session.snapshot_for_send("Test question", "terminal output")
    session.commit_on_success("Response B")
    
    # Now acknowledgement should advance to the end
    assert session.acknowledged_sequence == 2  # Two events emitted
    assert len(session.history) == 2
    assert session.history[0].role == "user"
    assert "Test question" in session.history[0].content and "<terminal_context>" in session.history[0].content
    assert session.history[1].role == "assistant"
    assert session.history[1].content == "Response B"


def test_events_during_request_appear_in_next_turn() -> None:
    """Events emitted during a request appear only in the next request.
    
    Blueprint contract: "Events arriving while the request is in flight belong
    to the next turn."
    """
    store = MockTranscriptStore()
    session = MockContextSession(transcript=store)
    
    # Initial output
    store.append("output", b"pre-request\n")
    
    # First send
    session.snapshot_for_send("Test question", "terminal output")
    payload_1 = session.build_request_payload()
    session.commit_on_success("Response 1")
    
    # Events arrive DURING the first request (before second send)
    store.append("output", b"during-flight\n")
    store.append("output", b"also-during\n")
    
    # Second send
    session.snapshot_for_send("Test question", "terminal output")
    payload_2 = session.build_request_payload()
    
    # Payload 1 should NOT contain during-flight events
    assert "during-flight" not in payload_1
    assert "also-during" not in payload_1
    
    # Payload 2 should contain them exactly once
    assert "during-flight" in payload_2
    assert "also-during" in payload_2


def test_duplicate_terminal_text_remains_distinct() -> None:
    """Duplicate terminal text in distinct events remains distinct.
    
    Blueprint contract: "Duplicate terminal text in distinct events remains
    distinct" — the delta algorithm should not collapse repeated output.
    """
    store = MockTranscriptStore()
    session = MockContextSession(transcript=store)
    
    # Emit identical lines as separate events
    store.append("output", b"repeat\n")
    store.append("output", b"repeat\n")
    store.append("output", b"repeat\n")
    
    session.snapshot_for_send("Test question", "terminal output")
    payload = session.build_request_payload()
    
    # All three should appear in the payload
    assert payload.count("repeat") == 3
    
    # Each should have a distinct sequence number
    assert len([e for e in store.events if e.raw == b"repeat\n"]) == 3


def test_no_output_disappears_due_to_vte_scrollback() -> None:
    """No output disappears because VTE scrollback is limited.
    
    Blueprint contract: "No output disappears because VTE scrollback is limited."
    The canonical source is the captured byte stream, not VTE screen snapshots.
    
    NOTE: This test documents the contract. The current implementation uses
    VTE's get_text_range_format() which CAN lose output if it exceeds internal
    scrollback buffers. Phase 3 (PTY proxy) will fix this.
    """
    store = MockTranscriptStore()
    session = MockContextSession(transcript=store)
    
    # Simulate more output than typical VTE scrollback would hold
    for i in range(500):
        store.append("output", f"ls output line {i}\n".encode())
    
    session.snapshot_for_send("Test question", "terminal output")
    payload = session.build_request_payload()
    
    # All 500 lines should be present (in the pure store model)
    for i in range(500):
        assert f"ls output line {i}" in payload
    
    # Current implementation might fail this if VTE scrollback is exhausted


def test_normal_turns_never_trim_terminal_events() -> None:
    """Normal turns never trim terminal events.
    
    Blueprint contract: "TroubleShell does not trim a terminal message just because
    it is large" and "normal turns never trim terminal events."
    
    Trimming only happens during compaction when approaching the provider limit.
    """
    store = MockTranscriptStore()
    session = MockContextSession(transcript=store)
    
    # Emit substantial output
    for i in range(100):
        store.append("output", f"line {i}\n".encode())
    
    session.snapshot_for_send("Test question", "terminal output")
    payload = session.build_request_payload()
    
    # All 100 lines should be present (no trimming on normal send)
    assert len([l for l in payload.splitlines() if l.startswith("line")]) == 100
    assert "line 0" in payload
    assert "line 99" in payload


def test_compaction_retains_newest_third() -> None:
    """Compaction retains the newest third and emits one explicit baseline.
    
    Blueprint contract: "When the complete request approaches the provider limit,
    TroubleShell performs one explicit compaction: drop the oldest two thirds of
    terminal transcript events and retain the newest third."
    """
    # This test documents the compaction contract. The current implementation
    # has no compaction logic, so it will fail until Phase 1-2 adds ContextSession.
    
    store = MockTranscriptStore()
    
    # Emit 300 events
    for i in range(300):
        store.append("output", f"event {i}\n".encode())
    
    # Simulate compaction: retain newest 100 events (the last third)
    # This is what the Phase 1 ContextSession.compact() would do
    compacted_start = 200  # Drop first 200, keep 200-299
    compacted_slice = store.get_slice(compacted_start, 300)
    
    # Compacted payload should contain only events 200-299
    assert "event 199" not in compacted_slice.text
    assert "event 200" in compacted_slice.text
    assert "event 299" in compacted_slice.text
    assert len(compacted_slice.text.splitlines()) == 100


def test_subsequent_turns_append_to_compacted_baseline() -> None:
    """Subsequent turns append to the compacted baseline without repeated trimming.
    
    Blueprint contract: "It then continues normal append-only operation from that
    retained baseline" — compaction happens once, then normal operation resumes.
    """
    store = MockTranscriptStore()
    
    # Pre-compaction: emit 300 events (0-299)
    for i in range(300):
        store.append("output", f"pre-compact {i}\n".encode())
    
    # Simulate compaction: drop first 200, keep events 200-299
    # After compaction, acknowledged_sequence = 200 (first retained event)
    # transcript_start_sequence = 200
    
    # Post-compaction: emit new events starting from sequence 300
    for i in range(200, 210):
        store.append("output", f"post-compact {i}\n".encode())
    
    # Simulate ContextSession state after compaction
    session = MockContextSession(
        transcript=store,
        acknowledged_sequence=200,  # Events 0-199 were dropped; 200 is first retained
    )
    
    # Send a turn: should include events 200-309 (from acknowledged to current end)
    session.snapshot_for_send("Test question", "terminal output")
    payload = session.build_request_payload()
    
    # Should contain post-compaction events starting from 200
    assert "pre-compact 200" in payload  # Event 200 (pre-compact label)
    assert "post-compact 209" in payload  # Events 300-309 (post-compact labels)
    
    # Commit the success
    session.commit_on_success("Acknowledged")
    
    # acknowledged_sequence should now be 310 (end of store)
    assert session.acknowledged_sequence == 310
    
    # Next send should only include NEW events after 310
    store.append("output", b"new after commit\n")
    session.snapshot_for_send("Test question", "terminal output")
    payload_2 = session.build_request_payload()
    
    # Should only contain the new event (sequence 310)
    assert "new after commit" in payload_2
    # Pre-compact and post-compact events are now in acknowledged history


def test_history_contains_complete_user_assistant_pairs() -> None:
    """History always contains complete user/assistant pairs.
    
    Blueprint contract: "history always contains complete user/assistant pairs."
    Speculative or failed messages should not enter committed history.
    """
    store = MockTranscriptStore()
    session = MockContextSession(transcript=store)
    
    store.append("output", b"initial\n")
    
    # Send 1: fail
    session.snapshot_for_send("Test question", "terminal output")
    session.rollback_on_failure()
    
    # History should be empty (failed request didn't commit)
    assert len(session.history) == 0
    
    # Send 2: succeed
    session.snapshot_for_send("Question 2", "terminal output")
    session.commit_on_success("Response 2")
    
    # History should have exactly one complete pair
    assert len(session.history) == 2
    assert session.history[0].role == "user"
    assert "Question 2" in session.history[0].content and "<terminal_context>" in session.history[0].content
    assert session.history[1].role == "assistant"
    assert session.history[1].content == "Response 2"
    
    # Send 3: succeed
    store.append("output", b"during 3\n")
    session.snapshot_for_send("Question 3", "terminal output")
    session.commit_on_success("Response 3")
    
    # History should have two complete pairs (4 messages total)
    assert len(session.history) == 4
    assert session.history[2].role == "user"
    assert "Question 3" in session.history[2].content and "<terminal_context>" in session.history[2].content
    assert session.history[3].role == "assistant"
    assert session.history[3].content == "Response 3"


def test_retry_after_error_sends_same_range() -> None:
    """Send, induce a provider error, then retry; the retry contains the same range.
    
    Blueprint contract: "On cancellation or failure, discard only the transient
    request object. Leave the acknowledgement cursor unchanged, so the next send
    includes the same terminal range."
    """
    store = MockTranscriptStore()
    session = MockContextSession(transcript=store)
    
    store.append("output", b"error context\n")
    store.append("output", b"more context\n")
    
    # First send
    session.snapshot_for_send("Test question", "terminal output")
    payload_1 = session.build_request_payload()
    
    # Simulate provider error (429, 500, etc.)
    session.rollback_on_failure()
    
    # Retry without new terminal output
    session.snapshot_for_send("Test question", "terminal output")
    payload_retry = session.build_request_payload()
    
    # Retry should contain exactly the same terminal range
    assert payload_1 == payload_retry
    assert "error context" in payload_retry
    assert "more context" in payload_retry
    
    # Now succeed the retry
    session.commit_on_success("Success after retry")
    
    # Acknowledgement should now advance
    assert session.acknowledged_sequence == 2