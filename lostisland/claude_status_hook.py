#!/usr/bin/env python3
"""Claude Code hook that feeds the island's live Claude status.

Claude Code runs this on session events with a JSON payload on stdin. It
writes one small state file per session to
~/.cache/lost-island/claude-status/<session>.json and prints nothing, so it
never adds text to the conversation. It always exits 0 and never blocks.

Standard library only: `lost-island --setup-claude-status` copies it next to
the island config so it keeps working without the checkout on PYTHONPATH.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

STATUS_DIR = os.path.join(
    os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
    "lost-island", "claude-status",
)

# Notification messages that only mean "the session is idle"
_IDLE_TYPES = {"idle_prompt", "auth_success"}


def _short(text: str, limit: int = 38) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def tool_detail(name: str, args: dict) -> str:
    """A few words that say what a tool call is doing."""
    args = args if isinstance(args, dict) else {}
    if name == "Bash":
        return _short(args.get("description") or args.get("command") or "Running")
    for key in ("file_path", "notebook_path", "path"):
        if args.get(key):
            return f"{name} {os.path.basename(str(args[key]).rstrip('/'))}"
    if args.get("pattern"):
        return _short(f"{name} {args['pattern']}")
    if args.get("url"):
        host = re.sub(r"^https?://", "", str(args["url"])).split("/")[0]
        return f"{name} {host}"
    if args.get("query"):
        return _short(f"{name} {args['query']}")
    if args.get("description"):
        return _short(args["description"])
    if name.startswith("mcp__"):
        return _short(name.split("__")[-1].replace("_", " "))
    return name


def state_for(payload: dict) -> tuple[str, str] | None:
    """Map one hook payload to (state, detail); None leaves the file alone,
    ("ended", "") removes it."""
    event = payload.get("hook_event_name", "")
    if event == "SessionStart":
        return "idle", ""
    if event == "UserPromptSubmit":
        return "thinking", "Thinking"
    if event == "PreToolUse":
        return "tool", tool_detail(payload.get("tool_name", ""),
                                   payload.get("tool_input") or {})
    if event in ("PostToolUse", "PostToolUseFailure"):
        return "thinking", "Thinking"
    if event == "PreCompact":
        return "thinking", "Compacting"
    if event == "PermissionRequest":
        return "needs", _short(f"Allow {payload.get('tool_name') or 'tool'}?")
    if event == "Notification":
        kind = payload.get("notification_type", "")
        message = payload.get("message", "")
        if kind in _IDLE_TYPES or "waiting for your input" in message.lower():
            return None
        if kind == "permission_prompt" or "permission" in message.lower():
            match = re.search(r"use (\S+)", message)
            tool = match.group(1) if match else "a tool"
            return "needs", f"Allow {tool}?"
        return "needs", _short(message or "Needs you")
    if event == "Stop":
        return "done", "Done"
    if event == "SessionEnd":
        return "ended", ""
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    session = re.sub(r"[^A-Za-z0-9_-]", "", str(payload.get("session_id", "")))
    result = state_for(payload) if session else None
    if result is None:
        return 0
    state, detail = result
    path = os.path.join(STATUS_DIR, f"{session}.json")
    try:
        if state == "ended":
            os.unlink(path)
            return 0
        os.makedirs(STATUS_DIR, exist_ok=True)
        cwd = payload.get("cwd") or ""
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({
                "session": session,
                "state": state,
                "detail": detail,
                "project": os.path.basename(cwd.rstrip("/")) or cwd,
                # the hook's parent is Claude Code (or a shell it started);
                # the island walks up from here to find the terminal window
                "pid": os.getppid(),
                "updated": time.time(),
            }, f)
        os.replace(tmp, path)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
