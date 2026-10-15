"""Which controls the card shows, and in what order.

The order lives in config as `controls` (the round buttons) and `launchers`
(the app buttons). Edit mode in the card adds, removes and drags items; these
helpers keep that list valid. No GTK here, so the rules are unit tested.
"""

from __future__ import annotations

# key: (Material symbol, caption)
CONTROLS = {
    "wifi": ("wifi", "Wi-Fi"),
    "bluetooth": ("bluetooth", "Bluetooth"),
    "sound": ("volume_up", "Sound"),
    "mic": ("mic", "Mic"),
    "focus": ("do_not_disturb_on", "Focus"),
    "airplay": ("airplay", "AirPlay"),
    "screen": ("screenshot_monitor", "Screen"),
    "area": ("screenshot_region", "Area"),
    "color": ("colorize", "Color"),
    "record": ("videocam", "Record"),
    "clipboard": ("content_paste", "Clipboard"),
    "lock": ("lock", "Lock"),
    "power": ("power_settings_new", "Power"),
    "timer": ("timer", "Timer"),
    "settings": ("settings", "Settings"),
}

# switches on the first row, tools on the second; Power sits in the footer
DEFAULT_CONTROLS = ["wifi", "bluetooth", "sound", "mic", "focus", "airplay",
                    "screen", "area", "color", "record", "clipboard", "lock"]

LAUNCHERS = {
    # key: (label, svg asset, command)
    "claude": ("Claude", "claude.svg", "claude"),
    "codex": ("Codex", "codex.svg", "codex"),
    "cursor": ("Cursor", "cursor.svg", "cursor-agent"),
}
DEFAULT_LAUNCHERS = ["claude", "codex", "cursor"]

COLUMNS = 6


def normalize(layout, available) -> list[str]:
    """Known, available keys in their saved order, each once."""
    seen: list[str] = []
    for key in layout if isinstance(layout, list) else []:
        if key in available and key not in seen:
            seen.append(key)
    return seen


def hidden(layout: list[str], available) -> list[str]:
    return [key for key in available if key not in layout]


def remove(layout: list[str], key: str) -> list[str]:
    return [k for k in layout if k != key]


def add(layout: list[str], key: str) -> list[str]:
    return layout if key in layout else [*layout, key]


def move(layout: list[str], key: str, before: str | None) -> list[str]:
    """Move `key` in front of `before`; None or an unknown target moves it
    to the end. Dropping onto itself changes nothing."""
    if key not in layout or key == before:
        return list(layout)
    rest = [k for k in layout if k != key]
    if before in rest:
        index = rest.index(before)
        # dragging forward lands after the target, like iOS and macOS
        if layout.index(key) < layout.index(before):
            index += 1
        return [*rest[:index], key, *rest[index:]]
    return [*rest, key]
