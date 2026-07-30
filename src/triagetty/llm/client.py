from typing import Protocol

from triagetty.chat.models import ChatRequest, ChatResponse


class ChatClient(Protocol):
    async def complete(self, request: ChatRequest) -> ChatResponse:
        ...
