"""Wallpaper library: list a folder, make small thumbnails, set the wallpaper.

The idea comes from Tide Island's wallpaper switcher; this is a fresh
implementation for Sway. Setting a wallpaper picks the first backend that
works:

- a custom command from config (gets the image path as $1),
- awww or swww when their daemon is running (animated transition),
- Sway itself (`output * bg`), which also rewrites the `output * bg` line in
  the persist file so the choice survives a reload or reboot.

Thumbnails are JPEGs in ~/.cache/lost-island/wallpapers, keyed by path,
modification time and size, so a changed file gets a new one. They are made
on a worker thread one at a time and handed back on the main loop.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import threading
from collections.abc import Callable

from gi.repository import GdkPixbuf, Gio, GLib, GObject

from lostisland.config import CACHE_DIR

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".tif",
              ".tiff", ".bmp", ".jxl"}
THUMB_W, THUMB_H = 320, 184
THUMB_DIR = os.path.join(CACHE_DIR, "wallpapers")
FILL_MODES = ("fill", "fit", "stretch", "center", "tile")
TRANSITIONS = ("simple", "fade", "left", "right", "top", "bottom", "wipe",
               "wave", "grow", "center", "any", "outer", "random")
DEFAULTS = {
    "folder": "~/Pictures/Wallpapers",
    # auto | sway | awww | swww | command
    "backend": "auto",
    # shell command for the "command" backend; the image path is $1
    "command": "",
    "fill": "fill",
    # awww / swww transition
    "transition": "grow",
    # Sway file whose `output * bg` line is kept in step ("" = don't)
    "persist": "~/.config/sway/wallpaper.conf",
    # run pywal on the new wallpaper to recolor the terminal theme
    "pywal": False,
}
_BG_LINE = re.compile(r'^\s*output\s+\*\s+bg\s+(?:"((?:[^"\\]|\\.)*)"|(\S+))',
                      re.MULTILINE)


def settings(cfg: dict) -> dict:
    out = dict(DEFAULTS)
    saved = cfg.get("wallpaper")
    if isinstance(saved, dict):
        out.update({k: v for k, v in saved.items() if k in DEFAULTS})
    if out["fill"] not in FILL_MODES:
        out["fill"] = "fill"
    if out["transition"] not in TRANSITIONS:
        out["transition"] = "grow"
    return out


def scan(folder: str) -> list[str]:
    """Image files directly in `folder`, sorted by name, case-insensitive."""
    folder = os.path.expanduser(folder)
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return []
    found = [e.path for e in entries
             if os.path.splitext(e.name)[1].lower() in EXTENSIONS
             and e.is_file()]
    return sorted(found, key=lambda p: os.path.basename(p).lower())


def matches(path: str, query: str) -> bool:
    query = query.strip().lower()
    return not query or query in os.path.basename(path).lower()


def thumb_path(path: str, cache_dir: str = THUMB_DIR) -> str | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = f"{path}|{st.st_mtime_ns}|{st.st_size}|{THUMB_W}x{THUMB_H}"
    digest = hashlib.sha1(key.encode("utf-8", "surrogateescape")).hexdigest()
    return os.path.join(cache_dir, f"wp-{digest[:24]}.jpg")


def make_thumb(path: str, dest: str) -> bool:
    """Scale to cover THUMB_W x THUMB_H, centre-crop, save as JPEG."""
    try:
        src = GdkPixbuf.Pixbuf.new_from_file_at_scale(
            path, THUMB_W * 3, THUMB_H * 3, True)
    except GLib.Error:
        return False
    w, h = src.get_width(), src.get_height()
    scale = max(THUMB_W / w, THUMB_H / h)
    sw, sh = max(THUMB_W, round(w * scale)), max(THUMB_H, round(h * scale))
    scaled = src.scale_simple(sw, sh, GdkPixbuf.InterpType.BILINEAR)
    crop = scaled.new_subpixbuf((sw - THUMB_W) // 2, (sh - THUMB_H) // 2,
                                THUMB_W, THUMB_H)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".tmp"
    try:
        crop.savev(tmp, "jpeg", ["quality"], ["85"])
        os.replace(tmp, dest)
    except (GLib.Error, OSError):
        return False
    return True


def _sway_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def sway_bg_line(path: str, fill: str = "fill") -> str:
    return f"output * bg {_sway_quote(path)} {fill}"


def read_bg_line(text: str) -> str:
    """The image of the first `output * bg` line, or ""."""
    m = _BG_LINE.search(text)
    if not m:
        return ""
    if m.group(1) is not None:
        return re.sub(r"\\(.)", r"\1", m.group(1))
    return os.path.expanduser(m.group(2))


def replace_bg_line(text: str, path: str, fill: str = "fill") -> str:
    """Swap the `output * bg` line for one with `path`, or append one."""
    line = sway_bg_line(path, fill)
    pattern = re.compile(r"^\s*output\s+\*\s+bg\s+.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(lambda _m: line, text, count=1)
    if text and not text.endswith("\n"):
        text += "\n"
    return text + line + "\n"


def current(cfg: dict) -> str:
    """Best guess at the wallpaper on screen right now."""
    persist = os.path.expanduser(settings(cfg)["persist"] or "")
    if persist:
        try:
            with open(persist) as f:
                found = read_bg_line(f.read())
            if found:
                return found
        except OSError:
            pass
    # Sway runs swaybg with `-i <image>`
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    argv = f.read().split(b"\0")
            except OSError:
                continue
            if argv and os.path.basename(argv[0]) == b"swaybg" and b"-i" in argv:
                i = argv.index(b"-i")
                if i + 1 < len(argv):
                    return argv[i + 1].decode("utf-8", "surrogateescape")
    except OSError:
        pass
    return ""


def commands(path: str, opts: dict, backend: str) -> list[list[str]]:
    """The commands that set `path` with `backend`, in order."""
    if backend == "command":
        return [["sh", "-c", opts["command"], "lost-island-wallpaper", path]]
    if backend in ("awww", "swww"):
        return [[backend, "img", path,
                 "--transition-type", opts["transition"],
                 "--transition-pos", "top",
                 "--transition-duration", "1.2",
                 "--transition-fps", "60"]]
    return [["swaymsg", sway_bg_line(path, opts["fill"])]]


def pick_backend(opts: dict) -> str:
    wanted = opts["backend"]
    if wanted == "command" or (wanted == "auto" and opts["command"].strip()):
        return "command" if opts["command"].strip() else "sway"
    if wanted in ("sway", "awww", "swww"):
        return wanted
    for daemon in ("awww", "swww"):
        if shutil.which(daemon) and _daemon_running(daemon):
            return daemon
    return "sway"


def _daemon_running(name: str) -> bool:
    try:
        proc = Gio.Subprocess.new([name, "query"],
                                  Gio.SubprocessFlags.STDOUT_SILENCE
                                  | Gio.SubprocessFlags.STDERR_SILENCE)
        proc.wait(None)
        return proc.get_exit_status() == 0
    except GLib.Error:
        return False


def persist(path: str, opts: dict) -> None:
    """Rewrite the persist file's bg line; back it up once beforehand."""
    target = os.path.expanduser(opts["persist"] or "")
    if not target:
        return
    try:
        with open(target) as f:
            text = f.read()
    except FileNotFoundError:
        text = ""
    except OSError:
        return
    backup = target + ".pre-lost-island"
    if text and not os.path.exists(backup):
        try:
            shutil.copy2(target, backup)
        except OSError:
            pass
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w") as f:
        f.write(replace_bg_line(text, path, opts["fill"]))
    os.replace(tmp, target)


class WallpaperService(GObject.Object):
    """Folder listing, thumbnail queue and the apply step for the card."""

    __gsignals__ = {
        # path of the image whose thumbnail is now on disk
        "thumb-ready": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        # path, ok, message
        "applied": (GObject.SignalFlags.RUN_FIRST, None, (str, bool, str)),
    }

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self.active = current(cfg)
        self._queue: list[str] = []
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._busy = False

    @property
    def opts(self) -> dict:
        return settings(self.cfg)

    @property
    def folder(self) -> str:
        return os.path.expanduser(self.opts["folder"])

    def list(self) -> list[str]:
        return scan(self.folder)

    def thumb(self, path: str) -> str | None:
        """Cached thumbnail path if it exists; otherwise queue one."""
        dest = thumb_path(path)
        if dest is None:
            return None
        if os.path.isfile(dest):
            return dest
        with self._lock:
            if path not in self._queue:
                self._queue.append(path)
            if self._worker is None:
                self._worker = threading.Thread(target=self._work,
                                                daemon=True)
                self._worker.start()
        return None

    def prioritise(self, paths: list[str]):
        """Make the thumbnails the user can see first."""
        with self._lock:
            ahead = [p for p in paths if p in self._queue]
            self._queue = ahead + [p for p in self._queue if p not in ahead]

    def _work(self):
        while True:
            with self._lock:
                if not self._queue:
                    self._worker = None
                    return
                path = self._queue.pop(0)
            dest = thumb_path(path)
            if dest and make_thumb(path, dest):
                GLib.idle_add(self._emit_thumb, path)

    def _emit_thumb(self, path: str):
        self.emit("thumb-ready", path)
        return GLib.SOURCE_REMOVE

    def apply(self, path: str):
        if self._busy or not path:
            return
        opts = self.opts
        backend = pick_backend(opts)
        steps = commands(path, opts, backend)
        if opts.get("pywal") and shutil.which("wal"):
            steps.append(["wal", "-n", "-q", "-i", path])
        self._busy = True
        self._run(steps, path, backend, opts)

    def _run(self, steps: list[list[str]], path: str, backend: str,
             opts: dict):
        if not steps:
            self._finish(path, True, "", backend, opts)
            return
        argv, rest = steps[0], steps[1:]
        try:
            proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_SILENCE
                                      | Gio.SubprocessFlags.STDERR_PIPE)
        except GLib.Error as err:
            self._finish(path, False, f"{argv[0]}: {err.message}", backend,
                         opts)
            return

        def done(proc, result):
            try:
                _ok, _out, err = proc.communicate_utf8_finish(result)
            except GLib.Error as e:
                err = e.message
            if proc.get_exit_status() != 0:
                line = (err or "").strip().splitlines()
                self._finish(path, False,
                             line[-1] if line else f"{argv[0]} failed",
                             backend, opts)
                return
            self._run(rest, path, backend, opts)

        proc.communicate_utf8_async(None, None, done)

    def _finish(self, path: str, ok: bool, message: str, backend: str,
                opts: dict):
        self._busy = False
        if ok:
            self.active = path
            if backend == "sway":
                try:
                    persist(path, opts)
                except OSError as err:
                    message = f"Set, but not saved: {err.strerror}"
        self.emit("applied", path, ok, message)


def open_folder(folder: str, on_error: Callable[[str], None] | None = None):
    try:
        Gio.AppInfo.launch_default_for_uri(
            GLib.filename_to_uri(os.path.expanduser(folder)), None)
    except GLib.Error as err:
        if on_error:
            on_error(err.message)
