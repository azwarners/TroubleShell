"""Parent-side Unix seqpacket receiver for PTY output capture."""

from __future__ import annotations

import socket
import tempfile
import threading
from pathlib import Path
from typing import Literal

from .output_capturer import TerminalOutputCapturer


class CaptureServer:
    """Receive raw output packets from exactly one PTY proxy."""

    def __init__(self, capturer: TerminalOutputCapturer,
                 temp_dir_parent: str | Path | None = None) -> None:
        self.capturer = capturer
        self.temp_dir_parent = temp_dir_parent
        self.failure: Exception | None = None
        self.state: Literal["starting", "connected", "closed", "failed"] = "closed"
        self.connected = threading.Event()
        self.finished = threading.Event()
        self._directory: tempfile.TemporaryDirectory[str] | None = None
        self._listener: socket.socket | None = None
        self._connection: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._stopping = False

    def start(self) -> str:
        with self._lock:
            if self._thread is not None:
                raise RuntimeError("capture server already started")
            self._stopping = False
            self.failure = None
            self.state = "starting"
            self._directory = tempfile.TemporaryDirectory(dir=self.temp_dir_parent)
            path = Path(self._directory.name) / "capture.sock"
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            try:
                listener.bind(str(path))
                listener.listen(1)
            except Exception as exc:
                listener.close()
                self.failure = exc
                self.state = "failed"
                if self._directory is not None:
                    self._directory.cleanup()
                    self._directory = None
                raise
            self._listener = listener
            self._thread = threading.Thread(target=self._read_packets, name="terminal-capture", daemon=True)
            self._thread.start()
            return str(path)

    def _read_packets(self) -> None:
        try:
            listener = self._listener
            if listener is None:
                return
            connection, _ = listener.accept()
            with self._lock:
                self._connection = connection
                if self._stopping:
                    connection.close()
                    return
                self.state = "connected"
            self.connected.set()
            with connection:
                while True:
                    packet = connection.recv(65536)
                    if not packet:
                        with self._lock:
                            if self.state != "failed":
                                self.state = "closed"
                        return
                    self.capturer.record_output(packet)
        except Exception as exc:
            with self._lock:
                if not self._stopping:
                    self.failure = exc
                    self.state = "failed"
        finally:
            self.finished.set()

    def ensure_healthy(self) -> None:
        with self._lock:
            state = self.state
            failure = self.failure
        if state == "connected":
            return
        if state == "failed" and failure is not None:
            raise RuntimeError("terminal output capture failed") from failure
        raise RuntimeError(f"terminal output capture is {state}, not connected")

    def stop(self) -> None:
        with self._lock:
            self._stopping = True
            connection = self._connection
            listener = self._listener
            thread = self._thread
            directory = self._directory
            self._connection = None
            self._listener = None
            self._thread = None
            self._directory = None
        for sock in (connection, listener):
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()
        if thread is not None:
            thread.join(timeout=1.0)
        if directory is not None:
            directory.cleanup()
        with self._lock:
            if self.state != "failed":
                self.state = "closed"
