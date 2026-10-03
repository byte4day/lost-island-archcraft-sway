"""User configuration, stored as plain JSON in ~/.config/lost-island/config.json.

Missing keys fall back to defaults, so upgrades never break an old config.
"""

from __future__ import annotations

import json
import os

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
        "lyrics": False,
    },
    # weather location ("" = auto by IP); any wttr.in place name works
    "weather_city": "",
    # accent color used for progress bars and highlights
    "accent": "#CFD2D6",
}


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
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
        return dict(DEFAULTS)


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
