# Ubuntu 26.04 packaging and runtime

TriageTTY is a normal user-installed Python desktop application using the system GTK 4 and VTE GTK 4 libraries. VTE is not vendored or bundled.

Install the Ubuntu runtime dependencies:

```sh
sudo apt update
sudo apt install -y \
  python3-gi \
  gir1.2-gtk-4.0 \
  gir1.2-vte-3.91 \
  libvte-2.91-gtk4-0 \
  python3-venv
```

Install TriageTTY into a repository-local virtual environment that can see the system GI bindings:

```sh
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest -q
```

Install a user-local application-menu entry:

```sh
./packaging/install-desktop.sh
```

The installer writes the absolute path to the repository virtual environment's `triagetty` executable into the desktop entry. To use a different executable, set `TRIAGETTY_EXECUTABLE` when running the installer.

The bundled square PNG icon is installed into the user-local `hicolor/512x512/apps` icon directory. Its source lives in `packaging/` because it is a packaging asset, not an application runtime asset.

The application needs a graphical GTK session. VNC and NoMachine sessions are supported in principle because TriageTTY runs inside the remote Linux desktop; SSH-only sessions are not a graphical runtime target.
