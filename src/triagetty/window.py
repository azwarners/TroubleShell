"""GTK/VTE shell. Core behavior remains outside this module for testability."""

import asyncio
from dataclasses import replace
import threading

from .config import Config
from .chat.models import ChatMessage, ChatResponse
from .chat.parser import parse_response
from .chat.models import CodeSegment, TextSegment
from .chat.rendering import code_to_pango, prose_to_pango
from .llm.openai_compatible import OpenAICompatibleClient
from .llm.prompt import build_request
from .terminal.pane import TerminalPane
from .terminal.transcript import estimate_tokens
from .config import save_config


class TriageWindow:
    def __init__(self, config: Config) -> None:
        try:
            import gi
            gi.require_version("Gdk", "4.0")
            gi.require_version("Gtk", "4.0")
            gi.require_version("Vte", "3.91")
            from gi.repository import Gdk, GLib, Gtk, Vte
        except ImportError as exc:
            raise ImportError("GTK 4 and VTE GTK 4 bindings are required") from exc
        self._gtk = Gtk
        self._gdk = Gdk
        self._glib = GLib
        self._vte = Vte
        self.config = config
        self.application = Gtk.Application(application_id="org.triagetty.TriageTTY")
        self.application.connect("activate", self._activate)

    def _activate(self, application: object) -> None:
        self.window = self._gtk.ApplicationWindow(application=application, title="TriageTTY")
        self.window.set_default_size(1200, 760)
        css = self._gtk.CssProvider()
        css.load_from_data(b".question-frame { border-radius: 3px; padding: 0px; }")
        self._gtk.StyleContext.add_provider_for_display(
            self._gdk.Display.get_default(), css,
            self._gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.history: list[ChatMessage] = []
        self.request_id = 0
        self.cancel_event: threading.Event | None = None
        self.terminal_pane = TerminalPane(self._vte.Terminal(), shell=self.config.shell, vte=self._vte)
        self.terminal_pane.spawn(self._vte)

        self.response_box = self._gtk.Box(orientation=self._gtk.Orientation.VERTICAL, spacing=10)
        self.response_box.set_margin_top(8)
        self.response_box.set_margin_bottom(8)
        self.response_box.set_margin_start(8)
        self.response_box.set_margin_end(8)
        self.response_scroll = self._gtk.ScrolledWindow(vexpand=True, hexpand=True)
        self.response_scroll.set_child(self.response_box)
        self.status_label = self._gtk.Label(label="Ready", xalign=0)
        self.status_label.add_css_class("dim-label")
        self.context_used_label = self._gtk.Label(label="Context sent: none", xalign=0)
        self.context_used_label.add_css_class("dim-label")
        self.question = self._gtk.TextView(wrap_mode=self._gtk.WrapMode.WORD_CHAR)
        self.question.set_hexpand(True)
        self.question.set_size_request(-1, 84)
        self.question.set_left_margin(8)
        self.question.set_right_margin(8)
        self.question.set_top_margin(6)
        self.question.set_bottom_margin(6)
        self.question_buffer = self.question.get_buffer()
        self.question_placeholder = self._gtk.Label(
            label="Ask about the terminal output…", xalign=0)
        self.question_placeholder.add_css_class("dim-label")
        self.question_placeholder.set_can_target(False)
        self.question_placeholder.set_margin_start(8)
        self.question_placeholder.set_margin_top(4)
        self.question_placeholder.set_halign(self._gtk.Align.START)
        self.question_buffer.connect("changed", self._question_changed)
        self.include_context = self._gtk.CheckButton(label="Include recent terminal context", active=True)
        self.send_button = self._gtk.Button(label="Send")
        self.send_button.connect("clicked", self._send_question)
        self.cancel_button = self._gtk.Button(label="Cancel")
        self.cancel_button.connect("clicked", self._cancel_request)
        self.cancel_button.set_visible(False)

        chat = self._gtk.Box(orientation=self._gtk.Orientation.VERTICAL, spacing=8)
        chat.set_margin_top(12); chat.set_margin_bottom(12); chat.set_margin_start(12); chat.set_margin_end(12)
        chat.append(self.response_scroll)
        chat.append(self.status_label)
        chat.append(self.context_used_label)
        chat.append(self.include_context)
        settings = self._gtk.Expander(label="Settings")
        settings_box = self._gtk.Box(orientation=self._gtk.Orientation.VERTICAL, spacing=6)
        settings_box.set_margin_top(6)
        settings_box.set_margin_bottom(6)
        settings_box.set_margin_start(6)
        settings_box.set_margin_end(6)
        self.context_limit_label = self._gtk.Label(xalign=0)
        self.context_slider = self._gtk.Scale.new_with_range(
            self._gtk.Orientation.HORIZONTAL, 20, 1000, 10)
        self.context_slider.set_digits(0)
        self.context_slider.set_value(self.config.context_line_limit)
        self.context_slider.set_hexpand(True)
        self.context_slider.connect("value-changed", self._context_limit_changed)
        settings_box.append(self.context_limit_label)
        settings_box.append(self.context_slider)
        settings.set_child(settings_box)
        chat.append(settings)
        row = self._gtk.Box(spacing=8)
        question_frame = self._gtk.Frame()
        question_frame.add_css_class("question-frame")
        question_frame.set_child(self.question)
        question_stack = self._gtk.Overlay()
        question_stack.set_child(question_frame)
        question_stack.add_overlay(self.question_placeholder)
        row.append(question_stack); row.append(self.send_button); row.append(self.cancel_button)
        chat.append(row)
        self._update_context_limit_label(self.config.context_line_limit)

        split = self._gtk.Paned(orientation=self._gtk.Orientation.HORIZONTAL)
        split.set_start_child(self.terminal_pane.widget); split.set_end_child(chat); split.set_position(760)
        self.window.set_child(split)
        self.window.present()
        
    def run(self) -> None:
        self.application.run(None)

    def _send_question(self, _button: object) -> None:
        start, end = self.question_buffer.get_bounds()
        question = self.question_buffer.get_text(start, end, False).strip()
        if not question:
            return
        if self.cancel_event is not None:
            return
        self.question.set_sensitive(False); self.send_button.set_sensitive(False)
        self.cancel_button.set_visible(True)
        self.status_label.set_text("Thinking…")
        self._append_text(f"You: {question}\n\n")
        transcript = self.terminal_pane.recent_transcript(
            max_lines=self.config.context_line_limit,
            max_characters=self.config.context_character_limit,
        ) if self.include_context.get_active() else ""
        if transcript:
            line_count = len(transcript.splitlines())
            self.context_used_label.set_text(
                f"Context sent: {line_count:,} lines (~{estimate_tokens(transcript):,} tokens)"
            )
        else:
            self.context_used_label.set_text("Context sent: none")
        request = build_request(model=self.config.model, question=question, transcript=transcript,
                                max_lines=self.config.context_line_limit,
                                max_characters=self.config.context_character_limit,
                                system_prompt=self.config.system_prompt,
                                history=tuple(self.history))
        self.history.append(request.messages[-1])
        client = OpenAICompatibleClient(base_url=self.config.endpoint_url, api_key=self.config.api_key,
                                        verify_tls=self.config.verify_tls)
        self.request_id += 1
        request_id = self.request_id
        self.cancel_event = threading.Event()
        threading.Thread(target=self._complete_in_background,
                         args=(client, request, request_id, self.cancel_event), daemon=True).start()

    def _update_context_limit_label(self, lines: int) -> None:
        estimated_tokens = min(lines * 12, self.config.context_character_limit // 4)
        self.context_limit_label.set_text(
            f"Terminal context: {lines:,} lines (up to ~{estimated_tokens:,} tokens)"
        )

    def _context_limit_changed(self, scale: object) -> None:
        lines = int(round(scale.get_value()))
        self.config = replace(self.config, context_line_limit=lines)
        self._update_context_limit_label(lines)
        save_config(self.config)

    def _complete_in_background(self, client: OpenAICompatibleClient, request: object,
                                request_id: int, cancel_event: threading.Event) -> None:
        try:
            response = asyncio.run(client.complete(request))
            self._glib.idle_add(self._finish_request, response, None, request_id, cancel_event)
        except Exception as exc:  # GTK boundary: report provider failures on the UI thread.
            self._glib.idle_add(self._finish_request, None, str(exc), request_id, cancel_event)

    def _cancel_request(self, _button: object) -> None:
        if self.cancel_event is None:
            return
        self.cancel_event.set()
        self.cancel_event = None
        self.status_label.set_text("Cancelled")
        self.question.set_sensitive(True)
        self.send_button.set_sensitive(True)
        self.cancel_button.set_visible(False)

    def _finish_request(self, response: ChatResponse | None, error: str | None,
                        request_id: int, cancel_event: threading.Event) -> bool:
        if request_id != self.request_id or cancel_event.is_set():
            return False
        if error is not None:
            self._append_text(f"Request failed: {error}\n\n")
            self.status_label.set_text("Request failed")
        elif response is not None:
            self.history.append(ChatMessage("assistant", response.content))
            self._append_response(response.content)
            self.status_label.set_text("Ready")
        self.question_buffer.set_text("")
        self.question.set_sensitive(True)
        self.send_button.set_sensitive(True)
        self.cancel_button.set_visible(False)
        self.cancel_event = None
        return False

    def _question_changed(self, _buffer: object) -> None:
        start, end = self.question_buffer.get_bounds()
        self.question_placeholder.set_visible(start.equal(end))

    def _append_text(self, text: str) -> None:
        label = self._gtk.Label(label=prose_to_pango(text), use_markup=True, wrap=True, xalign=0)
        label.set_selectable(True)
        label.set_hexpand(True)
        self.response_box.append(label)

    def _append_response(self, markdown: str) -> None:
        for segment in parse_response(markdown):
            if isinstance(segment, TextSegment):
                self._append_text(segment.text)
            elif isinstance(segment, CodeSegment) and segment.insertable:
                card = self._gtk.Frame(label="Suggested shell command")
                content = self._gtk.Box(orientation=self._gtk.Orientation.VERTICAL, spacing=8)
                content.set_margin_top(8); content.set_margin_bottom(8)
                content.set_margin_start(8); content.set_margin_end(8)
                label = self._gtk.Label(label=code_to_pango(segment.code), use_markup=True,
                                        wrap=True, selectable=True, xalign=0)
                insert = self._gtk.Button(label="Insert")
                copy = self._gtk.Button(label="Copy")
                insert.connect("clicked", lambda _b, code=segment.code: self.terminal_pane.insert(code))
                copy.connect("clicked", lambda _b, code=segment.code: self._copy(code))
                actions = self._gtk.Box(spacing=8)
                actions.append(insert); actions.append(copy)
                content.append(label); content.append(actions)
                card.set_child(content)
                self.response_box.append(card)
            else:
                self._append_text(f"Code ({segment.language or 'unlabeled'}):\n{segment.code}\n")

    def _copy(self, text: str) -> None:
        self._gdk.Display.get_default().get_clipboard().set(text)
