import httpx
import pytest

from triagetty.chat.models import ChatMessage, ChatRequest
from triagetty.llm.openai_compatible import OpenAICompatibleClient


@pytest.mark.asyncio
async def test_openai_compatible_client_posts_chat_request() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        seen["json"] = request.read().decode()
        return httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}]})

    client = OpenAICompatibleClient(
        base_url="https://example.test/v1", api_key="secret",
        transport=httpx.MockTransport(handler))
    result = await client.complete(ChatRequest("model", (ChatMessage("user", "question"),)))

    assert result.content == "answer"
    assert seen["url"] == "https://example.test/v1/chat/completions"
    assert seen["authorization"] == "Bearer secret"
    assert '"model":"model"' in str(seen["json"])


@pytest.mark.asyncio
async def test_openai_compatible_client_rejects_malformed_response() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"choices": []}))
    client = OpenAICompatibleClient(base_url="http://test", transport=transport)

    with pytest.raises(ValueError, match="unexpected chat response"):
        await client.complete(ChatRequest("model", ()))
