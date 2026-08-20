"""GTK-free PTY relay which captures shell output before displaying it."""

from __future__ import annotations

import argparse
import errno
import fcntl
import os
import pty
import selectors
import signal
import socket
import subprocess
import sys
import termios
from collections.abc import Sequence

from .capture_protocol import (
    decode_proxy_packet,
    output_packet,
    sync_ack_packet,
)


MAX_READ = 64 * 1024


def write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        try:
            written = os.write(fd, view)
        except InterruptedError:
            continue
        if written <= 0:
            raise OSError("short write")
        view = view[written:]


def copy_winsize(source_fd: int, destination_fd: int) -> None:
    size = fcntl.ioctl(source_fd, termios.TIOCGWINSZ, b"\0" * 8)
    fcntl.ioctl(destination_fd, termios.TIOCSWINSZ, size)


def send_capture_packet(capture: socket.socket, data: bytes) -> None:
    """Send exactly one captured read chunk as one seqpacket."""
    packet = output_packet(data)
    sent = capture.send(packet)
    if sent != len(packet):
        raise OSError("short capture packet send")


def relay_shell_output(master_fd: int, capture: socket.socket, display_fd: int) -> bool:
    """Capture and display one shell read; return False at shell EOF."""
    try:
        data = os.read(master_fd, MAX_READ)
    except OSError as exc:
        if exc.errno == errno.EIO:
            data = b""
        else:
            raise
    if not data:
        return False
    # A failed capture send is fatal: never display uncaptured output.
    send_capture_packet(capture, data)
    write_all(display_fd, data)
    return True


def drain_shell_output(master_fd: int, capture: socket.socket, display_fd: int) -> bool:
    """Relay all output currently ready before acknowledging a sync barrier."""
    original_flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, original_flags | os.O_NONBLOCK)
    try:
        while True:
            try:
                if not relay_shell_output(master_fd, capture, display_fd):
                    return False
            except BlockingIOError:
                return True
    finally:
        fcntl.fcntl(master_fd, fcntl.F_SETFL, original_flags)


def configure_relay_terminal(fd: int) -> list[object]:
    """Make the VTE-side PTY a byte relay and return its original settings.

    Input flags are intentionally preserved, so the terminal's normal CR and
    other input mappings remain in effect.  Only local line editing, echo,
    and signal generation are moved out of this transport boundary.
    """
    original = termios.tcgetattr(fd)
    relay = original.copy()
    relay[3] &= ~(termios.ICANON | termios.ECHO | termios.ECHONL | termios.ISIG)
    relay[6] = relay[6][:]
    relay[6][termios.VMIN] = 1
    relay[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, relay)
    return original


def spawn_shell(shell: str) -> tuple[int, subprocess.Popen[bytes]]:
    master_fd, slave_fd = pty.openpty()

    def make_session() -> None:
        os.setsid()
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

    try:
        process = subprocess.Popen(
            [shell], stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
            preexec_fn=make_session, close_fds=True,
        )
    except BaseException:
        os.close(master_fd)
        os.close(slave_fd)
        raise
    os.close(slave_fd)
    return master_fd, process


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGHUP)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def run_proxy(capture_socket_path: str, shell: str) -> int:
    capture = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    try:
        capture.connect(capture_socket_path)
    except OSError as exc:
        print(f"troubleshell proxy: capture connection failed: {exc}", file=sys.stderr)
        capture.close()
        return 1

    master_fd = -1
    process: subprocess.Popen[bytes] | None = None
    selector = selectors.DefaultSelector()
    stdin_fd = -1
    original_stdin_attrs: list[object] | None = None
    try:
        stdin_fd = sys.stdin.fileno()
        try:
            original_stdin_attrs = configure_relay_terminal(stdin_fd)
        except (OSError, ValueError, termios.error):
            # Unit tests and non-VTE callers may provide a pipe instead of a PTY.
            pass
        master_fd, process = spawn_shell(shell)
        try:
            copy_winsize(sys.stdin.fileno(), master_fd)
        except (OSError, ValueError):
            pass
        selector.register(sys.stdin, selectors.EVENT_READ, "input")
        selector.register(master_fd, selectors.EVENT_READ, "shell")
        selector.register(capture, selectors.EVENT_READ, "capture")
        input_open = True

        def resize(_signum: int, _frame: object) -> None:
            try:
                copy_winsize(sys.stdin.fileno(), master_fd)
            except (OSError, ValueError):
                pass

        signal.signal(signal.SIGWINCH, resize)
        while True:
            for key, _ in selector.select(timeout=0.1):
                if key.data == "input":
                    try:
                        data = os.read(sys.stdin.fileno(), MAX_READ)
                    except OSError as exc:
                        if exc.errno == errno.EIO:
                            data = b""
                        else:
                            raise
                    if not data:
                        selector.unregister(sys.stdin)
                        input_open = False
                        try:
                            # Deliver terminal EOF to an interactive shell and
                            # leave the master readable long enough to drain
                            # output already produced by the child.
                            write_all(master_fd, b"\x04")
                        except OSError:
                            _terminate(process)
                        continue
                    write_all(master_fd, data)
                elif key.data == "shell":
                    if not relay_shell_output(master_fd, capture, sys.stdout.fileno()):
                        selector.unregister(master_fd)
                        if input_open:
                            selector.unregister(sys.stdin)
                            input_open = False
                        break
                else:
                    packet = capture.recv(MAX_READ)
                    if not packet:
                        raise OSError("capture connection closed")
                    kind, token = decode_proxy_packet(packet)
                    if kind == "sync":
                        if not drain_shell_output(master_fd, capture, sys.stdout.fileno()):
                            selector.unregister(master_fd)
                        sent = capture.send(sync_ack_packet(token))
                        if sent != len(sync_ack_packet(token)):
                            raise OSError("short capture sync acknowledgement")
            if not selector.get_map() or (not input_open and master_fd not in selector.get_map()):
                break
        # EOF on the VTE side intentionally tears down the shell group; a
        # signal-terminated child is still a clean proxy shutdown.
        code = process.returncode
        return 0 if code is None or code < 0 else code
    except Exception as exc:
        print(f"troubleshell proxy: relay failed: {exc}", file=sys.stderr)
        return 1
    finally:
        selector.close()
        if process is not None:
            _terminate(process)
        if master_fd >= 0:
            try:
                os.close(master_fd)
            except OSError:
                pass
        if original_stdin_attrs is not None:
            try:
                termios.tcsetattr(stdin_fd, termios.TCSANOW, original_stdin_attrs)
            except (OSError, ValueError, termios.error):
                pass
        capture.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TroubleShell PTY capture proxy")
    parser.add_argument("--capture-socket", required=True)
    parser.add_argument("--shell", required=True)
    args = parser.parse_args(argv)
    return run_proxy(args.capture_socket, args.shell)


if __name__ == "__main__":
    raise SystemExit(main())
