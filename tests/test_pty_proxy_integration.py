import subprocess
import sys
import threading
import time

from triagetty.terminal.capture_server import CaptureServer
from triagetty.terminal.output_capturer import TerminalOutputCapturer
from triagetty.terminal.transcript_store import TranscriptStore


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.01)
    raise AssertionError("condition was not reached")


def test_proxy_captures_and_forwards_exact_shell_bytes(tmp_path):
    source_output = b"\n\r\x1b[31mred\x1b[0m\nrepeat\nrepeat\xe2\x98\x83"
    expected = source_output.replace(b"\n", b"\r\n")
    wrapper = tmp_path / "emit-shell"
    wrapper.write_bytes(b"#!/usr/bin/env python3\nimport os\nos.write(1, " + repr(source_output).encode() + b")\n")
    wrapper.chmod(0o700)
    store = TranscriptStore()
    server = CaptureServer(TerminalOutputCapturer(store), temp_dir_parent=tmp_path)
    path = server.start()
    proc = None
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "triagetty.terminal.pty_proxy", "--capture-socket", path,
             "--shell", str(wrapper)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = proc.communicate(b"", timeout=5)
        assert proc.returncode == 0, stderr.decode(errors="replace")
        wait_for(lambda: b"".join(event.raw for event in store.events) == expected)
        assert stdout == expected
        assert server.state == "closed"
        assert server.failure is None
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
        server.stop()


def test_proxy_refuses_uncaptured_shell(tmp_path):
    missing = tmp_path / "missing.sock"
    proc = subprocess.run(
        [sys.executable, "-m", "triagetty.terminal.pty_proxy", "--capture-socket", str(missing),
         "--shell", "/bin/sh"], capture_output=True, check=False,
    )
    assert proc.returncode != 0
    assert b"capture" in proc.stderr.lower()


def test_proxy_preserves_ten_thousand_lines(tmp_path):
    wrapper = tmp_path / "many-lines"
    wrapper.write_bytes(
        b"#!/usr/bin/env python3\n"
        b"import os\n"
        b"os.write(1, b''.join(f'line-{i}\\n'.encode() for i in range(10000)))\n"
    )
    wrapper.chmod(0o700)
    store = TranscriptStore()
    server = CaptureServer(TerminalOutputCapturer(store), temp_dir_parent=tmp_path)
    path = server.start()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "triagetty.terminal.pty_proxy", "--capture-socket", path,
             "--shell", str(wrapper)], input=b"", capture_output=True, timeout=10,
        )
        assert proc.returncode == 0, proc.stderr.decode(errors="replace")
        wait_for(lambda: server.finished.is_set())
        captured = b"".join(event.raw for event in store.events).decode()
        lines = captured.splitlines()
        assert len(lines) == 10000
        assert lines[0] == "line-0"
        assert lines[5000] == "line-5000"
        assert lines[-1] == "line-9999"
        assert server.state == "closed"
        assert server.failure is None
    finally:
        server.stop()


def test_live_proxy_snapshot_boundary(tmp_path):
    wrapper = tmp_path / "boundary-shell"
    wrapper.write_bytes(
        b"#!/usr/bin/env python3\n"
        b"import os, termios\n"
        b"attrs = termios.tcgetattr(0); attrs[3] &= ~termios.ECHO; termios.tcsetattr(0, termios.TCSANOW, attrs)\n"
        b"os.write(1, b'A\\n'); os.read(0, 1); os.write(1, b'B\\n')\n"
    )
    wrapper.chmod(0o700)
    store = TranscriptStore()
    server = CaptureServer(TerminalOutputCapturer(store), temp_dir_parent=tmp_path)
    path = server.start()
    proc = subprocess.Popen(
        [sys.executable, "-m", "triagetty.terminal.pty_proxy", "--capture-socket", path,
         "--shell", str(wrapper)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        wait_for(lambda: "A" in store.get_slice(0, store.next_sequence).text)
        from triagetty.llm.context_session import ContextSession
        from triagetty.chat.models import ChatMessage
        session = ContextSession(store)
        first = session.request_slice()
        assert first.text == "A\r\n"
        proc.stdin.write(b"x\n")
        proc.stdin.flush()
        wait_for(lambda: "B" in store.get_slice(0, store.next_sequence).text)
        assert session.build_request_payload() == "A\r\n"
        session.snapshot_for_send(ChatMessage("user", "question"))
        session.commit_on_success("answer")
        assert session.request_slice().text == "B\r\n"
    finally:
        if proc.stdin is not None:
            proc.stdin.close()
        proc.wait(timeout=5)
        if proc.stdout is not None:
            proc.stdout.read()
        if proc.stderr is not None:
            proc.stderr.read()
        server.stop()


def test_proxy_exits_when_capture_connection_disconnects(tmp_path):
    wrapper = tmp_path / "disconnect-shell"
    wrapper.write_bytes(
        b"#!/usr/bin/env python3\n"
        b"import os, time\n"
        b"os.write(1, b'A\\n')\n"
        b"os.read(0, 1)\n"
        b"os.write(1, b'B\\n')\n"
        b"time.sleep(2)\n"
    )
    wrapper.chmod(0o700)
    store = TranscriptStore()
    server = CaptureServer(TerminalOutputCapturer(store), temp_dir_parent=tmp_path)
    path = server.start()
    proc = subprocess.Popen(
        [sys.executable, "-m", "triagetty.terminal.pty_proxy", "--capture-socket", path,
         "--shell", str(wrapper)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        wait_for(lambda: "A" in store.get_slice(0, store.next_sequence).text)
        with server._lock:
            connection = server._connection
        assert connection is not None
        connection.shutdown(2)
        connection.close()
        wait_for(lambda: server.state == "closed")
        proc.stdin.write(b"x")
        proc.stdin.flush()
        proc.wait(timeout=5)
        assert proc.returncode != 0
        assert "B" not in b"".join(event.raw for event in store.events).decode(errors="replace")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        if proc.stdin is not None:
            proc.stdin.close()
        if proc.stdout is not None:
            proc.stdout.close()
        if proc.stderr is not None:
            proc.stderr.close()
        server.stop()
