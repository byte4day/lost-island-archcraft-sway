"""Short-lived island faces.

Peek: the pill widens for one event (volume, brightness, Caps Lock, charger,
network, a finished focus round or download).
Banner: a notification with its app, text and action buttons. Clicking the
banner opens the app; the buttons act on mako's copy of it.
"""

from __future__ import annotations

import os

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango

from lostisland.ui.draw import ChargeGlyph, pick_icon

ASSETS = os.path.join(os.path.dirname(__file__), "assets")


class Peek(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.add_css_class("peek")
        self.set_valign(Gtk.Align.CENTER)

        self.icon = Gtk.Image()
        self.icon.set_pixel_size(20)
        self.icon.add_css_class("peek-icon")
        self.symbol = Gtk.Label()
        self.symbol.add_css_class("symbol-icon")
        self.symbol.add_css_class("peek-symbol")
        self.charge = ChargeGlyph()

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text_box.set_valign(Gtk.Align.CENTER)
        self.title = Gtk.Label(xalign=0)
        self.title.add_css_class("peek-title")
        self.title.set_ellipsize(Pango.EllipsizeMode.END)
        self.title.set_max_width_chars(30)
        self.body = Gtk.Label(xalign=0)
        self.body.add_css_class("peek-body")
        self.body.set_ellipsize(Pango.EllipsizeMode.END)
        self.body.set_max_width_chars(38)
        text_box.append(self.title)
        text_box.append(self.body)

        self.level = Gtk.LevelBar()
        self.level.set_min_value(0)
        self.level.set_max_value(100)
        self.level.set_valign(Gtk.Align.CENTER)
        # kill the default warning/error color breakpoints
        self.level.remove_offset_value("low")
        self.level.remove_offset_value("high")
        self.level.remove_offset_value("full")

        self.value = Gtk.Label()
        self.value.add_css_class("peek-value")

        for w in (self.icon, self.symbol, self.charge, text_box, self.level,
                  self.value):
            self.append(w)

    def _set(self, icon: str = "", title: str = "", body: str = "",
             level: float | None = None, symbol: str = "", value: str = "",
             tone: str = ""):
        self.icon.set_visible(bool(icon))
        if icon:
            self.icon.set_from_icon_name(icon)
        self.symbol.set_visible(bool(symbol))
        self.symbol.set_label(symbol)
        self.charge.set_visible(False)
        self.title.set_label(title)
        self.body.set_label(body)
        self.body.set_visible(bool(body))
        self.level.set_visible(level is not None)
        if level is not None:
            self.level.set_value(min(100, level))
        self.value.set_visible(bool(value))
        self.value.set_label(value)
        for t in ("green", "orange", "accent"):
            self.remove_css_class(f"peek--{t}")
        if tone:
            self.add_css_class(f"peek--{tone}")

    def show_volume(self, percent: int, muted: bool):
        if muted:
            self._set(symbol="volume_off", title="Muted", level=0)
        else:
            self._set(symbol="volume_mute" if percent == 0 else
                      "volume_down" if percent < 50 else "volume_up",
                      level=percent, value=f"{percent}%")

    def show_brightness(self, percent: int):
        self._set(symbol="light_mode" if percent >= 50 else "brightness_low",
                  level=percent, value=f"{percent}%")

    def show_caps_lock(self, on: bool):
        self._set(symbol="keyboard_capslock",
                  title="Caps Lock on" if on else "Caps Lock off",
                  tone="accent" if on else "")

    def show_battery(self, percent: float, plugged: bool):
        if plugged:
            self._set(title="Charging", value=f"{percent:.0f}%", tone="green")
            self.charge.set_visible(True)
            self.charge.play(percent)
        else:
            self._set(symbol="battery_full" if percent > 60 else
                      "battery_3_bar" if percent > 25 else "battery_1_bar",
                      title="On battery", value=f"{percent:.0f}%")

    def show_bluetooth(self, device: str, connected: bool):
        self._set(symbol="bluetooth_connected" if connected else
                  "bluetooth_disabled",
                  title=device or "Bluetooth",
                  body="Connected" if connected else "Disconnected")

    def show_network(self, name: str, kind: str, connected: bool):
        if not connected:
            self._set(symbol="wifi_off", title="Offline")
        elif "wireless" in kind:
            self._set(symbol="wifi", title=name, body="Wi-Fi")
        else:
            self._set(symbol="lan", title=name, body="Ethernet")

    def show_screenshot(self, filename: str):
        self._set(symbol="screenshot_monitor", title="Screenshot copied",
                  body=filename)

    def show_color(self, hex_color: str):
        self._set(title=hex_color, body="Copied to clipboard")
        rgb = int(hex_color.lstrip("#"), 16)
        swatch = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 20, 20)
        swatch.fill((rgb << 8) | 0xFF)
        self.icon.set_from_paintable(Gdk.Texture.new_for_pixbuf(swatch))
        self.icon.set_visible(True)

    def show_dnd(self, active: bool):
        self._set(symbol="do_not_disturb_on" if active else "notifications",
                  title="Focus on" if active else "Focus off",
                  body="Notifications are hidden" if active else "")

    def show_error(self, text: str):
        self._set(symbol="error", title=text, tone="orange")

    def show_clipboard(self, text: str):
        line = " ".join(text.split())
        self._set(symbol="content_paste", title="Copied", body=line)

    def show_timer_done(self, minutes: int):
        self._set(symbol="timer", title="Focus round done",
                  body=f"{minutes} minutes. Take a short break.",
                  tone="accent")

    def show_download_done(self, name: str):
        self._set(symbol="download_done", title="Downloaded", body=name,
                  tone="green")


class Banner(Gtk.Box):
    """A notification: app icon, app name, summary, two lines of body and
    up to three action buttons."""

    def __init__(self, on_open=None, on_action=None, on_dismiss=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add_css_class("banner")
        self.set_size_request(400, -1)  # Apple's expanded width is 408 pt
        self.note: dict | None = None
        self.on_open = on_open
        self.on_action = on_action
        self.on_dismiss = on_dismiss

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.image_frame = Gtk.Box()
        self.image_frame.add_css_class("banner-image")
        self.image_frame.set_overflow(Gtk.Overflow.HIDDEN)
        self.image_frame.set_valign(Gtk.Align.START)
        self.picture = Gtk.Picture()
        self.picture.set_content_fit(Gtk.ContentFit.COVER)
        self.picture.set_size_request(38, 38)
        self.icon = Gtk.Image()
        self.icon.set_pixel_size(30)
        self.icon.set_size_request(38, 38)
        self.image_frame.append(self.picture)
        self.image_frame.append(self.icon)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.app = Gtk.Label(xalign=0, hexpand=True)
        self.app.add_css_class("banner-app")
        self.when = Gtk.Label(label="now")
        self.when.add_css_class("banner-app")
        head.append(self.app)
        head.append(self.when)
        self.summary = Gtk.Label(xalign=0)
        self.summary.add_css_class("banner-summary")
        self.summary.set_ellipsize(Pango.EllipsizeMode.END)
        self.summary.set_max_width_chars(34)
        self.body = Gtk.Label(xalign=0)
        self.body.add_css_class("banner-body")
        self.body.set_wrap(True)
        self.body.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.body.set_lines(2)
        self.body.set_ellipsize(Pango.EllipsizeMode.END)
        self.body.set_max_width_chars(40)
        text.append(head)
        text.append(self.summary)
        text.append(self.body)

        close = Gtk.Button()
        close.add_css_class("banner-close")
        close.set_child(_symbol("close"))
        close.set_valign(Gtk.Align.START)
        close.set_tooltip_text("Dismiss")
        close.connect("clicked", lambda *_: self.note and self.on_dismiss
                      and self.on_dismiss(self.note))

        top.append(self.image_frame)
        top.append(text)
        top.append(close)
        self.append(top)

        self.actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                               spacing=8)
        self.actions.set_homogeneous(True)
        self.append(self.actions)

        click = Gtk.GestureClick()
        click.connect("released", self._on_click)
        top.add_controller(click)

    def _on_click(self, gesture, _n, x, y):
        picked = gesture.get_widget().pick(x, y, Gtk.PickFlags.DEFAULT)
        while picked is not None and picked is not gesture.get_widget():
            if isinstance(picked, Gtk.Button):
                return
            picked = picked.get_parent()
        if self.note and self.on_open:
            self.on_open(self.note)

    def show(self, note: dict):
        self.note = note
        self.app.set_label(note.get("app") or "Notification")
        self.summary.set_label(note.get("summary") or note.get("app") or "")
        body = " ".join((note.get("body") or "").split())
        self.body.set_label(body)
        self.body.set_visible(bool(body))

        texture = note.get("texture")
        if texture is None and note.get("image_path"):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    note["image_path"], 76, 76, True)
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            except GLib.Error:
                texture = None
        self.picture.set_visible(texture is not None)
        self.icon.set_visible(texture is None)
        if texture is not None:
            self.picture.set_paintable(texture)
        else:
            app = (note.get("app") or "").lower().replace(" ", "-")
            self.icon.set_from_icon_name(pick_icon(
                self, note.get("icon") or "-", app, f"org.{app}.{app}",
                "preferences-system-notifications",
                "dialog-information-symbolic"))

        while (child := self.actions.get_first_child()) is not None:
            self.actions.remove(child)
        buttons = [(k, v) for k, v in note.get("actions", [])
                   if k != "default"][:3]
        for key, label in buttons:
            button = Gtk.Button(label=label)
            button.add_css_class("banner-action")
            button.connect("clicked", lambda _b, k=key: self.on_action
                           and self.on_action(self.note, k))
            self.actions.append(button)
        self.actions.set_visible(bool(buttons))


def _symbol(name: str) -> Gtk.Label:
    label = Gtk.Label(label=name)
    label.add_css_class("symbol-icon")
    return label
