# Terminal Context Blueprint

## Purpose

Make terminal context reliable enough that the assistant sees each captured
terminal event exactly once, in order. Terminal context is normally unbounded.
It is compacted only when the *complete model request* approaches the selected
provider context limit.

This document is the implementation contract. It supersedes any older
documentation that describes per-message line, character, or token trimming.

## User-visible contract

1. Every terminal event captured after TriageTTY starts belongs to an ordered,
   append-only session transcript.
2. A terminal event is included in model context once, and never deliberately
   duplicated in a later event payload.
3. A failed, cancelled, or rejected model request does not consume context.
   Its unacknowledged terminal events are resent on the next successful
   submission attempt.
4. TriageTTY does not trim a terminal message just because it is large.
5. When the complete request approaches the provider limit, TriageTTY performs
   one explicit compaction: drop the oldest two thirds of terminal transcript
   events and retain the newest third. It then continues normal append-only
   operation from that retained baseline.
6. The UI reports normal sends, retries, and compactions. It never describes a
   rough estimate as a hard provider guarantee.

"Exactly once" refers to the internal captured event stream and payload
construction. HTTP cannot guarantee exactly-once delivery after a network
failure: a server may receive a request whose response is lost. The application
must therefore distinguish *accepted locally* from *known received by server*.
For the initial version, acknowledge after a successful complete response and
prefer a duplicate retry over silently losing output.

## Non-goals for the first version

- Persisting the transcript across application restarts.
- Semantic summarization of discarded terminal output.
- Recovering output generated before the capture layer started.
- Perfectly representing a terminal's visual screen state. The canonical
  source is terminal I/O bytes, not a VTE screen snapshot.

## Architecture

```text
shell <-> PTY proxy <-> VTE terminal
             |
             +--> append-only TranscriptStore
                         |
                         +--> ContextSession -> ChatRequest
                                           |
                                           +--> acknowledge / retry / compact
```

### PTY proxy

The proxy owns two PTY links and forwards bytes in both directions:

- VTE <-> proxy: user input and terminal control data;
- proxy <-> shell: shell input and shell output.

It appends every byte received from the shell side to `TranscriptStore` before
forwarding it to VTE. Capture happens before VTE interprets escape sequences,
redraws rows, or evicts scrollback. Do not derive the canonical transcript from
`Vte.Terminal.get_text*()`.

The proxy can use only the Python standard library (`pty`, `os`, `selectors`,
`termios`, `fcntl`, `signal`, and `subprocess`). Keep it isolated from GTK and
covered by integration tests. It must forward window-size changes, EOF, child
exit, and terminal signals correctly.

The first implementation may record shell-to-terminal output only. If the
product definition includes echoed commands and typed input, record a distinct
input event stream too, rather than assuming every shell echoes input.

### TranscriptStore

`TranscriptStore` is a pure-Python, append-only in-memory log. It is the only
owner of captured terminal data.

Suggested event model:

```python
@dataclass(frozen=True)
class TerminalEvent:
    sequence: int
    stream: Literal["output", "input"]
    raw: bytes

@dataclass(frozen=True)
class TranscriptSlice:
    start_sequence: int
    end_sequence: int
    text: str
```

Responsibilities:

- assign monotonically increasing sequence numbers;
- retain raw bytes exactly as captured;
- decode a slice deterministically for the model payload;
- expose slices by sequence range, never by visual line comparison;
- compact only when asked by `ContextSession`;
- retain the starting sequence after compaction so the UI can report the
  discarded range.

The model-facing decoder may normalize carriage returns and ANSI control
sequences, but raw bytes remain available for debugging. Define and test this
normalization separately; it must not alter event boundaries or acknowledgement
state.

### ContextSession

`ContextSession` is another pure-Python state machine. It owns no GTK widgets,
VTE objects, or HTTP client.

State:

```text
transcript_start_sequence    # first event still retained after compaction
acknowledged_sequence        # highest event in a completed model turn
pending_request_end_sequence # end captured for the in-flight request, if any
history                      # stable chat messages since the current baseline
```

Rules:

1. On Send, atomically snapshot the store's current end sequence and obtain
   the corresponding event slice. Events captured after that snapshot belong
   to the next request, including events that arrive while the current request
   is being constructed or sent.
2. Build the request from the stable history plus all unacknowledged terminal
   events through that snapshot. Events arriving while the request is in flight
   belong to the next turn.
3. Do not mutate `acknowledged_sequence` or committed history yet.
4. On a successful model response, append the user request and assistant
   response to committed history, then advance `acknowledged_sequence` to the
   snapshot end.
5. On cancellation or failure, discard only the transient request object. Leave
   the acknowledgement cursor unchanged, so the next send includes the same
   terminal range.
6. Never put speculative or failed user messages into committed history.

This intentionally replaces `_last_transcript` snapshot-diffing and the current
practice of appending a user message before the request completes.

## Request construction and compaction

There is no per-message request budget.

Before submitting, build the complete candidate request and estimate its size
using the same configurable estimator. The provider context limit must be a
separate configuration value, for example `provider_context_limit_tokens`.
Reserve a configurable response allowance before deciding whether to compact.

```text
candidate = system + committed history + current user turn
if estimated(candidate) <= provider_limit - response_reserve:
    submit candidate unchanged
else:
    compact once, rebuild, submit rebuilt candidate
```

### Compaction operation

When compaction is required:

1. Consider all terminal events retained in `TranscriptStore`, including
   acknowledged events represented by historical user messages.
2. Drop the oldest two thirds by byte/event position and retain the newest one
   third. Do not trim each terminal message independently.
3. Rebase the conversation into a new stable baseline:
   - retain the system prompt;
   - replace old terminal-bearing user history with one baseline user message
     containing the retained terminal third and a clear marker that earlier
     terminal output was discarded for context capacity;
   - retain only conversation messages that fit after that baseline, preferring
     the newest complete user/assistant turns;
   - include the new question and any newly captured, unacknowledged events.
4. Set `transcript_start_sequence` to the first retained event.
5. Continue appending new events without routine trimming.

Compaction deliberately invalidates the prompt cache once because the stable
prefix changes. The rebuilt baseline then remains stable, allowing later turns
to benefit from caching again.

If the retained third plus the system prompt, question, and response reserve
still cannot fit, retain less than one third only as necessary and report that
fact explicitly. Do not send a request that knowingly exceeds the configured
provider limit.

## Delivery semantics

The HTTP client does not provide a delivery receipt. Treat a completed response
as the initial acknowledgement boundary:

- response received: commit transcript cursor and history;
- connection error, timeout, malformed response, or cancellation: do not
  advance the cursor;
- if the server processed a request but the response was lost, the next retry
  may duplicate the request at the provider. This is safer than losing terminal
  evidence and is visible in the UI as a retry.

## UI behavior

The Context panel should show:

- retained terminal sequence range;
- event/byte count and approximate request tokens;
- unacknowledged range included in the pending request;
- whether this send is a retry;
- a durable compaction notice: `Discarded terminal events 1–800; retained
  801–1200 because the provider context limit was reached.`

Do not show a hidden context checkbox. If context is an invariant of the
product, make the behavior explicit in copy rather than pretending it is an
optional bounded snapshot.

## Proposed module boundaries

Repository root: `/home/nick/ServerData/repos/triagetty`. All application
source lives under its existing `src/triagetty/` package directory; do not
create a top-level `terminal/`, a top-level `triagetty/`, or `src/terminal/`.

```text
/home/nick/ServerData/repos/triagetty/src/triagetty/terminal/pty_proxy.py
    GTK-independent PTY forwarding/capture
/home/nick/ServerData/repos/triagetty/src/triagetty/terminal/transcript_store.py
    append-only events and deterministic slices
/home/nick/ServerData/repos/triagetty/src/triagetty/llm/context_session.py
    acknowledgement, request state, compaction
/home/nick/ServerData/repos/triagetty/src/triagetty/llm/prompt.py
    pure serialization of already-selected context
/home/nick/ServerData/repos/triagetty/src/triagetty/window.py
    GTK wiring only
```

`TerminalPane` should own the VTE widget only. It may receive a proxy endpoint,
but must not own transcript policy or inspect scrollback for canonical context.

## Implementation phases for Hermes

The settled Phase 3 design and its deliberately small implementation tasks are
in [Phase 3 implementation playbook](phase3-pty-proxy-implementation.md).
That playbook is authoritative for proxy process boundaries, IPC transport,
threading, and task order.

### Phase 0: lock the contract with tests

Phase 0 establishes test scaffolding and behavior documentation. It does not
claim the production contract is locked until the expected-failure tests have
become ordinary passing tests.

Use two deliberately different kinds of tests:

- **Production-seam tests** exercise the actual `TriageWindow` submission and
  completion workflow with fake GTK controls, a fake terminal source, and a
  patched request builder. They capture the payload passed to `build_request()`
  rather than reimplementing production logic in a mock window.
- **Pure contract examples** use small `TranscriptStore` / `ContextSession`
  fixtures only as executable documentation of the target state machine. They
  must be clearly named as examples and never treated as evidence that the
  production implementation is correct.

Production-seam tests must be fully deterministic:

- replace `threading.Thread` with a fake whose `start()` records work but never
  runs it;
- never contact an HTTP endpoint or start a real background thread;
- explicitly invoke `_finish_request()` once to model success, failure, or
  cancellation;
- inspect captured outbound payloads after each real `_send_question()` call.

Current behavioral violations are strict expected failures
(`pytest.mark.xfail(strict=True)`) that assert the desired result:

- a failed or cancelled request resends the same terminal range;
- normal turns never trim terminal events;
- history always contains complete user/assistant pairs.

Each expected failure must reach the assertion that expresses the desired
behavior. Do not make an expected-failure test fail on an unrelated setup
assertion. When a behavior is implemented, remove its `xfail` marker and retain
the test as an ordinary passing regression test.

Future-stage module-existence checks are allowed as clearly labeled deferred
architecture markers, but are not behavioral contract tests. Replace each
marker immediately with behavior tests when its module is introduced. Use the
module paths in [Proposed module boundaries](#proposed-module-boundaries):
`triagetty.terminal.transcript_store`, `triagetty.llm.context_session`, and
`triagetty.terminal.pty_proxy`.

### Phase 1: introduce pure state objects

Implement `TranscriptStore` and `ContextSession` with no GTK/VTE dependency.
Keep the existing VTE snapshot source temporarily behind a test-only adapter so
the state machine can be proven independently before changing process wiring.
Convert the Phase 0 retry and history expected failures into ordinary passing
tests, and replace the deferred `ContextSession` marker with tests for sequence
acknowledgement, rollback, compaction, and complete history pairs.

### Phase 2: replace snapshot delta handling

Remove `_last_transcript`, `_compute_transcript_delta`, and the direct private
call to `_get_full_transcript()` from `TriageWindow`. Wire sends, success,
failure, and cancellation through `ContextSession`.

**Scope change**: The polling-based VTE adapter is removed entirely. A pure
raw-byte sink `TerminalOutputCapturer.record_output(raw: bytes)` is introduced
so that Phase 3's PTY proxy has a documented target. No live capture occurs in
Phase 2; actual terminal I/O boundary capture is deferred to Phase 3.

Replace the deferred event-model marker with tests proving that identical bytes
in separate `TerminalEvent` values are retained as separate ordered events.

Add tests proving:
- exact raw-byte preservation (no line splitting, no padding added/removed);
- blank lines and trailing-newline absence are preserved;
- UTF-8 multi-byte characters split across chunks decode correctly
  (join raw bytes before decoding);
- zero-length chunks are not output events: the PTY proxy interprets `b""` as
  EOF/closure and must not call the sink with it. The sink may defensively
  ignore such a value;
- errors are never swallowed;
- ordered interleaving is maintained.

### Phase 3: add PTY capture

Implement the PTY proxy and use its `TranscriptStore` as the live source.
Test with a real child shell producing output exceeding VTE's scrollback limit,
carriage-return progress output, ANSI color output, and a long-running command.
Replace the deferred PTY marker with a real integration test; it must prove
that captured model context remains complete after VTE scrollback has evicted
the earliest displayed rows.

**Concurrency requirement (hard)**: The PTY proxy runs on its own I/O thread
and appends events to `TranscriptStore`. The GTK main thread slices the store
during request construction. Concurrent access must not race, and the end
sequence snapshot plus its slice must be atomic so the request boundary is
unambiguous.

The implementation must enforce one of the following:
(a) **Marshall all appends to the main thread** — the proxy calls
    `GLib.idle_add(capturer.record_output, raw)` so all mutations happen on
    the GTK thread; or
(b) **Explicit locking** — `TranscriptStore` guards `append()` and
    an atomic `snapshot_slice()` operation with a mutex.

No other solution is acceptable. A race between append and slice corrupts the
payload and violates the "exactly once" contract.

### Phase 4: remove obsolete controls and documentation

Remove per-message line/character budget behavior, stale configuration fields,
and stale documentation. Document the provider-limit compaction policy and its
one-time cache reset.

## Acceptance tests

The feature is complete only when these hold:

1. A child produces more output than VTE scrollback can display; the model
   payload still contains the full captured output.
2. Send, cancel, then send again without new output; the second payload contains
   the same terminal range.
3. Send, induce a provider error, then retry; the retry contains the same range.
4. Output produced during an in-flight request is absent from that request and
   present exactly once in the next successful request.
5. Repeated identical lines are preserved as separate ordered events.
6. Under the provider threshold, no terminal text is removed.
7. At the threshold, one compaction retains the newest third and reports it.
8. After compaction, several normal turns add output without another compaction
   until the full request again approaches the threshold.
9. All pure context tests run without GTK, VTE, a display server, or network.
