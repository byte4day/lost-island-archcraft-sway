"""Live activities: what the pill and its side bubble show.

Several things can be live at once: music, a Claude Code session, the focus
timer, a screen recording, a download. `rank()` orders them; the most
important one fills the pill and the next one gets the round bubble beside
it, like two activities on the hardware Dynamic Island.
"""

from __future__ import annotations

import os

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango

from lostisland.ui.draw import EqBars, ProgressRing, SparkIcon, hex_rgb

ASSETS = os.path.join(os.path.dirname(__file__), "assets")
CLAUDE_SVG = os.path.join(ASSETS, "claude.svg")

PRIORITY = {
    "recording": 60,
    "claude-needs": 50,
    "music": 40,
    "claude-done": 32,
    "claude-working": 30,
    "transfer": 28,
    "timer": 25,
    "timer-paused": 12,
}
ORANGE = (1.0, 0.62, 0.04)
GREEN = (0.19, 0.82, 0.35)


def priority(activity: dict) -> int:
    kind = activity["kind"]
    if kind == "claude":
        state = activity.get("state")
        return PRIORITY["claude-needs" if state == "needs" else
                        "claude-done" if state == "done" else
                        "claude-working"]
    if kind == "timer" and not activity.get("running"):
        return PRIORITY["timer-paused"]
    return PRIORITY.get(kind, 0)


def rank(activities: list[dict]) -> list[dict]:
    """Most important first; ties keep their given order."""
    return sorted(activities, key=priority, reverse=True)


def claude_text(activity: dict) -> str:
    state = activity.get("state")
    if state == "done":
        return "Done"
    if state == "needs":
        return activity.get("detail") or "Needs you"
    return activity.get("detail") or "Thinking"


class ActivityView(Gtk.Box):
    """Renders one activity. compact=True is the bubble: icon-first, short."""

    def __init__(self, compact: bool = False, accent: str = "#0A84FF"):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL,
                         spacing=6 if compact else 8)
        self.compact = compact
        self.accent = hex_rgb(accent)
        self.add_css_class("activity")
        self.add_css_class("activity--compact" if compact else "activity--full")
        self.set_valign(Gtk.Align.CENTER)
        self.kind = None

        self.art_frame = Gtk.Box()
        self.art_frame.add_css_class("activity-art")
        self.art_frame.set_overflow(Gtk.Overflow.HIDDEN)
        self.art = Gtk.Picture()
        self.art.set_content_fit(Gtk.ContentFit.COVER)
        self.art.set_size_request(20, 20)
        self.art_frame.append(self.art)

        self.eq = EqBars()
        self.spark = SparkIcon(CLAUDE_SVG, 15 if compact else 16)
        self.ring = ProgressRing(16 if compact else 17, 2.4)
        self.dot = Gtk.Box()
        self.dot.add_css_class("rec-dot")
        self.dot.set_valign(Gtk.Align.CENTER)

        self.label = Gtk.Label(xalign=0)
        self.label.add_css_class("activity-label")
        self.label.set_ellipsize(Pango.EllipsizeMode.END)
        self.label.set_max_width_chars(6 if compact else 18)
        self.sub = Gtk.Label(xalign=0)
        self.sub.add_css_class("activity-sub")
        self.sub.set_ellipsize(Pango.EllipsizeMode.END)
        self.sub.set_max_width_chars(14)

        # Apple's compact presentation: a leading graphic and a trailing
        # status, balanced on either side of an empty middle. The bubble
        # (compact=True) is Apple's minimal presentation: one glyph or a
        # few characters in a 37 px circle or short oval.
        self.gap = Gtk.Box()
        self.gap.set_hexpand(True)
        self.gap.set_size_request(0 if compact else 56, 1)
        for w in (self.art_frame, self.eq, self.spark, self.ring, self.dot,
                  self.sub, self.gap, self.label):
            w.set_visible(False)
            self.append(w)

    def _only(self, *widgets):
        for w in (self.art_frame, self.eq, self.spark, self.ring, self.dot,
                  self.label, self.sub):
            w.set_visible(w in widgets)
        self.gap.set_visible(not self.compact)

    def _tone(self, tone: str | None):
        for t in ("orange", "green", "red", "accent"):
            self.label.remove_css_class(f"tone-{t}")
        if tone:
            self.label.add_css_class(f"tone-{tone}")

    def show(self, a: dict):
        self.kind = a["kind"]
        kind = a["kind"]
        self.eq.set_playing(False)
        self._tone(None)
        if kind == "music":
            shown = []
            if a.get("art_path"):
                try:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                        a["art_path"], 60, 60, False)
                    self.art.set_paintable(Gdk.Texture.new_for_pixbuf(pixbuf))
                    shown.append(self.art_frame)
                except GLib.Error:
                    pass
            if a.get("tint"):
                self.eq.color = a["tint"]
            shown.append(self.eq)
            self._only(*shown)
            self.eq.set_playing(bool(a.get("playing")))
        elif kind == "claude":
            state = a.get("state")
            self.spark.set_mode("spin" if state in ("thinking", "tool")
                                else "breathe" if state == "needs" else "still")
            text = claude_text(a)
            if self.compact:
                widgets = [self.spark]
                if state == "done":
                    self.label.set_label("✓")
                    widgets.append(self.label)
                elif state == "needs":
                    self.label.set_label("!")
                    widgets.append(self.label)
                self._only(*widgets)
            else:
                self.label.set_label(text)
                count = a.get("count", 1)
                project = a.get("project") or "Claude Code"
                self.set_tooltip_text(
                    f"{project} · {count} sessions working" if count > 1
                    else f"{project}: click to open its terminal")
                self._only(self.spark, self.label)
            self._tone("orange" if state == "needs" else
                       "green" if state == "done" else None)
        elif kind == "timer":
            self.ring.set_progress(a.get("progress", 0.0),
                                   self.accent if a.get("running")
                                   else (0.62, 0.62, 0.66))
            self.label.set_label(a.get("text", ""))
            self._only(*([self.label] if self.compact
                         else [self.ring, self.label]))
            self._tone("accent" if a.get("running") else None)
        elif kind == "recording":
            self.label.set_label(a.get("text", ""))
            self._only(*([self.dot] if self.compact
                         else [self.dot, self.label]))
            self._tone("red")
        elif kind == "transfer":
            pct = a.get("percent")
            done = bool(a.get("done"))
            self.ring.set_progress(1.0 if done else
                                   None if pct is None else pct / 100,
                                   GREEN if done else self.accent)
            if self.compact:
                self._only(self.ring)
            else:
                self.label.set_label("Done" if done else
                                     a.get("size", "") if pct is None
                                     else f"{pct:.0f}%")
                self.set_tooltip_text(a.get("name", "Download"))
                self._only(self.ring, self.label)
                self._tone("green" if done else None)


class Satellite(Gtk.Box):
    """The detached round bubble for the second live activity."""

    def __init__(self, accent: str, on_click=None):
        super().__init__()
        self.add_css_class("satellite")
        self.set_valign(Gtk.Align.START)
        self.view = ActivityView(compact=True, accent=accent)
        self.view.set_halign(Gtk.Align.CENTER)
        self.view.set_hexpand(True)
        self.append(self.view)
        self.activity: dict | None = None
        if on_click is not None:
            click = Gtk.GestureClick()
            click.connect("released",
                          lambda *_: self.activity and on_click(self.activity))
            self.add_controller(click)

    def show(self, activity: dict):
        self.activity = activity
        self.view.show(activity)
