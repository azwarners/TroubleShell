"""Tests for the context debugging information shown by the GTK shell."""

from troubleshell.chat.models import ChatMessage, ChatRequest
from troubleshell.window import TroubleWindow


class _Label:
    def __init__(self) -> None:
        self.text = ""

    def set_text(self, text: str) -> None:
        self.text = text


class _Config:
    max_context_tokens = 96_000


def test_context_debug_panel_shows_actual_outbound_payload_and_usage() -> None:
    window = object.__new__(TroubleWindow)
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
        "Context used: 1% (960 / 96,000 rough estimate tokens)"
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
    window = object.__new__(TroubleWindow)
    window.config = _Config()
    window.context_used_label = _Label()

    window._show_context_usage(1_337, source="reported")

    assert window.context_used_label.text == (
        "Context used: 2% (1,337 / 96,000 reported tokens)"
    )


def test_context_debug_panel_uses_prior_provider_count_to_calibrate_next_send() -> None:
    window = object.__new__(TroubleWindow)
    window.config = _Config()
    window.context_used_label = _Label()
    window.context_tokens_label = _Label()
    window.context_payload_label = _Label()
    window._provider_token_ratio = 1.5
    request = ChatRequest("test-model", (ChatMessage("user", "question"),))

    window._show_sent_context(request, estimated_tokens=1_440)

    assert window.context_used_label.text == (
        "Context used: 2% (1,440 / 96,000 calibrated estimate tokens)"
    )
