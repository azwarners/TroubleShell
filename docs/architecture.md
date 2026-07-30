# Architecture

TriageTTY has three deliberately small boundaries:

1. `terminal.transcript` normalizes and bounds text captured from VTE.
2. `llm.prompt` constructs deterministic, labeled requests, while `llm.client` hides HTTP details behind `ChatClient`.
3. `chat.parser` returns data segments. A GTK pane can render those segments as prose or command cards without giving the parser any execution capability.

The GTK window owns the VTE widget and will own the chat controls. It should call `terminal.feed_child()` or the equivalent insertion API with command text only; it must not append a newline.
