"""GTK/VTE shell. Core behavior remains outside this module for testability."""

import asyncio
from dataclasses import replace
import threading
import time

from .config import Config, config_path, save_config
from .chat.models import ChatMessage, ChatRequest, CodeSegment, TextSegment
from .chat.parser import parse_response
from .chat.rendering import code_to_pango, prose_to_pango
from .llm.context_session import ContextSession
from .llm.openai_compatible import OpenAICompatibleClient
from .llm.prompt import build_request
from .terminal.pane import TerminalPane
from .terminal.output_capturer import TerminalOutputCapturer
from .terminal.transcript_store import TranscriptStore
from .terminal.transcript import estimate_tokens, bound_transcript, normalize_transcript
import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio


class TriageWindow:
    def __init__(self, config: Config) -> None:
        try:
            import gi
            gi.require_version("Gdk", "4.0")
            gi.require_version("Gtk", "4.0")
            gi.require_version("Vte", "3.91")
            from gi.repository import Gdk, GLib, Gtk, Vte, Pango
        except ImportError as exc:
            raise ImportError("GTK 4 and VTE GTK 4 bindings are required") from exc
        self._gtk = Gtk
        self._gdk = Gdk
        self._glib = GLib
        self._vte = Vte
        self._pango = Pango
        self.config = config
        self.application = Gtk.Application(
            application_id="org.triagetty.TriageTTY",
            flags=Gio.ApplicationFlags.NON_UNIQUE
        )
        self.application.connect("activate", self._activate)

    def _activate(self, application: object) -> None:
        self.window = self._gtk.ApplicationWindow(application=application, title="TriageTTY")
        self.window.set_default_size(1200, 760)
        css = self._gtk.CssProvider()
        css.load_from_data(b"""
            .question-frame { border-radius: 3px; padding: 0px; }
            .terminal-frame { border: 2px solid #444; border-radius: 3px; }
            .message-separator { border-top: 2px solid #555; margin: 8px 0; }
        """)
        self._gtk.StyleContext.add_provider_for_display(
            self._gdk.Display.get_default(), css,
            self._gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.history: list[ChatMessage] = []
        self.request_id = 0
        self.cancel_event: threading.Event | None = None
        # Phase 1: Context session state machine
        self.transcript_store = TranscriptStore()
        self.context_session = ContextSession(transcript=self.transcript_store)
        self.font_size = self.config.terminal_font_size  # Synced font size for both panes
        self.terminal_pane = TerminalPane(self._vte.Terminal(), shell=self.config.shell, vte=self._vte)
        self.terminal_pane.widget.add_css_class("terminal-frame")
        self.terminal_pane.spawn(self._vte)
        # Initialize terminal font from config
        self._update_terminal_font()
        # Phase 2: Output capturer sink (no start/stop — PTY proxy drives it in Phase 3)
        self.output_capturer = TerminalOutputCapturer(
            transcript_store=self.transcript_store
        )

        # Connect scroll event handler to terminal for Ctrl+scroll zoom using EventControllerScroll
        terminal_scroll_controller = self._gtk.EventControllerScroll.new(
            self._gtk.EventControllerScrollFlags.BOTH_AXES
        )
        terminal_scroll_controller.connect("scroll", self._on_terminal_scroll)
        self.terminal_pane.widget.add_controller(terminal_scroll_controller)

        self.response_box = self._gtk.Box(orientation=self._gtk.Orientation.VERTICAL, spacing=10)
        self.response_box.set_margin_top(8)
        self.response_box.set_margin_bottom(8)
        self.response_box.set_margin_start(8)
        self.response_box.set_margin_end(8)
        self.response_scroll = self._gtk.ScrolledWindow(vexpand=True, hexpand=True)
        self.response_scroll.set_child(self.response_box)
        # Connect scroll event handler to chat scroll window for Ctrl+scroll zoom
        chat_scroll_controller = self._gtk.EventControllerScroll.new(
            self._gtk.EventControllerScrollFlags.BOTH_AXES
        )
        chat_scroll_controller.connect("scroll", self._on_chat_scroll)
        self.response_scroll.add_controller(chat_scroll_controller)
        self.status_label = self._gtk.Label(label="Ready", xalign=0)
        self.status_label.add_css_class("dim-label")
        self.context_used_label = self._gtk.Label(label="Context sent: none", xalign=0)
        self.context_used_label.add_css_class("dim-label")
        self.question = self._gtk.TextView(wrap_mode=self._gtk.WrapMode.WORD_CHAR)
        self.question.set_hexpand(True)
        self.question.set_size_request(-1, 120)
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
        # Connect key press handler to capture Enter (send) vs Shift+Enter (new line)
        self.question_key_controller = self._gtk.EventControllerKey.new()
        self.question_key_controller.connect("key-pressed", self._on_question_key_pressed)
        self.question.add_controller(self.question_key_controller)
        # Terminal context always included; checkbox hidden for backward compatibility
        self.include_context = self._gtk.CheckButton(label="Include recent terminal context", active=True)
        self.include_context.set_visible(False)
        self.send_button = self._gtk.Button(label="Send")
        self.send_button.set_halign(self._gtk.Align.END)
        self.send_button.connect("clicked", self._send_question)
        self.cancel_button = self._gtk.Button(label="Cancel")
        self.cancel_button.set_halign(self._gtk.Align.END)
        self.cancel_button.connect("clicked", self._cancel_request)
        self.cancel_button.set_visible(False)

        chat = self._gtk.Box(orientation=self._gtk.Orientation.VERTICAL, spacing=8)
        chat.set_margin_top(12); chat.set_margin_bottom(12); chat.set_margin_start(12); chat.set_margin_end(12)
        chat.append(self.response_scroll)
        chat.append(self.status_label)
        chat.append(self.context_used_label)
        chat.append(self.include_context)
        context = self._gtk.Expander(label="Context")
        context_box = self._gtk.Box(orientation=self._gtk.Orientation.VERTICAL, spacing=6)
        context_box.set_margin_top(6)
        context_box.set_margin_bottom(6)
        context_box.set_margin_start(6)
        context_box.set_margin_end(6)
        self.context_tokens_label = self._gtk.Label(xalign=0)
        self.context_payload_label = self._gtk.Label(
            label="Full context payload will appear here…", use_markup=True, wrap=True, xalign=0)
        self.context_payload_label.set_hexpand(True)
        self.context_payload_label.set_size_request(-1, 200)
        context_box.append(self.context_tokens_label)
        context_box.append(self.context_payload_label)
        context.set_child(context_box)
        chat.append(context)
        self._update_context_labels()
        # Initialize chat font from config (after all labels are created)
        self._update_chat_font()
        row = self._gtk.Box(spacing=8)
        row.set_hexpand(True)
        question_frame = self._gtk.Frame()
        question_frame.add_css_class("question-frame")
        question_frame.set_child(self.question)
        question_stack = self._gtk.Overlay()
        question_stack.set_child(question_frame)
        question_stack.add_overlay(self.question_placeholder)
        question_stack.set_hexpand(True)
        row.append(question_stack)
        row.append(self.send_button)
        row.append(self.cancel_button)
        chat.append(row)
        # Adjust TextView height based on font size after it's added to the widget tree
        min_height = int(self.font_size * 1.5 * 6)
        self.question.set_size_request(-1, min_height)

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
        self.question.set_sensitive(False)
        self.send_button.set_sensitive(False)
        self.cancel_button.set_visible(True)
        self.status_label.set_text("Thinking…")
        self._append_text(f"You: {question}\n\n")

        # Atomic snapshot of terminal context before building the request.
        self.context_session.request_slice()

        # Build a prospective complete request before deciding whether the one
        # permitted compaction is necessary. There is no per-message budget.
        payload_transcript = self.context_session.build_request_payload()
        request = build_request(model=self.config.model, question=question, transcript=payload_transcript,
                                max_tokens=self.config.max_context_tokens,
                                system_prompt=self.config.system_prompt,
                                history=tuple(self.context_session.history))
        total_estimated = sum(estimate_tokens(message.content) for message in request.messages)
        if total_estimated > self.config.max_context_tokens * 0.8:  # 80% threshold
            self.context_session.compact(self.config.max_context_tokens)
            # Rebase to the compacted start without moving this request's
            # atomic end boundary forward.
            self.context_session.rebase_pending_slice_after_compaction()
            payload_transcript = self.context_session.build_request_payload()
            request = build_request(model=self.config.model, question=question, transcript=payload_transcript,
                                    max_tokens=self.config.max_context_tokens,
                                    system_prompt=self.config.system_prompt,
                                    history=tuple(self.context_session.history))

        # Store the user message we are sending.
        self.context_session.snapshot_for_send(request.messages[-1])

        client = OpenAICompatibleClient(base_url=self.config.endpoint_url, api_key=self.config.api_key,
                                        verify_tls=self.config.verify_tls)
        self.request_id += 1
        request_id = self.request_id
        self.cancel_event = threading.Event()
        threading.Thread(target=self._complete_in_background,
                          args=(client, request, request_id, self.cancel_event), daemon=True).start()

    def _update_context_labels(self) -> None:
        """Update the Context panel labels with token budget info."""
        self.context_tokens_label.set_text(
            f"Max context tokens: {self.config.max_context_tokens:,}"
        )
        self.context_payload_label.set_text(
            "Full context payload will appear here…"
        )

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
        # Phase 1: Rollback the session state on cancellation
        self.context_session.rollback_on_failure()
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
            # Phase 1: Rollback the session state on failure
            self.context_session.rollback_on_failure()
            # Provide helpful status based on error type
            if "connect" in error.lower() or "connection" in error.lower():
                self.status_label.set_text("Request failed: Cannot connect to LLM server")
            elif "timeout" in error.lower():
                self.status_label.set_text("Request failed: Server timed out")
            elif "401" in error or "403" in error:
                self.status_label.set_text("Request failed: Authentication error")
            elif "429" in error:
                self.status_label.set_text("Request failed: Rate limited - try again")
            elif "500" in error or "503" in error:
                self.status_label.set_text("Request failed: Server error")
            else:
                self.status_label.set_text("Request failed")
        elif response is not None:
            # Phase 1: Commit the session state on success
            # Commit using the stored question from snapshot
            self.context_session.commit_on_success(response.content)
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

    def _on_question_key_pressed(self, _controller: object, key: int, _keycode: int, state: int) -> bool:
        """Handle key presses in the question input field.

        Enter (Return) sends the question, while Shift+Enter creates a new line.
        """
        # Check if Enter key was pressed (both regular Enter and numpad Enter)
        if key in (self._gdk.KEY_Return, self._gdk.KEY_KP_Enter):
            # Check if Shift is NOT held (state & Shift mask == 0 means no Shift)
            if not (state & self._gdk.ModifierType.SHIFT_MASK):
                # Plain Enter: send the question
                self._send_question(None)
                return True  # Consume the event to prevent default new line
        # Let other keys (including Shift+Enter) proceed with default behavior
        return False

    def _append_text(self, text: str) -> None:
        separator = self._gtk.Separator(orientation=self._gtk.Orientation.HORIZONTAL)  # type: ignore
        separator.add_css_class("message-separator")
        self.response_box.append(separator)
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
                execute = self._gtk.Button(label="Execute")
                copy = self._gtk.Button(label="Copy")
                insert.connect("clicked", lambda _b, code=segment.code: self.terminal_pane.insert(code))
                execute.connect("clicked", lambda _b, code=segment.code: self.terminal_pane.execute(code))
                copy.connect("clicked", lambda _b, code=segment.code: self._copy(code))
                actions = self._gtk.Box(spacing=8)
                actions.append(insert); actions.append(execute); actions.append(copy)
                content.append(label); content.append(actions)
                card.set_child(content)
                self.response_box.append(card)
            else:
                self._append_text(f"Code ({segment.language or 'unlabeled'}):\n{segment.code}\n")

    def _copy(self, text: str) -> None:
        self._gdk.Display.get_default().get_clipboard().set(text)

    def _on_terminal_scroll(self, _controller: object, dx: float, dy: float) -> bool:
        """Handle Ctrl+scroll on terminal to zoom font size."""
        # Check if Ctrl is held using the controller's current event state
        modifiers = _controller.get_current_event_state()
        if not (modifiers & self._gdk.ModifierType.CONTROL_MASK):
            return False

        # Adjust font size by 1 point per scroll notch
        # dy < 0 means scrolling up (increase font), dy > 0 means scrolling down (decrease)
        if dy < 0:
            new_size = self.font_size + 1
        else:
            new_size = self.font_size - 1

        # Clamp to reasonable bounds
        new_size = max(6, min(72, new_size))

        if new_size != self.font_size:
            self.font_size = new_size
            self._update_terminal_font()
            self._update_chat_font()
            # Save updated font size to config
            updated_config = replace(self.config, terminal_font_size=self.font_size, chat_font_size=self.font_size)
            save_config(updated_config, config_path())

        return True

    def _on_chat_scroll(self, _controller: object, dx: float, dy: float) -> bool:
        """Handle Ctrl+scroll on chat to zoom font size (synced with terminal)."""
        # Check if Ctrl is held using the controller's current event state
        modifiers = _controller.get_current_event_state()
        if not (modifiers & self._gdk.ModifierType.CONTROL_MASK):
            return False

        # Adjust font size by 1 point per scroll notch
        # dy < 0 means scrolling up (increase font), dy > 0 means scrolling down (decrease)
        if dy < 0:
            new_size = self.font_size + 1
        else:
            new_size = self.font_size - 1

        # Clamp to reasonable bounds
        new_size = max(6, min(72, new_size))

        if new_size != self.font_size:
            self.font_size = new_size
            self._update_terminal_font()
            self._update_chat_font()
            # Save updated font size to config
            updated_config = replace(self.config, terminal_font_size=self.font_size, chat_font_size=self.font_size)
            save_config(updated_config, config_path())

        return True

    def _update_terminal_font(self) -> None:
        """Update terminal font size."""
        # VTE uses Pango font description: "FontName size"
        font_desc = f"{self.config.terminal_font.rsplit(' ', 1)[0]} {self.font_size}"
        self.terminal_pane.widget.set_font(self._pango.font_description_from_string(font_desc))

    def _update_chat_font(self) -> None:
        """Update chat font size on all labels and text view in the window."""
        # Create CSS for the font
        font_name = self.config.terminal_font.rsplit(' ', 1)[0]

        # Collect all labels to update
        labels_to_update = [
            self.status_label,
            self.context_used_label,
            self.context_tokens_label,
            self.context_payload_label,
            self.question_placeholder,
        ]
        # Also add all labels in response_box
        for child in self.response_box:
            if isinstance(child, self._gtk.Label):
                labels_to_update.append(child)

        # Update each label with the new font size using CSS
        for label in labels_to_update:
            css_provider = self._gtk.CssProvider()
            css_data = f"label {{ font-family: {font_name}; font-size: {self.font_size}px; }}"
            css_provider.load_from_data(css_data.encode())
            label.get_style_context().add_provider_for_display(
                self._gdk.Display.get_default(), css_provider,
                self._gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

        # Update the input text view font size
        css_provider = self._gtk.CssProvider()
        css_data = f"textview {{ font-family: {font_name}; font-size: {self.font_size}px; }}"
        css_provider.load_from_data(css_data.encode())
        self.question.get_style_context().add_provider_for_display(
            self._gdk.Display.get_default(), css_provider,
            self._gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Update button font sizes
        for button in [self.send_button, self.cancel_button, self.include_context]:
            css_provider = self._gtk.CssProvider()
            css_data = f"button {{ font-family: {font_name}; font-size: {self.font_size}px; }}"
            css_provider.load_from_data(css_data.encode())
            button.get_style_context().add_provider_for_display(
                self._gdk.Display.get_default(), css_provider,
                self._gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
