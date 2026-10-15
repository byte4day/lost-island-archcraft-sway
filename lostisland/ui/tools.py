"""Tool actions: screenshot, area shot, color picker, Do Not Disturb, power.

The buttons are plain circles; the expanded card places them in its control
grid. Capture tools collapse the island first so the card is not in the
picture, then report the result as a peek. Power actions that end the session
need a second click within a few seconds.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from gi.repository import GLib, Gtk

from lostisland.services import tools

COLLAPSE_SETTLE_MS = 380   # island morph is 260 ms; leave it time to finish
CONFIRM_SECONDS = 4


def circle_button(icon: str, tooltip: str, toggle: bool = False) -> Gtk.Button:
    button = Gtk.ToggleButton() if toggle else Gtk.Button()
    button.add_css_class("circle")
    symbol = Gtk.Label(label=icon)
    symbol.add_css_class("symbol-icon")
    button.set_child(symbol)
    button.set_tooltip_text(tooltip)
    return button


class ToolActions:
    def __init__(self, on_collapse: Callable[[], None],
                 on_peek: Callable[..., None],
                 on_dnd: Callable[[bool], None]):
        self.on_collapse = on_collapse
        self.on_peek = on_peek
        self.on_dnd = on_dnd
        self._busy = False
        self._confirm: str | None = None
        self._confirm_timer = 0
        self.on_power_open: Callable[[], None] | None = None

        self.shot = circle_button("screenshot_monitor",
                                  "Capture this display; saved and copied")
        self.shot.connect("clicked", lambda *_: self._capture(region=False))
        self.region = circle_button("screenshot_region",
                                    "Select an area to capture; Esc cancels")
        self.region.connect("clicked", lambda *_: self._capture(region=True))
        self.picker = circle_button("colorize",
                                    "Pick a color from the screen; hex is copied")
        self.picker.connect("clicked", lambda *_: self._pick_color())

        self.dnd = circle_button("do_not_disturb_on",
                                 "Do Not Disturb: hide notifications",
                                 toggle=True)
        self._dnd_handler = self.dnd.connect("toggled", self._on_dnd_toggled)

        self.power = circle_button("power_settings_new",
                                   "Lock, sleep, restart or shut down",
                                   toggle=True)
        self.power.connect("toggled", self._on_power_toggled)

        self.power_revealer = Gtk.Revealer()
        self.power_revealer.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.power_revealer.set_transition_duration(180)
        power_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        power_row.set_homogeneous(True)
        power_row.add_css_class("power-row")
        self.power_buttons: dict[str, Gtk.Button] = {}
        for name, (label, _icon, _argv, _confirm) in tools.POWER_ACTIONS.items():
            button = Gtk.Button(label=label)
            button.add_css_class("power-btn")
            button.connect("clicked", self._on_power_action, name)
            self.power_buttons[name] = button
            power_row.append(button)
        self.power_revealer.set_child(power_row)
        self.power_revealer.connect("unmap", lambda *_: self.close_power())

        self.message = Gtk.Label(xalign=0)
        self.message.add_css_class("card-message")
        self.message.set_visible(False)

        GLib.idle_add(lambda: self.refresh_dnd() and False)

    # -- capture -----------------------------------------------------------

    def _capture(self, region: bool):
        if self._begin():
            GLib.timeout_add(COLLAPSE_SETTLE_MS, self._capture_after_collapse,
                             region)

    def _capture_after_collapse(self, region: bool) -> bool:
        target = tools.screenshot_path()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._fail(f"Cannot create {target.parent}: {exc.strerror}")
            return False

        def grab(geometry_args: list[str]):
            tools.run(["grim", *geometry_args, str(target)],
                      lambda ok, _out: self._captured(ok, target), timeout_s=15)

        if region:
            # slurp waits for the user; Esc exits non-zero = quiet cancel
            tools.run(["slurp", "-d"],
                      lambda ok, out: grab(["-g", out.strip()])
                      if ok and out.strip() else self._end(),
                      timeout_s=120)
        else:
            tools.run(["swaymsg", "-t", "get_outputs", "-r"],
                      lambda ok, out: grab(
                          ["-o", name] if ok and (name := tools.focused_output(out))
                          else []))
        return False

    def _captured(self, ok: bool, target: Path):
        if not ok or not target.exists():
            self._fail("Screenshot failed; check that grim is installed")
            return
        tools.run(["wl-copy", "--type", "image/png"], stdin_path=str(target))
        self._end()
        self.on_peek("screenshot", target.name)

    # -- color picker ------------------------------------------------------

    def _pick_color(self):
        if self._begin():
            GLib.timeout_add(COLLAPSE_SETTLE_MS, self._pick_after_collapse)

    def _pick_after_collapse(self) -> bool:
        def picked(ok: bool, out: str):
            self._end()
            color = tools.parse_color(out) if ok else None
            if color:
                tools.run(["wl-copy", color])
                self.on_peek("color", color)

        tools.run(["hyprpicker", "--format=hex", "--no-fancy", "--quiet"],
                  picked, timeout_s=120)
        return False

    # -- do not disturb ----------------------------------------------------

    def refresh_dnd(self):
        tools.run(["makoctl", "mode"], lambda ok, out: self._show_dnd(
            tools.DND_MODE in tools.parse_modes(out) if ok else None))

    def _show_dnd(self, active: bool | None):
        self.dnd.set_sensitive(active is not None)
        if active is None:
            self.dnd.set_tooltip_text("Do Not Disturb needs mako")
            return
        self.dnd.handler_block(self._dnd_handler)
        self.dnd.set_active(active)
        self.dnd.handler_unblock(self._dnd_handler)
        self.dnd.set_tooltip_text(
            "Do Not Disturb is on; click to show notifications" if active
            else "Do Not Disturb: hide notifications")
        self.on_dnd(active)

    def _on_dnd_toggled(self, button: Gtk.ToggleButton):
        flag = "-a" if button.get_active() else "-r"
        button.set_sensitive(False)
        tools.run(["makoctl", "mode", flag, tools.DND_MODE],
                  lambda _ok, _out: self.refresh_dnd())

    # -- power -------------------------------------------------------------

    def _on_power_toggled(self, button: Gtk.ToggleButton):
        if button.get_active() and self.on_power_open:
            self.on_power_open()
        self.power_revealer.set_reveal_child(button.get_active())
        if not button.get_active():
            self._reset_confirm()

    def close_power(self):
        self.power.set_active(False)

    def _on_power_action(self, _button: Gtk.Button, name: str):
        needs_confirm = tools.POWER_ACTIONS[name][3]
        if needs_confirm and self._confirm != name:
            self._reset_confirm()
            self._confirm = name
            button = self.power_buttons[name]
            button.add_css_class("power-btn--confirm")
            button.set_label(f"{tools.POWER_ACTIONS[name][0]}?")
            self._confirm_timer = GLib.timeout_add_seconds(
                CONFIRM_SECONDS, self._reset_confirm)
            return
        self._reset_confirm()
        self.close_power()
        self.on_collapse()
        argv = tools.power_command(name)
        if name == "lock":
            if not tools.spawn_detached(argv):
                self._fail("No screen locker found")
            return
        if name == "suspend":
            tools.spawn_detached(tools.lock_command())
        tools.run(argv, lambda ok, _out: None if ok else self._fail(
            f"{tools.POWER_ACTIONS[name][0]} failed"))

    def _reset_confirm(self) -> bool:
        if self._confirm_timer:
            GLib.source_remove(self._confirm_timer)
            self._confirm_timer = 0
        if self._confirm:
            button = self.power_buttons[self._confirm]
            button.remove_css_class("power-btn--confirm")
            button.set_label(tools.POWER_ACTIONS[self._confirm][0])
            self._confirm = None
        return False

    def lock(self):
        """Lock the screen now (the Lock control in the grid)."""
        self.on_collapse()
        if not tools.spawn_detached(tools.lock_command()):
            self._fail("No screen locker found")

    # -- helpers -----------------------------------------------------------

    def _begin(self) -> bool:
        if self._busy:
            return False
        self._busy = True
        self.message.set_visible(False)
        self.on_collapse()
        return True

    def _end(self):
        self._busy = False

    def _fail(self, text: str):
        self._end()
        self.message.set_label(text)
        self.message.set_visible(True)
        self.on_peek("error", text)
