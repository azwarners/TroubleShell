"""Small VTE adapter owned by the desktop layer.

The adapter intentionally exposes only bounded observation and text insertion. It
does not expose a command execution method.
"""

from .insertion import insertable_text
from .transcript import bound_transcript


class TerminalPane:
    """Own a VTE terminal widget and keep its model-facing surface narrow."""

    def __init__(self, terminal: object, *, shell: str, vte: object | None = None) -> None:
        self.widget = terminal
        self.shell = shell
        self.vte = vte

    def spawn(self, vte: object) -> None:
        """Start the configured interactive shell in the VTE widget."""
        self.widget.spawn_async(vte.PtyFlags.DEFAULT, None, [self.shell], None, 0,
                                None, None, -1, None, None)

    @staticmethod
    def _select_all(_terminal: object, _column: int, _row: int, _user_data: object) -> bool:
        """VTE asks this callback which cells should be included in get_text()."""
        return True

    def recent_transcript(self, *, max_lines: int, max_characters: int) -> str:
        """Read VTE scrollback only when requested, then apply both bounds."""
        if self.vte is not None and hasattr(self.widget, "get_text_range_format"):
            # GTK4 VTE deprecated get_text(); the format API is the supported way
            # to read the full scrollback without a selection callback.
            start_row = -self.widget.get_scrollback_lines()
            end_row = self.widget.get_row_count()
            end_col = self.widget.get_column_count()
            text, _length = self.widget.get_text_range_format(
                self.vte.Format.TEXT, start_row, 0, end_row, end_col
            )
        else:
            text, _attributes = self.widget.get_text(self._select_all, None)
        return bound_transcript(text or "", max_lines=max_lines, max_characters=max_characters)

    def insert(self, text: str) -> None:
        """Insert text at the active prompt without sending Enter."""
        self.widget.feed_child(insertable_text(text).encode("utf-8"))
