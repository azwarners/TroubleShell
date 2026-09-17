import os
import pty
import select
import subprocess
import sys
import threading
import termios
import time

from troubleshell.terminal.capture_server import CaptureServer
from troubleshell.terminal.output_capturer import TerminalOutputCapturer
from troubleshell.terminal.transcript_store import TranscriptStore


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.01)
    raise AssertionError("condition was not reached")


def test_proxy_owns_outer_pty_relay_and_restores_termios(tmp_path):
    wrapper = tmp_path / "interactive-shell"
    wrapper.write_text("#!/bin/sh\nPS1=; export PS1\nprintf 'READY\\n'\nexec /bin/sh -i\n")
    wrapper.chmod(0o700)
    command = b"pwd; exit"
    outer_master, outer_slave = pty.openpty()
    original_outer_attrs = termios.tcgetattr(outer_slave)
    test_outer_attrs = original_outer_attrs.copy()
    test_outer_attrs[1] &= ~termios.OPOST
    termios.tcsetattr(outer_slave, termios.TCSANOW, test_outer_attrs)
    relay_baseline_attrs = termios.tcgetattr(outer_slave)
    store = TranscriptStore()
    server = CaptureServer(TerminalOutputCapturer(store), temp_dir_parent=tmp_path)
    path = server.start()
    proc = None
    displayed = bytearray()
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "troubleshell.terminal.pty_proxy", "--capture-socket", path,
             "--shell", str(wrapper)],
            stdin=outer_slave, stdout=outer_slave, stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + 5
        while b"READY\r\n" not in displayed and time.monotonic() < deadline:
            readable, _, _ = select.select([outer_master], [], [], 0.1)
            if readable:
                displayed.extend(os.read(outer_master, 65536))
        assert b"READY\r\n" in displayed
        os.write(outer_master, command + b"\n")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            readable, _, _ = select.select([outer_master], [], [], min(0.1, remaining))
            if readable:
                try:
                    displayed.extend(os.read(outer_master, 65536))
                except OSError:
                    break
            if proc.poll() is not None:
                break
        proc.wait(timeout=5)
        for _ in range(10):
            readable, _, _ = select.select([outer_master], [], [], 0.05)
            if not readable:
                break
            try:
                displayed.extend(os.read(outer_master, 65536))
            except OSError:
                break
        stderr = proc.stderr.read() if proc.stderr is not None else b""
        assert proc.returncode == 0, stderr.decode(errors="replace")
        assert displayed.count(command) == 1
        expected = command + b"\r\n" + os.getcwd().encode()
        assert expected in displayed
        assert command + b"\r\n\r\n" + os.getcwd().encode() not in displayed
        assert termios.tcgetattr(outer_slave) == relay_baseline_attrs
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        if outer_slave >= 0:
            os.close(outer_slave)
        os.close(outer_master)
        server.stop()


def test_proxy_forwards_ctrl_c_without_terminating(tmp_path):
    wrapper = tmp_path / "ctrl-c-shell"
    wrapper.write_bytes(
        b"#!/usr/bin/env python3\n"
        b"import os, termios\n"
        b"attrs = termios.tcgetattr(0)\n"
        b"attrs[3] &= ~(termios.ICANON | termios.ISIG)\n"
        b"attrs[6][termios.VMIN] = 1; attrs[6][termios.VTIME] = 0\n"
        b"termios.tcsetattr(0, termios.TCSANOW, attrs)\n"
        b"os.write(1, b'READY\\n')\n"
        b"value = os.read(0, 1)\n"
        b"os.write(1, b'CTRL_C_FORWARDED\\n' if value == b'\\x03' else b'WRONG_BYTE\\n')\n"
    )
    wrapper.chmod(0o700)
    outer_master, outer_slave = pty.openpty()
    outer_attrs = termios.tcgetattr(outer_slave)
    outer_attrs[1] &= ~termios.OPOST
    termios.tcsetattr(outer_slave, termios.TCSANOW, outer_attrs)
    store = TranscriptStore()
    server = CaptureServer(TerminalOutputCapturer(store), temp_dir_parent=tmp_path)
    path = server.start()
    proc = None
    displayed = bytearray()
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "troubleshell.terminal.pty_proxy", "--capture-socket", path,
             "--shell", str(wrapper)],
            stdin=outer_slave, stdout=outer_slave, stderr=subprocess.PIPE,
        )
        os.close(outer_slave)
        outer_slave = -1
        deadline = time.monotonic() + 5
        while b"READY\r\n" not in displayed and time.monotonic() < deadline:
            readable, _, _ = select.select([outer_master], [], [], 0.1)
            if readable:
                displayed.extend(os.read(outer_master, 65536))
        os.write(outer_master, b"\x03")
        while proc.poll() is None and time.monotonic() < deadline:
            readable, _, _ = select.select([outer_master], [], [], 0.1)
            if readable:
                try:
                    displayed.extend(os.read(outer_master, 65536))
                except OSError:
                    break
        proc.wait(timeout=5)
        assert proc.returncode == 0
        captured = b"".join(event.raw for event in store.events)
        assert b"CTRL_C_FORWARDED\r\n" in captured
        assert b"WRONG_BYTE" not in captured
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        if outer_slave >= 0:
            os.close(outer_slave)
        os.close(outer_master)
        server.stop()


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
            [sys.executable, "-m", "troubleshell.terminal.pty_proxy", "--capture-socket", path,
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
        [sys.executable, "-m", "troubleshell.terminal.pty_proxy", "--capture-socket", str(missing),
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
            [sys.executable, "-m", "troubleshell.terminal.pty_proxy", "--capture-socket", path,
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
        [sys.executable, "-m", "troubleshell.terminal.pty_proxy", "--capture-socket", path,
         "--shell", str(wrapper)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        wait_for(lambda: "A" in store.get_slice(0, store.next_sequence).text)
        from troubleshell.llm.context_session import ContextSession
        from troubleshell.chat.models import ChatMessage
        session = ContextSession(store)
        first = session.request_slice()
        assert first.text == "A\r\n"
        proc.stdin.write(b"x\n")
        proc.stdin.flush()
        wait_for(lambda: "B" in store.get_slice(0, store.next_sequence).text)
        assert session.build_request_payload() == "A\n"
        session.snapshot_for_send(ChatMessage("user", "question"))
        session.commit_on_success("answer")
        second = session.request_slice()
        assert second.text == "B\r\n"
        assert session.build_request_payload() == "B\n"
    finally:
        if proc.stdin is not None:
            proc.stdin.close()
        proc.wait(timeout=5)
        if proc.stdout is not None:
            proc.stdout.read()
        if proc.stderr is not None:
            proc.stderr.read()
        server.stop()


def test_interrupted_long_running_command_is_captured_before_each_snapshot(tmp_path):
    """Visible live output survives both an in-flight question and Ctrl-C.

    This is the real desktop sequence: an interactive shell runs a streaming
    command, the user asks a question, then interrupts it and asks again.
    ``CaptureServer.synchronize()`` is the screen-to-store barrier used by the
    submission path, so each request snapshot includes output the user could
    already see in the terminal.
    """
    wrapper = tmp_path / "interactive-shell"
    wrapper.write_text(
        "#!/bin/sh\n"
        "PS1='TROUBLE_PROMPT> '; export PS1\n"
        "exec /bin/sh -i\n"
    )
    wrapper.chmod(0o700)
    outer_master, outer_slave = pty.openpty()
    attrs = termios.tcgetattr(outer_slave)
    attrs[1] &= ~termios.OPOST
    termios.tcsetattr(outer_slave, termios.TCSANOW, attrs)
    store = TranscriptStore()
    server = CaptureServer(TerminalOutputCapturer(store), temp_dir_parent=tmp_path)
    path = server.start()
    proc = None
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "troubleshell.terminal.pty_proxy", "--capture-socket", path,
             "--shell", str(wrapper)],
            stdin=outer_slave, stdout=outer_slave, stderr=subprocess.PIPE,
        )
        os.close(outer_slave)
        outer_slave = -1
        wait_for(lambda: b"TROUBLE_PROMPT> " in b"".join(event.raw for event in store.events))

        os.write(
            outer_master,
            b"i=0; while :; do printf 'device-%03d\\n' \"$i\"; "
            b"i=$((i + 1)); sleep 0.01; done\n",
        )
        wait_for(lambda: b"device-005\r\n" in b"".join(event.raw for event in store.events))

        from troubleshell.chat.models import ChatMessage
        from troubleshell.llm.context_session import ContextSession

        session = ContextSession(store)
        server.synchronize()
        first = session.request_slice()
        assert "device-000" in first.text
        assert "device-005" in first.text
        session.snapshot_for_send(ChatMessage("user", "question while command runs"))
        session.commit_on_success("response")

        wait_for(lambda: b"device-012\r\n" in b"".join(event.raw for event in store.events))
        os.write(outer_master, b"\x03")
        wait_for(
            lambda: b"".join(event.raw for event in store.events).count(b"TROUBLE_PROMPT> ") >= 2
        )

        server.synchronize()
        second = session.request_slice()
        assert "device-012" in second.text
        assert "device-000" not in second.text

        os.write(outer_master, b"exit\n")
        proc.wait(timeout=5)
        assert proc.returncode == 0, proc.stderr.read().decode(errors="replace")
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        if outer_slave >= 0:
            os.close(outer_slave)
        os.close(outer_master)
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
        [sys.executable, "-m", "troubleshell.terminal.pty_proxy", "--capture-socket", path,
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
        proc.stdin.write(b"x\n")
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
