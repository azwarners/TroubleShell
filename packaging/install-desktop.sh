#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
data_root=${XDG_DATA_HOME:-"$HOME/.local/share"}
desktop_dir="$data_root/applications"
icon_dir="$data_root/icons/hicolor/512x512/apps"
icon_path="$icon_dir/org.troubleshell.TroubleShell.png"
executable="${TROUBLESHELL_EXECUTABLE:-$repo_root/.venv/bin/troubleshell}"

if [ ! -x "$executable" ]; then
  executable=$(command -v troubleshell || true)
fi
if [ -z "$executable" ] || [ ! -x "$executable" ]; then
  printf 'Could not find troubleshell. Activate/install the repository environment first.\n' >&2
  exit 1
fi

temporary_desktop=$(mktemp)
trap 'rm -f "$temporary_desktop"' EXIT
sed "s|^Exec=.*$|Exec=$executable|" \
  "$repo_root/packaging/org.troubleshell.TroubleShell.desktop" > "$temporary_desktop"
sed -i "s|^Icon=.*$|Icon=$icon_path|" "$temporary_desktop"
install -Dm644 "$temporary_desktop" "$desktop_dir/org.troubleshell.TroubleShell.desktop"
install -Dm644 "$repo_root/packaging/troubleshell-icon.png" "$icon_path"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$desktop_dir" >/dev/null 2>&1 || true
fi

printf 'Installed TroubleShell desktop entry at %s\n' "$desktop_dir/org.troubleshell.TroubleShell.desktop"
printf 'Installed TroubleShell icon at %s\n' "$icon_dir/org.troubleshell.TroubleShell.png"
