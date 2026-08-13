"""Concurrency tests for TranscriptStore locking and atomic snapshots.

Validates:
- Lock protects append, snapshot_slice, next_sequence, is_empty
- snapshot_slice returns a consistent prefix that excludes later appends
- Split UTF-8 decodes correctly through snapshot_slice
"""

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from triagetty.terminal.transcript_store import TranscriptStore


class TestSnapshotSliceConsistency:
    """Tests for atomic snapshot behavior."""

    def test_snapshot_excludes_later_append(self):
        """Append A, snapshot, append B — snapshot contains only A."""
        store = TranscriptStore()
        store.append("output", b"A\n")
        slice_ = store.snapshot_slice(0)
        store.append("output", b"B\n")

        assert slice_.text == "A\n"
        assert slice_.end_sequence == 1
        # B is not in the snapshot
        assert "B" not in slice_.text

    def test_snapshot_empty_store(self):
        """Snapshot of empty store returns empty slice at 0."""
        store = TranscriptStore()
        slice_ = store.snapshot_slice(0)
        assert slice_.text == ""
        assert slice_.end_sequence == 0

    def test_snapshot_multiple_events(self):
        """Snapshot includes all events up to current end."""
        store = TranscriptStore()
        store.append("output", b"A\n")
        store.append("output", b"B\n")
        store.append("output", b"C\n")
        slice_ = store.snapshot_slice(0)

        assert slice_.text == "A\nB\nC\n"
        assert slice_.end_sequence == 3

    def test_snapshot_from_nonzero_start(self):
        """Snapshot from start > 0 excludes earlier events."""
        store = TranscriptStore()
        store.append("output", b"A\n")
        store.append("output", b"B\n")
        slice_ = store.snapshot_slice(1)

        assert slice_.text == "B\n"
        assert slice_.start_sequence == 1
        assert slice_.end_sequence == 2


class TestConcurrentAccess:
    """Tests for thread-safety of store operations."""

    def test_concurrent_append_and_snapshot(self):
        """Multiple threads append and snapshot; results are consistent."""
        store = TranscriptStore()
        barrier = threading.Barrier(4)
        results: list[tuple[int, int, str]] = []
        errors: list[Exception] = []

        def appender(start: int, count: int):
            try:
                barrier.wait()
                for i in range(start, start + count):
                    store.append("output", f"line{i}\n".encode())
            except Exception as e:
                errors.append(e)

        def snapshotter(thread_id: int, times: int):
            try:
                barrier.wait()
                for _ in range(times):
                    slice_ = store.snapshot_slice(0)
                    results.append((thread_id, slice_.end_sequence, slice_.text))
                    threading.Event().wait(0.001)  # yield
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=appender, args=(0, 50)),
            threading.Thread(target=appender, args=(50, 50)),
            threading.Thread(target=snapshotter, args=(0, 30)),
            threading.Thread(target=snapshotter, args=(1, 30)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors: {errors}"

        # Verify no gaps or duplicates in sequence numbers
        all_seqs = sorted(e.sequence for e in store.events)
        expected_seqs = list(range(len(store.events)))
        assert all_seqs == expected_seqs, "Sequence numbers have gaps or duplicates"

        # Each snapshot must be a coherent ordered prefix:
        # for snapshot with end_sequence N, its text == joined raw of events[:N]
        for _, end_seq, text in results:
            assert end_seq <= len(store.events)
            expected_text = b"".join(e.raw for e in store.events[:end_seq]).decode("utf-8", errors="replace")
            assert text == expected_text, f"Snapshot end={end_seq} text mismatch"


class TestSplitUtf8:
    """Tests for UTF-8 handling through snapshot_slice."""

    def test_split_utf8_decodes_correctly(self):
        """A UTF-8 character split across events decodes correctly."""
        store = TranscriptStore()
        # "café" in UTF-8: c=a3, a=a3, f=a3, é=c3 a9
        # Split é across two events
        store.append("output", b"caf\xc3")
        store.append("output", b"\xa9\n")
        slice_ = store.snapshot_slice(0)
        assert slice_.text == "café\n"

    def test_split_utf8_across_many_events(self):
        """Multiple split UTF-8 sequences across many events."""
        store = TranscriptStore()
        # "🔥" = f0 9f 94 a5 (4 bytes)
        store.append("output", b"\xf0")
        store.append("output", b"\x9f")
        store.append("output", b"\x94")
        store.append("output", b"\xa5\n")
        slice_ = store.snapshot_slice(0)
        assert slice_.text == "🔥\n"

    def test_incomplete_utf8_at_boundary(self):
        """Incomplete UTF-8 at end is replaced with replacement character."""
        store = TranscriptStore()
        # Incomplete é: c3 (missing a9)
        store.append("output", b"caf\xc3")
        slice_ = store.snapshot_slice(0)
        assert slice_.text == "caf\ufffd"


class TestLockProperties:
    """Tests for lock behavior."""

    def test_rlock_allows_reentrant_access(self):
        """RLock allows same thread to acquire multiple times."""
        store = TranscriptStore()
        store.append("output", b"A\n")
        # These all acquire the same lock from the same thread
        with store._lock:
            assert store.next_sequence == 1
            assert not store.is_empty
            slice_ = store.snapshot_slice(0)
            assert slice_.text == "A\n"

    def test_concurrent_next_sequence_is_consistent(self):
        """Concurrent reads of next_sequence return consistent values."""
        store = TranscriptStore()
        errors: list[Exception] = []

        def read_sequence(times: int):
            try:
                for _ in range(times):
                    val = store.next_sequence
                    assert val >= 0
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(10) as pool:
            futures = [pool.submit(read_sequence, 100) for _ in range(10)]
            for f in as_completed(futures):
                f.result()

        assert not errors
