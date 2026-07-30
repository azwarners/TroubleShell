#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
data_root=${XDG_DATA_HOME:-"$HOME/.local/share"}
desktop_dir="$data_root/applications"
icon_dir="$data_root/icons/hicolor/512x512/apps"
icon_path="$icon_dir/org.triagetty.TriageTTY.png"
executable="${TRIAGETTY_EXECUTABLE:-$repo_root/.venv/bin/triagetty}"

if [ ! -x "$executable" ]; then
  executable=$(command -v triagetty || true)
fi
if [ -z "$executable" ] || [ ! -x "$executable" ]; then
  printf 'Could not find triagetty. Activate/install the repository environment first.\n' >&2
  exit 1
fi

temporary_desktop=$(mktemp)
trap 'rm -f "$temporary_desktop"' EXIT
sed "s|^Exec=.*$|Exec=$executable|" \
  "$repo_root/packaging/org.triagetty.TriageTTY.desktop" > "$temporary_desktop"
sed -i "s|^Icon=.*$|Icon=$icon_path|" "$temporary_desktop"
install -Dm644 "$temporary_desktop" "$desktop_dir/org.triagetty.TriageTTY.desktop"
install -Dm644 "$repo_root/packaging/triagetty-icon.png" "$icon_path"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$desktop_dir" >/dev/null 2>&1 || true
fi

printf 'Installed TriageTTY desktop entry at %s\n' "$desktop_dir/org.triagetty.TriageTTY.desktop"
printf 'Installed TriageTTY icon at %s\n' "$icon_dir/org.triagetty.TriageTTY.png"
