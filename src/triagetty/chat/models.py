from dataclasses import dataclass
from typing import Literal

Role = Literal["user", "assistant", "system"]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class ChatRequest:
    model: str
    messages: tuple[ChatMessage, ...]


@dataclass(frozen=True)
class ChatResponse:
    content: str


@dataclass(frozen=True)
class TextSegment:
    text: str


@dataclass(frozen=True)
class CodeSegment:
    language: str | None
    code: str
    insertable: bool
