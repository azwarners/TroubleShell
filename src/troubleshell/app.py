"""GTK application entry point; imports desktop dependencies only when launched."""

from .config import config_path, load_config, save_config


def main() -> None:
    try:
        from .window import TroubleWindow
    except ImportError as exc:
        raise SystemExit("TroubleShell needs PyGObject, GTK 4, and VTE GTK 4 bindings") from exc
    path = config_path()
    config = load_config(path)
    if not path.exists():
        save_config(config, path)
    TroubleWindow(config).run()
