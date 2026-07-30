from triagetty.terminal.pane import TerminalPane


class FakeTerminal:
    def __init__(self, text: str) -> None:
        self.text = text
        self.inserted: list[bytes] = []

    def get_text(self, selection, user_data):
        assert selection(self, 0, 0, user_data) is True
        return self.text, []

    def feed_child(self, text: bytes) -> None:
        self.inserted.append(text)


class FakeVte:
    class Format:
        TEXT = "text"


class ModernFakeTerminal(FakeTerminal):
    def get_scrollback_lines(self):
        return 100

    def get_row_count(self):
        return 24

    def get_column_count(self):
        return 80

    def get_text_range_format(self, format, start_row, start_col, end_row, end_col):
        assert (format, start_row, start_col, end_row, end_col) == ("text", -100, 0, 24, 80)
        return self.text, len(self.text)


def test_terminal_pane_bounds_vte_text_at_read_time() -> None:
    pane = TerminalPane(FakeTerminal("one\ntwo\nthree"), shell="/bin/bash")
    assert pane.recent_transcript(max_lines=2, max_characters=100) == "two\nthree"


def test_terminal_pane_insertion_does_not_execute() -> None:
    terminal = FakeTerminal("")
    TerminalPane(terminal, shell="/bin/bash").insert("echo safe")
    assert terminal.inserted == [b"echo safe"]


def test_terminal_pane_uses_modern_vte_full_scrollback_api() -> None:
    terminal = ModernFakeTerminal("one\ntwo\nthree")
    pane = TerminalPane(terminal, shell="/bin/bash", vte=FakeVte)
    assert pane.recent_transcript(max_lines=2, max_characters=100) == "two\nthree"
