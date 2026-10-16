"""User configuration, stored as plain JSON in ~/.config/lost-island/config.json.

Missing keys fall back to defaults, so upgrades never break an old config.
"""

from __future__ import annotations

import copy
import json
import os

from lostisland.ui.layout import DEFAULT_CONTROLS, DEFAULT_LAUNCHERS

CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "lost-island"
)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
CACHE_DIR = os.path.join(
    os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "lost-island"
)

DEFAULTS = {
    # top margin in px between screen edge and the island
    "margin_top": 6,
    # sit on top of panels/bars instead of being pushed below them
    "overlap_panel": False,
    # keep a strip at the top free so windows start below the pill
    # (off: the pill floats over windows and they get the full height)
    "reserve_space": False,
    # "island" floats below the edge; "notch" hangs from it, MacBook style
    "shape": "island",
    # monitor connector name ("" = primary / compositor default)
    "monitor": "",
    # "top" stays below fullscreen apps, "overlay" is always on top
    "layer": "top",
    # show the clock in the idle pill
    "idle_clock": True,
    # current collapsed face; cycled by click / swipe
    "pill_face": "auto",
    # faces included in the cycle, in order; available: auto, status,
    # lyrics, title, compact, clock, battery, weather, bluetooth, claude
    "pill_faces": ["auto", "title", "compact", "clock"],
    # how often (seconds) the claude face refreshes its usage figure
    # (the usage endpoint rate-limits fast polling, so keep this gentle)
    "claude_refresh": 60,
    # what a left click on the pill does: "cycle" faces or "expand" the card
    # (right click always expands)
    "click_action": "expand",
    # island background opacity, 0.3 .. 1.0
    "opacity": 1.0,
    # 24h clock
    "clock_24h": False,
    # small battery readout in the pill while charging or below 30%
    "pill_battery": False,
    # seconds a peek (volume / battery / notification) stays visible
    "peek_seconds": 1.6,
    # modules that may take over the island
    "modules": {
        "music": True,
        "volume_osd": True,
        "battery": True,
        "notifications": True,
        "network": True,
        "bluetooth": True,
        "weather": False,
        "system": False,
        "toggles": True,
        "tools": True,
        "clipboard": True,
        "lyrics": False,
        "claude_status": True,
        "transfers": True,
        "indicators": True,
        "wallpaper": True,
    },
    # round buttons in the card, in order (edit them in the card)
    "controls": list(DEFAULT_CONTROLS),
    # app launchers under the volume bar
    "launchers": list(DEFAULT_LAUNCHERS),
    # weather location ("" = auto by IP); any wttr.in place name works
    "weather_city": "",
    # accent color used for progress bars and highlights
    "accent": "#0A84FF",
    # focus timer length in minutes (scroll the timer tile to change)
    "timer_minutes": 25,
    # wallpaper picker (control "wallpaper", or `--wallpapers`)
    "wallpaper": {
        "folder": "~/Pictures/Wallpapers",
        # auto | sway | awww | swww | command
        "backend": "auto",
        # shell command for backend "command"; the image path is $1
        "command": "",
        # fill | fit | stretch | center | tile
        "fill": "fill",
        # awww/swww transition: grow, wipe, wave, fade, center, outer, ...
        "transition": "grow",
        # Sway file whose `output * bg` line follows the pick ("" = none)
        "persist": "~/.config/sway/wallpaper.conf",
        # recolor the terminal theme with pywal after setting it
        "pywal": False,
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            out[k] = _merge(base[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return _merge(DEFAULTS, json.load(f))
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULTS)


def write_default() -> str:
    """Write a commented default config if none exists; returns the path."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w") as f:
            json.dump(DEFAULTS, f, indent=2)
    return CONFIG_PATH


def save(cfg: dict) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
