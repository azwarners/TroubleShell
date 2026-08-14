import sys
import threading
import time

import pytest

from triagetty.terminal.capture_server import CaptureServer
from triagetty.terminal.output_capturer import TerminalOutputCapturer
from triagetty.terminal.transcript_store import TranscriptStore


def _wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.01)
    raise AssertionError("condition was not reached")


def test_real_vte_tiny_scrollback_does_not_limit_capture(tmp_path):
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Vte", "3.91")
        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk, GLib, Gtk, Vte
    except (ImportError, ValueError):
        pytest.skip("GTK/VTE is unavailable")

    if not Gtk.init_check() or Gdk.Display.get_default() is None:
        pytest.skip("GTK display is unavailable")

    wrapper = tmp_path / "vte-many-lines"
    wrapper.write_bytes(
        b"#!/usr/bin/env python3\n"
        b"import os\n"
        b"os.write(1, b''.join(f'vte-line-{i}\\n'.encode() for i in range(30)))\n"
    )
    wrapper.chmod(0o700)
    store = TranscriptStore()
    server = CaptureServer(TerminalOutputCapturer(store), temp_dir_parent=tmp_path)
    path = server.start()
    terminal = Vte.Terminal()
    terminal.set_scrollback_lines(2)
    exited = threading.Event()

    def child_exited(_terminal, _pid, _status, _data):
        exited.set()

    try:
        terminal.spawn_async(
            Vte.PtyFlags.DEFAULT, None,
            [sys.executable, "-m", "triagetty.terminal.pty_proxy", "--capture-socket", path,
             "--shell", str(wrapper)],
            None, GLib.SpawnFlags.DEFAULT, None, None, -1, None, child_exited, None,
        )
        deadline = time.monotonic() + 10
        context = GLib.MainContext.default()
        while not exited.is_set() and time.monotonic() < deadline:
            context.iteration(True)
        assert exited.is_set()
        _wait_for(lambda: server.finished.is_set())
        captured = b"".join(event.raw for event in store.events).decode(errors="replace")
        assert "vte-line-0" in captured
        assert "vte-line-15" in captured
        assert "vte-line-29" in captured
        assert terminal.get_scrollback_lines() <= 2
        assert server.state == "closed"
        assert server.failure is None
    finally:
        server.stop()
