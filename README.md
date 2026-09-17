# TroubleShell

**Two minds. One terminal. You stay in control.**

TroubleShell 0.2 is a native Linux desktop terminal with an AI troubleshooting pane. It captures ordered shell output through a PTY proxy and includes that context when you submit a question. Normal turns are untrimmed; explicit compaction occurs only when the complete request approaches the provider context limit. Suggested shell commands appear as **Insert**, **Execute**, and **Copy** controls.

TroubleShell is deliberately not an autonomous agent. The model cannot autonomously execute commands, browse files, call tools, or inspect the host directly. **Insert** places command text into the terminal input without pressing Enter. **Execute** runs a suggested command only when the operator explicitly clicks it.

## Status

**TroubleShell 0.2 is the first fully working release of the current standalone-terminal architecture, and the final release planned for that architecture.**

It provides:

- an embedded GTK 4/VTE terminal;
- a current-session troubleshooting chat;
- ordered PTY-captured terminal context with provider-limit compaction;
- a configurable OpenAI-compatible chat-completions client;
- an editable Linux administrator system prompt;
- safe rendering of a deliberately small Markdown subset;
- clickable shell command cards with Insert, Execute, and Copy actions;
- request status, cancellation, and provider error feedback;
- local TOML configuration and a user-local desktop launcher.

The tested development platform is Ubuntu 26.04 with GTK 4.22, VTE 0.84, and PyGObject. The application is intended to run on compatible Linux desktop environments as well. VTE is provided by the operating system; it is not bundled or modified by TroubleShell.

### What comes next

TroubleShell is moving away from being its own terminal application.

The next architecture will make TroubleShell a lightweight integration layer around mature components instead of continuing to maintain a complete terminal and AI chat UI itself. The current direction is:

```text
terminal application
        |
        v
   TroubleShell
        |
        v
      Ysparr
        |
        v
OpenAI-compatible AI provider
```

The terminal application has not been selected yet. The goal is to integrate TroubleShell with a mature terminal rather than compete with one.

In the new architecture, TroubleShell will concentrate on the terminal-specific behavior that makes it useful: observing terminal context, connecting that context to AI conversations, identifying suggested shell commands, and exposing safe human-controlled actions such as inserting, executing, or copying those commands. Ysparr will provide the durable OpenAI-compatible request path between clients and AI providers.

Version 0.2 remains available as the preserved standalone implementation while that architecture is developed.

## Install on Ubuntu 26.04

Install the system GTK, VTE, and PyGObject packages:

```sh
sudo apt update
sudo apt install -y \
  python3-gi \
  gir1.2-gtk-4.0 \
  gir1.2-vte-3.91 \
  libvte-2.91-gtk4-0 \
  python3-venv
```

From the repository, create an editable virtual environment that can see the system GI bindings:

```sh
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest -q
```

Launch the application from the terminal:

```sh
python -m troubleshell
```

To add it to the desktop application menu, run:

```sh
./packaging/install-desktop.sh
```

The installer creates a user-local launcher and installs the bundled icon. See [docs/packaging.md](docs/packaging.md) for the full runtime and VNC/NoMachine notes.

## Configure

On first launch, TroubleShell creates:

```text
${XDG_CONFIG_HOME:-~/.config}/troubleshell/config.toml
```

The file contains the endpoint, model, API key field, TLS setting, shell, context limits, and the complete editable system prompt. A typical local configuration starts like this:

```toml
endpoint_url = "http://<IP address>:<port #>/v1"
model = "<model alias>"
api_key = ""
verify_tls = true
# Keep the full LLM request payload hidden unless diagnosing context issues.
debug_context_payload = false
# Unlimited by default; set a number of seconds to enable a request timeout.
request_timeout = "none"
# Keep every terminal line for the session; use a positive number to cap it.
terminal_scrollback_lines = -1
```

The endpoint, model, TLS setting, shell, terminal scrollback, provider context limit, request timeout, system prompt, and context-payload debugging can be edited directly in `config.toml`; restart TroubleShell after changing them. Set `terminal_scrollback_lines` to `-1` (or `"none"`) for no terminal scrollback limit, or to a positive number to cap retained lines. Set `request_timeout` to a number of seconds, or leave it as `"none"` for no timeout. Set `debug_context_payload = true` to expose the full outbound request under **Context**; it is disabled by default because the payload can include sensitive terminal and conversation data.

The API key field is persisted locally when used. Treat the configuration file as sensitive and keep its permissions restricted.

## Use TroubleShell

1. Run commands normally in the embedded terminal.
2. Ask a troubleshooting question in the multiline chat field.
3. Review the captured context and the model's explanation.
4. Select private or irrelevant terminal text, right-click, and choose **Remove from context**. TroubleShell removes it from the local transcript and rebuilds the visible terminal scrollback; this cannot erase text already sent to a provider.
5. Review any suggested command before selecting **Insert**, **Execute**, or **Copy**.
6. **Insert** places the command in the terminal for editing and manual execution; **Execute** immediately submits that command to the shell after your explicit click.

The chat pane reports context information for each request. The model receives context only at submission time; TroubleShell does not continuously stream terminal output. Context is compacted as one whole request only near the provider limit.

## Safety boundary and known limitations

The model is a recommendation service, not an autonomous agent. TroubleShell 0.2 has no tool calling, function calling, filesystem browsing, repository analysis, autonomous loop, or automatic model-controlled execution path. The **Execute** action is a direct operator-controlled UI action and should only be used after reviewing the suggested command.

Terminal output can contain passwords, tokens, hostnames, paths, and other sensitive information. Review the captured output before sending it to a remote endpoint. The system prompt treats terminal text as untrusted data, but prompt-injection defenses are not a security guarantee.

The Cancel control prevents a completed or stale response from being displayed, while an already-started HTTP request may continue until its timeout.

Because 0.2 closes the standalone-terminal architecture, additional work such as richer Markdown, keyring integration, broader packaging, and further UI expansion will not be pursued in this implementation unless needed for maintenance.

## Development

Run the focused test suite from the repository:

```sh
. .venv/bin/activate
python -m pytest -q
```

Core transcript, prompt, parser, rendering, configuration, insertion/execution, VTE adapter, and mocked HTTP client behavior are covered by unit tests. GTK/VTE imports are also verified on the Ubuntu development environment; visual interaction still benefits from manual desktop playtesting.

Architecture details are in [docs/architecture.md](docs/architecture.md). The threat model is in [docs/threat-model.md](docs/threat-model.md).

## License

TroubleShell is licensed under the MIT License. See [LICENSE](LICENSE).
