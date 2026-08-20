# Phase 3 implementation playbook: lossless PTY capture

## Status and authority

This document is the implementation plan for Phase 3 of the Terminal Context
Blueprint. It makes the implementation decisions that the blueprint leaves
open. Follow it in order. Do not substitute VTE scrollback, polling, a
background GTK call, a different IPC transport, or a different concurrency
model without an explicit revision to this document.

Phase 2 intentionally removed live capture. Phase 3 restores it. A build is
not complete until a real shell is launched through the proxy and its output
reaches `TranscriptStore` without using a VTE text-reading API.

## Repository map and mandatory paths

The repository root is **`/home/nick/ServerData/repos/TroubleShell`**. This is a
standard `src`-layout Python project. The one and only importable application
package is:

```text
/home/nick/ServerData/repos/TroubleShell/src/troubleshell/
```

Every path in this playbook is relative to that package directory unless it is
written as an absolute path. Therefore the required Phase 3 files are exactly:

```text
/home/nick/ServerData/repos/TroubleShell/src/troubleshell/terminal/transcript_store.py
/home/nick/ServerData/repos/TroubleShell/src/troubleshell/terminal/output_capturer.py
/home/nick/ServerData/repos/TroubleShell/src/troubleshell/terminal/capture_server.py
/home/nick/ServerData/repos/TroubleShell/src/troubleshell/terminal/pty_proxy.py
/home/nick/ServerData/repos/TroubleShell/src/troubleshell/terminal/pane.py
/home/nick/ServerData/repos/TroubleShell/src/troubleshell/llm/context_session.py
/home/nick/ServerData/repos/TroubleShell/src/troubleshell/window.py
```

Tests belong only in:

```text
/home/nick/ServerData/repos/TroubleShell/tests/
```

Before each task, run `pwd` and `test -f pyproject.toml`; both must identify
`/home/nick/ServerData/repos/TroubleShell` as the current repository root. Then
run `test -d src/troubleshell/terminal`. It already exists.

**Never create** `/home/nick/ServerData/repos/TroubleShell/terminal/`,
`/home/nick/ServerData/repos/TroubleShell/troubleshell/`, or
`/home/nick/ServerData/repos/TroubleShell/src/terminal/`. They are not Python
package locations in this project. If any such directory exists, stop and
report it; do not create a competing copy of a module.

## Fixed design

Use a **parent capture server + proxy process** design.

```text
GTK / application process                         proxy process
─────────────────────────                         ─────────────
CaptureServer reader thread                        stdin/stdout: VTE PTY
  |                                                shell_master: real shell PTY
  +-> TerminalOutputCapturer.record_output(raw)      |
  +-> locked TranscriptStore                          +-- shell output read
                                                        1. send raw to CaptureServer
                                                        2. write same raw to stdout (VTE)
                                                        3. never inspect/normalize raw
VTE <──────────── proxy stdout                  shell ───> proxy shell_master
VTE ────────────> proxy stdin                   VTE input -> proxy -> shell_master
```

The VTE child process is the proxy, not the configured shell. The proxy starts
the configured shell under a second PTY. The proxy and application are separate
processes: the proxy must never import GTK, `TranscriptStore`, or
`TerminalOutputCapturer`.

### IPC transport: Unix `SOCK_SEQPACKET`

Use an AF_UNIX `SOCK_SEQPACKET` socket at a unique path inside a temporary
directory owned by the application. The parent listens; the proxy receives the
socket path as an argument and connects before it starts the shell.

Why this exact transport:

- TroubleShell is Linux-only.
- `SOCK_SEQPACKET` preserves one `send()` call as one `recv()` message, so a
  proxy-read chunk remains one `TerminalEvent`.
- A filesystem socket path avoids uncertain file-descriptor inheritance through
  VTE/GLib process spawning.
- There is one proxy producer, so no interleaving can occur on this channel.

The proxy reads at most `64 * 1024` bytes from the shell PTY per read, and sends
that one non-empty chunk as one `SOCK_SEQPACKET` packet. The parent receives
with a buffer at least that size. Do not use a stream socket, newline framing,
JSON, base64, or text encoding for capture data.

If the capture connection cannot be made, the proxy must write a concise error
to stderr and exit nonzero **before starting the shell**. It must never run a
shell whose output is displayed but not captured. If the connection breaks
after startup, terminate the shell process group, report failure on stderr, and
exit nonzero. Loss is never silently accepted.

### Concurrency: explicit locking

`TranscriptStore` is shared by the capture-server reader thread (writer) and
the GTK main thread (request builder). Use `threading.RLock` inside
`TranscriptStore`; do not marshal capture through `GLib.idle_add`.

All reads and writes of `events` and `_next_sequence` happen under that lock.
Implement one public atomic operation:

```python
def snapshot_slice(self, start_sequence: int) -> TranscriptSlice:
    """Atomically capture current end and return [start_sequence, end)."""
```

It must acquire the lock once, save `_next_sequence` as `end_sequence`, join
the matching raw bytes, decode once, and return a `TranscriptSlice` with that
end. An event appended after the lock is released belongs to the next request.

`ContextSession` must use this method on Send. It stores the returned end as
`pending_request_end_sequence` and builds the user message from exactly this
slice. Do not separately read `next_sequence` and later call `get_slice()`.

### Raw-byte rules

- `TerminalOutputCapturer.record_output(raw)` receives and appends a non-empty
  `bytes` object unchanged.
- `b""` means EOF from a read. The proxy handles EOF and must not send it to
  the capture server; the sink defensively ignores it.
- Blank lines, CR, ANSI bytes, missing trailing newlines, repeated chunks, and
  UTF-8 sequences split across chunks are retained in `TerminalEvent.raw`.
- `TranscriptStore.get_slice()` and `snapshot_slice()` join raw bytes first and
  decode once with `errors="replace"`. No ANSI or CR normalization in Phase 3.
- A model-facing visual rendering policy may be added later as a separate pure
  function. It must never mutate events or acknowledgement positions.

### PTY behavior

The proxy is a normal executable Python module:

```text
python -m troubleshell.terminal.pty_proxy --capture-socket PATH --shell SHELL
```

The parent launches that command through VTE's existing `spawn_async` path.
Use the same interpreter (`sys.executable`) that launched TroubleShell so the
installed package is available.

Inside the proxy:

1. Connect to the capture socket.
2. Create a shell master/slave pair with `pty.openpty()`.
3. Start the shell with stdin/stdout/stderr connected to the slave.
4. In the shell child pre-exec function: call `os.setsid()` then
   `fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)` so interactive job control
   works. Close inherited unrelated descriptors.
5. Close the proxy's slave FD after spawning.
6. Use `selectors.DefaultSelector` to relay proxy stdin and shell master.
7. On shell-master output, capture it first, then forward the identical bytes
   to proxy stdout (which VTE displays).
8. On proxy stdin input, write bytes unchanged to shell master. Input capture
   is out of scope; do not create `input` events in Phase 3.
9. On `SIGWINCH`, read the current window size from proxy stdin using
   `TIOCGWINSZ`, apply it to shell master using `TIOCSWINSZ`, and let the kernel
   notify the shell foreground process group. Apply the size once at startup.
10. On proxy-stdin EOF, shell exit, shell-master `EIO`/EOF, or VTE stdout
    write failure: close descriptors, terminate the shell process group if it
    still exists, wait/reap it, close the capture socket, and exit.

`os.write()` can be partial. Implement `write_all(fd, data)` and use it for
both VTE output and shell-master input. For the sequence-packet socket, use one
blocking `send(data)` and treat a short send or exception as capture failure;
the packet is at most 64 KiB.

## Files and exact responsibilities

| File | Responsibility | Must not do |
| --- | --- | --- |
| `/home/nick/ServerData/repos/TroubleShell/src/troubleshell/terminal/transcript_store.py` | locked append, deterministic slices, atomic snapshot slice | GTK, sockets, PTY, prompt policy |
| `/home/nick/ServerData/repos/TroubleShell/src/troubleshell/terminal/output_capturer.py` | append an exact non-empty raw output chunk | transform bytes, thread management |
| `/home/nick/ServerData/repos/TroubleShell/src/troubleshell/terminal/capture_server.py` | parent-side socket lifecycle and reader thread | GTK access, prompt/session policy |
| `/home/nick/ServerData/repos/TroubleShell/src/troubleshell/terminal/pty_proxy.py` | proxy CLI, shell PTY, byte relay, capture packet sends | import GTK or app state |
| `/home/nick/ServerData/repos/TroubleShell/src/troubleshell/terminal/pane.py` | VTE setup and spawn proxy argv | read VTE text as transcript |
| `/home/nick/ServerData/repos/TroubleShell/src/troubleshell/window.py` | construct/start/stop capture server; construct session; UI only | poll/read VTE transcript |
| `/home/nick/ServerData/repos/TroubleShell/src/troubleshell/llm/context_session.py` | atomic Send snapshot and acknowledgement lifecycle | thread synchronization details |

## Implementation tasks

Do these in order. Each task must include the stated tests before starting the
next task. Run the full test suite after every numbered section. **A task may
change only its listed production files and its listed tests.** Do not "clean
up" nearby APIs, compaction, prompt formatting, configuration, documentation,
or later-task files while completing it. If a task genuinely cannot proceed,
stop and report the exact blocking file, line, failing test, and proposed
minimal change.

### 1. Lock the store and make request snapshots atomic

**Complete. Do not reopen this task during Phase 3.** Its regression tests are
`tests/test_transcript_store_concurrency.py`.

1. Add a private `RLock` field to `TranscriptStore` using
   `field(default_factory=threading.RLock, init=False, repr=False)`.
2. Put `append()`, `get_slice()`, `next_sequence`, and `is_empty` under the
   lock. Never expose a mutable event list for production mutation; tests may
   inspect the list after their worker has stopped.
3. Add `snapshot_slice(start_sequence)` exactly as described above.
4. Do not change event sequence numbering or raw-byte decode behavior.
5. Add `tests/test_transcript_store_concurrency.py`:
   - append `A`; call `snapshot_slice(0)`; append `B`; assert snapshot is only
     `A` and its end is 1;
   - use a `threading.Barrier` to append while another thread snapshots; assert
     every result is a valid prefix with no duplicate/missing sequence;
   - test split UTF-8 still decodes correctly through `snapshot_slice`.

### 2. Teach `ContextSession` to use one snapshot result

**Complete. Do not reopen this task during Phase 3.** Its regression tests are
`tests/test_request_slice_atomic.py`. A send calls `request_slice()` exactly
once. If compaction changes the retained start,
`rebase_pending_slice_after_compaction()` may change only the pending slice's
start; it must retain its original end sequence. It must never call
`snapshot_slice()` or read `next_sequence`.

1. Add a method such as `snapshot_payload_for_send()` that calls
   `transcript.snapshot_slice(self.acknowledged_sequence)` exactly once.
2. Set `pending_request_end_sequence` from the returned slice end.
3. Keep the existing `snapshot_for_send(user_message)` as the final commit of
   the exact outbound message, or rename/restructure it only if all callers and
   tests stay clear. Do not let a second store read change the end boundary.
4. Add a unit test: append A, take payload snapshot, append B, build/commit the
   request; assert A is in the current turn and B remains unacknowledged for
   the next turn.

### 3. Add the parent-side capture server

**Allowed production file:**

```text
/home/nick/ServerData/repos/TroubleShell/src/troubleshell/terminal/capture_server.py  (new)
```

**Allowed test file:**

```text
/home/nick/ServerData/repos/TroubleShell/tests/test_capture_server.py  (new)
```

Do not modify `window.py`, `pane.py`, `pty_proxy.py`, `ContextSession`,
`TranscriptStore`, or any existing tests in this task. This task proves parent
IPC only; nothing in the GUI is wired yet.

1. Create `/home/nick/ServerData/repos/TroubleShell/src/troubleshell/terminal/capture_server.py` with a GTK-free `CaptureServer` class.
2. Constructor accepts a `TerminalOutputCapturer` and an optional temporary
   directory parent for tests.
3. `start()` creates a `tempfile.TemporaryDirectory`, binds a unique Unix
   `SOCK_SEQPACKET` listener, starts exactly one daemon reader thread, and
   returns the socket path.
4. The reader accepts exactly one proxy connection, then repeatedly `recv(65536)`.
   For every non-empty packet, call `capturer.record_output(packet)` directly.
5. EOF ends the reader cleanly. Unexpected socket errors are stored as a public
   `failure: Exception | None`, never swallowed. The parent must be able to
   check `ensure_healthy()` and receive a useful exception.
6. `stop()` closes connection/listener, joins the reader with a short timeout,
   removes the temporary directory, and is safe to call more than once.
7. Add `tests/test_capture_server.py` using a real client Unix seqpacket socket:
   - exact bytes arrive as one event;
   - two identical packets become two ordered events;
   - a split UTF-8 character across two packets decodes in a slice;
   - disconnect closes cleanly;
   - server socket failure becomes observable through `ensure_healthy()`.
8. The test must wait on an explicit server test hook or a bounded polling
   helper before inspecting `TranscriptStore`; it must never use `sleep()` as
   synchronization. Tests must call `stop()` in `finally` or fixture teardown.
9. Task-3 report must include only: changed paths, focused-test result, and
   full-suite result. Stop after that report.

### 4. Implement proxy mechanics without GTK wiring

**Allowed production file:**

```text
/home/nick/ServerData/repos/TroubleShell/src/troubleshell/terminal/pty_proxy.py  (new)
```

**Allowed test file:**

```text
/home/nick/ServerData/repos/TroubleShell/tests/test_pty_proxy_unit.py  (new)
```

Do not wire the proxy to VTE, modify `TerminalPane`, add a capture server, or
write subprocess integration tests in this task. This task is only pure proxy
helpers and an importable CLI/relay implementation.

1. Create `/home/nick/ServerData/repos/TroubleShell/src/troubleshell/terminal/pty_proxy.py`; it must be importable with no GTK imports.
2. Add `main(argv: Sequence[str] | None = None) -> int` using `argparse` for
   `--capture-socket` and `--shell`.
3. Implement small pure helpers first and test them:
   - `write_all(fd, data)` handles partial writes;
   - `copy_winsize(source_fd, destination_fd)` copies the complete winsize
     structure;
   - `spawn_shell(shell)` returns shell master FD and `Popen` object with the
     session/controlling-terminal setup.
4. Implement `run_proxy(capture_socket_path, shell)` with the selector loop.
   Capture shell output before writing it to stdout. Do not decode it.
5. Emit proxy diagnostics only to stderr, never to the capture socket.
6. Add `tests/test_pty_proxy_unit.py` for helpers, including partial writes and
   a monkeypatched capture send failure that terminates the relay.
7. Test the module imports with no `gi` module available. Test `main()` argument
   validation without starting a real shell. Stop after the focused and full
   suites pass.

### 5. Add proxy integration tests with real children

**Allowed files:**

```text
/home/nick/ServerData/repos/TroubleShell/tests/test_pty_proxy_integration.py  (new)
```

If a narrowly necessary test seam is missing in `capture_server.py` or
`pty_proxy.py`, stop and request approval before modifying it. Do not touch GTK
wiring in this task.

1. Add `tests/test_pty_proxy_integration.py`. It starts `CaptureServer` and
   invokes the proxy in a subprocess with pipes for the proxy's stdin/stdout.
2. Use `/bin/sh -c` only through a temporary executable wrapper script, because
   the proxy interface deliberately accepts a shell executable path. Make the
   wrapper deterministic and delete it through pytest's `tmp_path` fixture.
3. Test a known byte sequence containing blank lines, CR, ANSI color bytes,
   no final newline, repeated text, and split UTF-8. Assert the concatenated
   captured event bytes exactly equal the expected shell output, and proxy
   stdout equals those same bytes.
4. Test at least 10,000 numbered lines. Configure a small VTE scrollback only
   in the later GUI wiring test; here assert the raw captured output has every
   line in order.
5. Test clean shell exit and VTE-input EOF. Assert the proxy exits and the
   capture server reports no failure.
6. Test a simulated capture-server disconnect. Assert the proxy exits nonzero
   rather than continuing to display uncaptured shell output.

### 6. Wire proxy spawning into `TerminalPane`

**Allowed production file:**

```text
/home/nick/ServerData/repos/TroubleShell/src/troubleshell/terminal/pane.py
```

**Allowed test file:**

```text
/home/nick/ServerData/repos/TroubleShell/tests/test_terminal_pane.py
```

Do not construct a `CaptureServer` here; that belongs to Task 7. Do not change
the application window or context session.

1. Change `TerminalPane.__init__` to accept `capture_socket_path: str` and
   save it. Do not add a transcript-reading method.
2. Change `spawn()` to call VTE `spawn_async` with:
   ```python
   [sys.executable, "-m", "troubleshell.terminal.pty_proxy",
    "--capture-socket", capture_socket_path, "--shell", self.shell]
   ```
3. Update fake VTE tests to assert that argv launches the proxy and contains
   the configured shell and capture path.
4. Mark `recent_transcript()` and `_get_full_transcript()` deprecated or remove
   them only after updating their existing callers/tests. They must have zero
   callers in the canonical context path.

### 7. Wire lifecycle in `TroubleWindow`

**Allowed production file:**

```text
/home/nick/ServerData/repos/TroubleShell/src/troubleshell/window.py
```

**Allowed test file:**

```text
/home/nick/ServerData/repos/TroubleShell/tests/test_phase0_xfail.py
```

No proxy protocol changes, no store/session changes, and no documentation
changes belong here. Make the smallest lifecycle wiring change only.

1. Construct `TranscriptStore`, `TerminalOutputCapturer`, and `CaptureServer`
   before constructing/spawning `TerminalPane`.
2. Call `capture_server.start()` once and give its returned path to
   `TerminalPane`.
3. Ensure application/window shutdown calls `capture_server.stop()`. Connect a
   GTK close/destroy signal rather than relying on object finalization.
4. Before `_send_question()` snapshots context, call
   `capture_server.ensure_healthy()`. If it fails, show a clear UI error and do
   not send a request with incomplete terminal evidence.
5. Keep `window.py` free of VTE transcript reads, polling, and byte transforms.
6. Update production-seam fakes: they may append directly to the store, but
   must include a healthy fake capture server. Do not reintroduce a fake VTE
   text snapshot.

### 8. Replace the Phase 3 marker with end-to-end acceptance coverage

**Allowed files:** the new or existing Phase 3 integration tests and the one
deferred marker in `tests/test_phase0_xfail.py`. Do not alter production code
unless an acceptance test identifies a specific defect; if it does, stop and
report the defect before fixing it.

1. Remove the strict Phase 3 xfail only when the real integration test exists.
2. Add a test that starts a VTE terminal through the proxy with a deliberately
   tiny scrollback setting, runs a child that emits more lines than that setting,
   and verifies the captured `TranscriptStore` slice contains first, middle,
   and last lines. Skip only when GTK/VTE is unavailable; do not replace it
   with a source-text inspection.
3. Add a request-boundary integration test: while a request snapshot is held,
   make the proxy emit B after A; first request has A only; after success,
   second has B exactly once.
4. Run `.venv/bin/python3 -m pytest tests/ -q` and record the complete result.

## Phase 3 exit checklist

- [ ] No production context path calls `Vte.Terminal.get_text*()`.
- [ ] VTE launches the proxy, and the proxy launches the configured shell.
- [ ] Shell output is sent to capture IPC before identical bytes reach VTE.
- [ ] Parent receives capture packets and appends them unchanged to a locked
      `TranscriptStore`.
- [ ] Snapshot-and-slice is atomic; output after snapshot is sent next turn.
- [ ] Proxy does not continue if capture is unavailable or disconnected.
- [ ] Window-size changes, shell exit, input EOF, and cleanup work.
- [ ] Existing retry/history/compaction guarantees still pass.
- [ ] The former Phase 3 xfail is replaced by real behavior coverage.
- [ ] Entire suite passes without unexpected failures.

## Out of scope

- Capturing input events.
- Sanitizing ANSI/CR output for model presentation.
- Persisting transcript events.
- Reworking compaction policy beyond adapting it to `snapshot_slice()`.
- Sending a request when capture health is unknown or failed.
