"""Desktop utilities behind the island's tools row.

Screenshots (grim/slurp), color picking (hyprpicker), mako's Do Not Disturb
mode and the session power actions. Every command is an argv list run
asynchronously with a bound on how long it may take; nothing goes through a
shell.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from gi.repository import Gio, GLib

DND_MODE = "do-not-disturb"
SWAY_LOCK_SCRIPT = Path.home() / ".config/sway/scripts/current_lock"
_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def screenshots_dir() -> Path:
    pictures = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
    return Path(pictures or Path.home() / "Pictures") / "Screenshots"


def screenshot_path(now: datetime | None = None) -> Path:
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")
    return screenshots_dir() / f"Screenshot_{stamp}.png"


def focused_output(outputs_json: str) -> str | None:
    """Name of the focused output from `swaymsg -t get_outputs -r`."""
    try:
        outputs = json.loads(outputs_json)
    except ValueError:
        return None
    if not isinstance(outputs, list):
        return None
    for output in outputs:
        if isinstance(output, dict) and output.get("focused"):
            return output.get("name")
    return None


def parse_color(output: str) -> str | None:
    match = _HEX.search(output)
    return match.group(0).upper() if match else None


def parse_modes(output: str) -> set[str]:
    return {line.strip() for line in output.splitlines() if line.strip()}


def lock_command() -> list[str]:
    if os.access(SWAY_LOCK_SCRIPT, os.X_OK):
        return [str(SWAY_LOCK_SCRIPT)]
    return ["swaylock", "-f"]


POWER_ACTIONS = {
    # name: (label, Material symbol, argv, needs confirmation)
    "lock": ("Lock", "lock", None, False),
    "logout": ("Log out", "logout", ["swaymsg", "exit"], True),
    "suspend": ("Sleep", "bedtime", ["systemctl", "suspend"], True),
    "reboot": ("Restart", "restart_alt", ["systemctl", "reboot"], True),
    "poweroff": ("Shut down", "power_settings_new",
                 ["systemctl", "poweroff"], True),
}


def power_command(name: str) -> list[str]:
    _label, _icon, argv, _confirm = POWER_ACTIONS[name]
    return lock_command() if argv is None else list(argv)


def run(argv: list[str], callback: Callable[[bool, str], None] | None = None,
        timeout_s: int = 6, stdin_path: str | None = None) -> None:
    """Run argv without a shell; callback(success, stdout) on the main loop."""
    callback = callback or (lambda _ok, _out: None)
    if not shutil.which(argv[0]):
        print(f"lost-island: {argv[0]} is not installed", file=sys.stderr)
        callback(False, "")
        return
    launcher = Gio.SubprocessLauncher.new(
        Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)
    if stdin_path:
        launcher.set_stdin_file_path(stdin_path)
    try:
        proc = launcher.spawnv(argv)
    except GLib.Error as exc:
        print(f"lost-island: {argv[0]}: {exc.message}", file=sys.stderr)
        callback(False, "")
        return

    finished = False

    def on_timeout() -> bool:
        nonlocal finished
        if not finished:
            finished = True
            proc.force_exit()
            print(f"lost-island: {argv[0]} timed out", file=sys.stderr)
            callback(False, "")
        return False

    timeout_id = GLib.timeout_add_seconds(timeout_s, on_timeout)

    def done(process: Gio.Subprocess, result: Gio.AsyncResult) -> None:
        nonlocal finished
        if finished:
            return
        finished = True
        GLib.source_remove(timeout_id)
        try:
            _ok, out, err = process.communicate_utf8_finish(result)
            success = process.get_successful()
        except GLib.Error as exc:
            out, err, success = "", exc.message, False
        if not success and (err or "").strip():
            print(f"lost-island: {argv[0]}: {err.strip()}", file=sys.stderr)
        callback(success, out or "")

    proc.communicate_utf8_async(None, None, done)


def spawn_detached(argv: list[str]) -> bool:
    """Start a long-lived program (a locker) without waiting for it."""
    if not shutil.which(argv[0]) and not os.access(argv[0], os.X_OK):
        return False
    try:
        Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE)
    except GLib.Error:
        return False
    return True
