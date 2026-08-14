"""Tests for ContextSession.request_slice() atomic snapshot behavior.

Validates:
- request_slice() atomically snapshots and stores a TranscriptSlice
- build_request_payload() returns text from the stored slice
- commit_on_success() advances acknowledged_sequence to slice.end_sequence
- rollback_on_failure() clears pending_slice without advancing cursor
- Re-snapshot after compaction uses updated acknowledged_sequence
"""

from triagetty.chat.models import ChatMessage
from triagetty.llm.context_session import ContextSession
from triagetty.terminal.transcript_store import TranscriptStore


class TestRequestSliceAtomic:
    """Tests for atomic request slice snapshotting."""

    def test_request_slice_snapshots_automatically(self):
        """request_slice() creates and stores a TranscriptSlice."""
        store = TranscriptStore()
        store.append("output", b"event1\n")
        store.append("output", b"event2\n")
        session = ContextSession(transcript=store)

        slice_ = session.request_slice()

        assert slice_.text == "event1\nevent2\n"
        assert slice_.start_sequence == 0
        assert slice_.end_sequence == 2
        assert session.pending_slice is not None
        assert session.pending_slice.end_sequence == 2

    def test_request_slice_excludes_later_append(self):
        """Append A, request_slice, append B — first payload has A only; second has B only."""
        store = TranscriptStore()
        session = ContextSession(transcript=store)

        # Append A and snapshot
        store.append("output", b"A\n")
        session.request_slice()
        payload_1 = session.build_request_payload()

        # Append B after snapshot
        store.append("output", b"B\n")

        # First payload should contain A only
        assert payload_1 == "A\n"
        assert "B" not in payload_1

        # Commit first request
        user_msg = ChatMessage("user", "question")
        session.snapshot_for_send(user_msg)
        session.commit_on_success("response")

        # Re-snapshot for second request
        session.request_slice()
        payload_2 = session.build_request_payload()

        # Second payload should contain B only
        assert payload_2 == "B\n"
        assert "A" not in payload_2

    def test_build_request_payload_uses_stored_slice(self):
        """build_request_payload() returns text from the stored pending slice."""
        store = TranscriptStore()
        store.append("output", b"terminal output\n")
        session = ContextSession(transcript=store)

        session.request_slice()
        payload = session.build_request_payload()

        assert payload == "terminal output\n"

    def test_build_request_payload_empty_without_slice(self):
        """build_request_payload() returns empty string when no slice exists."""
        store = TranscriptStore()
        session = ContextSession(transcript=store)

        assert session.build_request_payload() == ""

    def test_commit_advances_to_slice_end(self):
        """commit_on_success() advances acknowledged_sequence to slice.end_sequence."""
        store = TranscriptStore()
        store.append("output", b"A\n")
        store.append("output", b"B\n")
        session = ContextSession(transcript=store)

        session.request_slice()
        user_msg = ChatMessage("user", "question")
        session.snapshot_for_send(user_msg)
        session.commit_on_success("response")

        assert session.acknowledged_sequence == 2
        assert session.pending_slice is None
        assert session.pending_user_message is None


class TestRollback:
    """Tests for rollback behavior."""

    def test_rollback_clears_slice_without_advancing(self):
        """rollback_on_failure() clears pending_slice but leaves cursor unchanged."""
        store = TranscriptStore()
        store.append("output", b"A\n")
        store.append("output", b"B\n")
        session = ContextSession(transcript=store, acknowledged_sequence=1)

        session.request_slice()
        session.snapshot_for_send(ChatMessage("user", "question"))
        session.rollback_on_failure()

        assert session.acknowledged_sequence == 1  # unchanged
        assert session.pending_slice is None
        assert session.pending_user_message is None

    def test_retry_after_rollback_resnapshots(self):
        """A new request_slice() works after rollback."""
        store = TranscriptStore()
        store.append("output", b"A\n")
        session = ContextSession(transcript=store)

        # First attempt
        session.request_slice()
        session.snapshot_for_send(ChatMessage("user", "question"))
        session.rollback_on_failure()

        # New output arrives
        store.append("output", b"B\n")

        # Retry
        slice_ = session.request_slice()
        assert slice_.text == "A\nB\n"
        assert slice_.end_sequence == 2


class TestResnapshotAfterCompaction:
    """Tests for re-snapshotting after compaction."""

    def test_resnapshot_after_compact_uses_new_start(self):
        """request_slice() after compaction starts at new acknowledged_sequence."""
        store = TranscriptStore()
        for i in range(10):
            store.append("output", f"event{i}\n".encode())

        session = ContextSession(transcript=store)

        # Initial snapshot
        session.request_slice()
        assert session.pending_slice is not None
        assert session.pending_slice.start_sequence == 0

        # Compact
        session.compact(provider_limit=100)
        new_start = session.acknowledged_sequence

        # Re-snapshot
        slice_ = session.request_slice()
        assert slice_.start_sequence == new_start
        assert slice_.end_sequence == 10

    def test_compaction_rebases_pending_slice_without_extending_its_end(self):
        """Output after a request snapshot belongs to the following request."""
        store = TranscriptStore()
        for i in range(6):
            store.append("output", f"A{i}\n".encode())
        session = ContextSession(transcript=store)

        # The current request boundary ends at event 6.
        first_slice = session.request_slice()
        assert first_slice.end_sequence == 6

        # B arrives while the request is being rebuilt for compaction.
        store.append("output", b"B\n")
        session.compact(provider_limit=4)
        rebased = session.pending_slice
        assert rebased is not None

        assert rebased.end_sequence == 6
        assert "B\n" not in rebased.text

        session.snapshot_for_send(ChatMessage("user", "question"))
        session.commit_on_success("response")

        next_slice = session.request_slice()
        assert next_slice.text == "B\n"
        assert next_slice.end_sequence == 7
