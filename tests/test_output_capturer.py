"""Phase 2 tests: output capturer sink and raw-byte preservation.

Tests the exact seam between the PTY proxy (producer) and TranscriptStore
(consumer) without involving VTE, GTK, or threads.

Proves:
1. Exact raw preservation (no line splitting, no padding added/removed)
2. Blank lines and trailing-newline absence are preserved
3. UTF-8 multi-byte characters split across chunks decode correctly
4. Zero-length chunks are silently ignored (EOF/closure from proxy)
5. Errors are never swallowed
6. Ordered interleaving is maintained
7. Repeated identical chunks are separate events
"""

import pytest

from troubleshell.terminal.output_capturer import TerminalOutputCapturer
from troubleshell.terminal.transcript_store import TranscriptStore


def test_exact_raw_preservation():
    """Raw bytes go in, identical bytes out — no transformation."""
    store = TranscriptStore()
    capturer = TerminalOutputCapturer(transcript_store=store)

    raw = b"hello\r\nworld\r\n"
    capturer.record_output(raw)

    assert len(store.events) == 1
    assert store.events[0].raw == raw


def test_blank_lines_preserved():
    """Empty lines in the output are not discarded."""
    store = TranscriptStore()
    capturer = TerminalOutputCapturer(transcript_store=store)

    # Output with blank lines
    raw = b"line 1\n\nline 3\n\n\nline 6\n"
    capturer.record_output(raw)

    assert len(store.events) == 1
    assert store.events[0].raw == raw


def test_no_trailing_newline_added():
    """Output without trailing newline is preserved as-is."""
    store = TranscriptStore()
    capturer = TerminalOutputCapturer(transcript_store=store)

    raw = b"incomplete line without newline"
    capturer.record_output(raw)

    assert len(store.events) == 1
    assert store.events[0].raw == raw
    assert not raw.endswith(b"\n")


def test_repeated_identical_chunks():
    """Two identical byte sequences produce two separate events."""
    store = TranscriptStore()
    capturer = TerminalOutputCapturer(transcript_store=store)

    raw = b"same output\n"
    capturer.record_output(raw)
    capturer.record_output(raw)

    assert len(store.events) == 2
    assert store.events[0].sequence == 0
    assert store.events[1].sequence == 1
    assert store.events[0].raw == raw
    assert store.events[1].raw == raw


def test_utf8_split_across_chunks():
    """UTF-8 multi-byte characters split across chunks decode correctly.
    
    Uses C3 A9 which is é in UTF-8.
    """
    store = TranscriptStore()
    capturer = TerminalOutputCapturer(transcript_store=store)

    # Split é (C3 A9) across two chunks
    capturer.record_output(b"caf\xc3")
    capturer.record_output(b"\xa9\n")

    # Slice and decode
    slice_result = store.get_slice(0, 2)
    assert "café" in slice_result.text


def test_empty_bytes_ignored():
    """Zero-length chunks are silently ignored (EOF/closure from proxy)."""
    store = TranscriptStore()
    capturer = TerminalOutputCapturer(transcript_store=store)

    initial_count = len(store.events)
    capturer.record_output(b"")
    
    assert len(store.events) == initial_count


def test_ordered_interleaving():
    """Multiple sequential events maintain order in payload."""
    store = TranscriptStore()
    capturer = TerminalOutputCapturer(transcript_store=store)

    for i in range(5):
        capturer.record_output(f"chunk {i}\n".encode("utf-8"))

    assert len(store.events) == 5
    for i, event in enumerate(store.events):
        assert event.sequence == i
        assert event.raw == f"chunk {i}\n".encode("utf-8")

    # Slice all events
    slice_result = store.get_slice(0, 5)
    for i in range(5):
        assert f"chunk {i}" in slice_result.text


def test_errors_not_silenced():
    """Errors in record_output propagate, not swallowed."""
    from unittest.mock import MagicMock

    # Fake store that raises on append
    fake_store = MagicMock()
    fake_store.append.side_effect = ValueError("I/O error")
    capturer = TerminalOutputCapturer(transcript_store=fake_store)

    with pytest.raises(ValueError, match="I/O error"):
        capturer.record_output(b"test\n")


def test_utf8_decode_correct_character():
    """Verify correct UTF-8 decoding: C3 A9 is é."""
    store = TranscriptStore()
    capturer = TerminalOutputCapturer(transcript_store=store)

    # Full é character
    capturer.record_output(b"\xc3\xa9\n")

    slice_result = store.get_slice(0, 1)
    assert "é" in slice_result.text
