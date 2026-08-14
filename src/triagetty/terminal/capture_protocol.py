"""Private framing for the proxy-to-parent capture socket.

The terminal bytes themselves remain unchanged in :class:`TranscriptStore`.
The small framing prefix exists only on the private Unix seqpacket transport so
the parent can ask the proxy for an ordered capture barrier before building a
model request.
"""

from __future__ import annotations


_PREFIX = b"\0triagetty:"
_OUTPUT = _PREFIX + b"output:"
_SYNC = _PREFIX + b"sync:"
_SYNC_ACK = _PREFIX + b"sync-ack:"


def output_packet(raw: bytes) -> bytes:
    """Frame raw shell output for the private capture transport."""
    return _OUTPUT + raw


def sync_packet(token: bytes) -> bytes:
    """Build a parent-to-proxy capture-barrier request."""
    return _SYNC + token


def sync_ack_packet(token: bytes) -> bytes:
    """Build a proxy-to-parent acknowledgement for a capture barrier."""
    return _SYNC_ACK + token


def decode_parent_packet(packet: bytes) -> tuple[str, bytes]:
    """Classify a packet received by the capture-server parent.

    Plain packets remain accepted for the small direct-socket unit-test seam;
    only proxy packets use this module's private framing.
    """
    if packet.startswith(_OUTPUT):
        return "output", packet[len(_OUTPUT):]
    if packet.startswith(_SYNC_ACK):
        return "sync-ack", packet[len(_SYNC_ACK):]
    return "output", packet


def decode_proxy_packet(packet: bytes) -> tuple[str, bytes]:
    """Classify a control packet received by the proxy."""
    if packet.startswith(_SYNC):
        return "sync", packet[len(_SYNC):]
    return "unknown", packet


def max_frame_overhead() -> int:
    """Return the largest output-frame prefix used by this protocol."""
    return len(_OUTPUT)
