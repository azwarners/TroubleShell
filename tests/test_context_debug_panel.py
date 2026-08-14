"""Tests for the context debugging information shown by the GTK shell."""

from triagetty.chat.models import ChatMessage, ChatRequest
from triagetty.window import TriageWindow


class _Label:
    def __init__(self) -> None:
        self.text = ""

    def set_text(self, text: str) -> None:
        self.text = text


class _Config:
    max_context_tokens = 96_000


def test_context_debug_panel_shows_actual_outbound_payload_and_usage() -> None:
    window = object.__new__(TriageWindow)
    window.config = _Config()
    window.context_used_label = _Label()
    window.context_tokens_label = _Label()
    window.context_payload_label = _Label()
    request = ChatRequest("test-model", (
        ChatMessage("system", "Follow the instructions."),
        ChatMessage("user", "Inspect this terminal output."),
    ))

    window._show_sent_context(request, estimated_tokens=960)

    assert window.context_used_label.text == (
        "Context used: 1% (960 / 96,000 conservative estimate tokens)"
    )
    assert window.context_tokens_label.text == "Max context tokens: 96,000"
    assert window.context_payload_label.text == '''{
  "model": "test-model",
  "messages": [
    {
      "role": "system",
      "content": "Follow the instructions."
    },
    {
      "role": "user",
      "content": "Inspect this terminal output."
    }
  ]
}'''


def test_context_debug_panel_replaces_estimate_with_server_count() -> None:
    window = object.__new__(TriageWindow)
    window.config = _Config()
    window.context_used_label = _Label()

    window._show_context_usage(1_337, source="reported")

    assert window.context_used_label.text == (
        "Context used: 2% (1,337 / 96,000 reported tokens)"
    )
