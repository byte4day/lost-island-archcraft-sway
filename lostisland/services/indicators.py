"""Caps Lock and screen brightness, for their on-screen peeks.

Wayland only tells the focused window about modifier state, and sysfs files
cannot be watched with inotify, so this reads two tiny sysfs files five
times a second. It emits only when a value actually changes.
"""

from __future__ import annotations

import glob

from gi.repository import GLib, GObject

POLL_MS = 200


def _read_int(path: str) -> int | None:
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def caps_lock_on(paths: list[str]) -> bool | None:
    values = [_read_int(p) for p in paths]
    values = [v for v in values if v is not None]
    return any(values) if values else None


def brightness_percent(value: int | None, maximum: int | None) -> int | None:
    if value is None or not maximum:
        return None
    return round(100 * value / maximum)


class IndicatorService(GObject.Object):
    __gsignals__ = {
        "caps-lock": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        "brightness": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self):
        super().__init__()
        self._caps_paths = glob.glob("/sys/class/leds/*::capslock/brightness")
        backlights = sorted(glob.glob("/sys/class/backlight/*"))
        self._bl = backlights[0] if backlights else None
        self._bl_max = (_read_int(f"{self._bl}/max_brightness")
                        if self._bl else None)
        self._caps = caps_lock_on(self._caps_paths)
        self._bright = self._read_brightness()
        self._src = 0
        if self._caps_paths or self._bl:
            self._src = GLib.timeout_add(POLL_MS, self._poll)

    def _read_brightness(self) -> int | None:
        if not self._bl:
            return None
        return brightness_percent(_read_int(f"{self._bl}/brightness"),
                                  self._bl_max)

    def _poll(self) -> bool:
        caps = caps_lock_on(self._caps_paths)
        if caps is not None and caps != self._caps:
            self._caps = caps
            self.emit("caps-lock", caps)
        bright = self._read_brightness()
        if bright is not None and bright != self._bright:
            self._bright = bright
            self.emit("brightness", bright)
        return True

    def stop(self):
        if self._src:
            GLib.source_remove(self._src)
            self._src = 0
