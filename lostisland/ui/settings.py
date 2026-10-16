"""Preferences window. Every change applies and persists instantly;
structural changes (modules) rebuild the island in place."""

from __future__ import annotations

from gi.repository import Adw, Gdk, Gtk

from lostisland import config

FACES = [
    ("auto", "Automatic", "Music with art + EQ when playing, clock otherwise"),
    ("status", "Clock + battery", "Time and charge, always"),
    ("lyrics", "Lyrics", "The current synced lyric line"),
    ("title", "Song title", "Just the title — never the artist"),
    ("compact", "Music icon", "Album art and EQ only"),
    ("clock", "Clock only", ""),
    ("battery", "Battery only", ""),
    ("weather", "Weather", "Temperature and conditions"),
    ("bluetooth", "Bluetooth", "Connected device and its battery"),
    ("claude", "Claude usage", "Time + Claude 5-hour session limit %"),
]

MODULES = [
    ("music", "Music", "MPRIS players: pill face, full controls, album art"),
    ("lyrics", "Lyrics", "Synced lyrics from lrclib.net for the lyrics face"),
    ("volume_osd", "Volume OSD", "Peek on volume changes"),
    ("battery", "Battery", "Charge ring and plug/unplug peeks"),
    ("notifications", "Notifications", "Mirror notifications as peeks"),
    ("network", "Network", "Connectivity chip and peeks"),
    ("bluetooth", "Bluetooth", "Connected device chip and peeks"),
    ("weather", "Weather", "Weather face on the pill and the card tile"),
    ("system", "System stats", "CPU and RAM readout while expanded"),
    ("toggles", "Quick toggles", "Wi-Fi, Bluetooth, sound and mic"),
    ("tools", "Tools", "Screenshot, color picker, Do Not Disturb, power"),
    ("clipboard", "Clipboard", "Recent copied text, kept in memory only"),
    ("claude_status", "Claude Code status",
     "Thinking, tool use and approval requests on the pill"),
    ("transfers", "Downloads", "Browser downloads and script progress"),
    ("indicators", "Caps Lock and brightness", "Peeks when they change"),
    ("wallpaper", "Wallpaper picker", "Wallpaper carousel in the card"),
]

WALL_BACKENDS = [("auto", "Automatic", "awww or swww if running, else Sway"),
                 ("sway", "Sway", "output * bg, saved to wallpaper.conf"),
                 ("awww", "awww", "Animated transitions"),
                 ("swww", "swww", "Animated transitions"),
                 ("command", "Custom command", "Runs your command with $1")]
WALL_FILLS = ["fill", "fit", "stretch", "center", "tile"]
WALL_TRANSITIONS = ["grow", "wipe", "wave", "fade", "center", "outer", "left",
                    "right", "top", "bottom", "simple", "any", "random"]


class SettingsWindow(Adw.PreferencesWindow):
    def __init__(self, cfg: dict, on_apply):
        super().__init__(title="Lost Island")
        self.set_default_size(420, 620)
        self.set_search_enabled(False)
        self.cfg = cfg
        self.on_apply = on_apply

        self.add(self._island_page())
        self.add(self._modules_page())

    # -- helpers -----------------------------------------------------------

    def _apply(self, structural: bool = False):
        config.save(self.cfg)
        self.on_apply(structural)

    def _switch(self, title: str, subtitle: str, key: str,
                structural: bool = False, mod: bool = False):
        row = Adw.SwitchRow(title=title, subtitle=subtitle)
        row.set_active(self.cfg["modules"][key] if mod else self.cfg[key])
        def on_change(r, _p):
            if mod:
                self.cfg["modules"][key] = r.get_active()
            else:
                self.cfg[key] = r.get_active()
            self._apply(structural)
        row.connect("notify::active", on_change)
        return row

    # -- pages -------------------------------------------------------------

    def _island_page(self):
        page = Adw.PreferencesPage(title="Island", icon_name="go-home-symbolic")

        pos = Adw.PreferencesGroup(title="Position")
        pos.add(self._switch(
            "Sit on top of panels",
            "Overlap the bar at the screen edge instead of sitting below it",
            "overlap_panel"))
        pos.add(self._switch(
            "Keep windows below the island",
            "Reserve a strip at the top so the pill never covers title bars",
            "reserve_space"))

        margin = Adw.SpinRow.new_with_range(0, 80, 1)
        margin.set_title("Top margin")
        margin.set_subtitle("Distance from the screen edge, px")
        margin.set_value(self.cfg["margin_top"])
        margin.connect("notify::value", lambda r, _p: (
            self.cfg.__setitem__("margin_top", int(r.get_value())),
            self._apply()))
        pos.add(margin)

        monitors = ["Primary"]
        display = Gdk.Display.get_default()
        if display:
            items = display.get_monitors()
            monitors += [items.get_item(i).get_connector() or f"#{i}"
                         for i in range(items.get_n_items())]
        combo = Adw.ComboRow(title="Monitor")
        combo.set_model(Gtk.StringList.new(monitors))
        try:
            combo.set_selected(monitors.index(self.cfg["monitor"]))
        except ValueError:
            combo.set_selected(0)
        def on_monitor(r, _p):
            i = r.get_selected()
            self.cfg["monitor"] = "" if i == 0 else monitors[i]
            self._apply()
        combo.connect("notify::selected", on_monitor)
        pos.add(combo)

        overlay = Adw.SwitchRow(
            title="Above fullscreen apps",
            subtitle="Keep the island visible over games and videos")
        overlay.set_active(self.cfg["layer"] == "overlay")
        overlay.connect("notify::active", lambda r, _p: (
            self.cfg.__setitem__("layer",
                                 "overlay" if r.get_active() else "top"),
            self._apply()))
        pos.add(overlay)
        page.add(pos)

        look = Adw.PreferencesGroup(title="Look")
        shape = Adw.ComboRow(
            title="Shape",
            subtitle="Floating island or top-edge notch")
        shapes = [("island", "Island"), ("notch", "Notch")]
        shape.set_model(Gtk.StringList.new([s[1] for s in shapes]))
        shape.set_selected(1 if self.cfg.get("shape") == "notch" else 0)
        shape.connect("notify::selected", lambda r, _p: (
            self.cfg.__setitem__("shape", shapes[r.get_selected()][0]),
            self._apply()))
        look.add(shape)
        # which face the resting pill shows now, like the Windows "Face"
        face = Adw.ComboRow(
            title="Pill face",
            subtitle="What the resting pill shows")
        face.set_model(Gtk.StringList.new([f[1] for f in FACES]))
        keys = [f[0] for f in FACES]
        current = self.cfg.get("pill_face", "auto")
        face.set_selected(keys.index(current) if current in keys else 0)
        face.connect("notify::selected",
                     lambda r, _p: self._pick_face(keys[r.get_selected()]))
        look.add(face)
        self._face_row = face
        opacity = Adw.SpinRow.new_with_range(30, 100, 5)
        opacity.set_title("Opacity")
        opacity.set_subtitle("Island background transparency, %")
        opacity.set_value(round(float(self.cfg.get("opacity", 0.97)) * 100))
        opacity.connect("notify::value", lambda r, _p: (
            self.cfg.__setitem__("opacity", round(r.get_value() / 100, 2)),
            self._apply()))
        look.add(opacity)
        color = Adw.ActionRow(title="Accent color")
        btn = Gtk.ColorDialogButton()
        btn.set_dialog(Gtk.ColorDialog(with_alpha=False))
        rgba = Gdk.RGBA()
        rgba.parse(self.cfg["accent"])
        btn.set_rgba(rgba)
        btn.set_valign(Gtk.Align.CENTER)
        def on_color(b, _p):
            c = b.get_rgba()
            self.cfg["accent"] = "#%02x%02x%02x" % (
                int(c.red * 255), int(c.green * 255), int(c.blue * 255))
            self._apply()
        btn.connect("notify::rgba", on_color)
        color.add_suffix(btn)
        look.add(color)
        look.add(self._switch("24-hour clock", "", "clock_24h"))
        look.add(self._switch("Clock in the idle pill", "", "idle_clock"))
        look.add(self._switch("Battery in the pill",
                              "Shown while charging or below 30%",
                              "pill_battery"))
        page.add(look)

        behavior = Adw.PreferencesGroup(title="Behavior")
        click = Adw.ComboRow(
            title="Left click on the pill",
            subtitle="Right click always opens the card; swipe cycles faces")
        actions = [("cycle", "Cycle faces"), ("expand", "Open the card")]
        click.set_model(Gtk.StringList.new([a[1] for a in actions]))
        click.set_selected(
            1 if self.cfg.get("click_action", "cycle") == "expand" else 0)
        click.connect("notify::selected", lambda r, _p: (
            self.cfg.__setitem__("click_action",
                                 actions[r.get_selected()][0]),
            self._apply()))
        behavior.add(click)
        peek = Adw.SpinRow.new_with_range(0.8, 6.0, 0.2)
        peek.set_digits(1)
        peek.set_title("Peek duration")
        peek.set_subtitle("Seconds a volume/notification peek stays up")
        peek.set_value(self.cfg["peek_seconds"])
        peek.connect("notify::value", lambda r, _p: (
            self.cfg.__setitem__("peek_seconds", round(r.get_value(), 1)),
            self._apply()))
        behavior.add(peek)
        page.add(behavior)

        faces = Adw.PreferencesGroup(
            title="Pill faces",
            description="Faces in the click/swipe cycle. The order is fixed; "
                        "a face with nothing to show falls back to the clock")
        enabled = self.cfg.get("pill_faces", [])
        self._face_switches = {}
        for key, title, subtitle in FACES:
            row = Adw.SwitchRow(title=title, subtitle=subtitle)
            self._face_switches[key] = row
            row.set_active(key in enabled)
            row.connect("notify::active",
                        lambda r, _p, k=key: self._toggle_face(k, r))
            faces.add(row)
        page.add(faces)
        return page

    def _pick_face(self, key: str):
        if key == self.cfg.get("pill_face"):
            return
        self.cfg["pill_face"] = key
        faces = list(self.cfg.get("pill_faces", []))
        structural = False
        if key not in faces:
            order = [f[0] for f in FACES]
            faces.append(key)
            faces.sort(key=order.index)
            self.cfg["pill_faces"] = faces
            row = self._face_switches.get(key)
            if row is not None:
                row.set_active(True)
        # the weather face needs the weather service running
        if key == "weather" and not self.cfg["modules"].get("weather"):
            self.cfg["modules"]["weather"] = True
            structural = True
        self._apply(structural)

    def _toggle_face(self, key: str, row):
        current = [f for f in self.cfg.get("pill_faces", []) if f != key]
        if row.get_active():
            order = [f[0] for f in FACES]
            current.append(key)
            current.sort(key=order.index)
        if not current:
            current = ["auto"]
        self.cfg["pill_faces"] = current
        if self.cfg.get("pill_face") not in current:
            self.cfg["pill_face"] = current[0]
            keys = [f[0] for f in FACES]
            if getattr(self, "_face_row", None) is not None:
                self._face_row.set_selected(keys.index(current[0]))
        self._apply()

    def _modules_page(self):
        page = Adw.PreferencesPage(title="Modules",
                                   icon_name="view-grid-symbolic")
        group = Adw.PreferencesGroup(
            title="Modules",
            description="Turning a module off removes its widgets, peeks "
                        "and background listeners entirely")
        for key, title, subtitle in MODULES:
            group.add(self._switch(title, subtitle, key,
                                   structural=True, mod=True))
        page.add(group)

        weather = Adw.PreferencesGroup(title="Weather")
        city = Adw.EntryRow(title="Location (empty = automatic)")
        city.set_text(self.cfg["weather_city"])
        city.connect("apply", lambda r: (
            self.cfg.__setitem__("weather_city", r.get_text().strip()),
            self._apply(structural=True)))
        city.set_show_apply_button(True)
        weather.add(city)
        page.add(weather)
        page.add(self._wallpaper_group())
        return page

    def _wallpaper_group(self):
        from lostisland.services import wallpaper as wp
        opts = wp.settings(self.cfg)
        group = Adw.PreferencesGroup(
            title="Wallpapers",
            description="The Wallpaper control in the card, or "
                        "lostisland --wallpapers (Super+Ctrl+W)")

        def save(key, value):
            saved = dict(self.cfg.get("wallpaper") or {})
            saved[key] = value
            self.cfg["wallpaper"] = saved
            self._apply()

        def entry(title, key):
            row = Adw.EntryRow(title=title)
            row.set_text(opts[key])
            row.set_show_apply_button(True)
            row.connect("apply", lambda r: save(key, r.get_text().strip()))
            group.add(row)
            return row

        entry("Folder", "folder")
        backend = Adw.ComboRow(title="Set with",
                               subtitle=WALL_BACKENDS[0][2])
        backend.set_model(Gtk.StringList.new([b[1] for b in WALL_BACKENDS]))
        keys = [b[0] for b in WALL_BACKENDS]
        backend.set_selected(keys.index(opts["backend"])
                             if opts["backend"] in keys else 0)
        backend.set_subtitle(WALL_BACKENDS[backend.get_selected()][2])

        def on_backend(r, _p):
            r.set_subtitle(WALL_BACKENDS[r.get_selected()][2])
            save("backend", keys[r.get_selected()])
        backend.connect("notify::selected", on_backend)
        group.add(backend)

        for title, key, values in (("Fill", "fill", WALL_FILLS),
                                   ("Transition (awww/swww)", "transition",
                                    WALL_TRANSITIONS)):
            row = Adw.ComboRow(title=title)
            row.set_model(Gtk.StringList.new(values))
            row.set_selected(values.index(opts[key])
                             if opts[key] in values else 0)
            row.connect("notify::selected", lambda r, _p, k=key, v=values:
                        save(k, v[r.get_selected()]))
            group.add(row)

        entry("Custom command ($1 = image)", "command")
        entry("Keep in sync (Sway file, empty = off)", "persist")
        pywal = Adw.SwitchRow(title="Recolor with pywal",
                              subtitle="Runs wal on the new wallpaper")
        pywal.set_active(bool(opts["pywal"]))
        pywal.connect("notify::active",
                      lambda r, _p: save("pywal", r.get_active()))
        group.add(pywal)
        return group
