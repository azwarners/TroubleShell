from triagetty.chat.models import ChatMessage, ChatRequest
from triagetty.config import DEFAULT_SYSTEM_PROMPT
from triagetty.terminal.transcript import bound_transcript


def build_request(*, model: str, question: str, transcript: str = "", max_lines: int = 200,
                  max_characters: int = 12000, history: tuple[ChatMessage, ...] = (),
                  system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> ChatRequest:
    bounded = bound_transcript(transcript, max_lines=max_lines, max_characters=max_characters)
    context = bounded if bounded else "(no terminal context was shared)"
    user_content = f"<terminal_context>\n{context}\n</terminal_context>\n\n<user_question>\n{question}\n</user_question>"
    return ChatRequest(model, (ChatMessage("system", system_prompt or DEFAULT_SYSTEM_PROMPT), *history,
                               ChatMessage("user", user_content)))
