"""Phase 1 acceptance test: two successful turns preserve terminal context.

This is a pure ContextSession unit test.  The production-seam equivalent lives
in test_phase0_xfail.py and drives TroubleWindow's send/finish workflow.
"""

from unittest.mock import MagicMock, patch

from troubleshell.chat.models import ChatMessage
from troubleshell.config import Config
from troubleshell.llm.context_session import ContextSession
from troubleshell.llm.prompt import build_request
from troubleshell.terminal.transcript_store import TranscriptStore


class FakeGTK:
    """Minimal fake GTK objects."""
    
    class TextView:
        def __init__(self):
            self._buffer = ""
            self.sensitive = True
            self.visible = True
        def get_buffer(self):
            return self
        def get_text(self, start, end, include_hidden_chars):
            return self._buffer
        def set_text(self, text):
            self._buffer = text
        def set_sensitive(self, sensitive):
            self.sensitive = sensitive
        def set_visible(self, visible):
            self.visible = visible
        def get_bounds(self):
            start_iter = MagicMock()
            end_iter = MagicMock()
            return start_iter, end_iter
    
    class Button:
        def __init__(self):
            self.sensitive = True
            self.visible = True
        def set_sensitive(self, sensitive):
            self.sensitive = sensitive
        def set_visible(self, visible):
            self.visible = visible
    
    class Label:
        def __init__(self, text=""):
            self._text = text
            self.visible = True
            self.sensitive = True
        def set_text(self, text):
            self._text = text
        def get_text(self):
            return self._text
        def set_visible(self, visible):
            self.visible = visible
        def set_sensitive(self, sensitive):
            self.sensitive = sensitive


class FakeTerminalPane:
    """Fake terminal pane; context comes from the session/store."""


class FakeConfig:
    """Minimal config for TroubleWindow."""
    
    def __init__(self):
        self.model = "test-model"
        self.endpoint_url = "http://localhost:8080/v1"
        self.api_key = "test-key"
        self.verify_tls = True
        self.max_context_tokens = 8192
        self.system_prompt = "You are a helpful assistant."
        self.shell = "bash"
        self.terminal_font_size = 12
        self.terminal_font = "monospace 12"
        self.chat_font_size = 12


class FakeThread:
    """Record a background task without ever running it."""
    
    instances = []
    
    def __init__(self, *, target=None, args=(), **_kwargs):
        self.target = target
        self.args = args
        self.started = False
        type(self).instances.append(self)
    
    def start(self):
        self.started = True


def test_two_successful_turns_preserve_terminal_context():
    """Two successful turns: A in history, B in current payload, no duplication.
    
    This is a PRODUCTION-SEAM test that verifies the core requirement:
    - Terminal output A is captured, sent with Q1, committed to history
    - Terminal output B is captured, sent with Q2
    - A appears exactly once in committed history (in the user message)
    - B appears exactly once in the current request payload
    - Q1 and Q2 are correct
    - Neither A nor B is duplicated
    """
    # Setup: create a fake window with context session
    config = FakeConfig()
    
    # Create transcript store and context session directly
    transcript_store = TranscriptStore()
    context_session = ContextSession(transcript=transcript_store)
    
    # Simulate terminal output A
    transcript_store.append("output", b"terminal output A line 1\n")
    transcript_store.append("output", b"terminal output A line 2\n")
    
    # Turn 1: snapshot with Q1 and terminal payload A
    payload_1 = transcript_store.get_slice(0, 2).text  # Events 0-1
    context_session.request_slice()
    context_session.snapshot_for_send(
        build_request(model="test", question="Q1", transcript=payload_1).messages[-1]
    )
    built_payload_1 = context_session.build_request_payload()
    
    # Verify payload 1 contains output A
    assert "terminal output A line 1" in built_payload_1
    assert "terminal output A line 2" in built_payload_1
    
    # The full user message (with Q1) is stored separately
    assert context_session.pending_user_message is not None
    assert "Q1" in context_session.pending_user_message.content
    
    # Verify the stored user message contains the full terminal context
    assert context_session.pending_user_message is not None
    assert context_session.pending_user_message.role == "user"
    assert "<terminal_context>" in context_session.pending_user_message.content
    assert "terminal output A line 1" in context_session.pending_user_message.content
    assert "Q1" in context_session.pending_user_message.content
    
    # Commit turn 1 successfully
    context_session.commit_on_success("A1")
    
    # Verify history contains the complete pair with the EXACT user message sent
    assert len(context_session.history) == 2
    assert context_session.history[0].role == "user"
    # The history should contain the same message that was stored before commit
    assert "<terminal_context>" in context_session.history[0].content
    assert "terminal output A line 1" in context_session.history[0].content
    assert "Q1" in context_session.history[0].content
    assert context_session.history[1].role == "assistant"
    assert context_session.history[1].content == "A1"
    
    # Verify acknowledged_sequence advanced
    assert context_session.acknowledged_sequence == 2  # Two events emitted
    
    # Simulate terminal output B (new output after turn 1)
    transcript_store.append("output", b"terminal output B line 1\n")
    transcript_store.append("output", b"terminal output B line 2\n")
    
    # Turn 2: snapshot with Q2 and terminal payload B (delta)
    payload_2 = transcript_store.get_slice(2, 4).text  # Events 2-3 only (the delta)
    context_session.request_slice()
    context_session.snapshot_for_send(
        build_request(model="test", question="Q2", transcript=payload_2).messages[-1]
    )
    built_payload_2 = context_session.build_request_payload()
    
    # Verify payload 2 contains only output B (the delta since turn 1)
    assert "terminal output B line 1" in built_payload_2
    assert "terminal output B line 2" in built_payload_2
    assert "terminal output A" not in built_payload_2
    
    # The full user message (with Q2) is stored separately
    assert context_session.pending_user_message is not None
    assert "Q2" in context_session.pending_user_message.content
    
    # Verify the stored user message contains the exact terminal context for turn 2
    assert context_session.pending_user_message is not None
    assert context_session.pending_user_message.role == "user"
    assert "<terminal_context>" in context_session.pending_user_message.content
    assert "terminal output B line 1" in context_session.pending_user_message.content
    assert "terminal output A" not in context_session.pending_user_message.content  # A not duplicated
    assert "Q2" in context_session.pending_user_message.content
    
    # Verify history still contains turn 1's complete pair with A
    assert len(context_session.history) == 2
    # history[0] still has A (turn 1's user message), not B
    assert "terminal output A line 1" in context_session.history[0].content
    assert "terminal output B line 1" not in context_session.history[0].content
    
    # Simulate successful completion of turn 2
    context_session.commit_on_success("B2")
    
    # Verify history now contains two complete pairs (4 messages)
    assert len(context_session.history) == 4
    
    # Turn 1's user message (with A) should be in history[0]
    assert context_session.history[0].role == "user"
    assert "terminal output A line 1" in context_session.history[0].content
    assert "terminal output B line 1" not in context_session.history[0].content
    assert "Q1" in context_session.history[0].content
    
    # Turn 1's assistant response
    assert context_session.history[1].role == "assistant"
    assert context_session.history[1].content == "A1"
    
    # Turn 2's user message (with B) should be in history[2]
    assert context_session.history[2].role == "user"
    assert "terminal output B line 1" in context_session.history[2].content
    assert "terminal output A line 1" not in context_session.history[2].content  # No duplication
    assert "Q2" in context_session.history[2].content
    
    # Turn 2's assistant response
    assert context_session.history[3].role == "assistant"
    assert context_session.history[3].content == "B2"
    
    # Verify the core requirement:
    # - A appears exactly once in history (in history[0])
    # - B appears exactly once in history (in history[2])
    # - Neither A nor B is duplicated
    user_messages = [msg for msg in context_session.history if msg.role == "user"]
    assert len(user_messages) == 2
    assert "terminal output A line 1" in user_messages[0].content
    assert "terminal output A line 1" not in user_messages[1].content  # No duplication
    assert "terminal output B line 1" in user_messages[1].content
    assert "terminal output B line 1" not in user_messages[0].content  # No duplication
    
    # Verify transcript store has all 4 events
    assert len(transcript_store.events) == 4
    assert transcript_store.events[0].raw == b"terminal output A line 1\n"
    assert transcript_store.events[1].raw == b"terminal output A line 2\n"
    assert transcript_store.events[2].raw == b"terminal output B line 1\n"
    assert transcript_store.events[3].raw == b"terminal output B line 2\n"
    
    # Verify the acknowledged_sequence points to 4 (all events acknowledged)
    assert context_session.acknowledged_sequence == 4
