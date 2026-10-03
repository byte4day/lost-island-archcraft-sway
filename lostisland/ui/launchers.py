"""Small terminal launchers for the installed coding assistants."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk


ASSISTANTS = (
    ("Claude", "claude.png", "claude"),
    ("Codex", "codex.png", "codex"),
    ("Cursor", "cursor.png", "cursor-agent"),
)

ALACRITTY_CONFIG = Path.home() / ".config/sway/alacritty/alacritty.toml"
ASSET_DIR = Path(__file__).parent / "assets"


def _find_command(command: str) -> str | None:
    search_path = f"{Path.home() / '.local/bin'}:{os.environ.get('PATH', '')}"
    return shutil.which(command, path=search_path)


def launcher_command(name: str, executable: str, terminal: str) -> list[str]:
    """Build an argv without a shell, using the user's Sway terminal theme."""
    args = [terminal]
    if ALACRITTY_CONFIG.is_file():
        args.extend(["--config-file", str(ALACRITTY_CONFIG)])
    args.extend(["--working-directory", str(Path.home()),
                 "--title", name, "-e", executable])
    return args


class LauncherRow(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("launchers")

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_homogeneous(True)
        for name, artwork, command in ASSISTANTS:
            button = Gtk.Button()
            button.add_css_class("launcher-btn")
            button.set_tooltip_text(f"Open {name} CLI in Alacritty")
            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            content.set_halign(Gtk.Align.CENTER)
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                str(ASSET_DIR / artwork), 21, 21, True)
            pixbuf.saturate_and_pixelate(pixbuf, 0.0, False)
            icon = Gtk.Picture.new_for_paintable(Gdk.Texture.new_for_pixbuf(pixbuf))
            icon.set_size_request(21, 21)
            icon.set_content_fit(Gtk.ContentFit.CONTAIN)
            icon.set_opacity(0.82)
            icon.add_css_class("launcher-logo")
            content.append(icon)
            content.append(Gtk.Label(label=name))
            button.set_child(content)
            button.connect("clicked", self._launch, name, command)
            row.append(button)
        self.append(row)

        self.message = Gtk.Label(xalign=0)
        self.message.add_css_class("launcher-message")
        self.message.set_visible(False)
        self.append(self.message)

    def _launch(self, _button: Gtk.Button, name: str, command: str):
        executable = _find_command(command)
        terminal = _find_command("alacritty")
        if not executable or not terminal:
            missing = command if not executable else "Alacritty"
            self._show_error(f"{missing} is not installed")
            return
        try:
            Gio.Subprocess.new(launcher_command(name, executable, terminal),
                               Gio.SubprocessFlags.NONE)
        except GLib.Error as exc:
            self._show_error(f"Could not open {name}: {exc.message}")
        else:
            self.message.set_visible(False)

    def _show_error(self, message: str):
        self.message.set_label(message)
        self.message.set_visible(True)
