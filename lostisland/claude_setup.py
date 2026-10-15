"""Install / remove the Claude Code statusLine hook.

The claude face needs live usage data. Claude Code hands that to a statusLine
command, so we drop a standalone copy of the hook next to the user's config
and register it in ~/.claude/settings.json. No login, no API — the data rides
in on stdin. settings.json is backed up before it's touched.
"""

from __future__ import annotations

import json
import os
import shutil
import time

from lostisland import config

CLAUDE_DIR = os.path.expanduser("~/.claude")
SETTINGS = os.path.join(CLAUDE_DIR, "settings.json")
HOOK_DEST = os.path.join(config.CONFIG_DIR, "claude-usage-hook.py")
MARKER = "claude-usage-hook.py"


def _hook_source() -> str:
    with open(os.path.join(os.path.dirname(__file__), "claude_hook.py")) as f:
        return f.read()


def install() -> str:
    if not os.path.isdir(CLAUDE_DIR):
        return (f"Claude Code config not found at {CLAUDE_DIR}. "
                "Install/run Claude Code first, then re-run this.")

    os.makedirs(config.CONFIG_DIR, exist_ok=True)
    with open(HOOK_DEST, "w") as f:
        f.write(_hook_source())
    os.chmod(HOOK_DEST, 0o755)

    try:
        with open(SETTINGS) as f:
            settings = json.load(f)
    except (OSError, ValueError):
        settings = {}

    existing = settings.get("statusLine")
    if isinstance(existing, dict):
        cmd = existing.get("command", "")
        if cmd and MARKER not in cmd:
            return (
                "You already have a statusLine set:\n"
                f"  {cmd}\n"
                "Not overwriting it. To combine them, have that script also run:\n"
                f"  python3 {HOOK_DEST}\n"
                "(it reads the same stdin and just writes the usage cache).")

    if os.path.exists(SETTINGS):
        shutil.copy2(SETTINGS, SETTINGS + f".bak-lostisland-{int(time.time())}")

    settings["statusLine"] = {
        "type": "command",
        "command": f"python3 {HOOK_DEST}",
        "padding": 0,
    }
    with open(SETTINGS, "w") as f:
        json.dump(settings, f, indent=2)

    # make sure the face is actually in the cycle
    cfg = config.load()
    faces = cfg.get("pill_faces", [])
    if "claude" not in faces:
        faces.append("claude")
        cfg["pill_faces"] = faces
        config.save(cfg)

    return ("Claude usage hook installed.\n"
            f"  hook:     {HOOK_DEST}\n"
            f"  statusLine registered in {SETTINGS}\n"
            "Open a Claude Code session once so the first numbers land, then "
            "cycle the pill to the Claude face.")


def uninstall() -> str:
    try:
        with open(SETTINGS) as f:
            settings = json.load(f)
    except (OSError, ValueError):
        return "Nothing to remove."
    sl = settings.get("statusLine")
    if isinstance(sl, dict) and MARKER in sl.get("command", ""):
        shutil.copy2(SETTINGS, SETTINGS + f".bak-lostisland-{int(time.time())}")
        settings.pop("statusLine", None)
        with open(SETTINGS, "w") as f:
            json.dump(settings, f, indent=2)
        return "Claude usage hook removed from settings.json."
    return "The statusLine isn't ours — left it untouched."


# -- live status hooks (the pill's Claude activity) --------------------------

STATUS_HOOK_DEST = os.path.join(config.CONFIG_DIR, "claude-status-hook.py")
STATUS_MARKER = "claude-status-hook.py"
STATUS_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse",
                 "PostToolUse", "PermissionRequest", "Notification", "Stop",
                 "PreCompact", "SessionEnd")
_TOOL_EVENTS = ("PreToolUse", "PostToolUse", "PermissionRequest")


def merge_status_hooks(settings: dict, command: str) -> dict:
    """Add our hook to every status event, keeping the user's own hooks and
    never adding it twice."""
    hooks = settings.setdefault("hooks", {})
    for event in STATUS_EVENTS:
        groups = hooks.setdefault(event, [])
        if any(STATUS_MARKER in h.get("command", "")
               for g in groups for h in g.get("hooks", [])):
            continue
        group = {"hooks": [{"type": "command", "command": command,
                            "timeout": 5}]}
        if event in _TOOL_EVENTS:
            group = {"matcher": "*", **group}
        groups.append(group)
    return settings


def strip_status_hooks(settings: dict) -> dict:
    hooks = settings.get("hooks", {})
    for event in list(hooks):
        kept = []
        for group in hooks[event]:
            inner = [h for h in group.get("hooks", [])
                     if STATUS_MARKER not in h.get("command", "")]
            if inner:
                kept.append({**group, "hooks": inner})
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event)
    if not hooks:
        settings.pop("hooks", None)
    return settings


def _read_settings() -> dict:
    try:
        with open(SETTINGS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write_settings(settings: dict):
    if os.path.exists(SETTINGS):
        shutil.copy2(SETTINGS, SETTINGS + f".bak-lostisland-{int(time.time())}")
    tmp = SETTINGS + ".tmp-lostisland"
    with open(tmp, "w") as f:
        json.dump(settings, f, indent=2)
    os.replace(tmp, SETTINGS)


def install_status() -> str:
    if not os.path.isdir(CLAUDE_DIR):
        return (f"Claude Code config not found at {CLAUDE_DIR}. "
                "Run Claude Code once, then run this again.")
    os.makedirs(config.CONFIG_DIR, exist_ok=True)
    with open(os.path.join(os.path.dirname(__file__),
                           "claude_status_hook.py")) as f:
        source = f.read()
    with open(STATUS_HOOK_DEST, "w") as f:
        f.write(source)
    os.chmod(STATUS_HOOK_DEST, 0o755)
    _write_settings(merge_status_hooks(_read_settings(),
                                       f"python3 {STATUS_HOOK_DEST}"))
    return ("Claude status hooks installed.\n"
            f"  hook: {STATUS_HOOK_DEST}\n"
            f"  events registered in {SETTINGS}\n"
            "New Claude Code sessions now show their status on the island.")


def uninstall_status() -> str:
    settings = _read_settings()
    if not settings.get("hooks"):
        return "Nothing to remove."
    _write_settings(strip_status_hooks(settings))
    return "Claude status hooks removed from settings.json."
