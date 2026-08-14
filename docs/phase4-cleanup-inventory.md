# Phase 4 cleanup inventory

Task 1 records stale references found under `README.md`, `docs`, `src`, and
`tests`. Each entry has one disposition. References in the Phase 3 and Phase 4
playbooks are retained because they describe implementation history or this
cleanup procedure, not current product behavior.

| Match | Location | Decision | Reason |
| --- | --- | --- | --- |
| bounded snapshot of recent terminal output | `README.md:5` | rewrite | Current context is the PTY-captured ordered transcript. |
| context line slider | `README.md:82` | remove | Obsolete UI control. |
| Include recent terminal context / bounded snapshot | `README.md:90` | remove | Context is invariant, not optional. |
| line/character limits and bounded snapshot | `docs/architecture.md:46,52` | rewrite | Architecture must describe PTY capture and whole-request compaction. |
| optional bounded snapshot | `docs/architecture.md:81` | rewrite | Context sharing is no longer an optional toggle. |
| bounded snapshot of recent terminal text | `src/triagetty/config.py:15` | rewrite | Default prompt must describe ordered captured context. |
| include_context checkbutton and references | `src/triagetty/window.py:122` | remove | Obsolete hidden context control. |
| recent_transcript / _get_full_transcript | `src/triagetty/terminal/pane.py` and direct tests | remove | No supported caller remains; canonical context uses CaptureServer. |
| bound_transcript | `src/triagetty/terminal/transcript.py` and direct tests | remove | No production caller remains; normal turns are untrimmed. |
| max_context_tokens | `src/triagetty/window.py`, `src/triagetty/config.py`, tests | retain | Overall provider-context compaction threshold. |
| provider context / compaction | `src`, `docs`, `tests` | retain | Current whole-request compaction contract. |
| _get_full_transcript in test fakes | `tests/test_two_success_turns.py`, Phase 0 setup | remove with obsolete fake | These fakes no longer provide model context. |
