"""Prompt building with context management."""

from troubleshell.chat.models import ChatMessage, ChatRequest
from troubleshell.config import DEFAULT_SYSTEM_PROMPT
from troubleshell.terminal.transcript import estimate_tokens

# Maximum estimated tokens for the entire request
MAX_REQUEST_TOKENS: int = 15000


def build_request(
    *,
    model: str,
    question: str,
    transcript: str = "",
    max_tokens: int = MAX_REQUEST_TOKENS,
    history: tuple[ChatMessage, ...] = (),
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> ChatRequest:
    """Build a chat request without per-message history trimming.
    
    Per blueprint contract:
    - History is preserved unchanged; trimming happens only at compaction time
    - Compaction is an explicit whole-request decision near provider limit
    - Normal turns never trim terminal events or history
    
    The max_tokens parameter is informational; actual compaction must be
    performed explicitly by the caller when approaching the limit.
    """
    system_msg = ChatMessage("system", system_prompt or DEFAULT_SYSTEM_PROMPT)
    
    # Process transcript for current message
    if not transcript:
        context = "(no terminal context was shared)"
    else:
        context = transcript
    user_content = (
        f"<terminal_context>\n{context}\n</terminal_context>\n\n"
        f"<user_question>\n{question}\n</user_question>"
    )
    current_msg = ChatMessage("user", user_content)
    
    # Return with full history; no trimming here
    return ChatRequest(model, (system_msg, *history, current_msg))