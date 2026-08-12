"""Tests for OpenAI-compatible API client."""

import httpx
import pytest

from triagetty.chat.models import ChatMessage, ChatRequest
from triagetty.llm.openai_compatible import OpenAICompatibleClient


def _req(text="hi"):
    msg = ChatMessage("user", text)
    return ChatRequest("model", (msg,))


def _ok_response():
    return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})


def _handler_ok():
    return httpx.MockTransport(lambda _req: _ok_response())


@pytest.mark.asyncio
async def test_openai_compatible_client_posts_chat_request():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["json"] = request.read().decode()
        return httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}]})

    client = OpenAICompatibleClient(
        base_url="https://example.test/v1", api_key="secret",
        transport=httpx.MockTransport(handler))
    msg = ChatMessage("user", "question")
    req = ChatRequest("model", (msg,))
    result = await client.complete(req)

    assert result.content == "answer"
    assert seen["url"] == "https://example.test/v1/chat/completions"
    assert seen["auth"] == "Bearer secret"
    assert '"model":"model"' in str(seen["json"])


@pytest.mark.asyncio
async def test_openai_compatible_client_without_api_key():
    seen_auth = []

    def handler(request):
        seen_auth.append(request.headers.get("authorization"))
        return _ok_response()

    client = OpenAICompatibleClient(
        base_url="http://localhost:11434/v1", api_key="",
        transport=httpx.MockTransport(handler))
    result = await client.complete(_req())
    assert result.content == "ok"
    assert seen_auth[0] is None


@pytest.mark.asyncio
async def test_openai_compatible_client_sends_multiple_messages():
    seen_messages = []

    def handler(request):
        import json
        payload = json.loads(request.read().decode())
        seen_messages.append(payload["messages"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "response"}}]})

    client = OpenAICompatibleClient(
        base_url="http://test/v1",
        transport=httpx.MockTransport(handler))
    
    messages = (
        ChatMessage("system", "You are helpful"),
        ChatMessage("user", "First question"),
        ChatMessage("assistant", "First answer"),
        ChatMessage("user", "Second question"),
    )
    await client.complete(ChatRequest("model", messages))

    assert len(seen_messages[0]) == 4
    assert seen_messages[0][0]["role"] == "system"
    assert seen_messages[0][3]["role"] == "user"


@pytest.mark.asyncio
async def test_openai_compatible_client_handles_long_responses():
    long_content = "This is a very long response. " * 10000

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": long_content}}]})

    client = OpenAICompatibleClient(
        base_url="http://test/v1",
        transport=httpx.MockTransport(handler))
    result = await client.complete(_req("tell me a story"))
    assert len(result.content) > 100000


@pytest.mark.asyncio
async def test_openai_compatible_client_handles_401_unauthorized():
    def handler(request):
        return httpx.Response(401, json={"error": "Unauthorized"})

    client = OpenAICompatibleClient(
        base_url="http://test/v1", api_key="wrong-key",
        transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionError) as exc_info:
        await client.complete(_req())
    assert "401" in str(exc_info.value)


@pytest.mark.asyncio
async def test_openai_compatible_client_handles_403_forbidden():
    def handler(request):
        return httpx.Response(403, json={"error": "Forbidden"})

    client = OpenAICompatibleClient(
        base_url="http://test/v1",
        transport=httpx.MockTransport(handler))

    with pytest.raises(PermissionError) as exc_info:
        await client.complete(_req())
    assert "403" in str(exc_info.value)


@pytest.mark.asyncio
async def test_openai_compatible_client_handles_404_not_found():
    def handler(request):
        return httpx.Response(404, json={"error": "Not found"})

    client = OpenAICompatibleClient(
        base_url="http://test/v1",
        transport=httpx.MockTransport(handler))

    with pytest.raises(ValueError) as exc_info:
        await client.complete(_req())
    assert "404" in str(exc_info.value)


@pytest.mark.asyncio
async def test_openai_compatible_client_handles_429_rate_limit():
    def handler(request):
        return httpx.Response(429, json={"error": "Rate limit exceeded"})

    client = OpenAICompatibleClient(
        base_url="http://test/v1",
        transport=httpx.MockTransport(handler))

    with pytest.raises(ValueError) as exc_info:
        await client.complete(_req())
    assert "429" in str(exc_info.value)


@pytest.mark.asyncio
async def test_openai_compatible_client_handles_500_server_error():
    def handler(request):
        return httpx.Response(500, json={"error": "Internal server error"})

    client = OpenAICompatibleClient(
        base_url="http://test/v1",
        transport=httpx.MockTransport(handler))

    with pytest.raises(RuntimeError) as exc_info:
        await client.complete(_req())
    assert "500" in str(exc_info.value)


@pytest.mark.asyncio
async def test_openai_compatible_client_handles_503_unavailable():
    def handler(request):
        return httpx.Response(503, json={"error": "Service unavailable"})

    client = OpenAICompatibleClient(
        base_url="http://test/v1",
        transport=httpx.MockTransport(handler))

    with pytest.raises(RuntimeError) as exc_info:
        await client.complete(_req())
    assert "503" in str(exc_info.value)


@pytest.mark.asyncio
async def test_openai_compatible_client_rejects_malformed_response():
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"choices": []}))
    client = OpenAICompatibleClient(base_url="http://test", transport=transport)

    with pytest.raises(RuntimeError, match="unexpected response"):
        await client.complete(ChatRequest("model", ()))


@pytest.mark.asyncio
async def test_openai_compatible_client_rejects_empty_json():
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={}))
    client = OpenAICompatibleClient(base_url="http://test", transport=transport)

    with pytest.raises(RuntimeError, match="unexpected response"):
        await client.complete(ChatRequest("model", ()))


@pytest.mark.asyncio
async def test_openai_compatible_client_rejects_null_content():
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={
        "choices": [{"message": {"content": None}}]
    }))
    client = OpenAICompatibleClient(base_url="http://test", transport=transport)

    with pytest.raises(RuntimeError, match="non-text"):
        await client.complete(_req())


@pytest.mark.asyncio
async def test_openai_compatible_client_rejects_non_string_content():
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={
        "choices": [{"message": {"content": 12345}}]
    }))
    client = OpenAICompatibleClient(base_url="http://test", transport=transport)

    with pytest.raises(RuntimeError, match="non-text"):
        await client.complete(_req())


@pytest.mark.asyncio
async def test_openai_compatible_client_rejects_non_json_response():
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content="not json"))
    client = OpenAICompatibleClient(base_url="http://test", transport=transport)

    with pytest.raises(RuntimeError):
        await client.complete(_req())


@pytest.mark.asyncio
async def test_openai_compatible_client_rejects_html_response():
    html = "<html><body><h1>502 Bad Gateway</h1></body></html>"
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=html.encode()))
    client = OpenAICompatibleClient(base_url="http://test", transport=transport)

    with pytest.raises(RuntimeError):
        await client.complete(_req())


@pytest.mark.asyncio
async def test_openai_compatible_client_handles_connection_error():
    def handler(request):
        raise httpx.ConnectError("Connection refused")

    client = OpenAICompatibleClient(
        base_url="http://localhost:99999/v1",
        transport=httpx.MockTransport(handler))

    with pytest.raises(ConnectionError):
        await client.complete(_req())


@pytest.mark.asyncio
async def test_openai_compatible_client_handles_connection_timeout():
    def handler(request):
        raise httpx.ConnectTimeout("Connection timed out")

    client = OpenAICompatibleClient(
        base_url="http://test/v1",
        transport=httpx.MockTransport(handler))

    with pytest.raises(TimeoutError):
        await client.complete(_req())


@pytest.mark.asyncio
async def test_openai_compatible_client_handles_read_timeout():
    def handler(request):
        raise httpx.ReadTimeout("Read timed out")

    client = OpenAICompatibleClient(
        base_url="http://test/v1",
        transport=httpx.MockTransport(handler))

    with pytest.raises(TimeoutError):
        await client.complete(_req())


@pytest.mark.asyncio
async def test_openai_compatible_client_handles_network_partition():
    def handler(request):
        raise httpx.NetworkError("Network is unreachable")

    client = OpenAICompatibleClient(
        base_url="http://test/v1",
        transport=httpx.MockTransport(handler))

    with pytest.raises(ConnectionError):
        await client.complete(_req())


@pytest.mark.asyncio
async def test_openai_compatible_client_strips_trailing_slash_from_base_url():
    seen_urls = []

    def handler(request):
        seen_urls.append(str(request.url))
        return _ok_response()

    client = OpenAICompatibleClient(
        base_url="http://test/v1/",
        transport=httpx.MockTransport(handler))
    await client.complete(_req())

    assert seen_urls[0] == "http://test/v1/chat/completions"


@pytest.mark.asyncio
async def test_openai_compatible_client_handles_multiple_trailing_slashes():
    seen_urls = []

    def handler(request):
        seen_urls.append(str(request.url))
        return _ok_response()

    client = OpenAICompatibleClient(
        base_url="http://test/v1///",
        transport=httpx.MockTransport(handler))
    await client.complete(_req())

    assert seen_urls[0] == "http://test/v1/chat/completions"
