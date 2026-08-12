#!/usr/bin/env python3
"""Test VTE with longer wait."""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Vte", "3.91")
from gi.repository import Gtk, Vte
import time

# Create app and window
app = Gtk.Application(application_id="org.test.VTE")
window = Gtk.ApplicationWindow(application=app, title="Test")
window.set_default_size(800, 600)

# Create terminal
terminal = Vte.Terminal()
window.set_child(terminal)

# Spawn bash
terminal.spawn_async(
    Vte.PtyFlags.DEFAULT,
    None,
    ["/bin/bash"],
    None,
    0,
    None,
    None,
    -1,
    None,
    None
)

def on_activate(app):
    window.show()
    print("Waiting for shell...")
    time.sleep(2)
    
    # Read initial
    text_initial = terminal.get_text_format(Vte.Format.TEXT)
    print(f"T=2s: {repr(text_initial)} (len={len(text_initial) if text_initial else 0})")
    
    # Feed command
    terminal.feed_child(b'echo "Hello"\n')
    print("Sent echo at T=2s")
    
    # Check at intervals
    for i in range(1, 6):
        time.sleep(1)
        text = terminal.get_text_format(Vte.Format.TEXT)
        cursor_col, cursor_row = terminal.get_cursor_position()
        print(f"T={2+i}s: cursor=({cursor_col},{cursor_row}), text={repr(text)} (len={len(text) if text else 0})")
        if text and "Hello" in text:
            print(f"  FOUND at T={2+i}s!")
            break
    
    app.quit()

app.connect("activate", on_activate)
app.run(["--g-type-init"])