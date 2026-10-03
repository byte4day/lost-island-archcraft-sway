#!/usr/bin/env python3
"""Claude Code statusLine hook.

Claude Code (>= 2.1) pipes a JSON blob to the statusLine command on stdin. For
Pro/Max subscribers that blob carries the live rate-limit usage — the same
numbers `/usage` shows — with no API call and no login. This reads the
5-hour session and 7-day figures, stashes them where the island can find
them, and prints a compact status line.

Self-contained (stdlib only) so it works as a standalone copy dropped next to
the user's Claude config.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime

CACHE_DIR = os.path.join(
    os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
    "lost-island",
)
CACHE_PATH = os.path.join(CACHE_DIR, "claude-usage.json")


def _epoch(iso: str) -> float:
    if not iso:
        return 0.0
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _fmt_reset(epoch: float) -> str:
    if epoch <= 0:
        return ""
    left = int(epoch - time.time())
    if left <= 0:
        return "resetting"
    h, m = divmod(left // 60, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (ValueError, OSError):
        data = {}

    limits = data.get("rate_limits") or {}
    five = limits.get("five_hour") or {}
    week = limits.get("seven_day") or {}

    session_pct = five.get("used_percentage")
    weekly_pct = week.get("used_percentage")
    session_reset = _epoch(five.get("resets_at", ""))
    weekly_reset = _epoch(week.get("resets_at", ""))

    # only overwrite the cache when we actually got fresh limit data, so a
    # session without rate_limits (API users, older CC) doesn't wipe it
    if session_pct is not None:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = CACHE_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump({
                "session_pct": session_pct,
                "session_reset": session_reset,
                "weekly_pct": weekly_pct,
                "weekly_reset": weekly_reset,
                "updated": time.time(),
            }, f)
        os.replace(tmp, CACHE_PATH)

    # the status line itself
    model = ((data.get("model") or {}).get("display_name")) or ""
    cwd = (data.get("workspace") or {}).get("current_dir") \
        or data.get("cwd") or ""
    parts = []
    if session_pct is not None:
        reset = _fmt_reset(session_reset)
        seg = f"◐ 5h {session_pct:.0f}%"
        if reset:
            seg += f" ({reset})"
        parts.append(seg)
    if weekly_pct is not None:
        parts.append(f"wk {weekly_pct:.0f}%")
    if model:
        parts.append(model)
    if cwd:
        parts.append(os.path.basename(cwd.rstrip("/")) or cwd)
    sys.stdout.write("   ".join(parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
