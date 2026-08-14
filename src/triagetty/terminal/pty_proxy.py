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
    sent = capture.send(data)
    if sent != len(data):
        raise OSError("short capture packet send")


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
        print(f"triagetty proxy: capture connection failed: {exc}", file=sys.stderr)
        capture.close()
        return 1

    master_fd = -1
    process: subprocess.Popen[bytes] | None = None
    selector = selectors.DefaultSelector()
    try:
        master_fd, process = spawn_shell(shell)
        try:
            copy_winsize(sys.stdin.fileno(), master_fd)
        except (OSError, ValueError):
            pass
        selector.register(sys.stdin, selectors.EVENT_READ, "input")
        selector.register(master_fd, selectors.EVENT_READ, "shell")
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
                else:
                    try:
                        data = os.read(master_fd, MAX_READ)
                    except OSError as exc:
                        if exc.errno == errno.EIO:
                            data = b""
                        else:
                            raise
                    if not data:
                        selector.unregister(master_fd)
                        if input_open:
                            selector.unregister(sys.stdin)
                            input_open = False
                        break
                    # A failed capture send is fatal: never display uncaptured output.
                    send_capture_packet(capture, data)
                    write_all(sys.stdout.fileno(), data)
            if not selector.get_map() or (not input_open and master_fd not in selector.get_map()):
                break
        # EOF on the VTE side intentionally tears down the shell group; a
        # signal-terminated child is still a clean proxy shutdown.
        code = process.returncode
        return 0 if code is None or code < 0 else code
    except Exception as exc:
        print(f"triagetty proxy: relay failed: {exc}", file=sys.stderr)
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
        capture.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TriageTTY PTY capture proxy")
    parser.add_argument("--capture-socket", required=True)
    parser.add_argument("--shell", required=True)
    args = parser.parse_args(argv)
    return run_proxy(args.capture_socket, args.shell)


if __name__ == "__main__":
    raise SystemExit(main())
