import os
import sys
from unittest.mock import Mock

import pytest

from triagetty.terminal import pty_proxy


def test_write_all_handles_partial_writes(monkeypatch):
    calls = []

    def partial_write(fd, data):
        calls.append(bytes(data))
        return min(2, len(data))

    monkeypatch.setattr(os, "write", partial_write)
    pty_proxy.write_all(7, b"abcdef")
    assert calls == [b"abcdef", b"cdef", b"ef"]


def test_copy_winsize_copies_complete_structure(monkeypatch):
    calls = []

    def ioctl(fd, operation, value):
        calls.append((fd, operation, value))
        return b"\x18\x00\x50\x00\x00\x00\x00\x00"

    monkeypatch.setattr(pty_proxy.fcntl, "ioctl", ioctl)
    pty_proxy.copy_winsize(3, 4)
    assert len(calls) == 2
    assert calls[1][0] == 4
    assert calls[0][2] == b"\0" * 8
    assert calls[1][2] == b"\x18\x00\x50\x00\x00\x00\x00\x00"


def test_capture_packet_failure_is_fatal():
    capture = Mock()
    capture.send.side_effect = BrokenPipeError("disconnected")
    with pytest.raises(BrokenPipeError):
        pty_proxy.send_capture_packet(capture, b"output")


def test_proxy_module_does_not_require_gi():
    assert "gi" not in sys.modules or pty_proxy.__name__ == "triagetty.terminal.pty_proxy"


def test_main_requires_proxy_arguments():
    with pytest.raises(SystemExit):
        pty_proxy.main([])
