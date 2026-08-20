"""Tests for proxy spawning and safe terminal command insertion."""

from troubleshell.terminal.pane import TerminalPane


class FakeTerminal:
    def __init__(self, text: str = "") -> None:
        self.inserted: list[bytes] = []
        self.focused = False
        self.spawned = None
        self.clipboard_actions: list[str] = []

    def feed_child(self, text: bytes) -> None:
        self.inserted.append(text)

    def grab_focus(self) -> None:
        self.focused = True

    def spawn_async(self, *args) -> None:
        self.spawned = args

    def copy_clipboard(self) -> None:
        self.clipboard_actions.append("copy")

    def paste_clipboard(self) -> None:
        self.clipboard_actions.append("paste")


class FakeVte:
    class PtyFlags:
        DEFAULT = 0


def test_terminal_pane_insertion_preserves_command() -> None:
    terminal = FakeTerminal()
    TerminalPane(terminal, shell="/bin/bash").insert("ls -la /path/to/file")
    assert terminal.inserted == [b"ls -la /path/to/file"]


def test_terminal_pane_insertion_handles_unicode_and_special_chars() -> None:
    terminal = FakeTerminal()
    TerminalPane(terminal, shell="/bin/bash").insert("echo 你好")
    assert terminal.inserted == ["echo 你好".encode()]
    terminal = FakeTerminal()
    TerminalPane(terminal, shell="/bin/bash").insert("grep -E '\\d+' file.txt")
    assert terminal.inserted == [b"grep -E '\\d+' file.txt"]


def test_terminal_pane_insertion_normalizes_line_endings_without_execution() -> None:
    terminal = FakeTerminal()
    TerminalPane(terminal, shell="/bin/bash").insert("line1\r\nline2\rline3")
    assert terminal.inserted == [b"line1\nline2\nline3"]
    assert terminal.focused is True


def test_terminal_pane_insertion_empty_string() -> None:
    terminal = FakeTerminal()
    TerminalPane(terminal, shell="/bin/bash").insert("")
    assert terminal.inserted == [b""]


def test_terminal_pane_execute_inserts_and_sends_enter() -> None:
    terminal = FakeTerminal()
    TerminalPane(terminal, shell="/bin/bash").execute("ls -la")
    assert terminal.inserted == [b"ls -la", b"\n"]
    assert terminal.focused is True


def test_terminal_pane_execute_handles_multiline_command() -> None:
    terminal = FakeTerminal()
    TerminalPane(terminal, shell="/bin/bash").execute("echo line1\necho line2")
    assert terminal.inserted == [b"echo line1\necho line2", b"\n"]


def test_terminal_pane_spawn_uses_configured_shell() -> None:
    pane = TerminalPane(FakeTerminal(), shell="/bin/zsh")
    assert pane.shell == "/bin/zsh"


def test_terminal_pane_spawn_with_default_shell() -> None:
    pane = TerminalPane(FakeTerminal(), shell="/bin/bash")
    assert pane.shell == "/bin/bash"


def test_terminal_pane_spawns_proxy_with_capture_socket_and_shell() -> None:
    terminal = FakeTerminal()
    pane = TerminalPane(terminal, shell="/bin/bash", capture_socket_path="/tmp/capture.sock")
    pane.spawn(FakeVte)
    argv = terminal.spawned[2]
    assert argv[1:4] == ["-m", "troubleshell.terminal.pty_proxy", "--capture-socket"]
    assert "/tmp/capture.sock" in argv
    assert argv[-2:] == ["--shell", "/bin/bash"]


def test_terminal_pane_handles_ctrl_shift_copy_and_paste_only() -> None:
    terminal = FakeTerminal()
    pane = TerminalPane(terminal, shell="/bin/bash")
    modifiers = {"control": 4, "shift": 1, "other": 8}

    assert pane.handle_clipboard_key(
        ord("c"), modifiers["control"] | modifiers["shift"],
        control_mask=modifiers["control"], shift_mask=modifiers["shift"],
        other_modifier_mask=modifiers["other"], copy_key=ord("c"), paste_key=ord("v")) is True
    assert pane.handle_clipboard_key(
        ord("v"), modifiers["control"] | modifiers["shift"],
        control_mask=modifiers["control"], shift_mask=modifiers["shift"],
        other_modifier_mask=modifiers["other"], copy_key=ord("c"), paste_key=ord("v")) is True
    assert pane.handle_clipboard_key(
        ord("C"), modifiers["control"] | modifiers["shift"],
        control_mask=modifiers["control"], shift_mask=modifiers["shift"],
        other_modifier_mask=modifiers["other"], copy_key=(ord("c"), ord("C")),
        paste_key=(ord("v"), ord("V"))) is True
    assert pane.handle_clipboard_key(
        ord("V"), modifiers["control"] | modifiers["shift"],
        control_mask=modifiers["control"], shift_mask=modifiers["shift"],
        other_modifier_mask=modifiers["other"], copy_key=(ord("c"), ord("C")),
        paste_key=(ord("v"), ord("V"))) is True
    assert terminal.clipboard_actions == ["copy", "paste", "copy", "paste"]


def test_terminal_pane_does_not_consume_unrelated_keys_or_modifiers() -> None:
    terminal = FakeTerminal()
    pane = TerminalPane(terminal, shell="/bin/bash")
    kwargs = dict(control_mask=4, shift_mask=1, other_modifier_mask=8,
                  copy_key=ord("c"), paste_key=ord("v"))

    assert pane.handle_clipboard_key(ord("c"), 4, **kwargs) is False
    assert pane.handle_clipboard_key(ord("c"), 4 | 1 | 8, **kwargs) is False
    assert pane.handle_clipboard_key(ord("x"), 4 | 1, **kwargs) is False
    assert terminal.clipboard_actions == []
