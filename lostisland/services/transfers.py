"""Download and copy progress for the island.

Two sources:
  * browser downloads in ~/Downloads, seen as Firefox `.part` and Chromium
    `.crdownload` files. Their final size is unknown, so the island shows
    the bytes received so far with an open ring.
  * scripts, through the app's `progress` action (see bin/island-progress),
    which report a real percentage.
"""

from __future__ import annotations

import os
import re
import time

from gi.repository import Gio, GLib, GObject

PARTIAL_SUFFIXES = (".part", ".crdownload")
DONE_SECONDS = 3
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_NUMBER = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*$")


def final_name(partial: str) -> str | None:
    for suffix in PARTIAL_SUFFIXES:
        if partial.endswith(suffix):
            return partial[: -len(suffix)] or None
    return None


def parse_percent(line: str) -> float | None:
    """Percent from one line of rsync --info=progress2, pv -n, curl -#."""
    match = _PERCENT.search(line) or _NUMBER.match(line)
    if not match:
        return None
    return max(0.0, min(100.0, float(match.group(1))))


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1000 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1000
    return f"{value:.1f} GB"


class TransferService(GObject.Object):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # name of a download that just finished
        "finished": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, folder: str | None = None):
        super().__init__()
        downloads = GLib.get_user_special_dir(
            GLib.UserDirectory.DIRECTORY_DOWNLOAD)
        self.folder = folder or downloads or os.path.expanduser("~/Downloads")
        # key -> {"name", "percent" (None = unknown), "size", "done_at"}
        self.items: dict[str, dict] = {}
        self._tick_src = 0
        self._monitor = None
        if os.path.isdir(self.folder):
            self._monitor = Gio.File.new_for_path(self.folder).monitor_directory(
                Gio.FileMonitorFlags.WATCH_MOVES, None)
            self._monitor.connect("changed", self._on_file)
            for entry in os.listdir(self.folder):
                if final_name(entry):
                    self._track(entry)

    # -- state -------------------------------------------------------------

    @property
    def top(self) -> dict | None:
        live = [i for i in self.items.values() if not i.get("done_at")]
        pool = live or list(self.items.values())
        return pool[-1] if pool else None

    # -- browser downloads ---------------------------------------------------

    def _on_file(self, _mon, file, other, event):
        name = file.get_basename() or ""
        if event == Gio.FileMonitorEvent.CREATED and final_name(name):
            self._track(name)
        elif event in (Gio.FileMonitorEvent.DELETED,
                       Gio.FileMonitorEvent.MOVED_OUT,
                       Gio.FileMonitorEvent.RENAMED) and name in self.items:
            self._finish(name)

    def _track(self, partial: str):
        self.items[partial] = {"name": final_name(partial), "percent": None,
                               "size": 0, "done_at": 0.0}
        self._arm()
        self.emit("changed")

    def _finish(self, key: str):
        item = self.items.get(key)
        if item is None or item["done_at"]:
            return
        item["done_at"] = time.time()
        item["percent"] = 100.0
        self.emit("changed")
        self.emit("finished", item["name"])
        self._arm()

    # -- script progress (app action) ------------------------------------------

    def report(self, label: str, percent: float):
        """percent < 0 means the job finished."""
        key = f"script:{label}"
        if percent < 0:
            if key in self.items:
                self._finish(key)
            return
        item = self.items.setdefault(
            key, {"name": label, "percent": 0.0, "size": 0, "done_at": 0.0})
        item["percent"] = max(0.0, min(100.0, percent))
        item["done_at"] = 0.0
        self._arm()
        self.emit("changed")

    # -- ticking -------------------------------------------------------------

    def _arm(self):
        if not self._tick_src and self.items:
            self._tick_src = GLib.timeout_add(1000, self._tick)

    def _tick(self) -> bool:
        now = time.time()
        changed = False
        for key, item in list(self.items.items()):
            if item["done_at"]:
                if now - item["done_at"] > DONE_SECONDS:
                    del self.items[key]
                    changed = True
                continue
            if key.startswith("script:"):
                continue
            try:
                size = os.path.getsize(os.path.join(self.folder, key))
            except OSError:
                self._finish(key)
                continue
            if size != item["size"]:
                item["size"] = size
                changed = True
        if changed:
            self.emit("changed")
        if not self.items:
            self._tick_src = 0
            return False
        return True
