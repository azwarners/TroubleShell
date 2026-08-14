# Phase 4 implementation playbook: remove obsolete context behavior

## Purpose

Phase 4 begins only after Phase 3 is accepted. It removes code and claims left
by the old bounded VTE-snapshot design. It must not redesign PTY capture,
acknowledgement, compaction, or provider integration.

## Repository map

Repository root: `/home/nick/ServerData/repos/triagetty`.

The sole application package is
`/home/nick/ServerData/repos/triagetty/src/triagetty/`. Tests are only under
`/home/nick/ServerData/repos/triagetty/tests/`; docs are only under
`/home/nick/ServerData/repos/triagetty/docs/`. Never create top-level
`terminal/`, top-level `triagetty/`, or `src/terminal/`.

Before every task, run `pwd`, `test -f pyproject.toml`, and
`test -d src/triagetty/terminal`. Work only from the repository root.

## Final product contract

- Canonical context comes only from PTY-captured raw bytes.
- Normal sends have no line, character, or per-message token budget.
- Terminal text is removed only by explicit whole-request compaction near the
  overall provider context limit.
- No UI control or documentation presents context as an optional bounded recent
  snapshot.
- Any display-only helper must never feed model context and must say so.

## Rules for every task

1. Complete one task only; run focused tests, then the full suite, then stop.
2. Change only the files listed for that task.
3. Before deleting code, use `rg` to prove callers/tests can be removed or
   migrated safely.
4. Never add VTE text reading, a fallback snapshot adapter, or a new request
   budget during cleanup.

## Task 1: inventory stale references

**Only allowed file:**
`/home/nick/ServerData/repos/triagetty/docs/phase4-cleanup-inventory.md` (new).

Run searches for `bounded snapshot`, `recent terminal`, `context.line`,
`context.character`, `line slider`, `Include recent`, `recent_transcript`,
`_get_full_transcript`, `bound_transcript`, `max_context_tokens`, `provider
context`, and `compaction` across `README.md docs src tests`. List every match
with exactly one decision: `remove`, `rewrite`, or `retain for display only`.
Every retained result must explain why it is outside the model-context path. Do
not change production code or user-facing docs in this task.

## Task 2: remove obsolete GTK context controls

**Only allowed files:**

- `/home/nick/ServerData/repos/triagetty/src/triagetty/window.py`
- `/home/nick/ServerData/repos/triagetty/tests/test_phase0_xfail.py`

Remove the hidden `include_context` checkbutton and every reference to it. Do
not alter capture health, send, cancellation, atomic snapshots, compaction, or
proxy lifecycle. Add one narrow test proving context always comes from
`ContextSession`; no condition can disable it. Require no production match for
`include_context` or `Include recent` in `src` and `tests`.

## Task 3: retire VTE transcript reading from `TerminalPane`

**Only allowed files:**

- `/home/nick/ServerData/repos/triagetty/src/triagetty/terminal/pane.py`
- `/home/nick/ServerData/repos/triagetty/tests/test_terminal_pane.py`

Use Task 1's inventory to determine whether `recent_transcript()` and
`_get_full_transcript()` have a supported display-only caller. If none remains,
remove both methods, their VTE text-range support code, and only direct tests.
Keep insertion and proxy-spawn tests. If a display-only caller remains, rename
the API to make `display_` explicit and document “Never used for model
context.” No model-context path may call VTE text reading.

## Task 4: remove bounded-transcript policy only when unused

**Only allowed files:**

- `/home/nick/ServerData/repos/triagetty/src/triagetty/terminal/transcript.py`
- `/home/nick/ServerData/repos/triagetty/tests/test_transcript.py`

If Task 1 proves `bound_transcript()` is unused, remove it and only its direct
tests. Retain `estimate_tokens()` for whole-request compaction. Decide
`normalize_transcript()` only from actual callers. Do not introduce a new
truncation function.

## Task 5: correct configuration and default-prompt wording

**Only allowed files:**

- `/home/nick/ServerData/repos/triagetty/src/triagetty/config.py`
- `/home/nick/ServerData/repos/triagetty/tests/test_config.py`

Replace stale wording such as “bounded snapshot” with accurate wording:
captured terminal output is ordered context and is compacted only near the
overall provider context limit. Keep `max_context_tokens` as the overall limit;
do not rename it without a migration task. Remove legacy line/character-limit
config only if Task 1 finds it. Add a focused assertion that the default prompt
does not claim a bounded/recent snapshot.

## Task 6: rewrite user-facing documentation

**Only allowed files:**

- `/home/nick/ServerData/repos/triagetty/README.md`
- `/home/nick/ServerData/repos/triagetty/docs/architecture.md`
- `/home/nick/ServerData/repos/triagetty/docs/terminal-context-blueprint.md`

README must say context is captured from shell output rather than VTE
scrollback; normal turns are untrimmed; compaction is only near the provider
limit. Remove slider/toggle instructions and old `context_line_limit` /
`context_character_limit` TOML examples. Architecture must show
`shell -> PTY proxy -> capture server -> TranscriptStore -> ContextSession` and
VTE as display recipient of the same proxy bytes. Preserve the safety promise:
commands are inserted only, never executed. Do not alter packaging,
threat-model, licensing, or version information.

## Task 7: add stale-claim regression coverage

**Only allowed file:**
`/home/nick/ServerData/repos/triagetty/tests/test_context_documentation.py`
(new).

Read `README.md`, `docs/architecture.md`, and `config.DEFAULT_SYSTEM_PROMPT`.
Assert they do not contain `bounded snapshot`, `context_line_limit`,
`context_character_limit`, or `Include recent terminal context`. Assert README
and architecture mention `PTY proxy` and `compaction`. This checks product
claims only; it does not replace Phase 3 integration coverage.

## Task 8: final acceptance and deletion audit

**Only allowed files:** tests, only if a focused test correction is required.

Search `README.md docs src tests` for `context_line_limit`,
`context_character_limit`, `Include recent terminal context`, and `bounded
snapshot`; it must find no obsolete product claim. Run the full test suite and
`git diff --check`. Confirm Phase 3 acceptance tests still pass. Report changed
paths, exact results, each retained display helper, and whether an untracked
duplicate package directory exists.

## Exit checklist

- [ ] No UI context toggle or slider remains.
- [ ] No model-context path reads VTE text or a bounded-transcript helper.
- [ ] No per-message line/character/token trimming remains.
- [ ] `max_context_tokens` is only an overall-request compaction threshold.
- [ ] README, architecture, and default prompt accurately describe PTY capture.
- [ ] Full suite passes without unexpected failures.
