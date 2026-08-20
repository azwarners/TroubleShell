# TroubleShell architecture

TroubleShell is a small, standalone GTK 4 application. Its architecture is intentionally direct: a VTE terminal, a chat pane, a deterministic prompt builder, one provider client, and pure parsing/rendering helpers. There are no agent, tool, plugin, workflow, or orchestration layers.

## Runtime data flow

```text
Shell output
        |
        v
PTY proxy --> CaptureServer --> TranscriptStore --> ContextSession
        |                                                |
        +--> VTE display                            prompt builder
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

- launches the configured shell through the PTY proxy;
- displays the identical bytes forwarded by the proxy; and
- inserts UTF-8 command text with `feed_child()` without appending a newline.

The proxy sends shell output to the parent CaptureServer before forwarding it
to VTE. The parent appends packets unchanged to the locked TranscriptStore;
VTE scrollback is display-only and is never a model-context source.

There is intentionally no `run_command()` method. Pressing Enter remains a human action in the terminal.

## Context construction

`llm/context_session.py` selects the complete unacknowledged captured event
range for each request. Normal turns do not trim terminal text. When the full
request approaches the provider context limit, ContextSession performs one
explicit whole-request compaction and retains the newest terminal third.

`llm/prompt.py` builds a deterministic request containing:

- the editable system prompt from configuration;
- prior user and assistant messages for the current session;
- a `<terminal_context>` envelope containing the selected captured transcript; and
- a `<user_question>` envelope containing the new question.

The captured terminal transcript is explicitly labeled as untrusted observational data. It is not continuously sent to the model and is not interpreted by TroubleShell as shell syntax.

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

GTK and VTE are system dependencies accessed through PyGObject. TroubleShell does not vendor, fork, or modify VTE. The desktop entry and icon installer are under `packaging/` and install to the user's local application and icon directories.

## Security posture

The main evidence boundary is PTY capture and request construction: captured
terminal output is included with each request and compacted only at the provider
limit. The main execution boundary is command insertion: the model can suggest
text, but the user must review and execute it.

The application does not provide a guarantee that terminal text cannot influence a model, that a suggested command is safe, or that a configured endpoint retains no data. Those are deployment and provider-policy concerns documented further in [threat-model.md](threat-model.md).
