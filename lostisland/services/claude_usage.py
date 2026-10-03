"""Claude usage service.

Primary source: Anthropic's usage endpoint, called with the OAuth token Claude
Code already stored locally (~/.claude/.credentials.json) — the same figures
`/usage` shows, fetched directly so the face is live without needing a
terminal session open. Fallback: the cache the statusLine hook writes (see
lostisland/claude_hook.py) for when the token is missing or expired.

The fetch runs on a background thread on a timer while the claude face is on
screen; nothing runs when the face isn't shown.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request

from gi.repository import GLib, GObject

from lostisland import config

CACHE_PATH = f"{config.CACHE_DIR}/claude-usage.json"
CREDENTIALS = os.path.expanduser("~/.claude/.credentials.json")
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
STALE_AFTER = 15 * 60


class ClaudeUsageService(GObject.Object):
    __gsignals__ = {
        # session %, weekly %, session reset epoch, stale
        "changed": (GObject.SignalFlags.RUN_FIRST, None, (int, int, float, bool)),
    }

    def __init__(self, refresh: int = 60):
        super().__init__()
        # the usage endpoint rate-limits aggressive callers (HTTP 429), and
        # the 5-hour number moves slowly, so keep the cadence gentle
        self.refresh = max(30, refresh)
        self.session_pct = -1
        self.weekly_pct = -1
        self.session_reset = 0.0
        self.updated = 0.0
        self._timer = 0
        self._busy = False
        self._cooldown_until = 0.0

    @property
    def available(self) -> bool:
        return self.session_pct >= 0

    @property
    def stale(self) -> bool:
        return self.updated > 0 and time.time() - self.updated > STALE_AFTER

    def start(self):
        if not self._timer:
            self.refresh_now()
            self._timer = GLib.timeout_add_seconds(self.refresh, self._tick)

    def stop(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _tick(self):
        self.refresh_now()
        return True

    def refresh_now(self):
        if self._busy or time.time() < self._cooldown_until:
            return
        self._busy = True
        threading.Thread(target=self._fetch, daemon=True).start()

    # -- background fetch ---------------------------------------------------

    def _fetch(self):
        # Prefer the statusLine cache: Claude Code pushes fresh numbers into it
        # for free while you're using it (no API call, no rate limit) — which
        # is exactly when usage moves. Only reach for the (rate-limited) API
        # when that cache is missing or has gone stale.
        cache = self._from_cache()
        if cache and time.time() - float(cache.get("updated", 0) or 0) < 120:
            data = cache
        else:
            data = self._from_api() or cache
        self._busy = False
        if data is None:
            return
        GLib.idle_add(self._apply, data)

    def _token(self) -> str | None:
        try:
            with open(CREDENTIALS) as f:
                return json.load(f)["claudeAiOauth"]["accessToken"]
        except (OSError, ValueError, KeyError):
            return None

    def _from_api(self):
        token = self._token()
        if not token:
            return None
        req = urllib.request.Request(USAGE_URL, headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                d = json.load(r)
        except urllib.error.HTTPError as e:
            # 429 (rate limited) or a hiccup: sit out a few cycles, keep the
            # value we already have rather than blanking it
            if e.code == 429:
                self._cooldown_until = time.time() + 5 * 60
            else:
                self._cooldown_until = time.time() + 60
            return None
        except Exception:
            self._cooldown_until = time.time() + 60
            return None
        five = d.get("five_hour") or {}
        week = d.get("seven_day") or {}
        if five.get("utilization") is None:
            return None
        return {
            "session_pct": five.get("utilization"),
            "session_reset": _epoch(five.get("resets_at", "")),
            "weekly_pct": week.get("utilization"),
            "updated": time.time(),
        }

    def _from_cache(self):
        try:
            with open(CACHE_PATH) as f:
                d = json.load(f)
        except (OSError, ValueError):
            return None
        return d

    def _apply(self, d: dict):
        self.session_pct = int(round(d.get("session_pct", -1)))
        wk = d.get("weekly_pct")
        self.weekly_pct = int(round(wk)) if wk is not None else -1
        self.session_reset = float(d.get("session_reset", 0) or 0)
        self.updated = float(d.get("updated", 0) or 0)
        self.emit("changed", self.session_pct, self.weekly_pct,
                  self.session_reset, self.stale)
        return False

    def reset_in(self) -> str:
        if self.session_reset <= 0:
            return ""
        left = int(self.session_reset - time.time())
        if left <= 0:
            return "0m"
        h, m = divmod(left // 60, 60)
        return f"{h}h{m:02d}m" if h else f"{m}m"


def _epoch(iso: str) -> float:
    if not iso:
        return 0.0
    try:
        from datetime import datetime
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0
