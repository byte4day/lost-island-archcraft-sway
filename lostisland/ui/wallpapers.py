"""Wallpaper picker: a carousel of the wallpaper folder inside the card.

The centred card is full size; its neighbours shrink and fade, like Tide
Island's switcher. Click a side card (or scroll, swipe, ←/→, h/l, Tab) to
bring it to the middle, click the middle card or press Enter to set it.
/ searches by file name, Esc closes. The thumbnails only live while the
picker is open; closing it drops them.
"""

from __future__ import annotations

import math
import os
import weakref
from collections.abc import Callable

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango

from lostisland.services import wallpaper as wp
from lostisland.ui.tools import circle_button

CARD_FRACTION = 0.40   # centre card width / carousel width
SPACING_FRACTION = 0.31
SIDE_SCALE = 0.76
RADIUS = 12
CAROUSEL_H = 104
VISIBLE_REACH = 2.6    # cards further than this from the centre aren't drawn


def card_geometry(width: float, offset: float) -> tuple[float, float, float,
                                                         float, float]:
    """x, y-centre, w, h and alpha of a card `offset` slots from the
    middle. Pure, so it is unit tested."""
    d = abs(offset)
    scale = 1 - (1 - SIDE_SCALE) * min(d, 1) - 0.10 * max(d - 1, 0)
    alpha = 1 - 0.35 * min(d, 1) - 0.45 * max(d - 1, 0)
    card_w = width * CARD_FRACTION
    w = card_w * scale
    h = w * 0.575
    # neighbours tuck in a little the further out they are
    shift = offset * width * SPACING_FRACTION * (1 - 0.08 * max(d - 1, 0))
    cx = width / 2 + shift
    return cx - w / 2, CAROUSEL_H / 2, w, h, max(0.0, alpha)


class Carousel(Gtk.DrawingArea):
    def __init__(self, picker: WallpaperPicker):
        super().__init__()
        self._picker = weakref.ref(picker)
        self.items: list[str] = []
        self.pixbufs: dict[str, GdkPixbuf.Pixbuf | None] = {}
        self.active = ""
        self.pos = 0.0
        self.target = 0
        self._tick = 0
        self._last_time = 0
        self._drag_from = 0.0
        self._scroll_acc = 0.0
        self.set_content_height(CAROUSEL_H)
        self.set_hexpand(True)
        self.set_focusable(True)
        self.set_can_focus(True)
        self.set_draw_func(self._draw)

        click = Gtk.GestureClick()
        click.connect("released", self._on_click)
        self.add_controller(click)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

        scroll = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.BOTH_AXES)
        scroll.connect("scroll", self._on_scroll)
        self.add_controller(scroll)

    # -- model -------------------------------------------------------------

    def set_items(self, items: list[str], keep: str = ""):
        self.items = items
        index = items.index(keep) if keep in items else 0
        self.target = index
        self.pos = float(index)
        self.queue_draw()

    @property
    def current(self) -> str:
        if not self.items:
            return ""
        return self.items[max(0, min(self.target, len(self.items) - 1))]

    def visible_items(self) -> list[str]:
        lo = max(0, self.target - 3)
        return self.items[lo:self.target + 4]

    def go(self, index: int):
        if not self.items:
            return
        self.target = max(0, min(index, len(self.items) - 1))
        self._animate()
        picker = self._picker()
        if picker is not None:
            picker.on_moved()

    def step(self, delta: int):
        self.go(self.target + delta)

    # -- animation ---------------------------------------------------------

    def _animate(self):
        if not self._tick:
            self._last_time = 0
            self._tick = self.add_tick_callback(self._on_tick)

    def _on_tick(self, _widget, clock) -> bool:
        now = clock.get_frame_time()
        dt = (now - self._last_time) / 1e6 if self._last_time else 1 / 60
        self._last_time = now
        gap = self.target - self.pos
        if abs(gap) < 0.002:
            self.pos = float(self.target)
            self._tick = 0
            self.queue_draw()
            return GLib.SOURCE_REMOVE
        # critically damped ease; ~200 ms to settle, like the reference
        self.pos += gap * (1 - math.exp(-dt * 16))
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    # -- drawing -----------------------------------------------------------

    def _pixbuf(self, path: str) -> GdkPixbuf.Pixbuf | None:
        if path in self.pixbufs and self.pixbufs[path] is not None:
            return self.pixbufs[path]
        picker = self._picker()
        if picker is None:
            return None
        thumb = picker.service.thumb(path)
        if thumb is None:
            return None
        try:
            pix = GdkPixbuf.Pixbuf.new_from_file(thumb)
        except GLib.Error:
            pix = None
        self.pixbufs[path] = pix
        return pix

    def _draw(self, _area, cr, width, height):
        if not self.items:
            return
        order = [i for i in range(len(self.items))
                 if abs(i - self.pos) < VISIBLE_REACH]
        order.sort(key=lambda i: -abs(i - self.pos))
        accent = _accent(self)
        for i in order:
            x, cy, w, h, alpha = card_geometry(width, i - self.pos)
            y = cy - h / 2
            r = RADIUS * w / (width * CARD_FRACTION)
            cr.save()
            _rounded(cr, x, y, w, h, r)
            cr.clip()
            pix = self._pixbuf(self.items[i])
            if pix is None:
                cr.set_source_rgba(0.16, 0.16, 0.16, alpha)
                cr.paint()
            else:
                cr.translate(x, y)
                cr.scale(w / pix.get_width(), h / pix.get_height())
                Gdk.cairo_set_source_pixbuf(cr, pix, 0, 0)
                cr.paint_with_alpha(alpha)
            cr.restore()
            # hairline so dark wallpapers keep an edge on the black card
            _rounded(cr, x + 0.5, y + 0.5, w - 1, h - 1, r)
            cr.set_source_rgba(1, 1, 1, 0.10 * alpha)
            cr.set_line_width(1)
            cr.stroke()
            if self.items[i] == self.active:
                _rounded(cr, x + 1.25, y + 1.25, w - 2.5, h - 2.5, r - 1)
                cr.set_source_rgba(*accent, alpha)
                cr.set_line_width(2.5)
                cr.stroke()
        if self.has_focus() and self.items:
            x, cy, w, h, _a = card_geometry(width, 0)
            _rounded(cr, x - 3, cy - h / 2 - 3, w + 6, h + 6, RADIUS + 3)
            cr.set_source_rgba(1, 1, 1, 0.35)
            cr.set_line_width(1.5)
            cr.stroke()

    def hit(self, x: float, y: float) -> int | None:
        width = self.get_width()
        near = sorted((i for i in range(len(self.items))
                       if abs(i - self.pos) < VISIBLE_REACH),
                      key=lambda i: abs(i - self.pos))
        for i in near:
            cx, cy, w, h, _a = card_geometry(width, i - self.pos)
            if cx <= x <= cx + w and cy - h / 2 <= y <= cy + h / 2:
                return i
        return None

    # -- input -------------------------------------------------------------

    def _on_click(self, gesture, _n, x, y):
        self.grab_focus()
        index = self.hit(x, y)
        if index is None:
            return
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        if index == self.target:
            picker = self._picker()
            if picker is not None:
                picker.apply_current()
        else:
            self.go(index)

    def _on_drag_begin(self, _gesture, _x, _y):
        self._drag_from = self.pos

    def _on_drag_update(self, gesture, dx, _dy):
        if abs(dx) < 6 or not self.items:
            return
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        spacing = self.get_width() * SPACING_FRACTION
        self.pos = max(-0.4, min(len(self.items) - 0.6,
                                 self._drag_from - dx / spacing))
        self.queue_draw()

    def _on_drag_end(self, _gesture, dx, _dy):
        if abs(dx) < 6:
            return
        self.go(round(self.pos))

    def _on_scroll(self, controller, dx, dy):
        unit = controller.get_unit()
        delta = dx if abs(dx) > abs(dy) else dy
        if unit == Gdk.ScrollUnit.SURFACE:
            delta /= 40   # touchpad pixels
        self._scroll_acc += delta
        moved = int(self._scroll_acc)
        if moved:
            self._scroll_acc -= moved
            self.step(moved)
        return True


class WallpaperPicker(Gtk.Box):
    """The panel: header (title, search, folder), carousel, name."""

    def __init__(self, service: wp.WallpaperService,
                 on_close: Callable[[], None],
                 on_applied: Callable[[str, bool, str], None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add_css_class("wall-panel")
        self.service = service
        self.on_close = on_close
        self.on_applied = on_applied
        self.all: list[str] = []
        self._handlers: list[int] = []

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.title = Gtk.Label(label="Wallpapers", xalign=0, hexpand=True)
        self.title.add_css_class("clip-title")
        self.search = Gtk.SearchEntry(placeholder_text="Search wallpapers")
        self.search.add_css_class("wall-search")
        self.search.set_hexpand(True)
        self.search.set_visible(False)
        self.search.connect("search-changed", lambda *_: self._filter())
        self.search.connect("stop-search", lambda *_: self._end_search())
        self.search.connect("activate", lambda *_: self.apply_current())
        self.search_btn = circle_button("search", "Search by name ( / )")
        self.search_btn.add_css_class("wall-mini")
        self.search_btn.connect("clicked", lambda *_: self.start_search())
        folder = circle_button("folder_open", "Open the wallpaper folder")
        folder.add_css_class("wall-mini")
        folder.connect("clicked", lambda *_: wp.open_folder(
            self.service.folder))
        for w in (self.title, self.search, self.search_btn, folder):
            head.append(w)
        self.append(head)

        self.carousel = Carousel(self)
        self.append(self.carousel)

        self.name = Gtk.Label(xalign=0.5)
        self.name.add_css_class("wall-name")
        self.name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.append(self.name)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

    # -- lifecycle -----------------------------------------------------------

    def open(self):
        self.service.active = wp.current(self.service.cfg) or \
            self.service.active
        self.carousel.active = self.service.active
        self.all = self.service.list()
        self._handlers = [
            self.service.connect("thumb-ready", self._on_thumb),
            self.service.connect("applied", self._on_applied),
        ]
        self.search.set_text("")
        self.search.set_visible(False)
        self.title.set_visible(True)
        self.search_btn.set_visible(True)
        self._filter(keep=self.service.active)
        # queue every missing thumbnail now, the visible ones first, so
        # scrolling later finds them ready
        for path in self.all:
            self.service.thumb(path)
        self.service.prioritise(self.carousel.visible_items())
        self.carousel.grab_focus()

    def release(self):
        """Drop thumbnails and listeners while the picker is closed."""
        for h in self._handlers:
            self.service.disconnect(h)
        self._handlers = []
        self.carousel.pixbufs.clear()
        self.carousel.items = []
        self.all = []

    # -- behaviour -----------------------------------------------------------

    def _filter(self, keep: str = ""):
        query = self.search.get_text()
        keep = keep or self.carousel.current
        items = [p for p in self.all if wp.matches(p, query)]
        self.carousel.set_items(items, keep)
        self.on_moved()

    def on_moved(self):
        items = self.carousel.items
        if not self.all:
            folder = self.service.opts["folder"]
            self.name.set_label(f"No images in {folder}")
        elif not items:
            self.name.set_label(f"Nothing matches “{self.search.get_text()}”")
        else:
            path = self.carousel.current
            mark = "  ·  current" if path == self.carousel.active else ""
            self.name.set_label(
                f"{os.path.basename(path)}{mark}   "
                f"{self.carousel.target + 1}/{len(items)}")
        self.service.prioritise(self.carousel.visible_items())

    def start_search(self):
        self.title.set_visible(False)
        self.search_btn.set_visible(False)
        self.search.set_visible(True)
        self.search.grab_focus()

    def _end_search(self):
        self.search.set_text("")
        self.search.set_visible(False)
        self.title.set_visible(True)
        self.search_btn.set_visible(True)
        self.carousel.grab_focus()

    def apply_current(self):
        path = self.carousel.current
        if path:
            self.name.set_label(f"Setting {os.path.basename(path)}…")
            self.service.apply(path)

    def _on_thumb(self, _svc, path: str):
        if path in self.carousel.items:
            self.carousel.pixbufs.pop(path, None)
            self.carousel.queue_draw()

    def _on_applied(self, _svc, path: str, ok: bool, message: str):
        if ok:
            self.carousel.active = path
            self.carousel.queue_draw()
        self.on_moved()
        self.on_applied(path, ok, message)

    def _on_key(self, _ctrl, keyval, _code, state) -> bool:
        name = Gdk.keyval_name(keyval) or ""
        root = self.get_root()
        focus = root.get_focus() if root is not None else None
        in_search = focus is not None and (
            focus == self.search or focus.is_ancestor(self.search))
        if name == "Escape":
            if self.search.get_visible():
                self._end_search()
            else:
                self.on_close()
            return True
        if in_search and name not in ("Tab", "ISO_Left_Tab", "Return",
                                      "KP_Enter"):
            return False
        if name in ("Right", "l", "Tab"):
            self.carousel.step(1)
        elif name in ("Left", "h", "ISO_Left_Tab"):
            self.carousel.step(-1)
        elif name in ("Home",):
            self.carousel.go(0)
        elif name in ("End",):
            self.carousel.go(len(self.carousel.items) - 1)
        elif name in ("Return", "KP_Enter", "space"):
            self.apply_current()
        elif name in ("slash",):
            self.start_search()
        else:
            return False
        return True


def _rounded(cr, x, y, w, h, r):
    r = max(0.0, min(r, w / 2, h / 2))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _accent(widget: Gtk.Widget) -> tuple[float, float, float]:
    found, color = widget.get_style_context().lookup_color("accent")
    if found:
        return color.red, color.green, color.blue
    return 0.04, 0.52, 1.0
