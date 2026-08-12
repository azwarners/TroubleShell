"""Tests for chat data models.

Targets dataclass behavior and immutability.
"""

import pytest
from triagetty.chat.models import (
    ChatMessage, ChatRequest, ChatResponse,
    TextSegment, CodeSegment,
)


# --- ChatMessage tests ---

def test_chat_message_creation() -> None:
    msg = ChatMessage("user", "Hello")
    assert msg.role == "user"
    assert msg.content == "Hello"


def test_chat_message_is_frozen() -> None:
    """ChatMessage should be immutable."""
    msg = ChatMessage("user", "Hello")
    with pytest.raises(AttributeError):
        msg.content = "Changed"


def test_chat_message_system_role() -> None:
    msg = ChatMessage("system", "You are helpful.")
    assert msg.role == "system"


def test_chat_message_assistant_role() -> None:
    msg = ChatMessage("assistant", "Here's the answer.")
    assert msg.role == "assistant"


def test_chat_message_with_unicode() -> None:
    msg = ChatMessage("user", "你好")
    assert msg.content == "你好"


def test_chat_message_with_multiline_content() -> None:
    msg = ChatMessage("user", "Line 1\nLine 2")
    assert "Line 1" in msg.content
    assert "Line 2" in msg.content


# --- ChatRequest tests ---

def test_chat_request_creation() -> None:
    msg = ChatMessage("user", "Question")
    req = ChatRequest("model-name", (msg,))
    assert req.model == "model-name"
    assert len(req.messages) == 1


def test_chat_request_is_frozen() -> None:
    """ChatRequest should be immutable."""
    req = ChatRequest("model", ())
    with pytest.raises(AttributeError):
        req.model = "changed"


def test_chat_request_with_multiple_messages() -> None:
    messages = (
        ChatMessage("system", "System prompt"),
        ChatMessage("user", "Question 1"),
        ChatMessage("assistant", "Answer 1"),
        ChatMessage("user", "Question 2"),
    )
    req = ChatRequest("model", messages)
    assert len(req.messages) == 4
    assert req.messages[0].role == "system"
    assert req.messages[3].role == "user"


def test_chat_request_with_empty_messages() -> None:
    req = ChatRequest("model", ())
    assert len(req.messages) == 0


# --- ChatResponse tests ---

def test_chat_response_creation() -> None:
    resp = ChatResponse("The answer is 42.")
    assert resp.content == "The answer is 42."


def test_chat_response_is_frozen() -> None:
    """ChatResponse should be immutable."""
    resp = ChatResponse("Answer")
    with pytest.raises(AttributeError):
        resp.content = "Changed"


def test_chat_response_with_long_content() -> None:
    long_content = "A " * 100000
    resp = ChatResponse(long_content)
    assert len(resp.content) > 100000


def test_chat_response_with_unicode() -> None:
    resp = ChatResponse("回答")
    assert resp.content == "回答"


# --- TextSegment tests ---

def test_text_segment_creation() -> None:
    seg = TextSegment("Some text")
    assert seg.text == "Some text"


def test_text_segment_is_frozen() -> None:
    seg = TextSegment("text")
    with pytest.raises(AttributeError):
        seg.text = "changed"


# --- CodeSegment tests ---

def test_code_segment_creation() -> None:
    seg = CodeSegment("bash", "echo hello", True)
    assert seg.language == "bash"
    assert seg.code == "echo hello"
    assert seg.insertable is True


def test_code_segment_is_frozen() -> None:
    seg = CodeSegment("bash", "code", True)
    with pytest.raises(AttributeError):
        seg.insertable = False


def test_code_segment_without_language() -> None:
    seg = CodeSegment(None, "code", False)
    assert seg.language is None
    assert seg.insertable is False


def test_code_segment_insertable_bash() -> None:
    seg = CodeSegment("bash", "code", True)
    assert seg.insertable is True


def test_code_segment_not_insertable_python() -> None:
    seg = CodeSegment("python", "code", False)
    assert seg.insertable is False
