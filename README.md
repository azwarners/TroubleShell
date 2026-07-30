# TriageTTY

**Two minds. One terminal. You stay in control.**

TriageTTY is a native Linux desktop terminal with an AI troubleshooting pane. It shares a bounded snapshot of recent terminal output only when you submit a question, sends that context to an OpenAI-compatible model endpoint, and renders suggested shell commands as **Insert** and **Copy** controls.

TriageTTY is deliberately not an autonomous agent. The model cannot execute commands, browse files, call tools, or inspect the host directly. **Insert** only places command text into the terminal input; it never presses Enter.


## Status

TriageTTY 0.1.0 is a working Linux desktop MVP. It provides:

- an embedded GTK 4/VTE terminal;
- a current-session troubleshooting chat;
- configurable bounded terminal-context sharing;
- a configurable OpenAI-compatible chat-completions client;
- an editable Linux administrator system prompt;
- safe rendering of a deliberately small Markdown subset;
- clickable shell command cards with Insert and Copy actions;
- request status, cancellation, and provider error feedback;
- local TOML configuration and a user-local desktop launcher.

The tested development platform is Ubuntu 26.04 with GTK 4.22, VTE 0.84, and PyGObject. The application is intended to run on compatible Linux desktop environments as well. VTE is provided by the operating system; it is not bundled or modified by TriageTTY.

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
python -m triagetty
```

To add it to the desktop application menu, run:

```sh
./packaging/install-desktop.sh
```

The installer creates a user-local launcher and installs the bundled icon. See [docs/packaging.md](docs/packaging.md) for the full runtime and VNC/NoMachine notes.

## Configure

On first launch, TriageTTY creates:

```text
${XDG_CONFIG_HOME:-~/.config}/triagetty/config.toml
```

The file contains the endpoint, model, API key field, TLS setting, shell, context limits, and the complete editable system prompt. A typical local configuration starts like this:

```toml
endpoint_url = "http://localhost:11434/v1"
model = "llama3.2"
api_key = ""
context_line_limit = 200
context_character_limit = 12000
verify_tls = true
```

The Settings expander in the application currently exposes the context line slider. The endpoint, model, TLS setting, and system prompt can be edited directly in `config.toml`; restart TriageTTY after changing them.

The API key field is persisted locally when used. Treat the configuration file as sensitive and keep its permissions restricted. Desktop keyring integration is a future improvement.

## Use TriageTTY

1. Run commands normally in the embedded terminal.
2. Adjust the terminal-context slider if you want to share fewer or more recent lines.
3. Leave **Include recent terminal context** enabled when the model should see the bounded snapshot.
4. Ask a troubleshooting question in the multiline chat field.
5. Review the displayed context count and the model’s explanation.
6. Review any suggested command before selecting **Insert** or **Copy**.
7. If inserted, edit the command in the terminal and press Enter yourself.

The chat pane reports the number of lines and approximate tokens sent for each request. The model receives context only at submission time; TriageTTY does not continuously stream terminal output.

## Safety boundary and known limitations

The model is a recommendation service, not an agent. TriageTTY has no tool calling, function calling, filesystem browsing, repository analysis, command interception, autonomous loop, or automatic execution path.

Terminal output can contain passwords, tokens, hostnames, paths, and other sensitive information. Review the context-sharing toggle and output before sending it to a remote endpoint. The system prompt treats terminal text as untrusted data, but prompt-injection defenses are not a security guarantee.

The Cancel control prevents a completed or stale response from being displayed, while an already-started HTTP request may continue until its timeout. API-key keyring storage, transcript redaction, richer Markdown, and broader packaging are intentionally left for later releases.

## Development

Run the focused test suite from the repository:

```sh
. .venv/bin/activate
python -m pytest -q
```

Core transcript, prompt, parser, rendering, configuration, insertion, VTE adapter, and mocked HTTP client behavior are covered by unit tests. GTK/VTE imports are also verified on the Ubuntu development environment; visual interaction still benefits from manual desktop playtesting.

Architecture details are in [docs/architecture.md](docs/architecture.md). The threat model is in [docs/threat-model.md](docs/threat-model.md).

## License

TriageTTY is licensed under the GNU Lesser General Public License, version 3 or later. See [LICENSE](LICENSE).
