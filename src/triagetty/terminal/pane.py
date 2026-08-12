"""Small VTE adapter owned by the desktop layer.

The adapter intentionally exposes only bounded observation and text insertion. It
does not expose a command execution method.
"""

from typing import TYPE_CHECKING

from .insertion import insertable_text
from .transcript import bound_transcript

if TYPE_CHECKING:
    import gi
    gi.require_version("Vte", "3.91")
    from gi.repository import Vte


class TerminalPane:
    """Own a VTE terminal widget and keep its model-facing surface narrow."""

    def __init__(self, terminal: "Vte.Terminal", *, shell: str, vte: object | None = None) -> None:
        self.widget: "Vte.Terminal" = terminal
        self.shell = shell
        self.vte = vte
        # Persistent transcript buffer that accumulates output independent of screen scrollback
        self._transcript_buffer: list[str] = []
        # Track the last line number we've read to avoid duplicates
        self._last_read_line: int = 0

    def spawn(self, vte: object) -> None:
        """Start the configured interactive shell in the VTE widget."""
        self.widget.spawn_async(vte.PtyFlags.DEFAULT, None, [self.shell], None, 0,
                                None, None, -1, None, None)

    @staticmethod
    def _select_all(_terminal: object, _column: int, _row: int, _user_data: object) -> bool:
        """VTE asks this callback which cells should be included in get_text()."""
        return True

    def _get_full_transcript(self) -> str:
       """Read the full terminal scrollback using VTE's range API.
    
       Uses get_text_range_format() to capture all visible lines plus
       scrollback history, independent of what's currently on screen.
    
       Note: This may miss very recent output if the terminal hasn't
       flushed the SSH session output yet. A small delay or explicit
       wait might be needed for interactive SSH sessions.
       """
       try:
           import gi
           gi.require_version("Vte", "3.91")
           from gi.repository import Vte
        
           # Calculate the full scrollback range
           # __firstlineno__ is the line number of the first visible row
           # get_scrollback_lines() returns lines above the visible area
           # get_row_count() returns visible rows
           first_visible_line = self.widget.__firstlineno__
           scrollback_lines = self.widget.get_scrollback_lines()
           visible_rows = self.widget.get_row_count()
        
           # Calculate the range to capture all text
           # Start from the first line of scrollback (first_visible - scrollback)
           # End at the last visible line
           start_row = first_visible_line - scrollback_lines
           end_row = first_visible_line + visible_rows - 1
        
           # Use get_text_range_format to get the full scrollback
           text, _ = self.widget.get_text_range_format(
               Vte.Format.TEXT,
               max(0, start_row), 0,  # start: first line of scrollback (at least 0), column 0
               end_row, -1,  # end: last visible line, last column
           )
           return text or ""
       except (AttributeError, TypeError):
           # Fallback to the old method if range API is unavailable
           return self.widget.get_text_format(Vte.Format.TEXT) or ""

    def recent_transcript(self, *, max_tokens: int) -> str:
        """Read terminal scrollback and apply token bound.
        
        Captures the full scrollback history (not just visible text) and
        applies the token budget using bound_transcript().
        """
        full_text = self._get_full_transcript()
        return bound_transcript(full_text, max_tokens=max_tokens)

    def insert(self, text: str) -> None:
        """Insert text at the active prompt without sending Enter."""
        self.widget.feed_child(insertable_text(text).encode("utf-8"))
        # Shift focus to the terminal so Enter executes the command
        self.widget.grab_focus()

    def execute(self, text: str) -> None:
        """Insert text and send Enter to execute immediately."""
        self.widget.feed_child(insertable_text(text).encode("utf-8"))
        # Send Enter to execute the command
        self.widget.feed_child(b"\n")
        # Shift focus to the terminal
        self.widget.grab_focus()
