"""Small, bounded command bridge for the island's system controls."""

from __future__ import annotations

import re
import sys
from collections.abc import Callable

from gi.repository import Gio, GLib


def parse_wifi_state(output: str) -> bool | None:
    value = output.strip().lower()
    if value == "enabled":
        return True
    if value == "disabled":
        return False
    return None


def parse_bluetooth_state(output: str) -> bool | None:
    # rfkill reports the adapter even when BlueZ hides a blocked controller.
    devices = [line.split() for line in output.splitlines() if line.strip()]
    usable = [parts[0] for parts in devices
              if len(parts) == 2 and parts[1] == "unblocked"]
    return any(soft == "unblocked" for soft in usable) if usable else None


def parse_audio_state(output: str) -> bool | None:
    match = re.search(r"^Mute:\s*(yes|no)\s*$", output, re.MULTILINE)
    return match.group(1) == "no" if match else None


class SystemControls:
    """Reads and changes only the four controls shown in the expanded island."""

    READ = {
        "wifi": ["nmcli", "radio", "wifi"],
        "bluetooth": ["rfkill", "--noheadings", "--raw", "--output",
                      "SOFT,HARD", "list", "bluetooth"],
        "sound": ["pactl", "get-sink-mute", "@DEFAULT_SINK@"],
        "mic": ["pactl", "get-source-mute", "@DEFAULT_SOURCE@"],
    }
    PARSE = {
        "wifi": parse_wifi_state,
        "bluetooth": parse_bluetooth_state,
        "sound": parse_audio_state,
        "mic": parse_audio_state,
    }

    def read(self, name: str, callback: Callable[[bool | None], None]) -> None:
        self._run(self.READ[name], lambda ok, out: callback(
            self.PARSE[name](out) if ok else None), report_errors=False)

    def set(self, name: str, enabled: bool, callback: Callable[[bool], None]) -> None:
        if name == "wifi":
            command = ["nmcli", "radio", "wifi", "on" if enabled else "off"]
        elif name == "bluetooth":
            command = ["rfkill", "unblock" if enabled else "block",
                       "bluetooth"]
        elif name == "sound":
            command = ["pactl", "set-sink-mute", "@DEFAULT_SINK@",
                       "0" if enabled else "1"]
        elif name == "mic":
            command = ["pactl", "set-source-mute", "@DEFAULT_SOURCE@",
                       "0" if enabled else "1"]
        else:
            raise ValueError(f"Unknown control: {name}")
        self._run(command, lambda ok, _out: callback(ok))

    @staticmethod
    def _run(command: list[str], callback: Callable[[bool, str], None],
             report_errors: bool = True) -> None:
        try:
            proc = Gio.Subprocess.new(
                command, Gio.SubprocessFlags.STDOUT_PIPE |
                Gio.SubprocessFlags.STDERR_PIPE)
        except GLib.Error as exc:
            if report_errors:
                print(f"lost-island: {command[0]}: {exc}", file=sys.stderr)
            callback(False, "")
            return

        finished = False

        def timeout() -> bool:
            nonlocal finished
            if not finished:
                finished = True
                proc.force_exit()
                if report_errors:
                    print(f"lost-island: {command[0]} timed out", file=sys.stderr)
                callback(False, "")
            return False

        timeout_id = GLib.timeout_add_seconds(6, timeout)

        def completed(process: Gio.Subprocess, result: Gio.AsyncResult) -> None:
            nonlocal finished
            if finished:
                return
            finished = True
            GLib.source_remove(timeout_id)
            try:
                _ok, out, err = process.communicate_utf8_finish(result)
                success = process.get_successful()
            except GLib.Error as exc:
                out, err, success = "", str(exc), False
            if not success and report_errors:
                detail = (err or "").strip() or f"exit {process.get_exit_status()}"
                print(f"lost-island: {command[0]}: {detail}", file=sys.stderr)
            callback(success, out or "")

        proc.communicate_utf8_async(None, None, completed)
