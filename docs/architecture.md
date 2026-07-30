# TriageTTY architecture

TriageTTY is a small, standalone GTK 4 application. Its architecture is intentionally direct: a VTE terminal, a chat pane, a deterministic prompt builder, one provider client, and pure parsing/rendering helpers. There are no agent, tool, plugin, workflow, or orchestration layers.

## Runtime data flow

```text
User types in VTE
        |
        v
TerminalPane -- on submit only --> bounded transcript
        |                                  |
        +--------------------------> prompt builder
                                           |
                                    ChatRequest
                                           |
                                           v
                         OpenAI-compatible /chat/completions
                                           |
                                      ChatResponse
                                           |
                                           v
                         fenced-block parser -> GTK renderer
                                           |
                         prose / command cards / errors
                                           |
                            Insert -> VTE input only
```

## Application boundary

`window.py` is the desktop composition root. It creates the GTK application, VTE terminal, chat controls, settings expander, response widgets, and background request thread. The window owns the GTK objects and schedules model results back onto the GTK main loop.

`terminal/pane.py` is the narrow VTE adapter. It:

- launches the configured user shell;
- reads terminal scrollback only when the user submits a question;
- uses VTE's GTK 4 full-range text API when available;
- delegates normalization and bounds to `terminal/transcript.py`; and
- inserts UTF-8 command text with `feed_child()` without appending a newline.

There is intentionally no `run_command()` method. Pressing Enter remains a human action in the terminal.

## Context construction

`terminal/transcript.py` normalizes line endings, removes obvious control noise, retains the newest content, and applies both the configured line and character limits. The line slider is the user-facing control; the character limit remains a quiet upper bound.

`llm/prompt.py` builds a deterministic request containing:

- the editable system prompt from configuration;
- prior user and assistant messages for the current session;
- a `<terminal_context>` envelope containing the bounded snapshot; and
- a `<user_question>` envelope containing the new question.

The terminal snapshot is explicitly labeled as untrusted observational data. It is not continuously sent to the model and is not interpreted by TriageTTY as shell syntax.

## Provider boundary

`llm/client.py` defines the narrow `ChatClient` protocol. `llm/openai_compatible.py` implements the standard chat-completions request shape with configurable base URL, model, API key, timeout, and TLS verification.

The HTTP client is isolated from GTK and can be replaced or mocked. Tests use `httpx.MockTransport` to verify request shape, authorization, response parsing, and malformed-response errors without contacting a model service.

## Response parsing and rendering

`chat/parser.py` returns immutable data segments rather than GTK widgets:

- prose becomes `TextSegment`;
- fenced `bash`, `sh`, and `shell` blocks become insertable `CodeSegment` values;
- untagged and non-shell fences remain non-insertable code.

`chat/rendering.py` escapes model prose before applying a small Pango-safe formatting subset. Shell cards display escaped code and expose only **Insert** and **Copy** actions. No rendered response can create an execution action.

## Configuration and packaging

`config.py` persists the local TOML configuration under the XDG config directory. The populated system prompt is stored there so users can edit it without changing source code. New installations create the configuration on first launch, while legacy `system_prompt_override` files remain readable.

GTK and VTE are system dependencies accessed through PyGObject. TriageTTY does not vendor, fork, or modify VTE. The desktop entry and icon installer are under `packaging/` and install to the user's local application and icon directories.

## Security posture

The main consent boundary is terminal-context sharing: the user chooses whether to include a bounded snapshot for each question. The main execution boundary is command insertion: the model can suggest text, but the user must review and execute it.

The application does not provide a guarantee that terminal text cannot influence a model, that a suggested command is safe, or that a configured endpoint retains no data. Those are deployment and provider-policy concerns documented further in [threat-model.md](threat-model.md).
