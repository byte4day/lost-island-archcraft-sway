"""The expanded card — media player up top, quick toggles and tiles below.

Every timer here lives only while the card is mapped: the 1 Hz seek tick,
the 3 s system sampler, the weather request. Unmapping tears it all down.
"""

from __future__ import annotations

import colorsys
import re
import time
import weakref

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango

from lostisland import config
from lostisland.services import tools
from lostisland.services.clipboard import preview as clipboard_preview
from lostisland.services.controls import SystemControls
from lostisland.services.recorder import system_audio_source
from lostisland.ui.draw import pick_icon
from lostisland.ui.launchers import LauncherRow
from lostisland.ui.tools import circle_button

ART_PX = 64
_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
         "Saturday", "Sunday")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")
TIMER_MIN_MINUTES, TIMER_MAX_MINUTES, TIMER_STEP = 5, 90, 5


class Expanded(Gtk.Box):
    def __init__(self, cfg: dict, media, power, on_timer_change=None,
                 weather=None, system=None, on_settings=None, recorder=None,
                 airplay=None, tools_row=None, clipboard=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=11)
        self.add_css_class("expanded")
        self.cfg = cfg
        self.media = media
        self.power = power
        self.weather = weather
        self.system = system
        self.on_timer_change = on_timer_change
        self.on_settings = on_settings
        self.recorder = recorder
        self.airplay = airplay

        self._pos_timer = 0
        self._seek_dragging = False
        self._position_us = 0
        self.controls = SystemControls()
        self._controls_timer = 0
        self._control_busy: set[str] = set()
        self.control_buttons: dict[str, Gtk.ToggleButton] = {}
        self.control_handlers: dict[str, int] = {}
        self.control_labels: dict[str, Gtk.Label] = {}
        self.on_clip_copied = None

        self.tools = tools_row
        self.clipboard = clipboard
        self._art_css: Gtk.CssProvider | None = None
        self._build_header()
        self._build_player()
        self._build_controls(cfg.get("modules", {}).get("toggles", True))
        self._build_volume()
        self.append(LauncherRow())
        self._build_tiles()
        self._build_footer()

        if self.recorder is not None:
            self_ref = weakref.ref(self)

            def on_recorder_changed(*_):
                widget = self_ref()
                if widget is not None:
                    widget._sync_recorder()

            handler = self.recorder.connect("changed", on_recorder_changed)
            weakref.finalize(self, self.recorder.disconnect, handler)
            self._sync_recorder()

        if self.airplay is not None:
            self_ref = weakref.ref(self)

            def on_airplay_changed(*_):
                widget = self_ref()
                if widget is not None:
                    widget._sync_airplay()

            handler = self.airplay.connect("changed", on_airplay_changed)
            weakref.finalize(self, self.airplay.disconnect, handler)
            self._sync_airplay()

        self.connect("map", lambda *_: self._on_map())
        self.connect("unmap", lambda *_: self._on_unmap())

    # -- header: gear + connectivity chips ---------------------------------

    def _build_header(self):
        # Record and AirPlay live in the control grid as circles; this
        # section only builds their state lines and the record setup panel.
        self.record_button = circle_button("videocam",
                                           "Record a display as MP4")
        self.record_icon = self.record_button.get_child()
        self.record_text = Gtk.Label(label="Record")
        self.record_button.connect("clicked", self._on_record_clicked)

        self.airplay_button = circle_button("airplay",
                                            "Start the AirPlay receiver")
        self.airplay_text = Gtk.Label(label="AirPlay")
        self.airplay_button.connect("clicked", self._on_airplay_clicked)

        self.clip_button = circle_button(
            "content_paste", "Clipboard history", toggle=True)
        self.clip_button.connect("toggled", self._on_clip_toggled)

        self._status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                   spacing=6)
        self.airplay_status = Gtk.Label(xalign=0)
        self.airplay_status.add_css_class("record-status")
        self.airplay_status.set_visible(False)
        self._status_box.append(self.airplay_status)

        self.record_status = Gtk.Label(xalign=0)
        self.record_status.add_css_class("record-status")
        self.record_status.set_visible(False)
        self._status_box.append(self.record_status)

        self.record_setup = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                    spacing=9)
        self.record_setup.add_css_class("record-setup")
        self.record_setup.set_visible(False)
        self._status_box.append(self.record_setup)

        self.record_display_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                          spacing=10)
        self.record_display_row.append(Gtk.Label(label="Display", xalign=0,
                                                  hexpand=True))
        self.record_display_picker = None
        self.record_display_row.set_visible(False)
        self.record_setup.append(self.record_display_row)

        audio_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        audio_row.append(Gtk.Label(label="Audio", xalign=0, hexpand=True))
        self.with_audio = Gtk.CheckButton(label="With audio")
        self.with_audio.set_tooltip_text(
            "Capture sound playing through the default output")
        self.without_audio = Gtk.CheckButton(label="Without audio")
        self.without_audio.set_group(self.with_audio)
        self.with_audio.set_active(True)
        audio_row.append(self.with_audio)
        audio_row.append(self.without_audio)
        self.record_setup.append(audio_row)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_halign(Gtk.Align.END)
        cancel = Gtk.Button(label="Cancel")
        cancel.add_css_class("record-action")
        cancel.connect("clicked", lambda *_: self.record_setup.set_visible(False))
        start = Gtk.Button(label="Start recording")
        start.add_css_class("record-action")
        start.add_css_class("record-action--primary")
        start.connect("clicked", self._start_recording)
        actions.append(cancel)
        actions.append(start)
        self.record_setup.append(actions)

    def _on_record_clicked(self, *_):
        if self.recorder.running:
            self.recorder.stop()
        else:
            self._show_record_setup()

    def _on_airplay_clicked(self, *_):
        if self.airplay.running:
            self.airplay.stop()
        else:
            self.airplay.start()

    def _sync_airplay(self, *_):
        if self.airplay is None:
            return
        running = self.airplay.running
        self.airplay_button.set_sensitive(not self.airplay.stopping)
        self.airplay_button.set_tooltip_text(
            f"Connect to Lost Island from AirPlay; click to stop"
            if running else "Start UxPlay AirPlay receiver")
        self.airplay_text.set_label("AirPlay on" if running else "AirPlay")
        if running:
            self.airplay_button.add_css_class("airplay-button--active")
        else:
            self.airplay_button.remove_css_class("airplay-button--active")
        error = self.airplay.message.startswith(("UxPlay", "Could not"))
        self.airplay_status.set_visible(error)
        if error:
            self.airplay_status.set_label(self.airplay.message)

    def _show_record_setup(self):
        display = self.get_display()
        model = display.get_monitors() if display else None
        monitors = []
        if model is not None:
            for index in range(model.get_n_items()):
                monitor = model.get_item(index)
                connector = monitor.get_connector()
                if connector:
                    size = monitor.get_geometry()
                    monitors.append((connector,
                                     f"{connector} · {size.width} × {size.height}"))
        self.record_monitors = monitors
        if not monitors:
            self.record_status.set_label("No connected display is available")
            self.record_status.set_visible(True)
            self.record_setup.set_visible(False)
            return
        if self.record_display_picker is not None:
            self.record_display_row.remove(self.record_display_picker)
        self.record_display_picker = Gtk.DropDown.new_from_strings(
            [label for _, label in monitors])
        self.record_display_picker.set_selected(next(
            (i for i, (connector, _) in enumerate(monitors)
             if connector == self.cfg.get("monitor")), 0))
        self.record_display_row.append(self.record_display_picker)
        self.record_display_row.set_visible(len(monitors) > 1)

        audio_available = system_audio_source() is not None
        self.with_audio.set_sensitive(audio_available)
        self.with_audio.set_active(audio_available)
        self.without_audio.set_active(not audio_available)
        self.record_status.set_visible(False)
        self.record_setup.set_visible(True)

    def _start_recording(self, *_):
        index = self.record_display_picker.get_selected()
        if index >= len(self.record_monitors):
            self.record_status.set_label("Choose a display to record")
            self.record_status.set_visible(True)
            return
        connector = self.record_monitors[index][0]
        if self.recorder.start(connector, self.with_audio.get_active()):
            self.record_setup.set_visible(False)

    def _sync_recorder(self, *_):
        if self.recorder is None:
            return
        running = self.recorder.running
        stopping = self.recorder.stopping
        if running:
            self.record_setup.set_visible(False)
        self.record_button.set_sensitive(not stopping)
        self.record_button.set_tooltip_text(
            self.recorder.message or "Record the selected monitor as MP4")
        self.record_icon.set_label("stop" if running else "videocam")
        self.record_text.set_label(
            "Saving" if stopping else "Stop" if running else "Record")
        if running:
            self.record_button.add_css_class("record-button--active")
        else:
            self.record_button.remove_css_class("record-button--active")
        message = self.recorder.message
        show_status = stopping or bool(message and not running)
        self.record_status.set_visible(show_status)
        if show_status:
            self.record_status.set_label(
                "Saving recording" if stopping else
                "Saved to Videos/Recordings" if message.startswith("Saved to ")
                else message)

    # -- media player section ---------------------------------------------

    def _build_player(self):
        self.player_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.player_box.add_css_class("player")

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        art_frame = Gtk.Box()
        art_frame.add_css_class("art-frame")
        art_frame.set_overflow(Gtk.Overflow.HIDDEN)
        self.art = Gtk.Picture()
        self.art.set_size_request(ART_PX, ART_PX)
        self.art.set_content_fit(Gtk.ContentFit.COVER)
        art_frame.append(self.art)

        meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        meta.set_valign(Gtk.Align.CENTER)
        meta.set_hexpand(True)
        self.title = _label("track-title", 24)
        self.artist = _label("track-artist", 30)
        self.album = _label("track-album", 34)
        for w in (self.title, self.artist, self.album):
            meta.append(w)

        head.append(art_frame)
        head.append(meta)

        seek_box = self.seek_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.time_now = Gtk.Label(label="0:00")
        self.time_now.add_css_class("seek-time")
        self.seek = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 1)
        self.seek.add_css_class("seek")
        self.seek.set_hexpand(True)
        self.seek.set_draw_value(False)
        self.time_total = Gtk.Label(label="0:00")
        self.time_total.add_css_class("seek-time")
        seek_box.append(self.time_now)
        seek_box.append(self.seek)
        seek_box.append(self.time_total)

        drag = Gtk.GestureClick()
        drag.connect("pressed", lambda *_: setattr(self, "_seek_dragging", True))
        drag.connect("released", self._on_seek_released)
        self.seek.add_controller(drag)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=28)
        controls.set_halign(Gtk.Align.CENTER)
        self.btn_prev = _media_btn("media-skip-backward-symbolic")
        self.btn_play = _media_btn("media-playback-start-symbolic", main=True)
        self.btn_next = _media_btn("media-skip-forward-symbolic")
        self.btn_prev.connect("clicked", lambda *_: self.media.previous())
        self.btn_play.connect("clicked", lambda *_: self.media.play_pause())
        self.btn_next.connect("clicked", lambda *_: self.media.next())
        for b in (self.btn_prev, self.btn_play, self.btn_next):
            controls.append(b)

        self.player_box.append(head)
        self.player_box.append(seek_box)
        self.player_box.append(controls)
        self.append(self.player_box)

        # idle header shown when nothing plays
        self.idle_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.idle_box.add_css_class("idle")
        self.big_clock = Gtk.Label(xalign=0)
        self.big_clock.add_css_class("idle-clock")
        self.big_date = Gtk.Label(xalign=0)
        self.big_date.add_css_class("idle-date")
        self.idle_box.append(self.big_clock)
        self.idle_box.append(self.big_date)
        self.append(self.idle_box)

    # -- quick toggles ------------------------------------------------------

    def _build_controls(self, with_toggles: bool):
        """One grid of identical circles: connectivity first, then tools."""
        cells: list[tuple[Gtk.Button, Gtk.Label | str]] = []
        if with_toggles:
            specs = (
                ("wifi", "wifi", "Wi-Fi", "nm-connection-editor"),
                ("bluetooth", "bluetooth", "Bluetooth", "blueman-manager"),
                ("sound", "volume_up", "Sound", "pavucontrol"),
                ("mic", "mic", "Mic", "pavucontrol"),
            )
            for name, icon, label, settings_app in specs:
                button = circle_button(
                    icon, f"Toggle {label}; right click for settings",
                    toggle=True)
                self.control_buttons[name] = button
                self.control_handlers[name] = button.connect(
                    "toggled", self._on_control_toggle, name)
                right = Gtk.GestureClick(button=3)
                right.connect("released", lambda *_args, app=settings_app:
                              _spawn([app]))
                button.add_controller(right)
                caption = Gtk.Label(label=label)
                self.control_labels[name] = caption
                cells.append((button, caption))
        if self.tools is not None:
            cells += [(self.tools.dnd, "Focus"), (self.tools.power, "Power"),
                      (self.tools.shot, "Screen"), (self.tools.region, "Area"),
                      (self.tools.picker, "Color")]
        if self.recorder is not None:
            cells.append((self.record_button, self.record_text))
        if self.airplay is not None:
            cells.append((self.airplay_button, self.airplay_text))
        if self.clipboard is not None and self.clipboard.available:
            cells.append((self.clip_button, "Clipboard"))

        grid = Gtk.Grid(column_spacing=4, row_spacing=10)
        grid.set_column_homogeneous(True)
        grid.add_css_class("controls")
        columns = 6 if len(cells) > 8 else 4
        for index, (button, caption) in enumerate(cells):
            grid.attach(_cell(button, caption), index % columns,
                        index // columns, 1, 1)
        # grid + its slide-out panels share one zero-spacing column, so
        # closed panels do not leave gaps; panels carry their own margin
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        section.append(grid)
        self._section = section
        self._build_clipboard()
        if self.tools is not None:
            section.append(self.tools.power_revealer)
            section.append(self.tools.message)
        self._status_box.add_css_class("status-box")
        section.append(self._status_box)
        self.append(section)

    def _on_control_toggle(self, button: Gtk.ToggleButton, name: str):
        self._control_busy.add(name)
        button.set_sensitive(False)
        self.controls.set(name, button.get_active(),
                          lambda ok: self._on_control_set(name, ok))

    def _on_control_set(self, name: str, ok: bool):
        self._control_busy.discard(name)
        if not ok:
            self.control_buttons[name].set_tooltip_text(
                f"Could not change {name}; check system permissions")
        self._refresh_control(name)

    def _refresh_control(self, name: str):
        if name in self._control_busy:
            return
        self.controls.read(name, lambda state: self._show_control_state(name, state))

    def _show_control_state(self, name: str, state: bool | None):
        if name in self._control_busy:
            return
        button = self.control_buttons[name]
        button.set_sensitive(state is not None)
        if state is None:
            button.set_tooltip_text(f"{name.capitalize()} unavailable")
            return
        button.handler_block(self.control_handlers[name])
        button.set_active(state)
        button.handler_unblock(self.control_handlers[name])
        button.set_tooltip_text(
            f"{name.capitalize()} {'on' if state else 'off'}; right click for settings")

    def _refresh_controls(self) -> bool:
        if not self.get_mapped():
            return False
        for name in self.control_buttons:
            self._refresh_control(name)
        return True

    # -- tiles -------------------------------------------------------------

    # -- clipboard ----------------------------------------------------------

    def _build_clipboard(self):
        self.clip_revealer = Gtk.Revealer()
        self.clip_revealer.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.clip_revealer.set_transition_duration(180)
        if self.clipboard is None or not self.clipboard.available:
            return
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        panel.add_css_class("clip-panel")
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label="Recently copied", xalign=0, hexpand=True)
        title.add_css_class("clip-title")
        clear = Gtk.Button(label="Clear")
        clear.add_css_class("clip-clear")
        clear.connect("clicked", lambda *_: self.clipboard.clear())
        head.append(title)
        head.append(clear)
        panel.append(head)

        self.clip_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                 spacing=2)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_max_content_height(196)
        scroller.set_propagate_natural_height(True)
        scroller.set_child(self.clip_list)
        panel.append(scroller)
        self.clip_revealer.set_child(panel)
        self._section.append(self.clip_revealer)

        self_ref = weakref.ref(self)

        def on_changed(*_):
            widget = self_ref()
            if widget is not None:
                widget._render_clipboard()

        handler = self.clipboard.connect("changed", on_changed)
        weakref.finalize(self, self.clipboard.disconnect, handler)
        self._render_clipboard()

    def _render_clipboard(self):
        while (child := self.clip_list.get_first_child()) is not None:
            self.clip_list.remove(child)
        if not self.clipboard.history:
            empty = Gtk.Label(label="Copy some text and it shows up here",
                              xalign=0)
            empty.add_css_class("clip-empty")
            self.clip_list.append(empty)
            return
        for text in self.clipboard.history:
            button = Gtk.Button()
            button.add_css_class("clip-item")
            line = Gtk.Label(label=clipboard_preview(text), xalign=0)
            line.set_ellipsize(Pango.EllipsizeMode.END)
            button.set_child(line)
            button.set_tooltip_text("Copy again")
            button.connect("clicked", self._on_clip_pick, text)
            self.clip_list.append(button)

    def _on_clip_toggled(self, button: Gtk.ToggleButton):
        open_ = button.get_active()
        if open_ and self.tools is not None:
            self.tools.close_power()
        self.clip_revealer.set_reveal_child(open_)

    def _on_clip_pick(self, _button: Gtk.Button, text: str):
        self.clipboard.copy(text)
        self.clip_button.set_active(False)
        if self.on_clip_copied:
            self.on_clip_copied(text)

    def _build_volume(self):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add_css_class("volume-row")
        self.vol_icon = _symbol("volume_up")
        self.vol = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.vol.add_css_class("vol")
        self.vol.set_hexpand(True)
        self.vol.set_draw_value(False)
        self.vol.connect("change-value", self._on_vol_set)
        self.vol_value = Gtk.Label(label="")
        self.vol_value.add_css_class("vol-value")
        self.vol_value.set_width_chars(4)
        self.vol_value.set_xalign(1)
        row.append(self.vol_icon)
        row.append(self.vol)
        row.append(self.vol_value)
        self.append(row)

    def _build_tiles(self):
        """One quiet line: focus timer, weather, battery."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.add_css_class("info-line")

        self.timer_tile = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                  spacing=6)
        self.timer_tile.add_css_class("info-item")
        self.timer_tile.append(_symbol("timer"))
        self.timer_label = Gtk.Label(label="25:00")
        self.timer_label.add_css_class("info-value")
        self.timer_tile.set_tooltip_text(
            "Focus timer; scroll to change length")
        timer_scroll = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.VERTICAL
            | Gtk.EventControllerScrollFlags.DISCRETE)
        timer_scroll.connect("scroll", self._on_timer_scroll)
        self.timer_tile.add_controller(timer_scroll)
        self.timer_toggle = Gtk.Button()
        self.timer_toggle.add_css_class("mini-btn")
        self.timer_toggle.set_icon_name("media-playback-start-symbolic")
        self.timer_toggle.set_tooltip_text("Start or pause the focus timer")
        self.timer_toggle.connect("clicked", self._on_timer_toggle)
        timer_reset = Gtk.Button()
        timer_reset.add_css_class("mini-btn")
        timer_reset.set_icon_name("view-refresh-symbolic")
        timer_reset.set_tooltip_text("Reset the focus timer")
        timer_reset.connect("clicked", self._on_timer_reset)
        self.timer_tile.append(self.timer_label)
        self.timer_tile.append(self.timer_toggle)
        self.timer_tile.append(timer_reset)

        self.weather_tile = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                    spacing=6)
        self.weather_tile.add_css_class("info-item")
        self.weather_tile.set_hexpand(True)
        self.weather_tile.set_halign(Gtk.Align.CENTER)
        self.weather_icon = Gtk.Image.new_from_icon_name("weather-clear-symbolic")
        self.weather_icon.set_pixel_size(18)
        self.weather_temp = Gtk.Label(label="")
        self.weather_temp.add_css_class("info-value")
        self.weather_desc = Gtk.Label(label="")
        self.weather_desc.add_css_class("info-sub")
        self.weather_desc.set_ellipsize(Pango.EllipsizeMode.END)
        self.weather_desc.set_max_width_chars(12)
        self.weather_tile.append(self.weather_icon)
        self.weather_tile.append(self.weather_temp)
        self.weather_tile.append(self.weather_desc)

        self.battery_tile = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                    spacing=4)
        self.battery_tile.add_css_class("info-item")
        self.batt_icon = _symbol("battery_full")
        self.batt_value = Gtk.Label(label="")
        self.batt_value.add_css_class("info-value")
        self.batt_label = self.batt_value  # kept for older callers
        self.battery_tile.append(self.batt_icon)
        self.battery_tile.append(self.batt_value)

        settings = Gtk.Button()
        settings.add_css_class("mini-btn")
        settings.set_child(_symbol("settings"))
        settings.set_tooltip_text("Island settings")
        settings.connect("clicked",
                         lambda *_: self.on_settings and self.on_settings())

        row.append(self.timer_tile)
        row.append(self.weather_tile)
        row.append(self.battery_tile)
        row.append(settings)
        self.append(row)

        if self.weather is None:
            self.weather_tile.set_visible(False)
        else:
            self.weather.connect("changed", self._on_weather)

        # timer state
        self.timer_minutes = _clamp_minutes(self.cfg.get("timer_minutes", 25))
        self.timer_left = self.timer_minutes * 60
        self.timer_running = False
        self._timer_src = 0
        self._sync_timer_ui()

    def _build_footer(self):
        self.sys_label = Gtk.Label()
        self.sys_label.add_css_class("sys-stats")
        self.sys_label.set_visible(self.system is not None)
        if self.system is not None:
            self.system.connect("changed", self._on_system)
        self.append(self.sys_label)

    # -- refresh from services --------------------------------------------

    def refresh_media(self):
        p = self.media.active
        has = p is not None
        self.player_box.set_visible(has)
        self.idle_box.set_visible(not has)
        if not has:
            self._set_art_tint(None)
            self._refresh_big_clock()
            self._sync_pos_timer()
            return
        self.title.set_label(p.title or "Unknown track")
        self.artist.set_label(p.artist or "")
        self.album.set_label(p.album or "")
        self.artist.set_visible(bool(p.artist))
        self.album.set_visible(bool(p.album))
        pixbuf = None
        if p.art_path:
            try:
                # load at display size so the picture never inflates the card
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    p.art_path, ART_PX, ART_PX, False)
            except GLib.Error:
                pixbuf = None
        self.art.set_paintable(
            Gdk.Texture.new_for_pixbuf(pixbuf) if pixbuf else None)
        self._set_art_tint(art_tint(pixbuf) if pixbuf else None)
        playing = p.status == "Playing"
        self.btn_play.set_icon_name(
            "media-playback-pause-symbolic" if playing
            else "media-playback-start-symbolic")
        self.btn_prev.set_sensitive(p.can_prev)
        self.btn_next.set_sensitive(p.can_next)
        total = p.length_us
        # browsers often publish no track length; a bar pinned at the end
        # with "0:00" is worse than no bar
        self.seek_box.set_visible(total > 0)
        self.seek.set_range(0, max(1, total))
        self.time_total.set_label(_fmt_us(total))
        self._sync_pos_timer()
        self._poll_position()

    def _set_art_tint(self, rgb: tuple[int, int, int] | None):
        display = self.get_display() or Gdk.Display.get_default()
        if self._art_css is not None:
            Gtk.StyleContext.remove_provider_for_display(display, self._art_css)
            self._art_css = None
        if rgb is None:
            return
        base, bright = rgb, _shade(rgb, value=0.95, min_sat=0.25)
        provider = Gtk.CssProvider()
        provider.load_from_string(f"""
            .player {{
              background-image: linear-gradient(160deg,
                  rgba({base[0]}, {base[1]}, {base[2]}, 0.62),
                  rgba({base[0]}, {base[1]}, {base[2]}, 0.18));
              border-color: rgba({bright[0]}, {bright[1]}, {bright[2]}, 0.22);
            }}
            .player scale.seek highlight {{
              background: rgb({bright[0]}, {bright[1]}, {bright[2]});
            }}
        """)
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self._art_css = provider

    def refresh_battery(self):
        if not self.power.available:
            self.battery_tile.set_visible(False)
            return
        pct = self.power.percentage
        self.batt_value.set_label(f"{pct:.0f}%")
        self.batt_icon.set_label(
            "battery_charging_full" if self.power.charging else
            "battery_full" if pct > 80 else "battery_5_bar" if pct > 55 else
            "battery_3_bar" if pct > 30 else "battery_1_bar")
        self.battery_tile.set_tooltip_text(
            "Charging" if self.power.charging else "On battery")

    def refresh_volume(self, percent: int, muted: bool = False):
        self.vol.set_value(percent)
        self.vol_value.set_label("Muted" if muted else f"{percent}%")
        self.vol_icon.set_label(
            "volume_off" if muted or percent == 0 else
            "volume_down" if percent < 50 else "volume_up")
        if "sound" in self.control_buttons:
            self._show_control_state("sound", not muted)

    def _read_volume(self):
        def got_volume(ok: bool, out: str):
            match = re.search(r"(\d+)%", out) if ok else None
            if match:
                percent = int(match.group(1))
                tools.run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"],
                          lambda ok2, out2: self.refresh_volume(
                              percent, ok2 and "yes" in out2))
        tools.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], got_volume)

    def refresh_network(self, name: str, kind: str, connected: bool):
        label = self.control_labels.get("wifi")
        if label is None:
            return
        wireless = connected and "wireless" in kind
        label.set_label(_short(name) if wireless and name else "Wi-Fi")
        self.control_buttons["wifi"].get_parent().set_tooltip_text(
            f"Connected to {name}" if connected and name else
            "Offline" if not connected else "Connected")

    def refresh_bluetooth(self, device: str, connected: bool, battery: int):
        label = self.control_labels.get("bluetooth")
        if label is None:
            return
        label.set_label(_short(device) if connected and device else "Bluetooth")
        if connected:
            self.control_buttons["bluetooth"].get_parent().set_tooltip_text(
                device if battery < 0 else f"{device}, {battery}% battery")

    def _on_weather(self, _svc, temp, desc, icon):
        self.weather_temp.set_label(temp)
        self.weather_desc.set_label(desc)
        # prefer the full-color weather set; symbolic suns get too abstract
        self.weather_icon.set_from_icon_name(pick_icon(
            self, icon.replace("-symbolic", ""), icon,
            "weather-few-clouds"))

    def _on_system(self, _svc, cpu, ram, ram_gib):
        self.sys_label.set_label(
            f"CPU {cpu}%     RAM {ram_gib:.1f} GiB ({ram}%)")

    # -- lifecycle ----------------------------------------------------------

    def _on_map(self):
        self.refresh_media()
        self.refresh_battery()
        self._read_volume()
        self._refresh_big_clock()
        if self.control_buttons:
            self._refresh_controls()
            self._controls_timer = GLib.timeout_add_seconds(
                5, self._refresh_controls)
        if self.weather is not None:
            self.weather.request()
        if self.system is not None:
            self.system.start()

    def _on_unmap(self):
        self.clip_button.set_active(False)
        if self._controls_timer:
            GLib.source_remove(self._controls_timer)
            self._controls_timer = 0
        if self._pos_timer:
            GLib.source_remove(self._pos_timer)
            self._pos_timer = 0
        if self.system is not None:
            self.system.stop()

    # -- seek bar ----------------------------------------------------------

    def _sync_pos_timer(self):
        playing = self.media.active and self.media.active.status == "Playing"
        want = bool(playing) and self.get_mapped()
        if want and not self._pos_timer:
            self._pos_timer = GLib.timeout_add_seconds(1, self._poll_position)
        elif not want and self._pos_timer:
            GLib.source_remove(self._pos_timer)
            self._pos_timer = 0

    def _poll_position(self):
        self.media.get_position(self._on_position)
        return True

    def _on_position(self, pos_us: int):
        self._position_us = pos_us
        if not self._seek_dragging:
            self.seek.set_value(pos_us)
        self.time_now.set_label(_fmt_us(pos_us))

    def _on_seek_released(self, gesture, n, x, y):
        self._seek_dragging = False
        self.media.seek_to(int(self.seek.get_value()))

    def _on_vol_set(self, scale, scroll, value):
        Gio.Subprocess.new(
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@",
             f"{int(max(0, min(100, value)))}%"],
            Gio.SubprocessFlags.NONE)
        return False

    # -- pomodoro ----------------------------------------------------------

    def _on_timer_toggle(self, *_):
        self.timer_running = not self.timer_running
        if self.timer_running and not self._timer_src:
            self._timer_src = GLib.timeout_add_seconds(1, self._timer_tick)
        self._sync_timer_ui()

    def _on_timer_reset(self, *_):
        self.timer_running = False
        self.timer_left = self.timer_minutes * 60
        if self._timer_src:
            GLib.source_remove(self._timer_src)
            self._timer_src = 0
        self._sync_timer_ui()

    def _on_timer_scroll(self, _ctrl, _dx, dy):
        # only a stopped, untouched timer changes length
        if self.timer_running or self.timer_left != self.timer_minutes * 60:
            return False
        step = -TIMER_STEP if dy > 0 else TIMER_STEP
        minutes = _clamp_minutes(self.timer_minutes + step)
        if minutes == self.timer_minutes:
            return True
        self.timer_minutes = minutes
        self.timer_left = minutes * 60
        self.cfg["timer_minutes"] = minutes
        config.save(self.cfg)
        self._sync_timer_ui()
        return True

    def _timer_tick(self):
        if not self.timer_running:
            self._timer_src = 0
            return False
        self.timer_left -= 1
        if self.timer_left <= 0:
            self.timer_left = 0
            self.timer_running = False
            self._timer_src = 0
            self._notify_done()
            self._sync_timer_ui()
            return False
        self._sync_timer_ui()
        return True

    def _sync_timer_ui(self):
        m, s = divmod(self.timer_left, 60)
        text = f"{m:02d}:{s:02d}"
        self.timer_label.set_label(text)
        self.timer_toggle.set_icon_name(
            "media-playback-pause-symbolic" if self.timer_running
            else "media-playback-start-symbolic")
        if self.timer_running:
            self.timer_tile.add_css_class("info-item--running")
        else:
            self.timer_tile.remove_css_class("info-item--running")
        if self.on_timer_change:
            self.on_timer_change(text if self.timer_running else None)

    def _notify_done(self):
        app = Gio.Application.get_default()
        if app:
            note = Gio.Notification.new("Focus round complete")
            note.set_body(f"{self.timer_minutes} minutes are up — take a break.")
            app.send_notification("pomodoro", note)

    def _refresh_big_clock(self):
        now = time.localtime()
        if self.cfg.get("clock_24h", True):
            clock = f"{now.tm_hour:02d}:{now.tm_min:02d}"
        else:
            clock = (f"{now.tm_hour % 12 or 12:02d}:{now.tm_min:02d} "
                     f"{'AM' if now.tm_hour < 12 else 'PM'}")
        self.big_clock.set_label(clock)
        # spelled out here so the system locale cannot change the script
        self.big_date.set_label(
            f"{_DAYS[now.tm_wday]}, {now.tm_mday} {_MONTHS[now.tm_mon - 1]}")


def _clamp_minutes(value) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        minutes = 25
    return max(TIMER_MIN_MINUTES, min(TIMER_MAX_MINUTES, minutes))


def _label(css: str, width: int) -> Gtk.Label:
    lbl = Gtk.Label(xalign=0)
    lbl.add_css_class(css)
    lbl.set_ellipsize(Pango.EllipsizeMode.END)
    lbl.set_max_width_chars(width)
    return lbl


def _media_btn(icon: str, main: bool = False) -> Gtk.Button:
    btn = Gtk.Button()
    btn.set_icon_name(icon)
    btn.add_css_class("media-btn")
    if main:
        btn.add_css_class("media-btn--main")
    return btn


def _symbol(name: str) -> Gtk.Label:
    icon = Gtk.Label(label=name)
    icon.add_css_class("symbol-icon")
    return icon


def _cell(button: Gtk.Button, caption: Gtk.Label | str) -> Gtk.Box:
    """A circle with its caption underneath, Control Center style."""
    cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
    cell.set_halign(Gtk.Align.CENTER)
    button.set_halign(Gtk.Align.CENTER)
    label = caption if isinstance(caption, Gtk.Label) else Gtk.Label(label=caption)
    label.add_css_class("circle-label")
    label.set_ellipsize(Pango.EllipsizeMode.END)
    label.set_max_width_chars(10)
    cell.append(button)
    cell.append(label)
    return cell


def _short(text: str, limit: int = 9) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _spawn(argv: list[str]):
    try:
        Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE)
    except GLib.Error:
        pass


def _shade(rgb, value: float, min_sat: float = 0.0):
    h, sat, _v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    r, g, b = colorsys.hsv_to_rgb(h, max(min_sat, min(sat, 0.85)), value)
    return int(r * 255), int(g * 255), int(b * 255)


def art_tint(pixbuf: GdkPixbuf.Pixbuf) -> tuple[int, int, int]:
    """Dominant color of the cover, darkened enough for white text."""
    one = pixbuf.scale_simple(1, 1, GdkPixbuf.InterpType.BILINEAR)
    data = one.get_pixels()
    rgb = (data[0], data[1], data[2])
    _h, sat, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    return _shade(rgb, value=max(0.30, min(v, 0.55)), min_sat=min(sat, 0.5))


def _fmt_us(us: int) -> str:
    s = max(0, us // 1_000_000)
    return f"{s // 60}:{s % 60:02d}"
