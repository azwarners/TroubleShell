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
        argv = [sys.executable, "-m", "triagetty.terminal.pty_proxy",
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
