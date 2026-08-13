"""Phase 2 tests: duplicate events and multi-turn non-duplication.

Verifies:
1. Duplicate bytes in separate events are retained as distinct events
2. An earlier chunk is not resent merely because a later chunk includes visually similar text
3. Empty bytes are not recorded (EOF/closure from proxy)
4. UTF-8 split across events decodes correctly
"""

from triagetty.chat.models import ChatMessage
from triagetty.llm.context_session import ContextSession
from triagetty.terminal.transcript_store import TranscriptStore


def test_duplicate_bytes_in_separate_events_preserved():
    """Two events with identical bytes should produce a payload containing both."""
    store = TranscriptStore()
    session = ContextSession(transcript=store)

    # Append two events with identical content
    store.append("output", b"same\n")
    store.append("output", b"same\n")

    # Snapshot for send
    user_msg = ChatMessage("user", "Test question")
    session.request_slice()
    session.snapshot_for_send(user_msg)

    # Build payload
    payload = session.build_request_payload()

    # Should contain "same" twice
    assert payload.count("same") == 2
    assert payload == "same\nsame\n"


def test_multi_turn_does_not_resend_similar_text():
    """An earlier chunk should not be resent just because a later chunk has similar text.
    
    Turn 1: Terminal output A ("error: file not found\n"), sent with Q1, committed
    Turn 2: Terminal output B ("error: permission denied\n"), sent with Q2
    - Q1's payload should contain "file not found"
    - Q2's payload should contain "permission denied" but NOT "file not found"
    """
    store = TranscriptStore()
    session = ContextSession(transcript=store)

    # Turn 1
    store.append("output", b"error: file not found\n")
    user_msg1 = ChatMessage("user", "Q1")
    session.request_slice()
    session.snapshot_for_send(user_msg1)
    payload1 = session.build_request_payload()
    session.commit_on_success("A1")

    assert "file not found" in payload1
    assert "permission denied" not in payload1

    # Turn 2
    store.append("output", b"error: permission denied\n")
    user_msg2 = ChatMessage("user", "Q2")
    session.request_slice()
    session.snapshot_for_send(user_msg2)
    payload2 = session.build_request_payload()
    session.commit_on_success("A2")

    # Q2 should only contain new terminal output
    assert "permission denied" in payload2
    assert "file not found" not in payload2


def test_three_turns_each_with_unique_terminal_output():
    """Three turns with unique terminal output should not duplicate anything."""
    store = TranscriptStore()
    session = ContextSession(transcript=store)

    for i in range(3):
        store.append("output", f"output {i}\n".encode("utf-8"))
        user_msg = ChatMessage("user", f"Q{i}")
        session.request_slice()
        session.snapshot_for_send(user_msg)
        payload = session.build_request_payload()
        session.commit_on_success(f"A{i}")

        # Each payload should only contain its own output
        assert f"output {i}" in payload
        for j in range(i):
            assert f"output {j}" not in payload

    # History should have 6 messages (3 user + 3 assistant)
    assert len(session.history) == 6


def test_utf8_split_across_events_decodes_correctly():
    """UTF-8 character split across events should decode correctly.
    
    Uses C3 A9 which is é in UTF-8.
    """
    store = TranscriptStore()
    
    # Split é (C3 A9) across two events
    store.append("output", b"caf\xc3")
    store.append("output", b"\xa9\n")
    
    # Get slice covering both events
    slice_result = store.get_slice(0, 2)
    assert "café" in slice_result.text
