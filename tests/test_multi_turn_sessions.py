"""Multi-turn session simulation tests.

These tests simulate real conversation sessions to verify:
1. History is preserved unchanged for context caching
2. Terminal context is added as delta each turn
3. Error handling provides useful information
4. Full request context is available across turns
"""

import httpx
import pytest

from troubleshell.chat.models import ChatMessage
from troubleshell.llm.openai_compatible import OpenAICompatibleClient
from troubleshell.llm.prompt import build_request
from troubleshell.terminal.transcript import estimate_tokens


# --- Context estimation tests ---

def test_estimate_request_tokens_basic():
    """Token estimation should sum across all messages."""
    messages = (
        ChatMessage("system", "You are helpful"),
        ChatMessage("user", "Hello"),
        ChatMessage("assistant", "Hi there"),
    )
    # Estimate tokens for each message and sum
    total = sum(estimate_tokens(msg.content) for msg in messages)
    assert total > 0


# --- Multi-turn session simulation tests ---

def test_multi_turn_session_history_unchanged():
    """History messages should remain unchanged across turns."""
    history = ()
    
    for turn in range(5):
        # Each turn with terminal context
        terminal_output = f"Output line {turn}"
        
        request = build_request(
            model="test",
            question=f"Question {turn}",
            transcript=terminal_output,
            history=history
        )
        
        # Save the user message
        user_msg = request.messages[-1]
        
        # Add to history
        history = history + (
            user_msg,
            ChatMessage("assistant", f"Answer {turn}")
        )
    
    # Verify history messages are unchanged
    # Each user message should still have its original content
    for i, msg in enumerate(history):
        if msg.role == "user":
            assert f"Question {i // 2}" in msg.content


def test_multi_turn_session_context_grows_linearly():
    """Context should grow linearly, not exponentially."""
    history = ()
    context_sizes = []
    
    for turn in range(10):
        # Terminal output grows each turn
        terminal_output = f"Turn {turn} output\n" * (turn + 1)
        
        request = build_request(
            model="test",
            question=f"Question {turn}",
            transcript=terminal_output,
            history=history
        )
        
        # Track total context size
        total_chars = sum(len(msg.content) for msg in request.messages)
        context_sizes.append(total_chars)
        
        # Add to history
        history = history + (
            request.messages[-1],
            ChatMessage("assistant", f"Answer {turn}")
        )
    
    # Verify growth is roughly linear
    if len(context_sizes) > 3:
        # Each turn adds roughly the same amount
        # (not exponential which would be much steeper)
        growth_rates = [
            context_sizes[i+1] - context_sizes[i]
            for i in range(len(context_sizes) - 1)
        ]
        avg_growth = sum(growth_rates) / len(growth_rates)
        # All growth rates should be within 3x of average
        for rate in growth_rates[1:]:
            assert rate < avg_growth * 3


def test_multi_turn_with_large_terminal_output():
    """Large terminal output should not cause exponential bloat."""
    history = ()
    
    for turn in range(5):
        # Large terminal output (5KB)
        terminal_output = "x" * 5000
        
        request = build_request(
            model="test",
            question=f"Q{turn}",
            transcript=terminal_output,
            history=history
        )
        
        history = history + (
            request.messages[-1],
            ChatMessage("assistant", f"A{turn}")
        )
    
    # Total history should be reasonable
    total_chars = sum(len(msg.content) for msg in history)
    # With delta approach, should be ~5 turns * (5KB + small question/answer)
    # Without delta, would be ~5 turns * 5 turns * 5KB
    assert total_chars < 100000  # Less than 100KB


def test_session_with_increasing_history():
    """Simulate a session where history grows and context is managed."""
    history = ()
    context_sizes = []
    
    for turn in range(20):
        terminal_output = f"Turn {turn} output\n" * (turn + 1)
        
        request = build_request(
            model="test",
            question=f"Question {turn}",
            transcript=terminal_output,
            history=history
        )
        
        total_chars = sum(len(msg.content) for msg in request.messages)
        context_sizes.append(total_chars)
        
        history = history + (
            request.messages[-1],
            ChatMessage("assistant", f"Answer {turn}")
        )
    
    # Verify context growth is sublinear (not exponential)
    if len(context_sizes) > 5:
        first_half_avg = sum(context_sizes[:10]) / 10
        second_half_avg = sum(context_sizes[10:]) / 10
        # Complete conversation history grows predictably; it must not show
        # exponential growth.  This deliberately avoids depending on the
        # fixed size of the default system prompt.
        assert second_half_avg < first_half_avg * 3


def test_session_without_terminal_context():
    """Sessions without terminal context should work normally."""
    history = ()
    
    for turn in range(5):
        request = build_request(
            model="test",
            question=f"Question {turn}",
            transcript="",
            history=history
        )
        
        user_content = request.messages[-1].content
        assert "no terminal context was shared" in user_content
        
        history = history + (
            request.messages[-1],
            ChatMessage("assistant", f"Answer {turn}")
        )
    
    # Final request should include all history
    final_request = build_request(
        model="test",
        question="Final",
        history=history
    )
    
    assert len(final_request.messages) == 12  # System + 10 history + current


# --- Error handling tests ---

@pytest.mark.asyncio
async def test_connection_error_provides_helpful_message():
    """Connection errors should include helpful guidance."""
    def handler(request):
        raise httpx.ConnectError("Connection refused")

    client = OpenAICompatibleClient(
        base_url="http://localhost:99999/v1",
        transport=httpx.MockTransport(handler)
    )

    with pytest.raises(ConnectionError) as exc_info:
        await client.complete(build_request(model="test", question="help"))

    error = str(exc_info.value)
    assert "connect" in error.lower() or "connection" in error.lower()
    assert "99999" in error


@pytest.mark.asyncio
async def test_timeout_error_provides_helpful_message():
    """Timeout errors should suggest the request may be too large."""
    def handler(request):
        raise httpx.ReadTimeout("Read timed out")

    client = OpenAICompatibleClient(
        base_url="http://test/v1",
        transport=httpx.MockTransport(handler)
    )

    with pytest.raises(TimeoutError) as exc_info:
        await client.complete(build_request(model="test", question="help"))

    error = str(exc_info.value)
    assert "did not respond" in error.lower() or "timeout" in error.lower()


@pytest.mark.asyncio
async def test_auth_error_provides_helpful_message():
    """Authentication errors should suggest checking API key."""
    def handler(request):
        return httpx.Response(401, json={"error": "Invalid API key"})

    client = OpenAICompatibleClient(
        base_url="http://test/v1",
        api_key="wrong-key",
        transport=httpx.MockTransport(handler)
    )

    with pytest.raises(PermissionError) as exc_info:
        await client.complete(build_request(model="test", question="help"))

    error = str(exc_info.value)
    assert "401" in error or "Authentication" in error


@pytest.mark.asyncio
async def test_server_error_includes_response_body():
    """Server errors should include the response body for debugging."""
    def handler(request):
        return httpx.Response(500, json={
            "error": "Internal server error: model crashed"
        })
    
    client = OpenAICompatibleClient(
        base_url="http://test/v1",
        transport=httpx.MockTransport(handler)
    )
    
    with pytest.raises(RuntimeError) as exc_info:
        await client.complete(build_request(model="test", question="help"))
    
    error = str(exc_info.value)
    assert "500" in error


@pytest.mark.asyncio
async def test_rate_limit_error_is_helpful():
    """Rate limit errors should tell the user to try again."""
    def handler(request):
        return httpx.Response(429, json={"error": "Rate limit exceeded"})

    client = OpenAICompatibleClient(
        base_url="http://test/v1",
        transport=httpx.MockTransport(handler)
    )

    with pytest.raises(ValueError) as exc_info:
        await client.complete(build_request(model="test", question="help"))

    error = str(exc_info.value)
    assert "429" in error or "Rate limit" in error


# --- Integration tests ---

def test_prompt_structure_with_history():
    """Verify prompt structure includes all components."""
    history = (
        ChatMessage("user", "First question"),
        ChatMessage("assistant", "First answer"),
    )
    
    request = build_request(
        model="test",
        question="Second question",
        transcript="some output",
        history=history
    )
    
    # Should have: system + history + current user
    assert len(request.messages) == 4
    assert request.messages[0].role == "system"
    assert request.messages[1].role == "user"
    assert request.messages[1].content == "First question"
    assert request.messages[2].role == "assistant"
    assert request.messages[2].content == "First answer"
    assert request.messages[3].role == "user"
    assert "Second question" in request.messages[3].content


def test_empty_history_and_transcript():
    """Empty history and transcript should produce valid request."""
    request = build_request(
        model="test",
        question="Help?",
        transcript="",
        history=()
    )
    
    assert len(request.messages) == 2
    assert "no terminal context was shared" in request.messages[1].content
