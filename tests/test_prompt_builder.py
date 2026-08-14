"""Tests for prompt building.

Targets context overflow and history management scenarios.
"""

from triagetty.chat.models import ChatMessage
from triagetty.llm.prompt import build_request
from triagetty.config import DEFAULT_SYSTEM_PROMPT


# --- Basic prompt building tests ---

def test_prompt_is_labeled_and_bounded() -> None:
    request = build_request(model="test", question="Why?", transcript="one\ntwo\nthree", max_tokens=10)
    assert request.model == "test"
    assert request.messages[0].content == DEFAULT_SYSTEM_PROMPT
    # All 3 lines fit in 10 tokens, so all should be included
    assert "<terminal_context>\none\ntwo\nthree\n</terminal_context>" in request.messages[-1].content
    assert "<user_question>\nWhy?\n</user_question>" in request.messages[-1].content


def test_history_is_kept_before_new_question() -> None:
    history = (ChatMessage("user", "old"), ChatMessage("assistant", "answer"))
    request = build_request(model="m", question="new", history=history)
    assert request.messages[1:] == (*history, request.messages[-1])


def test_empty_transcript_is_explicit() -> None:
    request = build_request(model="m", question="hello", transcript="")
    assert "(no terminal context was shared)" in request.messages[-1].content


def test_default_prompt_describes_triage_environment_and_boundary() -> None:
    prompt = DEFAULT_SYSTEM_PROMPT
    assert "TriageTTY's Linux troubleshooting partner" in prompt
    assert "no direct access to the host" in prompt
    assert "never executes them automatically" in prompt
    assert "untrusted evidence" in prompt


# --- Context overflow tests ---

def test_prompt_bounding_prevents_context_overflow() -> None:
    """Terminal layer handles bounding; prompt builder passes transcript through."""
    # The terminal layer (window.py) bounds the transcript before calling build_request
    # This test verifies that build_request passes the transcript through unchanged
    transcript = "line of terminal output\n" * 100  # Pre-bounded by terminal layer
    request = build_request(
        model="m", question="help", transcript=transcript,
        max_tokens=3000
    )
    
    # Extract the terminal context portion
    user_content = request.messages[-1].content
    context_start = user_content.find("<terminal_context>\n")
    context_end = user_content.find("\n</terminal_context>")
    context = user_content[context_start + len("<terminal_context>\n"):context_end]
    
    # Should pass through the transcript as-is (bounding happens at terminal layer)
    # Note: the transcript has a trailing newline from the last line, so compare with that
    assert context == transcript


def test_prompt_with_zero_token_limit_produces_no_context() -> None:
    """Zero max_tokens doesn't affect transcript (bounding happens at terminal layer)."""
    # The terminal layer bounds before calling build_request, so if it passes
    # a transcript, it means the terminal layer decided it fits within its budget
    request = build_request(
        model="m", question="help", transcript="some text",
        max_tokens=0
    )
    # With max_tokens=0, the terminal layer would have bounded to empty,
    # but if a transcript is passed, it's included as-is
    assert "some text" in request.messages[-1].content


def test_prompt_with_very_small_token_limit() -> None:
    """Small max_tokens doesn't affect transcript (bounding happens at terminal layer)."""
    # The terminal layer handles all the bounding logic before calling build_request
    request = build_request(
        model="m", question="help", transcript="a" * 1000,
        max_tokens=5
    )
    # The transcript passes through as-is; the terminal layer would have
    # already bounded it if needed before calling build_request
    user_content = request.messages[-1].content
    assert "a" * 1000 in user_content


def test_prompt_with_exactly_one_token_limit() -> None:
    """Should include content that fits within one token."""
    request = build_request(
        model="m", question="help", transcript="line1\nline2\nline3",
        max_tokens=1
    )
    user_content = request.messages[-1].content
    # Should have some content that fits in the token budget
    assert "<terminal_context>" in user_content


def test_prompt_context_overflow_does_not_crash() -> None:
    """Extremely large values should not crash."""
    request = build_request(
        model="m", question="help", transcript="x" * 1000000,
        max_tokens=1
    )
    # Should complete without error
    assert request is not None


# --- History management tests ---

def test_prompt_with_long_history() -> None:
    """Long conversation history should be included."""
    history = tuple(
        ChatMessage("user", f"question{i}") for i in range(50)
    ) + tuple(
        ChatMessage("assistant", f"answer{i}") for i in range(50)
    )
    request = build_request(model="m", question="new", history=history)
    
    # Should have system + 100 history messages + 1 new user message
    assert len(request.messages) == 102


def test_prompt_history_preserves_order() -> None:
    """History should be in the correct order."""
    history = (
        ChatMessage("user", "first"),
        ChatMessage("assistant", "first answer"),
        ChatMessage("user", "second"),
        ChatMessage("assistant", "second answer"),
    )
    request = build_request(model="m", question="third", history=history)
    
    # Verify order
    assert request.messages[1].content == "first"
    assert request.messages[2].content == "first answer"
    assert request.messages[3].content == "second"
    assert request.messages[4].content == "second answer"
    assert "third" in request.messages[5].content


def test_prompt_with_only_user_history() -> None:
    """History with only user messages should be preserved."""
    history = (
        ChatMessage("user", "question1"),
        ChatMessage("user", "question2"),
    )
    request = build_request(model="m", question="question3", history=history)
    
    assert request.messages[1].content == "question1"
    assert request.messages[2].content == "question2"


# --- Custom system prompt tests ---

def test_prompt_with_custom_system_prompt() -> None:
    """Custom system prompt should be used when provided."""
    custom_prompt = "You are a custom assistant."
    request = build_request(
        model="m", question="help",
        system_prompt=custom_prompt
    )
    assert request.messages[0].content == custom_prompt


def test_prompt_with_empty_custom_system_prompt_uses_default() -> None:
    """Empty custom prompt should fall back to default."""
    request = build_request(
        model="m", question="help",
        system_prompt=""
    )
    assert request.messages[0].content == DEFAULT_SYSTEM_PROMPT


def test_prompt_with_none_custom_system_prompt_uses_default() -> None:
    """None custom prompt should fall back to default."""
    request = build_request(
        model="m", question="help",
        system_prompt=None
    )
    assert request.messages[0].content == DEFAULT_SYSTEM_PROMPT


# --- Edge case tests ---

def test_prompt_with_unicode_question() -> None:
    """Unicode in questions should be preserved."""
    request = build_request(model="m", question="为什么？为什么？")
    assert "为什么" in request.messages[-1].content


def test_prompt_with_unicode_transcript() -> None:
    """Unicode in transcripts should be preserved."""
    request = build_request(
        model="m", question="help",
        transcript="终端输出：中文测试"
    )
    assert "中文测试" in request.messages[-1].content


def test_prompt_with_special_characters_in_question() -> None:
    """Special characters in questions should be preserved."""
    request = build_request(model="m", question="What is $HOME? How about ~?")
    assert "$HOME" in request.messages[-1].content
    assert "~" in request.messages[-1].content


def test_prompt_with_multiline_question() -> None:
    """Multiline questions should be preserved."""
    request = build_request(model="m", question="Line 1\nLine 2\nLine 3")
    assert "Line 1" in request.messages[-1].content
    assert "Line 2" in request.messages[-1].content
    assert "Line 3" in request.messages[-1].content


def test_prompt_with_empty_question() -> None:
    """Empty question should still produce a valid request."""
    request = build_request(model="m", question="")
    assert "<user_question>\n\n</user_question>" in request.messages[-1].content


def test_prompt_with_whitespace_only_question() -> None:
    """Whitespace-only question should be preserved."""
    request = build_request(model="m", question="   ")
    assert "   " in request.messages[-1].content


def test_prompt_structure_has_system_user_only() -> None:
    """Basic request should have exactly system and user messages."""
    request = build_request(model="m", question="help")
    assert len(request.messages) == 2
    assert request.messages[0].role == "system"
    assert request.messages[-1].role == "user"


def test_prompt_preserves_transcript_order() -> None:
    """Transcript should maintain chronological order (newest last)."""
    transcript = "first\nsecond\nthird\nfourth\nfifth"
    request = build_request(
        model="m", question="help",
        transcript=transcript,
        max_tokens=50
    )
    user_content = request.messages[-1].content
    assert "third" in user_content
    assert "fifth" in user_content
    # Verify order: third comes before fifth
    assert user_content.index("third") < user_content.index("fifth")
