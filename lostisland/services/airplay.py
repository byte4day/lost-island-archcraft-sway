"""User-controlled UxPlay receiver for the Sway island."""

from __future__ import annotations

import os
import shutil
import signal
from pathlib import Path

from gi.repository import Gio, GLib, GObject


RECEIVER_NAME = "Lost Island"


class AirPlayReceiver(GObject.Object):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__()
        self.process: Gio.Subprocess | None = None
        self.stopping = False
        self.message = ""

    @property
    def running(self) -> bool:
        return self.process is not None

    def start(self) -> bool:
        if self.running:
            return False
        search_path = f"{Path.home() / '.local/bin'}:{os.environ.get('PATH', '')}"
        executable = shutil.which("uxplay", path=search_path)
        if not executable:
            self.message = "UxPlay is not installed"
            self.emit("changed")
            return False
        try:
            process = Gio.Subprocess.new(
                [executable, "-n", RECEIVER_NAME, "-nh", "-vs", "waylandsink"],
                Gio.SubprocessFlags.NONE)
        except GLib.Error as exc:
            self.message = f"Could not start UxPlay: {exc.message}"
            self.emit("changed")
            return False
        self.process = process
        self.stopping = False
        self.message = f"AirPlay receiver: {RECEIVER_NAME}"
        process.wait_async(None, self._on_finished)
        self.emit("changed")
        return True

    def stop(self) -> None:
        if self.process is None or self.stopping:
            return
        self.stopping = True
        self.message = "Stopping AirPlay"
        self.process.send_signal(signal.SIGINT)
        self.emit("changed")

    def _on_finished(self, process: Gio.Subprocess, result: Gio.AsyncResult):
        try:
            process.wait_finish(result)
        except GLib.Error:
            pass
        if process is not self.process:
            return
        was_stopping = self.stopping
        self.process = None
        self.stopping = False
        self.message = "AirPlay off" if was_stopping else "UxPlay stopped unexpectedly"
        self.emit("changed")
