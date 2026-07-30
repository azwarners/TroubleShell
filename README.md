# TriageTTY

**Two minds. One terminal. You stay in control.**

TriageTTY is a small Linux desktop terminal with an optional AI troubleshooting pane. It sends a bounded, user-visible terminal transcript only when the user submits a question. Suggested shell commands can be inserted into the terminal for review; they are never executed by TriageTTY.

## Status

This repository contains the first standalone implementation scaffold. The core transcript, prompt, parser, configuration, and OpenAI-compatible client are usable and tested. The GTK/VTE desktop shell is intentionally kept thin so it can be completed on a Linux machine with GTK 4, VTE 3.91 GTK 4 bindings, and PyGObject installed.

## Development

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
pytest
```

For the desktop dependencies, install the distribution packages for `python3-gi`, GTK 4, and VTE GTK 4 bindings, then install `-e '.[desktop]'`.

Ubuntu 26.04 setup and the user-local desktop launcher are documented in [docs/packaging.md](docs/packaging.md).

Configuration is stored in `${XDG_CONFIG_HOME:-~/.config}/triagetty/config.toml`, including the editable system prompt, endpoint, model, and context limits. API keys are read from `TRIAGETTY_API_KEY` when set; the MVP config file also supports a key value for local development, but a future keyring integration should be preferred for persistent secrets.

## Safety boundary

The model is a recommendation service, not an agent. TriageTTY has no tool calling, filesystem access, command interception, or execution path. The **Insert** action only writes command text into the terminal input and never appends a newline.

TriageTTY is licensed under the GNU Lesser General Public License, version 3 or later. See [LICENSE](LICENSE).
