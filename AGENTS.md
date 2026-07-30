# TriageTTY contributor guidance

- Keep this a standalone Linux desktop application; do not add Apmatia imports or agent/tool abstractions.
- Commands suggested by the model may be copied or inserted only. They must never be executed automatically.
- Keep transcript and prompt handling deterministic and covered by unit tests.
- Keep GTK/VTE imports at the UI boundary so core tests run without a display server.
- Preserve the LGPL-3.0-or-later license and add SPDX headers to new source files where practical.
