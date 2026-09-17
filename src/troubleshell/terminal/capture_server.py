"""Parent-side Unix seqpacket receiver for PTY output capture."""

from __future__ import annotations

import socket
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Literal

from .output_capturer import TerminalOutputCapturer
from .capture_protocol import decode_parent_packet, max_frame_overhead, sync_packet


_MAX_CAPTURE_PACKET = (64 * 1024) + max_frame_overhead()


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
        self._sync_waiters: dict[bytes, threading.Event] = {}

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
                    packet = connection.recv(_MAX_CAPTURE_PACKET)
                    if not packet:
                        with self._lock:
                            if self.state != "failed":
                                self.state = "closed"
                            self._release_sync_waiters()
                        return
                    kind, payload = decode_parent_packet(packet)
                    if kind == "output":
                        self.capturer.record_output(payload)
                    elif kind == "sync-ack":
                        with self._lock:
                            waiter = self._sync_waiters.pop(payload, None)
                        if waiter is not None:
                            waiter.set()
        except Exception as exc:
            with self._lock:
                if not self._stopping:
                    self.failure = exc
                    self.state = "failed"
                self._release_sync_waiters()
        finally:
            self.finished.set()

    def _release_sync_waiters(self) -> None:
        """Wake pending barriers when the connection can no longer answer."""
        waiters = tuple(self._sync_waiters.values())
        self._sync_waiters.clear()
        for waiter in waiters:
            waiter.set()

    def synchronize(self, timeout: float = 1.0) -> None:
        """Wait until output already displayed by the proxy is in the store.

        The proxy drains shell output available at the barrier, then replies on
        its ordered seqpacket connection.  Since this reader processes packets
        in order, receiving that reply means every earlier output packet has
        reached ``TerminalOutputCapturer``.  This closes the screen-to-store
        race immediately before a model-request snapshot.
        """
        token = uuid.uuid4().bytes
        waiter = threading.Event()
        with self._lock:
            if self.state != "connected" or self._connection is None:
                self.ensure_healthy()
                raise RuntimeError("terminal output capture is not connected")
            connection = self._connection
            self._sync_waiters[token] = waiter
            try:
                connection.send(sync_packet(token))
            except Exception:
                self._sync_waiters.pop(token, None)
                raise
        if not waiter.wait(timeout):
            with self._lock:
                self._sync_waiters.pop(token, None)
            raise RuntimeError("terminal output capture did not synchronize in time")
        self.ensure_healthy()

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
            self._release_sync_waiters()
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
