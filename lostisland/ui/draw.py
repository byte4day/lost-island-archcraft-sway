"""Hand-drawn cairo widgets: the equalizer bars and the battery ring.

Both are strictly demand-driven: the EQ animates on a 80 ms timer only while
music is actually playing *and* the widget is mapped; the ring redraws only
when UPower reports a change.
"""

from __future__ import annotations

import math

from gi.repository import GLib, Gtk


class EqBars(Gtk.DrawingArea):
    """Five bouncing bars, the universal 'something is playing' glyph.

    With cava feeding real spectrum levels through `feed()`, the bars follow
    the actual music; without it they fall back to a gentle sine animation.
    """

    BAR_W = 3.0
    GAP = 2.5
    N = 5

    def __init__(self, color=(1.0, 1.0, 1.0)):
        super().__init__()
        self.color = color
        self._phase = 0.0
        self._playing = False
        self._timer = 0
        self._levels: list[float] | None = None
        self._external = False
        width = int(self.N * self.BAR_W + (self.N - 1) * self.GAP)
        self.set_content_width(width)
        self.set_content_height(14)
        self.set_draw_func(self._draw)
        self.connect("map", lambda *_: self._sync_timer())
        self.connect("unmap", lambda *_: self._sync_timer())

    def set_playing(self, playing: bool):
        self._playing = playing
        self._sync_timer()
        self.queue_draw()

    def set_external(self, external: bool):
        """True while a live level source (cava) is driving the bars."""
        self._external = external
        self._levels = None
        self._sync_timer()

    def feed(self, levels: list[float]):
        self._levels = levels
        self.queue_draw()

    def _sync_timer(self):
        want = self._playing and self.get_mapped() and not self._external
        if want and not self._timer:
            self._timer = GLib.timeout_add(80, self._tick)
        elif not want and self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _tick(self):
        self._phase += 0.55
        self.queue_draw()
        return True

    def _draw(self, area, cr, w, h):
        cr.set_source_rgb(*self.color)
        for i in range(self.N):
            if self._playing and self._external and self._levels:
                frac = 0.15 + 0.85 * self._levels[i]
            elif self._playing:
                frac = 0.35 + 0.65 * abs(math.sin(self._phase + i * 1.1))
            else:
                frac = 0.25
            bh = h * frac
            x = i * (self.BAR_W + self.GAP)
            y = (h - bh) / 2
            _rounded_rect(cr, x, y, self.BAR_W, bh, self.BAR_W / 2)
            cr.fill()


class BatteryRing(Gtk.DrawingArea):
    """Charge level as a ring, accent-colored when charging."""

    def __init__(self, accent=(1.0, 0.62, 0.04)):
        super().__init__()
        self.accent = accent
        self.percent = 0.0
        self.charging = False
        self.set_content_width(40)
        self.set_content_height(40)
        self.set_draw_func(self._draw)

    def update(self, percent: float, charging: bool):
        self.percent = percent
        self.charging = charging
        self.queue_draw()

    def _draw(self, area, cr, w, h):
        cx, cy = w / 2, h / 2
        radius = min(w, h) / 2 - 3
        cr.set_line_width(3.5)
        cr.set_line_cap(1)  # ROUND
        # track
        cr.set_source_rgba(1, 1, 1, 0.13)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.stroke()
        # level, from 12 o'clock
        if self.charging:
            cr.set_source_rgb(*self.accent)
        elif self.percent <= 20:
            cr.set_source_rgb(1.0, 0.27, 0.23)
        else:
            cr.set_source_rgb(0.20, 0.84, 0.29)
        start = -math.pi / 2
        cr.arc(cx, cy, radius, start, start + 2 * math.pi * max(0.01, self.percent / 100))
        cr.stroke()


def pick_icon(widget, *names: str) -> str:
    """First icon name the current theme actually ships (breeze and adwaita
    disagree on several battery/bluetooth names)."""
    theme = Gtk.IconTheme.get_for_display(widget.get_display())
    for name in names:
        if theme.has_icon(name):
            return name
    return names[-1]


def _rounded_rect(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


# -- live activity glyphs --------------------------------------------------------

def hex_rgb(value: str, fallback=(0.04, 0.52, 1.0)) -> tuple[float, float, float]:
    value = (value or "").lstrip("#")
    if len(value) != 6:
        return fallback
    try:
        return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return fallback


class _Ticking(Gtk.DrawingArea):
    """A drawing area that redraws every frame only while `animated` is
    true and the widget is on screen."""

    def __init__(self, size: int):
        super().__init__()
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_valign(Gtk.Align.CENTER)
        self._tick_id = 0
        self._t0 = 0
        self.animated = False
        self.set_draw_func(self._draw)
        self.connect("map", lambda *_: self._sync())
        self.connect("unmap", lambda *_: self._sync())

    def _sync(self):
        want = self.animated and self.get_mapped()
        if want and not self._tick_id:
            self._tick_id = self.add_tick_callback(self._on_tick)
        elif not want and self._tick_id:
            self.remove_tick_callback(self._tick_id)
            self._tick_id = 0

    def _on_tick(self, _widget, clock) -> bool:
        now = clock.get_frame_time()
        if not self._t0:
            self._t0 = now
        self.elapsed = (now - self._t0) / 1_000_000
        self.queue_draw()
        return True

    elapsed = 0.0

    def _draw(self, area, cr, w, h):
        raise NotImplementedError


class ProgressRing(_Ticking):
    """A thin ring. `progress` 0..1 fills it; None spins an open arc."""

    def __init__(self, size: int = 18, width: float = 2.6,
                 color=(1.0, 1.0, 1.0)):
        super().__init__(size)
        self.line = width
        self.color = color
        self.progress: float | None = 0.0

    def set_progress(self, progress: float | None, color=None):
        self.progress = progress
        if color is not None:
            self.color = color
        self.animated = progress is None
        self._sync()
        self.queue_draw()

    def _draw(self, area, cr, w, h):
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - self.line / 2 - 0.5
        cr.set_line_width(self.line)
        cr.set_line_cap(1)
        cr.set_source_rgba(*self.color, 0.25)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()
        cr.set_source_rgb(*self.color)
        if self.progress is None:
            start = self.elapsed * 2 * math.pi * 0.9
            cr.arc(cx, cy, r, start, start + math.pi * 0.6)
        else:
            p = max(0.0, min(1.0, self.progress))
            if p <= 0:
                return
            start = -math.pi / 2
            cr.arc(cx, cy, r, start, start + 2 * math.pi * p)
        cr.stroke()


class SparkIcon(Gtk.Widget):
    """An SVG logo that can spin (working), breathe (needs you) or rest."""

    __gtype_name__ = "LostIslandSparkIcon"

    def __init__(self, path: str, size: int = 16):
        super().__init__()
        from gi.repository import Gdk, GdkPixbuf
        scale = 3
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
            path, size * scale, size * scale, True)
        self.texture = Gdk.Texture.new_for_pixbuf(pixbuf)
        self.size = size
        self.mode = "still"
        self._tick_id = 0
        self._t0 = 0
        self._elapsed = 0.0
        self.set_valign(Gtk.Align.CENTER)
        self.connect("map", lambda *_: self._sync())
        self.connect("unmap", lambda *_: self._sync())

    def set_mode(self, mode: str):
        if mode != self.mode:
            self.mode = mode
            self._sync()
            self.queue_draw()

    def _sync(self):
        want = self.mode != "still" and self.get_mapped()
        if want and not self._tick_id:
            self._t0 = 0
            self._tick_id = self.add_tick_callback(self._on_tick)
        elif not want and self._tick_id:
            self.remove_tick_callback(self._tick_id)
            self._tick_id = 0

    def _on_tick(self, _widget, clock) -> bool:
        now = clock.get_frame_time()
        self._t0 = self._t0 or now
        self._elapsed = (now - self._t0) / 1_000_000
        self.queue_draw()
        return True

    def do_measure(self, orientation, for_size):
        return self.size, self.size, -1, -1

    def do_snapshot(self, snapshot):
        from gi.repository import Graphene
        s = self.size
        angle, scale = 0.0, 1.0
        if self.mode == "spin":
            angle = (self._elapsed * 140.0) % 360.0
        elif self.mode == "breathe":
            scale = 0.86 + 0.14 * (0.5 + 0.5 * math.sin(self._elapsed * 5.0))
        centre = Graphene.Point()
        centre.init(s / 2, s / 2)
        back = Graphene.Point()
        back.init(-s / 2, -s / 2)
        snapshot.save()
        snapshot.translate(centre)
        snapshot.rotate(angle)
        snapshot.scale(scale, scale)
        snapshot.translate(back)
        rect = Graphene.Rect()
        rect.init(0, 0, s, s)
        snapshot.append_scaled_texture(self.texture,
                                       _filter_trilinear(), rect)
        snapshot.restore()


def _filter_trilinear():
    from gi.repository import Gsk
    return Gsk.ScalingFilter.TRILINEAR


class ChargeGlyph(_Ticking):
    """A battery that fills up to the charge level, then the bolt pulses."""

    FILL_SECONDS = 0.9

    def __init__(self):
        super().__init__(30)
        self.set_content_width(40)
        self.set_content_height(22)
        self.percent = 0.0

    def play(self, percent: float):
        self.percent = max(0.0, min(100.0, percent))
        self._t0 = 0
        self.elapsed = 0.0
        self.animated = True
        self._sync()

    def _draw(self, area, cr, w, h):
        t = min(1.0, self.elapsed / self.FILL_SECONDS)
        ease = 1 - (1 - t) ** 3
        body_w, body_h = w - 5, h - 2
        x, y = 1, 1
        cr.set_line_width(1.6)
        cr.set_source_rgba(1, 1, 1, 0.45)
        _rounded_rect(cr, x, y, body_w, body_h, 5)
        cr.stroke()
        cr.set_source_rgba(1, 1, 1, 0.45)
        _rounded_rect(cr, x + body_w + 1, y + body_h * 0.32, 2.5,
                      body_h * 0.36, 1.2)
        cr.fill()
        fill = (body_w - 4) * (self.percent / 100) * ease
        if fill > 0.5:
            cr.set_source_rgb(0.20, 0.84, 0.29)
            _rounded_rect(cr, x + 2, y + 2, fill, body_h - 4, 3)
            cr.fill()
        # bolt, pulsing once the fill settles
        pulse = 1.0 if t < 1 else 0.75 + 0.25 * math.cos(
            (self.elapsed - self.FILL_SECONDS) * 4)
        cr.set_source_rgba(1, 1, 1, pulse)
        cx, cy = x + body_w / 2, y + body_h / 2
        cr.move_to(cx + 1.5, cy - 6.5)
        cr.line_to(cx - 3.5, cy + 1)
        cr.line_to(cx - 0.2, cy + 1)
        cr.line_to(cx - 1.5, cy + 6.5)
        cr.line_to(cx + 3.5, cy - 1)
        cr.line_to(cx + 0.2, cy - 1)
        cr.close_path()
        cr.fill()
        if self.elapsed > 4:
            self.animated = False
            self._sync()
