from triagetty.chat.models import ChatMessage
from triagetty.llm.prompt import DEFAULT_SYSTEM_PROMPT, build_request


def test_prompt_is_labeled_and_bounded() -> None:
    request = build_request(model="test", question="Why?", transcript="one\ntwo\nthree", max_lines=2,
                            max_characters=100)
    assert request.model == "test"
    assert request.messages[0].content == DEFAULT_SYSTEM_PROMPT
    assert "<terminal_context>\ntwo\nthree\n</terminal_context>" in request.messages[-1].content
    assert "<user_question>\nWhy?\n</user_question>" in request.messages[-1].content


def test_history_is_kept_before_new_question() -> None:
    history = (ChatMessage("user", "old"), ChatMessage("assistant", "answer"))
    request = build_request(model="m", question="new", history=history)
    assert request.messages[1:] == (*history, request.messages[-1])


def test_empty_transcript_is_explicit() -> None:
    request = build_request(model="m", question="hello", transcript="")
    assert "(no terminal context was shared)" in request.messages[-1].content


def test_default_prompt_describes_triage_environment_and_boundary() -> None:
    prompt = DEFAULT_SYSTEM_PROMPT
    assert "TriageTTY's Linux troubleshooting partner" in prompt
    assert "You do not have direct access to the terminal" in prompt
    assert "It never executes commands" in prompt
    assert "untrusted data" in prompt
