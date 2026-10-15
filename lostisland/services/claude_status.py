"""Live Claude Code status, read from the files claude_status_hook.py writes.

A directory monitor picks up every change, so nothing polls while Claude is
quiet. A single timeout clears a finished session from the island a few
seconds after it ends.
"""

from __future__ import annotations

import json
import os
import time

from gi.repository import Gio, GLib, GObject

from lostisland.claude_status_hook import STATUS_DIR
from lostisland.services import tools

DONE_SECONDS = 8          # how long "Done" stays on the island
STALE_SECONDS = 30 * 60   # a working state with no event this long is dropped
_RANK = {"needs": 3, "tool": 2, "thinking": 2, "done": 1}


def visible_sessions(sessions: list[dict], now: float) -> list[dict]:
    """Sessions worth showing, most urgent first."""
    out = []
    for s in sessions:
        state = s.get("state")
        age = now - float(s.get("updated", 0))
        if state not in _RANK:
            continue
        if state == "done" and age > DONE_SECONDS:
            continue
        if state in ("thinking", "tool") and age > STALE_SECONDS:
            continue
        out.append(s)
    out.sort(key=lambda s: (_RANK[s["state"]], s.get("updated", 0)),
             reverse=True)
    return out


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


def ancestors(pid: int) -> list[int]:
    """pid and its parents up to init, read from /proc."""
    chain = []
    while pid > 1 and len(chain) < 64:
        chain.append(pid)
        try:
            with open(f"/proc/{pid}/stat") as f:
                stat = f.read()
            pid = int(stat.rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return chain


def window_for_pid(tree: dict, pid: int) -> int | None:
    """Sway con_id of the window owning `pid` or one of its parents."""
    by_pid: dict[int, int] = {}

    def walk(node):
        if node.get("pid"):
            by_pid.setdefault(node["pid"], node["id"])
        for child in node.get("nodes", []) + node.get("floating_nodes", []):
            walk(child)

    walk(tree)
    for p in ancestors(pid):
        if p in by_pid:
            return by_pid[p]
    return None


class ClaudeStatusService(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__()
        self.sessions: list[dict] = []
        self._expire = 0
        self._reload_src = 0
        os.makedirs(STATUS_DIR, exist_ok=True)
        self._monitor = Gio.File.new_for_path(STATUS_DIR).monitor_directory(
            Gio.FileMonitorFlags.NONE, None)
        self._monitor.connect("changed", lambda *_: self._queue_reload())
        self._reload()

    # -- state -------------------------------------------------------------

    @property
    def top(self) -> dict | None:
        return self.sessions[0] if self.sessions else None

    @property
    def working(self) -> int:
        return sum(s["state"] in ("thinking", "tool") for s in self.sessions)

    def _queue_reload(self):
        if not self._reload_src:
            self._reload_src = GLib.timeout_add(80, self._reload)

    def _reload(self) -> bool:
        self._reload_src = 0
        found = []
        try:
            names = os.listdir(STATUS_DIR)
        except OSError:
            names = []
        for name in names:
            if not name.endswith(".json"):
                continue
            path = os.path.join(STATUS_DIR, name)
            try:
                with open(path) as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue
            # Claude exited without SessionEnd (killed terminal): clean up
            if not _pid_alive(data.get("pid")):
                try:
                    os.unlink(path)
                except OSError:
                    pass
                continue
            found.append(data)
        self.sessions = visible_sessions(found, time.time())
        self._arm_expiry()
        self.emit("changed")
        return False

    def _arm_expiry(self):
        if self._expire:
            GLib.source_remove(self._expire)
            self._expire = 0
        done = [s for s in self.sessions if s["state"] == "done"]
        if done:
            left = min(DONE_SECONDS - (time.time() - s["updated"])
                       for s in done)
            self._expire = GLib.timeout_add(
                int(max(0.2, left) * 1000) + 50, self._on_expire)

    def _on_expire(self) -> bool:
        self._expire = 0
        self._reload()
        return False

    # -- actions -----------------------------------------------------------

    def focus(self, session: dict | None = None):
        """Bring the terminal running this Claude session to the front."""
        session = session or self.top
        if not session or not session.get("pid"):
            return

        def got_tree(ok: bool, out: str):
            if not ok:
                return
            try:
                con = window_for_pid(json.loads(out), int(session["pid"]))
            except (ValueError, TypeError):
                return
            if con is not None:
                tools.run(["swaymsg", f"[con_id={con}]", "focus"])

        tools.run(["swaymsg", "-t", "get_tree", "-r"], got_tree)
