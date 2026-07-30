import httpx

from triagetty.chat.models import ChatRequest, ChatResponse


class OpenAICompatibleClient:
    def __init__(self, *, base_url: str, api_key: str = "", timeout: float = 60.0,
                 verify_tls: bool = True, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.verify_tls = verify_tls
        self.transport = transport

    async def complete(self, request: ChatRequest) -> ChatResponse:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {"model": request.model, "messages": [m.__dict__ for m in request.messages]}
        async with httpx.AsyncClient(timeout=self.timeout, verify=self.verify_tls,
                                     transport=self.transport) as client:
            response = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("The model endpoint returned an unexpected chat response") from exc
        if not isinstance(content, str):
            raise ValueError("The model endpoint returned non-text content")
        return ChatResponse(content)
