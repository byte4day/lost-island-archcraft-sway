"""The island: one surface whose faces morph with a spring.

Faces: pill (the resting state), peek (one event), banner (a notification)
and the expanded card. `IslandShell` puts the island in the middle of the
layer surface with the side bubble for a second live activity to its right,
and an invisible twin of the bubble on its left so the island never shifts
off-centre.
"""

from __future__ import annotations

from gi.repository import Gio, GLib, Gtk

from lostisland.services import notify as notify_actions
from lostisland.services.transfers import human_size
from lostisland.ui import art as art_cache
from lostisland.ui.activity import Satellite, place, rank
from lostisland.ui.expanded import Expanded
from lostisland.ui.morph import MorphBin
from lostisland.ui.peek import Banner, Peek
from lostisland.ui.pill import Pill
from lostisland.ui.tools import ToolActions

COLLAPSE_DELAY_MS = 700
BANNER_SECONDS = 5.5
BANNER_HOVER_GRACE_MS = 1800
CHIME = "/usr/share/sounds/freedesktop/stereo/complete.oga"


class Island(Gtk.Box):
    def __init__(self, cfg: dict, media, power, weather=None, system=None,
                 on_settings=None, cava=None, lyrics=None, claude=None,
                 recorder=None, airplay=None, clipboard=None, timer=None,
                 claude_status=None, transfers=None):
        super().__init__()
        self.add_css_class("island")
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.START)
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.cfg = cfg
        self.media = media
        self.timer = timer
        self.recorder = recorder
        self.claude_status = claude_status
        self.transfers = transfers

        self._peek_timeout = 0
        self._collapse_timeout = 0
        self._record_tick = 0
        self._hovered = False
        # mirrors mako's do-not-disturb mode; suppresses notification peeks
        self.dnd_active = False
        self.on_activities = None   # set by the shell: (secondary or None)

        self.stack = MorphBin()

        self.lyrics = lyrics
        self.pill = Pill(cfg, media=media, cava=cava, weather=weather,
                         lyrics=lyrics, claude=claude)
        self.peek = Peek()
        self.banner = Banner(on_open=self._banner_open,
                             on_action=self._banner_action,
                             on_dismiss=self._banner_dismiss)
        tools_row = (ToolActions(on_collapse=self.collapse,
                                 on_peek=self._tool_peek,
                                 on_dnd=self._set_dnd)
                     if cfg.get("modules", {}).get("tools", True) else None)
        self.expanded = Expanded(cfg, media, power, timer=timer,
                                 weather=weather, system=system,
                                 on_settings=on_settings, recorder=recorder,
                                 airplay=airplay, tools_row=tools_row,
                                 clipboard=clipboard,
                                 claude_status=claude_status)
        self.expanded.on_clip_copied = self._clip_copied
        self.expanded.on_edit_changed = lambda _editing: self._cancel_collapse()
        if tools_row is not None:
            tools_row.on_power_open = (
                lambda: self.expanded.clip_button.set_active(False))
        self.expanded.set_size_request(400, -1)

        self.pill.on_face_changed = self.refresh_activities
        self.stack.add_named(self.pill, "pill", smooth=True)
        self.stack.add_named(self.peek, "peek", smooth=True)
        self.stack.add_named(self.banner, "banner")
        self.stack.add_named(self.expanded, "expanded")
        self.append(self.stack)

        click = Gtk.GestureClick()
        click.connect("released", self._on_click)
        self.add_controller(click)

        # right click always opens/closes the card
        right = Gtk.GestureClick(button=3)
        right.connect("released", lambda *_: self.toggle())
        self.add_controller(right)

        # horizontal swipe on the pill cycles faces
        drag = Gtk.GestureDrag()
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

        # scroll over the pill changes volume; middle click plays/pauses
        scroll = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.VERTICAL
            | Gtk.EventControllerScrollFlags.DISCRETE)
        scroll.connect("scroll", self._on_scroll)
        self.add_controller(scroll)

        middle = Gtk.GestureClick(button=2)
        middle.connect("released", lambda *_: self.media.play_pause())
        self.add_controller(middle)

        motion = Gtk.EventControllerMotion()
        motion.connect("enter", self._on_enter)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

        # live activities
        if timer is not None:
            timer.connect("changed", lambda *_: self.refresh_activities())
            timer.connect("finished", lambda *_: self._timer_finished())
        if recorder is not None:
            recorder.connect("changed", lambda *_: self._sync_record_tick())
        if claude_status is not None:
            claude_status.connect("changed",
                                  lambda *_: self.refresh_activities())
        if transfers is not None:
            transfers.connect("changed", lambda *_: self.refresh_activities())
            transfers.connect("finished", lambda _s, name: self.show_peek(
                self.peek.show_download_done, name))

    def set_shape(self, shape: str):
        """"island" floats like the iPhone's; "notch" hangs from the top edge
        with square top corners, like Mac notch apps."""
        if shape == "notch":
            self.add_css_class("island--notch")
        else:
            self.remove_css_class("island--notch")

    # -- state -------------------------------------------------------------

    @property
    def state(self) -> str:
        return self.stack.get_visible_child_name() or "pill"

    def collapse(self):
        self._cancel_peek()
        self.remove_css_class("island--expanded")
        self.remove_css_class("island--banner")
        self.stack.set_visible_child_name("pill")
        self._notify_shell()

    def expand(self):
        self._cancel_peek()
        self.remove_css_class("island--banner")
        self.add_css_class("island--expanded")
        self.stack.set_visible_child_name("expanded")
        self._notify_shell()

    def toggle(self):
        self.collapse() if self.state == "expanded" else self.expand()

    def show_peek(self, setter, *args):
        """Run `setter(*args)` on the peek widget and surface it briefly."""
        if self.state in ("expanded", "banner"):
            return
        setter(*args)
        self.stack.set_visible_child_name("peek")
        self._notify_shell()
        self._arm_peek(int(float(self.cfg.get("peek_seconds", 2.2)) * 1000))

    def show_banner(self, note: dict):
        if self.state == "expanded" or self.dnd_active:
            return
        self.banner.show(note)
        self.add_css_class("island--banner")
        self.stack.set_visible_child_name("banner")
        self._notify_shell()
        self._arm_peek(int(BANNER_SECONDS * 1000))

    def _arm_peek(self, ms: int):
        self._cancel_peek()
        self._peek_timeout = GLib.timeout_add(ms, self._peek_done)

    def _peek_done(self):
        self._peek_timeout = 0
        if self.state == "banner" and self._hovered:
            return False   # leaving the banner re-arms the timeout
        if self.state in ("peek", "banner"):
            self.remove_css_class("island--banner")
            self.stack.set_visible_child_name("pill")
            self._notify_shell()
        return False

    def _cancel_peek(self):
        if self._peek_timeout:
            GLib.source_remove(self._peek_timeout)
            self._peek_timeout = 0

    # -- live activities -----------------------------------------------------

    def activities(self) -> list[dict]:
        acts: list[dict] = []
        rec = self.recorder
        if rec is not None and rec.running:
            m, s = divmod(rec.elapsed(), 60)
            acts.append({"kind": "recording",
                         "text": "Saving" if rec.stopping else f"{m}:{s:02d}"})
        cs = self.claude_status
        if cs is not None and cs.top is not None:
            top = cs.top
            acts.append({"kind": "claude", "state": top["state"],
                         "detail": top.get("detail", ""),
                         "project": top.get("project", ""),
                         "count": max(1, cs.working), "session": top})
        p = getattr(self.media, "active", None)
        if p is not None and p.status == "Playing":
            acts.append({"kind": "music", "playing": True,
                         "art_path": p.art_path, "tint": self._tint})
        tr = self.transfers
        if tr is not None and tr.top is not None:
            item = tr.top
            acts.append({"kind": "transfer", "name": item["name"],
                         "percent": item["percent"],
                         "size": human_size(item["size"]),
                         "done": bool(item["done_at"])})
        t = self.timer
        if t is not None and t.touched:
            acts.append({"kind": "timer", "text": t.text,
                         "progress": t.progress, "running": t.running})
        return rank(acts)

    _tint = None

    def refresh_activities(self):
        pill, bubble = place(self.activities(), self.pill.face)
        self.pill.show_activity(pill)
        self._secondary = bubble
        self._notify_shell()

    _secondary = None

    def _notify_shell(self):
        if self.on_activities:
            self.on_activities(self._secondary if self.state == "pill"
                               else None)
        if self.on_state:
            self.on_state(self.state)

    on_state = None   # set by the app: raises the island over fullscreen

    def on_activity_clicked(self, activity: dict):
        kind = activity["kind"]
        if kind == "claude" and self.claude_status is not None:
            self.claude_status.focus(activity.get("session"))
        elif kind == "music":
            p = getattr(self.media, "active", None)
            if p is not None:
                notify_actions.focus_app(getattr(p, "app", ""))
        elif kind == "timer" and self.timer is not None:
            self.timer.toggle()
        else:
            self.expand()

    def _sync_record_tick(self):
        running = self.recorder is not None and self.recorder.running
        if running and not self._record_tick:
            self._record_tick = GLib.timeout_add_seconds(
                1, lambda: self.refresh_activities() or True)
        elif not running and self._record_tick:
            GLib.source_remove(self._record_tick)
            self._record_tick = 0
        self.refresh_activities()

    def _timer_finished(self):
        if self.timer is None:
            return
        _play_chime()
        if self.state == "banner":
            self.collapse()
        self.show_peek(self.peek.show_timer_done, self.timer.minutes)

    # -- notification banner ---------------------------------------------------

    def _banner_open(self, note: dict):
        self.collapse()
        has_default = any(k == "default" for k, _ in note.get("actions", []))
        if has_default:
            notify_actions.act(note, "default",
                               lambda: notify_actions.focus_app(note["app"]))
        else:
            notify_actions.focus_app(note["app"])

    def _banner_action(self, note: dict, key: str):
        self.collapse()
        notify_actions.act(note, key)

    def _banner_dismiss(self, note: dict):
        self.collapse()
        notify_actions.act(note, None)

    # -- input -------------------------------------------------------------

    def _on_click(self, gesture, n, x, y):
        # clicks on buttons/sliders inside the card never reach here; GTK
        # claims them first, so this only fires on the surface itself
        if self.state == "banner":
            return
        if self.state in ("pill", "peek"):
            # a click always does what the setting says; what Claude is up
            # to is listed in the card, with a button to its terminal
            if self.cfg.get("click_action", "cycle") == "cycle":
                self.pill.cycle(+1)
            else:
                self.expand()
        elif not self.expanded.editing:
            # a click on empty card space closes it again
            self.collapse()

    def _on_drag_update(self, gesture, dx, dy):
        # once it's clearly a horizontal swipe, claim it away from the click
        if self.state == "pill" and abs(dx) > 18 and abs(dx) > abs(dy):
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    def _on_drag_end(self, gesture, dx, dy):
        if self.state == "pill" and abs(dx) > 36 and abs(dx) > abs(dy):
            self.pill.cycle(+1 if dx < 0 else -1)

    def _on_scroll(self, _ctrl, _dx, dy):
        if self.state == "expanded" or dy == 0:
            return False
        step = "-5%" if dy > 0 else "+5%"
        try:
            Gio.Subprocess.new(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", step],
                Gio.SubprocessFlags.NONE)
        except GLib.Error:
            return False
        return True

    # -- tools row callbacks -------------------------------------------------

    def _tool_peek(self, kind: str, *args):
        setter = {"screenshot": self.peek.show_screenshot,
                  "color": self.peek.show_color,
                  "error": self.peek.show_error}[kind]
        self.show_peek(setter, *args)

    def _clip_copied(self, text: str):
        self.collapse()
        # let the morph settle before the peek widens the pill
        GLib.timeout_add(320, lambda: self.show_peek(
            self.peek.show_clipboard, text) and False)

    def _set_dnd(self, active: bool):
        self.dnd_active = active

    def _cancel_collapse(self):
        if self._collapse_timeout:
            GLib.source_remove(self._collapse_timeout)
            self._collapse_timeout = 0

    def _on_enter(self, motion, x, y):
        self._hovered = True
        self._cancel_collapse()
        if self.state == "banner":
            self._cancel_peek()

    def _on_leave(self, motion):
        self._hovered = False
        if self.state == "banner":
            self._arm_peek(BANNER_HOVER_GRACE_MS)
            return
        # dragging a control fires leave on Wayland; edit mode stays open
        if self.state != "expanded" or self.expanded.editing:
            return
        self._cancel_collapse()
        self._collapse_timeout = GLib.timeout_add(
            COLLAPSE_DELAY_MS, self._leave_collapse)

    def _leave_collapse(self):
        self._collapse_timeout = 0
        if self.state == "expanded" and not self.expanded.editing:
            self.collapse()
        return False

    # -- service wiring ----------------------------------------------------

    def on_media_changed(self):
        p = self.media.active
        if p is None:
            self._tint = None
            self.pill.show_idle()
        else:
            self._tint = art_cache.tint(p.art_path)
            # the pill shows the title only; the artist lives in the card
            self.pill.show_music(p.title, p.art_path, p.status == "Playing",
                                 tint=self._tint)
            if self.lyrics is not None:
                self.lyrics.set_track(p.artist, p.title, p.album,
                                      p.length_us // 1_000_000)
        if self.state == "expanded":
            self.expanded.refresh_media()
        self.refresh_activities()


class IslandShell(Gtk.Box):
    """[twin][island][bubble]: the bubble shows the second live activity."""

    def __init__(self, island: Island):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.START)
        self.island = island
        accent = island.cfg.get("accent", "#0A84FF")
        self.satellite = Satellite(accent, on_click=island.on_activity_clicked)

        self.twin = Gtk.Box()
        self.left = Gtk.Revealer()
        self.right = Gtk.Revealer()
        for rev, child, kind in ((self.left, self.twin,
                                  Gtk.RevealerTransitionType.SLIDE_LEFT),
                                 (self.right, self.satellite,
                                  Gtk.RevealerTransitionType.SLIDE_RIGHT)):
            rev.set_transition_type(kind)
            rev.set_transition_duration(300)
            rev.set_valign(Gtk.Align.START)
            rev.set_child(child)
        self.satellite.set_margin_start(7)
        self.twin.set_margin_end(7)

        self.append(self.left)
        self.append(island)
        self.append(self.right)
        island.on_activities = self.show_secondary

    def show_secondary(self, activity: dict | None):
        if activity is not None:
            was_shown = self.right.get_reveal_child()
            self.satellite.show(activity)
            width = self.satellite.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
            self.twin.set_size_request(width, 1)
            if not was_shown:
                # restart the pop animation
                self.satellite.remove_css_class("satellite--pop")
                self.satellite.add_css_class("satellite--pop")
        self.left.set_reveal_child(activity is not None)
        self.right.set_reveal_child(activity is not None)


def _play_chime():
    for argv in (["pw-play", CHIME], ["paplay", CHIME],
                 ["canberra-gtk-play", "-i", "complete"]):
        try:
            Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDERR_SILENCE)
            return
        except GLib.Error:
            continue

