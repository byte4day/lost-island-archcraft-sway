"""Text clipboard history, kept in memory only.

`wl-paste --watch` runs a tiny writer for every clipboard change; each entry
reaches us NUL-terminated on one long-lived pipe. Nothing is written to disk,
so copied passwords never land in a file, and history ends with the session.
"""

from __future__ import annotations

import shutil

from gi.repository import Gio, GLib, GObject

LIMIT = 25
MAX_CHARS = 20_000
# runs once per clipboard change; stdin is the new clipboard content
_WRITER = ["sh", "-c", "cat; printf '\\000'"]


def add_entry(history: list[str], text: str, limit: int = LIMIT) -> bool:
    """Put text at the top of history. Returns False when it is ignored."""
    if not text.strip() or len(text) > MAX_CHARS:
        return False
    if history and history[0] == text:
        return False
    if text in history:
        history.remove(text)
    history.insert(0, text)
    del history[limit:]
    return True


def preview(text: str, width: int = 60) -> str:
    """One line for the list: whitespace collapsed, long text cut."""
    line = " ".join(text.split())
    return line if len(line) <= width else line[:width - 1] + "…"


class ClipboardService(GObject.Object):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__()
        self.history: list[str] = []
        self.available = shutil.which("wl-paste") is not None
        self._proc: Gio.Subprocess | None = None
        self._stream: Gio.DataInputStream | None = None
        self._cancel = Gio.Cancellable()
        if self.available:
            self._start()

    def _start(self):
        argv = ["wl-paste", "--no-newline", "--type", "text", "--watch",
                *_WRITER]
        try:
            self._proc = Gio.Subprocess.new(
                argv, Gio.SubprocessFlags.STDOUT_PIPE
                | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error:
            self.available = False
            return
        self._stream = Gio.DataInputStream.new(self._proc.get_stdout_pipe())
        self._read_next()

    def _read_next(self):
        self._stream.read_upto_async("\0", 1, GLib.PRIORITY_DEFAULT,
                                     self._cancel, self._on_entry)

    def _on_entry(self, stream, result):
        try:
            text, _length = stream.read_upto_finish(result)
            if text is None:
                return  # wl-paste exited
            stream.read_byte(None)  # consume the NUL separator
        except GLib.Error:
            return
        if add_entry(self.history, text):
            self.emit("changed")
        self._read_next()

    def copy(self, text: str):
        """Put an older entry back on the clipboard."""
        try:
            Gio.Subprocess.new(["wl-copy", "--", text], Gio.SubprocessFlags.NONE)
        except GLib.Error:
            pass

    def clear(self):
        self.history.clear()
        self.emit("changed")

    def stop(self):
        self._cancel.cancel()
        if self._proc is not None:
            self._proc.force_exit()
            self._proc = None
