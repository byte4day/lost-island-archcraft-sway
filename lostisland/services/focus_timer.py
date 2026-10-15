"""Focus timer shared by the pill, the satellite bubble and the card.

It ticks once a second only while running. When a round ends it emits
`finished`; the island plays a chime and shows a peek.
"""

from __future__ import annotations

from gi.repository import GLib, GObject

MIN_MINUTES, MAX_MINUTES, STEP = 5, 90, 5


def clamp_minutes(value) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        minutes = 25
    return max(MIN_MINUTES, min(MAX_MINUTES, minutes))


def fmt_left(seconds: int) -> str:
    m, s = divmod(max(0, int(seconds)), 60)
    return f"{m:02d}:{s:02d}"


class FocusTimer(GObject.Object):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "finished": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, minutes: int = 25):
        super().__init__()
        self.minutes = clamp_minutes(minutes)
        self.left = self.minutes * 60
        self.running = False
        self._src = 0

    # -- state -------------------------------------------------------------

    @property
    def total(self) -> int:
        return self.minutes * 60

    @property
    def touched(self) -> bool:
        """Running, or paused part-way through a round."""
        return self.running or self.left != self.total

    @property
    def progress(self) -> float:
        return 1.0 - self.left / self.total if self.total else 0.0

    @property
    def text(self) -> str:
        return fmt_left(self.left)

    # -- control -----------------------------------------------------------

    def toggle(self):
        self.pause() if self.running else self.start()

    def start(self):
        if self.left <= 0:
            self.left = self.total
        self.running = True
        if not self._src:
            self._src = GLib.timeout_add_seconds(1, self._tick)
        self.emit("changed")

    def pause(self):
        self.running = False
        self._stop_source()
        self.emit("changed")

    def reset(self):
        self.running = False
        self._stop_source()
        self.left = self.total
        self.emit("changed")

    def set_minutes(self, minutes: int) -> bool:
        """Change the round length; only while the timer is untouched."""
        if self.touched:
            return False
        minutes = clamp_minutes(minutes)
        if minutes == self.minutes:
            return False
        self.minutes = minutes
        self.left = self.total
        self.emit("changed")
        return True

    # -- ticking -----------------------------------------------------------

    def _stop_source(self):
        if self._src:
            GLib.source_remove(self._src)
            self._src = 0

    def _tick(self) -> bool:
        if not self.running:
            self._src = 0
            return False
        self.left -= 1
        if self.left <= 0:
            self.left = self.total
            self.running = False
            self._src = 0
            self.emit("changed")
            self.emit("finished")
            return False
        self.emit("changed")
        return True
