"""One screen recording at a time, finalized with wf-recorder's SIGINT path."""

from __future__ import annotations

import shutil
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

from gi.repository import Gio, GLib, GObject


RECORDINGS_DIR = Path.home() / "Videos" / "Recordings"


def system_audio_source() -> str | None:
    """Return the monitor of the current output sink, if PulseAudio has one."""
    if not shutil.which("pactl"):
        return None
    try:
        result = subprocess.run(
            ["pactl", "get-default-sink"], capture_output=True,
            text=True, check=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    sink = result.stdout.strip()
    return f"{sink}.monitor" if sink and "\n" not in sink else None


class ScreenRecorder(GObject.Object):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__()
        self.process: Gio.Subprocess | None = None
        self.output_file: Path | None = None
        self.started_at = 0.0
        self.stopping = False
        self.audio_included = False
        self.message = ""

    @property
    def running(self) -> bool:
        return self.process is not None

    def start(self, output: str, include_audio: bool = True) -> bool:
        if self.running:
            return False
        if not output:
            self.message = "Choose a display to record"
            self.emit("changed")
            return False
        if not shutil.which("wf-recorder"):
            self.message = "wf-recorder is not installed"
            self.emit("changed")
            return False
        audio = system_audio_source() if include_audio else None
        if include_audio and not audio:
            self.message = "System audio is unavailable; choose Without audio"
            self.emit("changed")
            return False
        try:
            RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.message = f"Cannot create recording folder: {exc.strerror}"
            self.emit("changed")
            return False

        target = RECORDINGS_DIR / ("screen-" + datetime.now().strftime(
            "%Y-%m-%d_%H-%M-%S_%f") + ".mp4")
        argv = ["wf-recorder", "-o", output, "-f", str(target)]
        if audio:
            argv.append(f"--audio={audio}")
        try:
            process = Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE)
        except GLib.Error as exc:
            self.message = f"Could not start recording: {exc.message}"
            self.emit("changed")
            return False

        self.process = process
        self.output_file = target
        self.started_at = time.monotonic()
        self.stopping = False
        self.audio_included = bool(audio)
        self.message = "Recording screen" if audio else "Recording without audio"
        process.wait_async(None, self._on_finished)
        self.emit("changed")
        return True

    def stop(self) -> None:
        if self.process is None or self.stopping:
            return
        self.stopping = True
        self.message = "Saving recording"
        self.process.send_signal(signal.SIGINT)
        self.emit("changed")

    def _on_finished(self, process: Gio.Subprocess, result: Gio.AsyncResult):
        try:
            process.wait_finish(result)
            success = process.get_successful()
        except GLib.Error:
            success = False
        if process is not self.process:
            return
        target = self.output_file
        was_stopping = self.stopping
        self.process = None
        self.stopping = False
        if target and target.is_file() and target.stat().st_size > 0 \
                and (success or was_stopping):
            self.message = f"Saved to {target}"
        else:
            self.message = "Screen recording failed"
        self.emit("changed")

    def elapsed(self) -> int:
        return int(time.monotonic() - self.started_at) if self.running else 0
