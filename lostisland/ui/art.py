"""Album art thumbnails, decoded once and shared.

The pill, the side bubble and the EQ tint all want the same cover at small
sizes. Decoding a full-size cover for each of them on every metadata update
wastes memory and time, so this keeps a few small textures keyed by file,
size and modification time.
"""

from __future__ import annotations

import colorsys
import os
from collections import OrderedDict

from gi.repository import Gdk, GdkPixbuf, GLib

_MAX = 12
_cache: OrderedDict[tuple, object] = OrderedDict()


def _key(path: str, kind: str, px: int):
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        return None
    return (path, kind, px, mtime)


def _remember(key, value):
    _cache[key] = value
    _cache.move_to_end(key)
    while len(_cache) > _MAX:
        _cache.popitem(last=False)
    return value


def thumb(path: str, px: int) -> Gdk.Texture | None:
    """A square texture of the cover at `px` pixels (cropped, not stretched)."""
    if not path:
        return None
    key = _key(path, "thumb", px)
    if key is None:
        return None
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, px * 4, px * 4,
                                                         True)
    except GLib.Error:
        return _remember(key, None)
    # centre-crop to a square, then scale to the target size
    w, h = pixbuf.get_width(), pixbuf.get_height()
    side = min(w, h)
    square = pixbuf.new_subpixbuf((w - side) // 2, (h - side) // 2, side, side)
    small = square.scale_simple(px, px, GdkPixbuf.InterpType.BILINEAR)
    return _remember(key, Gdk.Texture.new_for_pixbuf(small))


def tint(path: str) -> tuple[float, float, float] | None:
    """A bright version of the cover's average color, for the EQ bars."""
    if not path:
        return None
    key = _key(path, "tint", 0)
    if key is None:
        return None
    if key in _cache:
        return _cache[key]
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 16, 16, False)
    except GLib.Error:
        return _remember(key, None)
    one = pixbuf.scale_simple(1, 1, GdkPixbuf.InterpType.BILINEAR)
    data = one.get_pixels()
    h, s, _v = colorsys.rgb_to_hsv(data[0] / 255, data[1] / 255, data[2] / 255)
    rgb = colorsys.hsv_to_rgb(h, max(0.35, min(s, 0.85)), 0.98)
    return _remember(key, rgb)
