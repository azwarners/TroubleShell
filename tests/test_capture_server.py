import socket
import threading
import time
import pytest

from troubleshell.terminal.capture_protocol import (
    decode_proxy_packet,
    output_packet,
    sync_ack_packet,
)
from troubleshell.terminal.capture_server import CaptureServer
from troubleshell.terminal.output_capturer import TerminalOutputCapturer
from troubleshell.terminal.transcript_store import TranscriptStore


def wait_for(predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.01)
    raise AssertionError("condition was not reached")


def test_capture_server_receives_ordered_seqpackets(tmp_path):
    store = TranscriptStore()
    server = CaptureServer(TerminalOutputCapturer(store), temp_dir_parent=tmp_path)
    path = server.start()
    assert server.state == "starting"
    client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    try:
        client.connect(path)
        wait_for(lambda: server.state == "connected")
        client.send(b"same")
        client.send(b"same")
        client.send(b"\xe2")
        client.send(b"\x98\x83")
        wait_for(lambda: len(store.events) == 4)
        assert [event.raw for event in store.events] == [b"same", b"same", b"\xe2", b"\x98\x83"]
        assert store.get_slice(2, 4).text == "☃"
        client.close()
        server.finished.wait(2)
        assert server.state == "closed"
        try:
            server.ensure_healthy()
        except RuntimeError as exc:
            assert "closed" in str(exc)
        else:
            raise AssertionError("closed capture server must not be healthy")
    finally:
        client.close()
        server.stop()


def test_capture_server_records_reader_failure_and_preserves_it_on_stop(tmp_path):
    class FailingCapturer:
        def record_output(self, _packet):
            raise ValueError("sink failed")

    server = CaptureServer(FailingCapturer(), temp_dir_parent=tmp_path)
    path = server.start()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    try:
        client.connect(path)
        client.send(b"output")
        wait_for(lambda: server.state == "failed")
        assert isinstance(server.failure, ValueError)
        with pytest.raises(RuntimeError, match="terminal output capture failed") as exc_info:
            server.ensure_healthy()
        assert isinstance(exc_info.value.__cause__, ValueError)
        server.stop()
        assert server.state == "failed"
        with pytest.raises(RuntimeError):
            server.ensure_healthy()
    finally:
        client.close()
        server.stop()


def test_synchronize_waits_for_output_before_the_proxy_barrier(tmp_path):
    """A model snapshot cannot overtake output already sent for display."""
    store = TranscriptStore()
    server = CaptureServer(TerminalOutputCapturer(store), temp_dir_parent=tmp_path)
    path = server.start()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    try:
        client.connect(path)
        wait_for(lambda: server.state == "connected")

        def acknowledge_barrier() -> None:
            packet = client.recv(1024)
            kind, token = decode_proxy_packet(packet)
            assert kind == "sync"
            # On the proxy's ordered connection, this output is sent before
            # the acknowledgement. The parent reader must append it first.
            client.send(output_packet(b"visible-before-question\n"))
            client.send(sync_ack_packet(token))

        worker = threading.Thread(target=acknowledge_barrier)
        worker.start()
        server.synchronize()
        worker.join(timeout=2)

        assert store.get_slice(0, store.next_sequence).text == "visible-before-question\n"
    finally:
        client.close()
        server.stop()
