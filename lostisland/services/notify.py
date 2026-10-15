"""Notification mirror with actions.

A private monitor connection watches org.freedesktop.Notifications Notify
calls without answering them, so mako keeps working untouched; the island
shows its own banner of what flies by. Buttons on that banner act through
`makoctl` on mako's copy of the notification.
"""

from __future__ import annotations

import json

from gi.repository import Gio, GLib, GObject

from lostisland.services import tools

# hint the Archcraft volume/brightness scripts set on their OSD popups;
# the island draws its own OSD for those, so the banner skips them
OSD_HINT = "x-canonical-private-synchronous"


def parse_actions(flat: list[str]) -> list[tuple[str, str]]:
    """["default", "Open", "reply", "Reply"] -> [(key, label), ...]"""
    pairs = list(zip(flat[0::2], flat[1::2]))
    return [(k, v) for k, v in pairs if k]


def is_osd(hints: dict) -> bool:
    return str(hints.get(OSD_HINT, "")).startswith("sys-notify")


def find_mako_id(listing: str, app: str, summary: str) -> int | None:
    """Newest id in `makoctl list -j` output matching app + summary."""
    try:
        data = json.loads(listing)
    except ValueError:
        return None
    # mako < 1.9 wrapped the list as {"data": [[...]]}
    if isinstance(data, dict):
        data = data.get("data", [[]])
        data = data[0] if data and isinstance(data[0], list) else data
    best = None
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue

        def field(*names):
            for name in names:
                value = item.get(name)
                if isinstance(value, dict):  # old mako: {"data": ...}
                    value = value.get("data")
                if value is not None:
                    return value
            return None

        nid = field("id")
        if (field("app_name", "app-name") == app
                and field("summary") == summary
                and isinstance(nid, int) and (best is None or nid > best)):
            best = nid
    return best


def _image_texture(hints: dict):
    """A Gdk.Texture from an image-data hint, or None."""
    raw = hints.get("image-data") or hints.get("image_data") or hints.get("icon_data")
    if not raw:
        return None
    try:
        from gi.repository import Gdk, GdkPixbuf
        width, height, stride, alpha, _bits, _chans, data = raw
        pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(
            GLib.Bytes.new(bytes(data)), GdkPixbuf.Colorspace.RGB, alpha, 8,
            width, height, stride)
        return Gdk.Texture.new_for_pixbuf(pixbuf)
    except (TypeError, ValueError, GLib.Error):
        return None


class NotifyService(GObject.Object):
    __gsignals__ = {
        # one dict: app, summary, body, icon, image_path, texture, actions
        "notified": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self):
        super().__init__()
        try:
            addr = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None)
            self._conn = Gio.DBusConnection.new_for_address_sync(
                addr,
                Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
                | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
                None, None,
            )
            self._conn.call_sync(
                "org.freedesktop.DBus", "/org/freedesktop/DBus",
                "org.freedesktop.DBus.Monitoring", "BecomeMonitor",
                GLib.Variant("(asu)", (
                    ["type='method_call',"
                     "interface='org.freedesktop.Notifications',"
                     "member='Notify'"], 0)),
                None, Gio.DBusCallFlags.NONE, -1, None,
            )
        except GLib.Error:
            self._conn = None
            return
        self._conn.add_filter(self._on_message)

    def _on_message(self, conn, message, incoming):
        # A monitor must never send anything. Returning None drops each
        # message after reading it, so GDBus does not auto-reply to the
        # Notify calls it sees (dbus-daemon closes monitors that do).
        if not incoming:
            return None
        try:
            if (message.get_interface() == "org.freedesktop.Notifications"
                    and message.get_member() == "Notify"):
                body = message.get_body()
                if body is not None:
                    app, _rid, icon, summary, text, actions, hints = \
                        body.unpack()[:7]
                    GLib.idle_add(self._emit, app, icon, summary, text,
                                  actions, hints)
        except (GLib.Error, ValueError):
            pass
        return None

    def _emit(self, app, icon, summary, text, actions, hints):
        hints = hints or {}
        if is_osd(hints):
            return False
        image_path = hints.get("image-path") or hints.get("image_path") or ""
        if not image_path and icon and (icon.startswith("/")
                                        or icon.startswith("file://")):
            image_path, icon = icon, ""
        if image_path.startswith("file://"):
            image_path = GLib.filename_from_uri(image_path)[0]
        self.emit("notified", {
            "app": app or "",
            "summary": summary or "",
            "body": text or "",
            "icon": icon or "",
            "image_path": image_path,
            "texture": _image_texture(hints),
            "actions": parse_actions(list(actions or [])),
        })
        return False


# -- acting on mako's copy -----------------------------------------------------

def act(note: dict, action: str | None, on_fallback=None):
    """Invoke `action` (None = dismiss) on mako's copy of `note`. When mako
    no longer has it, call on_fallback() instead."""
    def listed(ok: bool, out: str):
        nid = find_mako_id(out, note["app"], note["summary"]) if ok else None
        if nid is None:
            if on_fallback:
                on_fallback()
            return
        if action is None:
            tools.run(["makoctl", "dismiss", "-n", str(nid)])
        else:
            tools.run(["makoctl", "invoke", "-n", str(nid), action])
            tools.run(["makoctl", "dismiss", "-n", str(nid)])

    tools.run(["makoctl", "list", "-j"], listed)


def focus_app(app: str):
    """Bring the sending app's window forward, matching app_id or class."""
    if not app:
        return
    pattern = "(?i)^" + "".join(c if c.isalnum() else "." for c in app)

    def tried(ok: bool, _out: str):
        if not ok:
            tools.run(["swaymsg", f'[class="{pattern}"]', "focus"])

    tools.run(["swaymsg", f'[app_id="{pattern}"]', "focus"], tried)
