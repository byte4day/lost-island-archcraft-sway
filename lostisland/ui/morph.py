"""Spring morph between the island's faces (pill, peek, banner, card).

A Gtk.Stack can only crossfade with a fixed ease. This container animates
its own size with a libadwaita spring, so the island overshoots a little and
settles, like the hardware Dynamic Island. During the morph the outgoing
face blurs and fades while the incoming one scales up from 94%.

Each child is always allocated at its own natural size, centred, and the
container clips it, so no child is ever squeezed below its minimum size.
When the visible child's natural size changes on its own (the pill gets a
longer title), the container springs to the new size too.
"""

from __future__ import annotations

from gi.repository import Adw, GLib, Graphene, Gsk, Gtk

OPEN = (0.72, 1.0, 210.0)     # damping ratio, mass, stiffness
CLOSE = (0.88, 1.0, 320.0)
SETTLE = (0.82, 1.0, 380.0)
BLUR_MAX_AREA = 60_000   # px; roughly a peek or banner, never the card


def _point(x: float, y: float) -> Graphene.Point:
    p = Graphene.Point()
    p.init(x, y)
    return p


def _mix(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


class MorphBin(Gtk.Widget):
    __gtype_name__ = "LostIslandMorphBin"

    def __init__(self):
        super().__init__()
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self._children: dict[str, Gtk.Widget] = {}
        self._smooth: set[Gtk.Widget] = set()
        self._current: Gtk.Widget | None = None
        self._previous: Gtk.Widget | None = None
        self._from = (0.0, 0.0)
        self._t = 1.0
        self._shown = [0, 0]
        self._retarget_src = 0
        target = Adw.CallbackAnimationTarget.new(self._on_value)
        self._anim = Adw.SpringAnimation.new(
            self, 0.0, 1.0, Adw.SpringParams.new(*SETTLE), target)
        self._anim.set_clamp(False)
        self._anim.connect("done", self._on_done)

    # -- stack-like API ------------------------------------------------------

    def add_named(self, child: Gtk.Widget, name: str, smooth: bool = False):
        """smooth: spring to the child's new size when it changes by itself
        (good for the pill; the card animates its own panels)."""
        self._children[name] = child
        if smooth:
            self._smooth.add(child)
        child.set_parent(self)
        if self._current is None:
            self._current = child
        else:
            child.set_child_visible(False)

    def get_visible_child_name(self) -> str | None:
        for name, child in self._children.items():
            if child is self._current:
                return name
        return None

    def set_visible_child_name(self, name: str):
        child = self._children[name]
        if child is self._current:
            return
        grows = self._area(child) > self._area(self._current)
        if self._previous is not None and self._previous is not child:
            self._previous.set_child_visible(False)
        self._previous, self._current = self._current, child
        child.set_child_visible(True)
        if not self.get_mapped() or self.get_width() <= 0:
            self._previous.set_child_visible(False)
            self._previous = None
            self._t = 1.0
            self.queue_resize()
            return
        self._start(OPEN if grows else CLOSE)

    # -- animation -----------------------------------------------------------

    def _area(self, child: Gtk.Widget | None) -> int:
        if child is None:
            return 0
        w = self._natural(child, Gtk.Orientation.HORIZONTAL)
        return w * self._natural(child, Gtk.Orientation.VERTICAL)

    def _start(self, params):
        self._from = (float(self.get_width()), float(self.get_height()))
        self._anim.reset()
        self._anim.set_spring_params(Adw.SpringParams.new(*params))
        self._t = 0.0
        self._anim.play()

    @property
    def animating(self) -> bool:
        return self._anim.get_state() == Adw.AnimationState.PLAYING

    def _on_value(self, value: float):
        self._t = value
        self.queue_resize()

    def _on_done(self, *_):
        self._t = 1.0
        if self._previous is not None:
            self._previous.set_child_visible(False)
            self._previous = None
        self.queue_resize()

    def _retarget(self) -> bool:
        self._retarget_src = 0
        if not self.animating and self.get_mapped():
            self._start(SETTLE)
        return False

    # -- layout ----------------------------------------------------------------

    @staticmethod
    def _natural(child: Gtk.Widget, orientation: Gtk.Orientation) -> int:
        if orientation == Gtk.Orientation.HORIZONTAL:
            return child.measure(orientation, -1)[1]
        width = child.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
        return child.measure(orientation, width)[1]

    def do_measure(self, orientation, for_size):
        child = self._current
        if child is None:
            return 0, 0, -1, -1
        axis = 0 if orientation == Gtk.Orientation.HORIZONTAL else 1
        nat = self._natural(child, orientation)
        if self.animating:
            size = max(1.0, _mix(self._from[axis], nat, self._t))
        elif (child in self._smooth and self._shown[axis]
              and nat != self._shown[axis] and self.get_mapped()):
            # the face changed size on its own: hold this frame, then spring
            size = self._shown[axis]
            if not self._retarget_src:
                self._retarget_src = GLib.idle_add(self._retarget)
        else:
            size = nat
        size = int(round(size))
        self._shown[axis] = size
        return size, size, -1, -1

    def do_size_allocate(self, width, height, baseline):
        for child in (self._previous, self._current):
            if child is None or not child.get_child_visible():
                continue
            w = self._natural(child, Gtk.Orientation.HORIZONTAL)
            h = self._natural(child, Gtk.Orientation.VERTICAL)
            x = (width - w) / 2
            # smaller faces sit centred; a bigger one is revealed from the top
            y = (height - h) / 2 if h <= height else 0
            child.allocate(w, h, -1,
                           Gsk.Transform.new().translate(_point(x, y)))

    def do_snapshot(self, snapshot):
        width = self.get_width()
        t = max(0.0, min(1.0, self._t))
        morphing = self.animating and self._previous is not None
        layers = []
        if morphing:
            out = max(0.0, 1.0 - t * 2.4)
            layers.append((self._previous, out, _mix(1.0, 1.05, t),
                           (1.0 - out) * 6.0))
            fade_in = max(0.0, min(1.0, (t - 0.12) / 0.55))
            layers.append((self._current, fade_in, _mix(0.94, 1.0, t),
                           (1.0 - fade_in) * 4.0))
        elif self._current is not None:
            layers.append((self._current, 1.0, 1.0, 0.0))
        for child, alpha, scale, blur in layers:
            if child is None or alpha <= 0.01:
                continue
            # blur is cheap on a pill but costly on the whole card with the
            # software renderer; the card fades and scales without it
            if child.get_width() * child.get_height() > BLUR_MAX_AREA:
                blur = 0.0
            snapshot.push_opacity(alpha)
            if blur > 0.3:
                snapshot.push_blur(blur)
            snapshot.save()
            if abs(scale - 1.0) > 0.001:
                snapshot.translate(_point(width / 2, 0))
                snapshot.scale(scale, scale)
                snapshot.translate(_point(-width / 2, 0))
            self.snapshot_child(child, snapshot)
            snapshot.restore()
            if blur > 0.3:
                snapshot.pop()
            snapshot.pop()

    def do_dispose(self):
        if self._retarget_src:
            GLib.source_remove(self._retarget_src)
            self._retarget_src = 0
        for child in list(self._children.values()):
            child.unparent()
        self._children.clear()
        self._current = self._previous = None
        Gtk.Widget.do_dispose(self)
