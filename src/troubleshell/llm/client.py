from typing import Protocol

from troubleshell.chat.models import ChatRequest, ChatResponse


class ChatClient(Protocol):
    async def complete(self, request: ChatRequest) -> ChatResponse:
        ...
