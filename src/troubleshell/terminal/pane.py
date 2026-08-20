"""Small VTE adapter owned by the desktop layer."""

import sys
from typing import TYPE_CHECKING

from .insertion import insertable_text

if TYPE_CHECKING:
    import gi
    gi.require_version("Vte", "3.91")
    from gi.repository import Vte


class TerminalPane:
    """Own the VTE widget and proxy process; transcript policy lives elsewhere."""

    def __init__(self, terminal: "Vte.Terminal", *, shell: str,
                 capture_socket_path: str = "", vte: object | None = None) -> None:
        self.widget: "Vte.Terminal" = terminal
        self.shell = shell
        self.capture_socket_path = capture_socket_path
        self.vte = vte

    def spawn(self, vte: object) -> None:
        """Start the configured shell through the PTY capture proxy."""
        argv = [sys.executable, "-m", "troubleshell.terminal.pty_proxy",
                "--capture-socket", self.capture_socket_path, "--shell", self.shell]
        self.widget.spawn_async(vte.PtyFlags.DEFAULT, None, argv, None, 0,
                                None, None, -1, None, None)

    def insert(self, text: str) -> None:
        """Insert text at the active prompt without sending Enter."""
        self.widget.feed_child(insertable_text(text).encode("utf-8"))
        self.widget.grab_focus()

    def execute(self, text: str) -> None:
        """Insert text and send Enter to execute immediately."""
        self.widget.feed_child(insertable_text(text).encode("utf-8"))
        self.widget.feed_child(b"\n")
        self.widget.grab_focus()

    def handle_clipboard_key(self, key: int, state: int, *,
                             control_mask: int, shift_mask: int,
                             other_modifier_mask: int,
                             copy_key: int | tuple[int, ...],
                             paste_key: int | tuple[int, ...]) -> bool:
        """Handle only the terminal's explicit Ctrl+Shift clipboard shortcuts.

        Modifier and key constants are supplied by the GTK boundary so this
        adapter remains importable in non-display unit tests.
        """
        expected_modifiers = control_mask | shift_mask
        if state & (control_mask | shift_mask | other_modifier_mask) != expected_modifiers:
            return False
        copy_keys = (copy_key,) if isinstance(copy_key, int) else copy_key
        paste_keys = (paste_key,) if isinstance(paste_key, int) else paste_key
        if key in copy_keys or key in paste_keys:
            if key in copy_keys:
                self.widget.copy_clipboard()
            else:
                self.widget.paste_clipboard()
            return True
        return False
