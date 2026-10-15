"""Terminal launchers for the installed coding assistants.

Logos are SVGs rendered at 3x and drawn at 20 px, so they stay sharp on any
display scale. In the card's edit mode each launcher gets a remove badge.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

from lostisland.ui.layout import LAUNCHERS

ALACRITTY_CONFIG = Path.home() / ".config/sway/alacritty/alacritty.toml"
ASSET_DIR = Path(__file__).parent / "assets"
LOGO_PX = 20

# kept for callers that iterate (label, artwork, command)
ASSISTANTS = tuple(LAUNCHERS.values())


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


def logo(artwork: str, size: int = LOGO_PX) -> Gtk.Image:
    """A crisp image of an SVG asset: rendered at 3x, drawn at `size`."""
    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
        str(ASSET_DIR / artwork), size * 3, size * 3, True)
    image = Gtk.Image.new_from_paintable(Gdk.Texture.new_for_pixbuf(pixbuf))
    image.set_pixel_size(size)
    image.set_valign(Gtk.Align.CENTER)
    image.add_css_class("launcher-logo")
    return image


class LauncherRow(Gtk.Box):
    def __init__(self, keys: list[str], on_remove=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("launchers")
        self.on_remove = on_remove
        self.cells: dict[str, Gtk.Overlay] = {}
        self.badges: list[Gtk.Widget] = []

        self.row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.row.set_homogeneous(True)
        for key, (name, artwork, command) in LAUNCHERS.items():
            button = Gtk.Button()
            button.add_css_class("launcher-btn")
            button.set_tooltip_text(f"Open {name} in Alacritty")
            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            content.set_halign(Gtk.Align.CENTER)
            content.append(logo(artwork))
            content.append(Gtk.Label(label=name))
            button.set_child(content)
            button.connect("clicked", self._launch, name, command)

            cell = Gtk.Overlay()
            cell.set_child(button)
            badge = Gtk.Button(label="−")
            badge.add_css_class("edit-badge")
            badge.set_halign(Gtk.Align.START)
            badge.set_valign(Gtk.Align.START)
            badge.set_visible(False)
            badge.set_tooltip_text(f"Remove {name}")
            badge.connect("clicked", lambda _b, k=key: self.on_remove
                          and self.on_remove(k))
            cell.add_overlay(badge)
            self.badges.append(badge)
            self.cells[key] = cell
        self.append(self.row)
        self.set_keys(keys)

        self.message = Gtk.Label(xalign=0)
        self.message.add_css_class("launcher-message")
        self.message.set_visible(False)
        self.append(self.message)

    def set_keys(self, keys: list[str]):
        while (child := self.row.get_first_child()) is not None:
            self.row.remove(child)
        for key in keys:
            if key in self.cells:
                self.row.append(self.cells[key])
        self.row.set_visible(bool(keys))

    def set_editing(self, editing: bool):
        for badge in self.badges:
            badge.set_visible(editing)
        for index, cell in enumerate(self.cells.values()):
            for cls in ("jiggle-a", "jiggle-b"):
                cell.remove_css_class(cls)
            if editing:
                cell.add_css_class("jiggle-a" if index % 2 else "jiggle-b")

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
