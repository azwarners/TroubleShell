# TriageTTY contributor guidance

- Keep this a standalone Linux desktop application; do not add Apmatia imports or agent/tool abstractions.
- Commands suggested by the model may be copied or inserted only. They must never be executed automatically.
- Keep transcript and prompt handling deterministic and covered by unit tests.
- Keep GTK/VTE imports at the UI boundary so core tests run without a display server.
- Preserve the MIT license and add SPDX headers to new source files where practical.

## Virtual environment setup

PyGObject (GTK bindings) is installed as a system package and must be accessible from the virtual environment. When creating a new venv, **always use the `--system-site-packages` flag**:

```bash
python3 -m venv --system-site-packages .venv
```

Without this flag, the app will fail to start with `ModuleNotFoundError: No module named 'gi'` because PyGObject won't be importable.

To run tests, activate the existing venv and run pytest directly:

```bash
.venv/bin/python3 -m pytest tests/ -v
```

Do not recreate the `.venv` directory unless absolutely necessary, as this will wipe out all installed dependencies including PyGObject.
